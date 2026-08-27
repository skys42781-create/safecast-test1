"""
Safecast — 지점 상세화 보정 (downscaling correction)
=====================================================
기상청 격자값·관측소 실측값을 현장 지점 조건에 맞춰 보정한다.

[방향 설정의 근거]
  조창제(2020)는 지상관측 604지점을 공간보간해 LSTM·공간랜덤포레스트로
  기온 예측모형을 만들고 기상청 동네예보와 비교했으나, 시간단위 자료에서
  동네예보(RMSE 3.2~7.6℃)를 능가하지 못했다(PCA sRF 7.0~8.6℃).
  → 예보를 '대체'하지 않는다. 예보를 '출발점'으로 삼아 보정한다.
    보정량이 0이면 원본과 동일하므로 성능 하한이 보장된다.

[보정의 근거]
  김용석 외(2014): 해발고도 기온감률 적용 시 공간내삽 RMSE가 26~37% 개선.
                   특히 산지가 많은 강원도에서 감소폭이 가장 컸다.
  조아영 외(2018): 고도를 부변수로 넣은 공동크리깅이 온도 공간화에 가장 적합.
                   고도·경사가 높을수록 편이가 커진다(고지대 4.56℃ vs 저지대 0.70℃).

[이 보정이 잡지 못하는 것]
  관측소는 잔디밭 백엽상, 건설현장은 콘크리트·철골이다. 그 격차(미기후)는
  관측 데이터에 정보가 존재하지 않으므로 어떤 통계적 보정으로도 제거할 수 없다.
  → 실측 센서 연동이 필요한 이유. 센서값이 있으면 항상 그쪽을 우선한다.
"""

from __future__ import annotations

import math

import requests
import streamlit as st

# =====================================================================
# 월별 기온감률 (℃/m)
#   출처: 김용석·심교문·정명표·최인태(2014), 「기온감률 효과 적용에 따른
#        공간내삽기법의 기온 추정 정확도 비교」, 한국기후변화학회지 5(4), Table 1
#   폭염 관제는 주간 최고기온이 관심사이므로 '최고기온' 계열을 사용한다.
# =====================================================================
LAPSE_MAX = {1: 0.0068, 2: 0.0074, 3: 0.0080, 4: 0.0083, 5: 0.0083, 6: 0.0080,
             7: 0.0074, 8: 0.0067, 9: 0.0061, 10: 0.0058, 11: 0.0058, 12: 0.0062}

LAPSE_SRC = "김용석 외(2014) 「기온감률 효과 적용에 따른 공간내삽기법의 기온 추정 정확도 비교」 Table 1"

# 보정량 상한. 이보다 큰 값이 나오면 고도 입력이 잘못됐을 가능성이 높다.
MAX_CORRECTION = 6.0

OPEN_ELEVATION = "https://api.open-elevation.com/api/v1/lookup"


# =====================================================================
# 습도 재계산 — 이 모듈의 핵심
# =====================================================================

def es(t: float) -> float:
    """포화수증기압 (hPa). Magnus 식."""
    return 6.112 * math.exp(17.67 * t / (t + 243.5))


def dewpoint(ta: float, rh: float) -> float:
    """이슬점 온도(℃)."""
    rh = min(max(rh, 1.0), 100.0)
    a = math.log(es(ta) * rh / 100 / 6.112)
    return 243.5 * a / (17.67 - a)


def rh_at(ta: float, td: float) -> float:
    """이슬점을 보존한 채 기온만 바뀌었을 때의 상대습도(%)."""
    return min(100.0, max(1.0, 100.0 * es(td) / es(ta)))


def correct_ta_rh(ta: float, rh: float, delta_t: float) -> tuple[float, float]:
    """기온을 delta_t만큼 보정하고, 상대습도를 다시 계산한다.

    [왜 습도를 다시 계산해야 하는가]
      기온이 내려가면 같은 수증기량이라도 포화에 가까워져 상대습도가 오른다.
      습도를 그대로 두면 체감온도를 1℃ 가까이 과소평가하며,
      그 방향이 항상 '실제보다 시원함'이라 안전 관점에서 위험하다.
      물리적으로 보존되는 것은 상대습도가 아니라 이슬점(절대 수증기량)이다.
    """
    td = dewpoint(ta, rh)
    ta2 = ta + delta_t
    return round(ta2, 1), round(rh_at(ta2, td), 1)


# =====================================================================
# 고도
# =====================================================================

@st.cache_data(ttl=86400, show_spinner=False)
def get_elevation(lat: float, lon: float) -> float | None:
    """좌표 → 해발고도(m). 실패하면 None (호출부에서 수동 입력으로 대체)."""
    try:
        r = requests.get(OPEN_ELEVATION,
                         params={"locations": f"{lat},{lon}"}, timeout=8)
        r.raise_for_status()
        return float(r.json()["results"][0]["elevation"])
    except Exception:
        return None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 간 거리(km)."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# =====================================================================
# 보정 적용
# =====================================================================

def lapse_correction(site_elev: float, ref_elev: float, month: int) -> float:
    """고도차에 따른 기온 보정량(℃). 현장이 높으면 음수(더 시원)."""
    rate = LAPSE_MAX.get(month, 0.0065)
    dz = site_elev - ref_elev
    return max(-MAX_CORRECTION, min(MAX_CORRECTION, -rate * dz))


def apply(ta: float, rh: float, site_elev: float | None, ref_elev: float | None,
          month: int) -> dict:
    """보정 결과를 근거와 함께 반환한다.

    고도 정보가 없으면 보정하지 않고 원본을 그대로 돌려준다.
    (보정량 0 = 원본. 성능 하한이 보장되는 구조)
    """
    if site_elev is None or ref_elev is None:
        return {"ta": ta, "rh": rh, "delta_t": 0.0, "delta_rh": 0.0,
                "applied": False, "reason": "고도 정보 없음 — 원본 사용",
                "rate": None, "dz": None}

    dz = site_elev - ref_elev
    dt = lapse_correction(site_elev, ref_elev, month)
    ta2, rh2 = correct_ta_rh(ta, rh, dt)
    clipped = abs(-LAPSE_MAX.get(month, 0.0065) * dz) > MAX_CORRECTION

    return {
        "ta": ta2, "rh": rh2,
        "delta_t": round(dt, 2), "delta_rh": round(rh2 - rh, 1),
        "applied": True,
        "reason": (f"고도차 {dz:+.0f}m × {LAPSE_MAX.get(month, 0.0065):.4f}℃/m"
                   + (f" (상한 ±{MAX_CORRECTION}℃ 적용)" if clipped else "")),
        "rate": LAPSE_MAX.get(month, 0.0065), "dz": dz,
    }


# =====================================================================
# UI
# =====================================================================

def render_panel(res: dict, ta0: float, rh0: float, at0: float, at1: float,
                 site_elev: float | None, ref_elev: float | None,
                 ref_name: str, ref_dist: float | None, month: int) -> None:
    """보정 근거 표시. 심사·감독 시 '이 숫자 어디서 왔나'에 화면이 답해야 한다."""
    if not res["applied"]:
        st.caption(f"⚪ 고도 보정 미적용 — {res['reason']}")
        return

    with st.expander(f"🏔️ 고도 보정 {res['delta_t']:+.2f}℃ · 체감온도 "
                     f"{at0:.1f} → {at1:.1f}℃", expanded=False):
        c1, c2 = st.columns(2)
        c1.markdown(f"""
**기준 지점**
{ref_name}{f' · {ref_dist:.1f}km' if ref_dist is not None else ''}
해발 {ref_elev:.0f}m

**현장**
해발 {site_elev:.0f}m ({res['dz']:+.0f}m)
""")
        c2.markdown(f"""
**보정 결과**
기온 {ta0:.1f} → {res['ta']:.1f}℃ ({res['delta_t']:+.2f})
습도 {rh0:.0f} → {res['rh']:.0f}% ({res['delta_rh']:+.1f})
체감 {at0:.1f} → {at1:.1f}℃
""")
        st.caption(f"산출: {res['reason']}")
        st.caption(f"기온감률 {month}월 {res['rate']:.4f}℃/m · 출처: {LAPSE_SRC}")
        st.caption("습도는 이슬점을 보존한 채 재계산했습니다. 기온만 보정하고 "
                   "상대습도를 그대로 두면 체감온도를 약 1℃ 과소평가합니다.")

        if ref_dist is not None and ref_dist > 20:
            st.warning(f"⚠️ 기준 지점이 {ref_dist:.0f}km 떨어져 있습니다. "
                       "고도 외 요인(해안 영향·도시열섬·국지 바람)이 커질 수 있습니다.")

    st.caption("ℹ️ 이 보정은 **고도차로 인한 규칙적 오차**만 제거합니다. "
               "관측소(잔디·백엽상)와 건설현장(콘크리트·철골)의 미기후 격차는 "
               "관측 데이터에 정보가 없어 보정이 불가능하며, 실측 센서로만 해결됩니다.")


def render_basis() -> None:
    """근거 탭에 넣을 설명."""
    st.markdown("""
#### 지점 상세화 보정

**왜 예보를 대체하지 않고 보정하는가**

조창제(2020)는 지상관측 604지점을 공간보간해 LSTM·공간랜덤포레스트 기반
기온 예측모형을 만들고 기상청 동네예보와 비교했습니다. 결과는 다음과 같습니다.

| 모형 | 시간단위 RMSE |
|---|---|
| 기상청 동네예보 | 3.2 ~ 7.6℃ |
| PCA 공간랜덤포레스트 | 7.0 ~ 8.6℃ |
| LSTM | 11 ~ 25℃ |

→ 슈퍼컴퓨터 수치예보를 관측자료 기반 모형으로 대체하는 것은 실효성이 없습니다.
본 시스템은 **동네예보를 출발점으로 삼아 보정**하며, 보정량이 0이면 원본과
동일하므로 **성능 하한이 보장**됩니다.

**보정 근거**

- 김용석 외(2014): 기온감률 적용 시 공간내삽 RMSE **26~37% 개선**,
  산지가 많은 **강원도에서 감소폭 최대**
- 조아영 외(2018): 고도를 부변수로 넣은 공동크리깅이 온도 공간화에 최적,
  고지대 편이 4.56℃ vs 저지대 0.70℃

**습도 재계산**

세 선행연구 모두 기온만 다룹니다. 그러나 법정 판정 기준은 체감온도이며
체감온도는 기온과 습도의 함수이므로, 기온 보정 시 이슬점을 보존한 채
상대습도를 재계산해야 합니다. 이를 생략하면 체감온도를 약 1℃ 과소평가하며
그 방향이 항상 '실제보다 시원함'이라 안전 관점에서 위험합니다.

**한계**

고도차로 인한 규칙적 오차만 제거됩니다. 현장 미기후(복사열, 콘크리트 축열,
통풍 조건)는 관측 데이터에 정보가 존재하지 않아 통계적 보정이 불가능합니다.

⚠️ 시간대별 예보 오차는 오후(15시 RMSE 7.63℃)가 오전(8시 3.20℃)의 약 2.4배이며,
이는 폭염 조치가 필요한 시각과 정확히 겹칩니다. (조창제 2020, 부록 11)
""")
