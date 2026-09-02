"""
Safecast — 지상관측 지점 연동 (ASOS / AWS)
============================================
격자 예보값이 아니라 '실제 온도계가 있는 지점'의 실측값을 기준으로 삼는다.

[왜 격자가 아니라 관측소인가]
  격자 보정의 걸림돌은 "그 격자값이 대표하는 고도가 몇 m인가"가 불명확하다는 점이다.
  기준 고도가 불확실하면 기온감률 보정식 자체가 성립하지 않는다.

  관측소는 다르다. 기상청이 지점별로 다음을 공개한다.
    HT     노장해발고도(m)
    HT_TA  온도계 지상높이(m)
  → 기준 고도 = HT + HT_TA 로 확정된다. 보정식의 두 항이 모두 확실한 숫자가 된다.

[ASOS와 AWS를 함께 쓰는 이유]
  ASOS  약 100지점. 기온·습도 등 전 요소를 정규 관측한다. 대신 성기다.
  AWS   약 510지점. 훨씬 촘촘하나 습도가 없는 지점이 많다.
  → 기온은 더 가까운 AWS, 습도는 ASOS에서 가져오는 조합이 오차가 가장 작다.
    체감온도에 기온의 기여가 더 크므로, 기온의 거리를 줄이는 편이 유리하다.

[한계]
  관측소는 잔디 위 백엽상, 건설현장은 콘크리트·철골이다. 이 격차(미기후)는
  관측 데이터에 정보가 없어 어떤 보정으로도 제거되지 않는다.
"""

from __future__ import annotations

import math
import time

import pandas as pd
import requests
import streamlit as st

TYP01 = "https://apihub.kma.go.kr/api/typ01/url"

# 관측소가 이보다 멀면 고도 외 요인(해안·열섬·국지풍)이 커진다.
FAR_KM = 20.0


# =====================================================================
# 공통
# =====================================================================

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# 연결이 막힌 환경에서는 호출 하나하나가 타임아웃까지 기다린다.
# 지점목록 2회 + 실황 최대 6회면 화면이 수 분간 멈추므로 짧게 끊는다.
CONNECT_TIMEOUT = 6
READ_TIMEOUT = 10

# 한 번 실패하면 이 시간 동안은 아예 시도하지 않는다.
# 이미 막힌 걸 매 조작마다 다시 두드리면 앱이 계속 느려진다.
COOLDOWN_SEC = 300


def _down() -> bool:
    """직전 실패로부터 아직 쿨다운 중인가."""
    t = st.session_state.get("_kma_down_at")
    return bool(t and (time.time() - t) < COOLDOWN_SEC)


def _get(url: str, params: dict,
         timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)) -> str:
    if _down():
        raise RuntimeError("직전 호출이 실패해 잠시 건너뜁니다")
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        st.session_state.pop("_kma_down_at", None)
        return r.text
    except Exception:
        st.session_state["_kma_down_at"] = time.time()
        raise


def _parse_fixed(text: str) -> pd.DataFrame:
    """API허브 typ01 응답은 '#'으로 시작하는 주석 + 공백 구분 텍스트다."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line.split())
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# =====================================================================
# 지점 목록
# =====================================================================

@st.cache_data(ttl=86400 * 7, show_spinner=False)
def load_stations(key: str, kind: str = "SFC") -> pd.DataFrame:
    """지점 목록. kind: SFC(ASOS) / AWS.

    관측소 위치·고도는 거의 변하지 않으므로 일주일 캐시한다.
    반환: [stn_id, name, lat, lon, ht, ht_ta, ref_elev]
    """
    txt = _get(f"{TYP01}/stn_inf.php",
               {"inf": kind, "stn": "", "help": "0", "authKey": key})
    df = _parse_fixed(txt)
    if df.empty:
        return pd.DataFrame()

    # 컬럼 순서: STN_ID LON LAT STN_SP HT HT_PA HT_TA HT_WD HT_RN STN_CD STN_KO ...
    out = []
    for r in df.itertuples(index=False):
        try:
            v = list(r)
            stn = int(v[0]); lon = float(v[1]); lat = float(v[2])
            ht = float(v[4]); ht_ta = float(v[6])
            # 실제 응답 컬럼 순서 (help=1 헤더로 확인):
            #   0 STN_ID  1 LON  2 LAT  3 STN_SP  4 HT  5 HT_PA  6 HT_TA
            #   7 HT_WD  8 HT_RN  9 STN_AD  10 STN_KO  11 STN_EN  … 15+ LAW_ADDR
            # LAW_ADDR도 한글이므로 '한글 검색'이 아니라 인덱스로 잡는다.
            name = v[10] if len(v) > 10 else f"지점{stn}"
            if not _has_hangul(name):
                name = f"지점{stn}"
            if not (32 < lat < 40 and 124 < lon < 132):
                continue
            if ht < -50 or ht > 2500:
                continue
            out.append({
                "stn_id": stn, "name": name, "lat": lat, "lon": lon,
                "ht": ht, "ht_ta": ht_ta if 0 <= ht_ta <= 30 else 1.5,
            })
        except (ValueError, IndexError):
            continue

    res = pd.DataFrame(out)
    if not res.empty:
        # 기준 고도 = 노장해발고도 + 온도계 지상높이
        res["ref_elev"] = res["ht"] + res["ht_ta"]
    return res


def _has_hangul(s: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in str(s))


def _is_num(s: str) -> bool:
    try:
        float(s); return True
    except ValueError:
        return False


# 고도차 1m를 수평거리 몇 km와 동등하게 볼 것인가.
#   기온감률은 전국·월평균값이므로 실제와 ±20% 정도 어긋날 수 있다.
#   500m를 보정하면 잔차가 약 0.67℃ 생기는데, 이는 수평으로 25km 떨어진
#   지점의 기온차와 비슷한 수준이다. → 100m ≈ 5km, 즉 1m ≈ 0.05km.
ELEV_PENALTY_KM_PER_M = 0.05


def nearest(stations: pd.DataFrame, lat: float, lon: float,
            n: int = 1) -> pd.DataFrame:
    """순수 거리 기준 최근접."""
    if stations.empty:
        return pd.DataFrame()
    s = stations.copy()
    s["dist_km"] = [haversine(lat, lon, r.lat, r.lon) for r in s.itertuples()]
    return s.nsmallest(n, "dist_km")


def best_reference(stations: pd.DataFrame, lat: float, lon: float,
                   site_elev: float | None, n: int = 3) -> pd.DataFrame:
    """거리와 고도차를 함께 고려해 기준 지점을 고른다.

    [왜 최근접이 최선이 아닌가]
      보정량이 클수록 기온감률의 불확실성이 그대로 증폭된다.
      가깝지만 고도차가 500m인 지점보다, 조금 멀어도 고도가 비슷한 지점이
      보정 후 오차가 작을 수 있다.

      예) 하이원(812m) 기준
          태백   21.8km / 고도차 +503m → 보정 -3.37℃ (감률 오차 크게 증폭)
          대관령 53.1km / 고도차  +38m → 보정 -0.25℃ (보정 거의 불필요)

      비용 = 수평거리 + |고도차| × 0.05
      현장 고도를 모르면 거리만으로 판단한다.
    """
    if stations.empty:
        return pd.DataFrame()
    s = stations.copy()
    s["dist_km"] = [haversine(lat, lon, r.lat, r.lon) for r in s.itertuples()]
    if site_elev is None:
        s["dz"] = 0.0
        s["cost"] = s["dist_km"]
    else:
        s["dz"] = site_elev - s["ref_elev"]
        s["cost"] = s["dist_km"] + s["dz"].abs() * ELEV_PENALTY_KM_PER_M
    return s.nsmallest(n, "cost")


# =====================================================================
# 실황
# =====================================================================

def _header_index(text: str, names: list[str]) -> dict[str, int]:
    """help=1 응답의 주석 헤더에서 컬럼 위치를 찾는다.

    [왜 인덱스를 하드코딩하지 않는가]
      API 응답의 컬럼 순서는 문서와 다를 수 있고, 개편 시 조용히 바뀐다.
      잘못된 열을 기온으로 읽으면 등급이 통째로 틀리므로,
      헤더에서 이름으로 찾고 실패할 때만 기존 인덱스로 되돌아간다.
    """
    best = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        toks = line.lstrip("#").split()
        hit = {n: toks.index(n) for n in names if n in toks}
        if len(hit) > len(best):
            best = hit
    return best


def _obs_from(text: str, fallback: dict[str, int]) -> dict | None:
    """관측 응답 1행을 {ta, rh, ws, tm}으로."""
    df = _parse_fixed(text)
    if df.empty:
        return None
    v = list(df.iloc[0])
    idx = _header_index(text, ["TA", "HM", "WS", "REH"])

    def pick(name: str, fb: int | None):
        i = idx.get(name, fb)
        if i is None or i >= len(v):
            return None
        return _num(v[i])

    ta = pick("TA", fallback.get("TA"))
    rh = pick("HM", fallback.get("HM"))
    if rh is None:
        rh = pick("REH", None)
    ws = pick("WS", fallback.get("WS"))
    if ta is None:
        return None
    return {"ta": ta, "rh": rh, "ws": ws, "tm": v[0]}


@st.cache_data(ttl=600, show_spinner=False)
def asos_now(key: str, stn_id: int, tm: str) -> dict | None:
    """ASOS 매시 관측. tm은 YYYYMMDDHHMM(KST, 정시).

    컬럼(문서 기준): TM STN WD WS GST_WD GST_WS GST_TM PA PS PT PR TA TD HM ...
    실제 위치는 헤더에서 찾고, 못 찾으면 이 인덱스를 쓴다.
    """
    try:
        txt = _get(f"{TYP01}/kma_sfctm2.php",
                   {"tm": tm, "stn": stn_id, "help": "1", "authKey": key})
        return _obs_from(txt, {"TA": 11, "HM": 13, "WS": 3})
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def aws_now(key: str, stn_id: int, tm: str) -> dict | None:
    """AWS 매시 관측. 습도(HM)가 결측인 지점이 많다."""
    try:
        txt = _get(f"{TYP01}/awsh.php",
                   {"tm": tm, "stn": stn_id, "help": "1", "authKey": key})
        return _obs_from(txt, {"TA": 2, "HM": 5, "WS": None})
    except Exception:
        return None


def _num(x) -> float | None:
    """결측 코드(-9, -99, -999 …)를 None으로."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if f <= -9 or f > 900:
        return None
    return f


# =====================================================================
# 기준 지점 선정
# =====================================================================

def pick_reference(key: str, lat: float, lon: float, tm: str,
                   use_aws: bool = True, site_elev: float | None = None) -> dict:
    """현장 기준으로 쓸 관측값을 고른다.

    기온 — 더 가까운 지점(AWS 우선)
    습도 — ASOS (AWS는 습도 결측이 잦다)

    체감온도에 기온의 기여가 크므로 기온의 거리를 줄이는 것이 유리하다.
    두 지점이 다르면 화면에 각각 표시해 근거를 남긴다.
    """
    res = {"ok": False, "ta": None, "rh": None,
           "ta_src": None, "rh_src": None, "ref_elev": None, "note": ""}

    # ---- ASOS: 습도 확보용 ----
    asos = load_stations(key, "SFC")
    a_near = best_reference(asos, lat, lon, site_elev, 3)
    a_hit = None
    for r in a_near.itertuples():
        d = asos_now(key, int(r.stn_id), tm)
        if d and d.get("rh") is not None:
            a_hit = (r, d)
            break
        if d and a_hit is None:
            a_hit = (r, d)

    # ---- AWS: 더 가까운 기온 확보용 ----
    w_hit = None
    if use_aws:
        aws = load_stations(key, "AWS")
        for r in best_reference(aws, lat, lon, site_elev, 3).itertuples():
            d = aws_now(key, int(r.stn_id), tm)
            if d:
                w_hit = (r, d)
                break

    if a_hit is None and w_hit is None:
        res["note"] = ("인근 관측소 실황을 가져오지 못했습니다. "
                       "기상청 연결이 불안정하면 격자 실황·수집 스냅샷으로 "
                       "대체됩니다.")
        return res

    # ---- 기온: 더 가까운 쪽 ----
    cand = [c for c in (w_hit, a_hit) if c and c[1].get("ta") is not None]
    if not cand:
        res["note"] = "기온 관측값이 없습니다."
        return res
    t_stn, t_obs = min(cand, key=lambda c: c[0].dist_km)

    # ---- 습도: ASOS 우선 ----
    h_stn, h_obs = None, None
    if a_hit and a_hit[1].get("rh") is not None:
        h_stn, h_obs = a_hit
    elif w_hit and w_hit[1].get("rh") is not None:
        h_stn, h_obs = w_hit

    res.update({
        "ok": True,
        "ta": t_obs["ta"],
        "rh": h_obs["rh"] if h_obs else None,
        "ta_src": {"name": t_stn.name, "stn": int(t_stn.stn_id),
                   "dist": float(t_stn.dist_km), "elev": float(t_stn.ref_elev),
                   "kind": "AWS" if (w_hit and t_stn is w_hit[0]) else "ASOS"},
        "rh_src": ({"name": h_stn.name, "stn": int(h_stn.stn_id),
                    "dist": float(h_stn.dist_km), "kind": "ASOS"}
                   if h_stn is not None else None),
        # 고도 보정 기준은 '기온을 가져온 지점'의 고도여야 한다.
        "ref_elev": float(t_stn.ref_elev),
        "tm": t_obs.get("tm", tm),
        "candidates": a_near[["name", "dist_km", "ref_elev"]].to_dict("records")
        if not a_near.empty else [],
    })
    return res


# =====================================================================
# UI
# =====================================================================

def render_source(ref: dict) -> None:
    """기준 지점 표시. 거리가 멀면 신뢰도 경고."""
    if not ref.get("ok"):
        st.caption(f"⚪ 관측소 기준 미적용 — {ref.get('note', '')}")
        return

    t = ref["ta_src"]
    line = (f"🌡️ 기온 **{t['name']}**({t['kind']}) · {t['dist']:.1f}km · "
            f"기준고도 {t['elev']:.0f}m")
    if ref.get("rh_src") and ref["rh_src"]["stn"] != t["stn"]:
        h = ref["rh_src"]
        line += f"  ／  💧 습도 **{h['name']}**(ASOS) · {h['dist']:.1f}km"
    st.caption(line)

    if ref.get("candidates"):
        with st.expander("기준 지점 선정 근거"):
            st.caption("거리와 고도차를 함께 고려합니다. 보정량이 클수록 "
                       "기온감률의 불확실성이 증폭되므로, 가깝기만 한 지점보다 "
                       "고도가 비슷한 지점이 유리할 수 있습니다.")
            _c = pd.DataFrame(ref["candidates"])
            _c["dist_km"] = _c["dist_km"].round(1)
            _c["ref_elev"] = _c["ref_elev"].round(0).astype(int)
            st.dataframe(_c.rename(columns={
                "name": "지점", "dist_km": "거리(km)", "ref_elev": "기준고도(m)"}),
                hide_index=True, use_container_width=True)

    if t["dist"] > FAR_KM:
        st.warning(f"⚠️ 기준 관측소가 {t['dist']:.0f}km 떨어져 있습니다. "
                   "고도 외 요인(해안 영향·도시열섬·국지 바람)이 커질 수 있어 "
                   "보정 신뢰도가 낮아집니다.", icon="⚠️")


def render_basis() -> None:
    st.markdown("""
#### 관측소 기준 보정

**왜 격자가 아니라 관측소인가**

격자 예보값을 고도 보정하려면 "그 격자가 대표하는 고도"를 알아야 하는데, 이 값이
공개되지 않아 보정식이 성립하지 않습니다. 반면 지상관측 지점정보는 지점별로
**노장해발고도(HT)**와 **온도계 지상높이(HT_TA)**를 함께 제공하므로,
기준 고도를 `HT + HT_TA`로 확정할 수 있습니다.

→ 보정식 `현장값 = 관측값 + (현장고도 − 기준고도) × 기온감률`의
   **두 항이 모두 확실한 숫자**가 됩니다.

**ASOS와 AWS의 역할 분담**

| | 지점 수 | 특징 | 본 시스템에서 |
|---|---|---|---|
| ASOS(종관) | 약 100 | 기온·습도 등 전 요소 정규 관측 | **습도** |
| AWS(방재) | 약 510 | 촘촘하나 습도 결측이 잦음 | **기온**(더 가까울 때) |

체감온도에 기온의 기여가 더 크므로, 기온을 가져오는 지점의 거리를 줄이는 편이
전체 오차를 줄입니다. 고도 보정의 기준 고도는 **기온을 가져온 지점**의 값을 씁니다.

**신뢰도 표시**

기준 관측소까지의 거리를 항상 화면에 표시하며, 20km를 넘으면 경고합니다.
거리가 멀수록 고도 외 요인(해안 영향·도시열섬·국지 바람)이 커지기 때문입니다.
""")
