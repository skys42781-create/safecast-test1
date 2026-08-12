"""
Safecast — 스마트 건설 폭염 관제 대시보드
==========================================
건설현장 온열질환 예방을 위한 체감온도 기반 작업 통제 시스템.
산업안전보건기준에 관한 규칙(2025.7 개정) 기준.

실행:
    pip install -r requirements.txt
    streamlit run app.py

.streamlit/secrets.toml
    KAKAO_KEY = "카카오 REST API 키"
    KMA_KEY   = "공공데이터포털 기상청 일반인증키(Decoding)"
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import tbm as T

KST = ZoneInfo("Asia/Seoul")

# ---------------------------------------------------------------------
# 기상청 API 제공처 선택
#   True  → 기상청 API허브 (apihub.kma.go.kr).  인증 파라미터: authKey
#   False → 공공데이터포털 (data.go.kr).        인증 파라미터: serviceKey (Decoding 키)
# 두 곳은 응답 형식이 같고 인증 방식만 다르다.
# ---------------------------------------------------------------------
USE_APIHUB = True

if USE_APIHUB:
    BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"
    KEY_PARAM = "authKey"
else:
    BASE_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
    KEY_PARAM = "serviceKey"


# =====================================================================
# SECTION 0. 법적 기준 정의
# =====================================================================

@dataclass(frozen=True)
class HeatTier:
    min_temp: float
    code: str
    label: str
    short: str
    color: str
    legal: str
    cycle_hours: float | None   # 휴식 주기(시간)
    rest_minutes: int           # 1회 휴식(분)
    stop_work: bool
    actions: tuple[str, ...]

    @property
    def rest_ratio(self) -> float:
        return self.rest_minutes / (self.cycle_hours * 60) if self.cycle_hours else 0.0


# ※ 내림차순 정렬 필수 (classify가 위에서부터 검사)
HEAT_TIERS: list[HeatTier] = [
    HeatTier(38.0, "CRITICAL", "위험 (폭염중대경보)", "위험", "#7F1D1D", "권고", 1, 15, True, (
        "긴급조치 작업 외 옥외작업 중지",
        "온열질환 민감군 옥외작업 제한",
        "업무담당자 건강상태 확인 강화",
    )),
    HeatTier(35.0, "SEVERE", "심각 (폭염경보)", "심각", "#DC2626", "권고", 1, 15, True, (
        "매시간 15분 이상 휴식",
        "14~17시 옥외작업 중지 (불가피한 경우 제외)",
        "업무담당자 지정 후 근로자 건강상태 확인",
    )),
    HeatTier(33.0, "ALERT", "경계 (폭염주의보)", "경계", "#EA580C", "의무", 2, 20, False, (
        "2시간 이내 20분 이상 휴식 부여  [법적 의무]",
        "작업시간대 조정 또는 옥외작업 단축",
        "체감온도·조치사항 일자별 기록 (연말까지 보관)",
    )),
    HeatTier(31.0, "CAUTION", "주의 (폭염작업)", "주의", "#F59E0B", "의무", None, 0, False, (
        "폭염안전 5대 기본수칙 이행  [법적 의무]",
        "작업장소 온·습도계 비치",
        "2시간 이상 연속작업 지양",
    )),
    HeatTier(-99.0, "NORMAL", "관심 (평시)", "평시", "#16A34A", "-", None, 0, False, (
        "평시 작업 / 수분 섭취 안내",
    )),
]


@dataclass(frozen=True)
class WorkBlock:
    key: str
    name: str
    start_h: int
    end_h: int
    is_work: bool = True


WORK_BLOCKS: list[WorkBlock] = [
    WorkBlock("morning", "오전 작업", 8, 12),
    WorkBlock("lunch", "점심·휴게", 12, 14, is_work=False),
    WorkBlock("peak", "피크 (무더위 시간대)", 14, 17),
    WorkBlock("closing", "마무리·철수", 17, 18),
]

LEAD_OPTIONS = {"20분 (소규모 현장)": 20, "30분 (대규모·고층 현장)": 30}


def classify(v: float) -> HeatTier:
    for t in HEAT_TIERS:
        if v >= t.min_temp:
            return t
    return HEAT_TIERS[-1]


def tier_by_code(code: str) -> HeatTier:
    return next(t for t in HEAT_TIERS if t.code == code)


# =====================================================================
# SECTION 1. 체감온도 (법정 기준 공식)
# =====================================================================

def wet_bulb(ta: float, rh: float) -> float:
    """습구온도 근사 (Stull, 2011)."""
    rh = float(np.clip(rh, 1.0, 100.0))
    return (ta * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
            + math.atan(ta + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


def apparent_temp(ta: float, rh: float) -> float:
    """기상청 여름철 체감온도(℃).

    ⚠️ 미국 NWS Heat Index(Rothfusz)와 혼동 주의.
       법령상 31/33/35/38℃ 기준은 모두 이 공식 기준이며,
       Heat Index를 쓰면 같은 조건에서 등급이 1~2단계 어긋난다.
    """
    tw = wet_bulb(ta, rh)
    return round(-0.2442 + 0.55399 * tw + 0.45535 * ta
                 - 0.0022 * tw ** 2 + 0.00278 * tw * ta + 3.0, 1)


# =====================================================================
# SECTION 2. 위치 → 격자
# =====================================================================

@st.cache_data(ttl=86400, show_spinner=False)
def geocode(query: str, kakao_key: str) -> tuple[float, float, str] | None:
    """카카오 로컬 API: 장소명 → (위도, 경도, 정식명칭)."""
    try:
        r = requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": query, "size": 1},
            headers={"Authorization": f"KakaoAK {kakao_key}"}, timeout=10)
        r.raise_for_status()
        docs = r.json().get("documents", [])
        if not docs:
            return None
        d = docs[0]
        return float(d["y"]), float(d["x"]), d.get("place_name", query)
    except Exception:
        return None


_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT, _XO, _YO = 30.0, 60.0, 126.0, 38.0, 43, 136


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """기상청 Lambert Conformal Conic 5km 격자 변환.

    ⚠️ theta *= sn 누락 시 최대 100km 이상 어긋난 격자를 조회하게 된다.
    """
    DEGRAD = math.pi / 180.0
    re = _RE / _GRID
    slat1, slat2 = _SLAT1 * DEGRAD, _SLAT2 * DEGRAD
    olon, olat = _OLON * DEGRAD, _OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn                                   # ← 필수

    return (int(ra * math.sin(theta) + _XO + 0.5),
            int(ro - ra * math.cos(theta) + _YO + 0.5))


# =====================================================================
# SECTION 3. 기상청 API
# =====================================================================

FCST_BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def latest_fcst_base(now: datetime) -> tuple[str, str]:
    """단기예보: 가장 최근 제공 완료된 발표시각 (발표 +10분 후 조회 가능)."""
    avail = [h for h in FCST_BASE_HOURS if now >= datetime.combine(now.date(), time(h, 10))]
    if avail:
        return now.strftime("%Y%m%d"), f"{max(avail):02d}00"
    return (now.date() - timedelta(days=1)).strftime("%Y%m%d"), "2300"


def latest_ncst_base(now: datetime) -> tuple[str, str]:
    """초단기실황: 매시 정시 관측, 40분 이후 제공."""
    t = now - timedelta(hours=1) if now.minute < 40 else now
    return t.strftime("%Y%m%d"), t.strftime("%H00")


def latest_ultra_base(now: datetime) -> tuple[str, str]:
    """초단기예보: 매시 30분 발표(45분 제공), 발표시각+1h부터 6시간 제공.

    현재 시각을 커버하려면 '1시간 전 30분' 발표본을 써야 한다.
    예) 11:50 조회 → 10:30 발표본(10:45 제공) → 11:00~16:00 예보 포함
    """
    t = now - timedelta(hours=1)
    return t.strftime("%Y%m%d"), t.strftime("%H30")


@st.cache_data(ttl=600, show_spinner=False)
def fetch_ultra_fcst(nx: int, ny: int, key: str, bd: str, bt: str) -> pd.DataFrame:
    """초단기예보 → [datetime, ta, rh]. 실황이 아직 안 나온 현재 시각을 메운다."""
    r = requests.get(f"{BASE_URL}/getUltraSrtFcst", timeout=15, params={
        KEY_PARAM: key, "pageNo": 1, "numOfRows": 300, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny})
    r.raise_for_status()
    items = r.json()["response"]["body"]["items"]["item"]

    raw = pd.DataFrame(items)
    want = {"T1H": "ta", "REH": "rh"}
    raw = raw[raw["category"].isin(want)]
    wide = raw.pivot_table(index=["fcstDate", "fcstTime"], columns="category",
                           values="fcstValue", aggfunc="first").reset_index()
    wide.columns.name = None
    wide = wide.rename(columns=want)
    wide["datetime"] = pd.to_datetime(wide["fcstDate"] + wide["fcstTime"],
                                      format="%Y%m%d%H%M")
    for c in ["ta", "rh"]:
        wide[c] = pd.to_numeric(wide[c], errors="coerce")
    return wide[["datetime", "ta", "rh"]].dropna().sort_values("datetime")


@st.cache_data(ttl=600, show_spinner="기상청 실황 수신 중…")
def fetch_now(nx: int, ny: int, key: str, bd: str, bt: str) -> dict:
    """초단기실황 → {T1H: 기온, REH: 습도, ...}"""
    r = requests.get(f"{BASE_URL}/getUltraSrtNcst", timeout=15, params={
        KEY_PARAM: key, "pageNo": 1, "numOfRows": 100, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny})
    r.raise_for_status()
    items = r.json()["response"]["body"]["items"]["item"]
    return {i["category"]: float(i["obsrValue"]) for i in items}


@st.cache_data(ttl=1800, show_spinner="기상청 단기예보 수신 중…")
def fetch_forecast(nx: int, ny: int, key: str, bd: str, bt: str) -> pd.DataFrame:
    """단기예보 → [datetime, ta, rh].

    ⚠️ numOfRows는 1000 이상. 300이면 뒤쪽 시간대가 잘려 0℃로 표시된다.
    """
    r = requests.get(f"{BASE_URL}/getVilageFcst", timeout=20, params={
        KEY_PARAM: key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny})
    r.raise_for_status()
    items = r.json()["response"]["body"]["items"]["item"]

    raw = pd.DataFrame(items)
    want = {"TMP": "ta", "REH": "rh"}
    raw = raw[raw["category"].isin(want)]
    wide = raw.pivot_table(index=["fcstDate", "fcstTime"], columns="category",
                           values="fcstValue", aggfunc="first").reset_index()
    wide.columns.name = None
    wide = wide.rename(columns=want)
    wide["datetime"] = pd.to_datetime(wide["fcstDate"] + wide["fcstTime"],
                                      format="%Y%m%d%H%M")
    for c in ["ta", "rh"]:
        wide[c] = pd.to_numeric(wide[c], errors="coerce")
    return wide[["datetime", "ta", "rh"]].dropna().sort_values("datetime")


def demo_forecast(start: date, days: int = 2, peak: float = 36.0) -> pd.DataFrame:
    """API 없이 시연하기 위한 더미. 심사 중 API 장애 대비 fallback."""
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        p = peak - d * 1.5
        for h in range(24):
            ta = max(p - 9.5 * (1 - math.sin(math.pi * max(h - 5, 0) / 20)) ** 1.3, p - 11)
            rows.append({"datetime": datetime.combine(day, time(h)),
                         "ta": round(ta, 1),
                         "rh": round(float(np.clip(88 - (ta - 23) * 3.2, 35, 95)))})
    return pd.DataFrame(rows)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["at"] = [apparent_temp(r.ta, r.rh) for r in out.itertuples()]
    out["hour"] = out["datetime"].dt.hour
    out["day"] = out["datetime"].dt.date
    return out


# =====================================================================
# SECTION 4. 알고리즘 1 — 블록화 + 보수적 MAX
# =====================================================================

def build_blocks(day_df: pd.DataFrame, target: date, conservative: bool = True) -> pd.DataFrame:
    """1시간 예보 → 공정 블록 재집계.

    [보수적 MAX]
      안전보건규칙은 여러 작업장소 중 '가장 높은 온도'를 기준으로 적용하도록 한다(공간축 MAX).
      본 시스템은 인체 열 축적을 근거로 같은 원칙을 시간축으로 확장한다.
    """
    rows = []
    for b in WORK_BLOCKS:
        c = day_df[(day_df["hour"] >= b.start_h) & (day_df["hour"] < b.end_h)]
        if c.empty:
            continue
        rep = c["at"].max() if conservative else c["at"].mean()
        t = classify(rep)
        rows.append({
            "block_name": b.name, "is_work": b.is_work,
            "start": datetime.combine(target, time(b.start_h)),
            "end": datetime.combine(target, time(b.end_h)),
            "at_max": round(c["at"].max(), 1), "at_mean": round(c["at"].mean(), 1),
            "at_rep": round(rep, 1),
            "peak_hour": int(c.loc[c["at"].idxmax(), "hour"]),
            "ta_max": round(c["ta"].max(), 1), "rh_mean": round(c["rh"].mean()),
            "tier_code": t.code, "tier_label": t.label, "color": t.color,
            "legal": t.legal, "stop_work": t.stop_work,
        })
    return pd.DataFrame(rows)


def rest_slots(row: pd.Series) -> list[dict]:
    """블록 내 휴식 타이밍. 휴식이 블록 안에 온전히 들어가는 것만 채택."""
    t = tier_by_code(row["tier_code"])
    if not t.cycle_hours or not row["is_work"]:
        return []
    out, cur = [], row["start"] + timedelta(hours=t.cycle_hours)
    while cur + timedelta(minutes=t.rest_minutes) <= row["end"]:
        out.append({"휴식 시작": cur.strftime("%H:%M"),
                    "휴식 종료": (cur + timedelta(minutes=t.rest_minutes)).strftime("%H:%M"),
                    "근거": f"{t.short} · {t.legal}"})
        cur += timedelta(hours=t.cycle_hours)
    return out


def loss_ratio(blocks: pd.DataFrame) -> float:
    total = lost = 0.0
    for _, r in blocks[blocks["is_work"]].iterrows():
        h = (r["end"] - r["start"]).seconds / 3600
        t = tier_by_code(r["tier_code"])
        total += h
        lost += h * (1.0 if t.stop_work else t.rest_ratio)
    return round(lost / total * 100, 1) if total else 0.0


# =====================================================================
# SECTION 5. 알고리즘 2 — T-20 / T-30 사전 알람
# =====================================================================

ALARM_TMPL = ("[Safecast] {lead}분 후 '{block}' 구간 진입\n"
              "· 예상 체감온도 {at}℃ / {tier} ({legal})\n"
              "· 조치: {action}\n"
              "· 안전관리자: 휴게시설 냉방·음용수 상태 사전 점검 요망")


def build_alarms(blocks: pd.DataFrame, lead: int, trigger: str = "ALERT") -> pd.DataFrame:
    """위험 블록 T-lead 사전 알람.

    정각이 아닌 이유: ① 작업의 안전한 마무리 ② 근로자 이동시간
                     ③ 안전관리자의 휴게시설 점검 리드타임
    """
    order = [t.code for t in HEAT_TIERS]
    limit = order.index(trigger)
    rows = []
    for _, r in blocks.iterrows():
        if not r["is_work"] or order.index(r["tier_code"]) > limit:
            continue
        t = tier_by_code(r["tier_code"])
        rows.append({
            "발송시각": (r["start"] - timedelta(minutes=lead)).strftime("%H:%M"),
            "대상 블록": r["block_name"], "블록 시작": r["start"].strftime("%H:%M"),
            "등급": r["tier_label"], "체감온도": r["at_rep"],
            "메시지": ALARM_TMPL.format(lead=lead, block=r["block_name"],
                                      at=r["at_rep"], tier=t.label,
                                      legal=t.legal, action=t.actions[0]),
        })
    return pd.DataFrame(rows)


# =====================================================================
# SECTION 6. UI
# =====================================================================

def block_card(r: pd.Series) -> str:
    stop = "🚫 옥외작업 중지 권고" if r["stop_work"] else "&nbsp;"
    dim = "opacity:0.55;" if not r["is_work"] else ""
    return f"""
<div style="border-left:8px solid {r['color']};background:#FAFAFA;{dim}
            padding:12px 16px;border-radius:8px;margin-bottom:9px;">
  <div style="font-size:12px;color:#666;">{r['start']:%H:%M} ~ {r['end']:%H:%M}</div>
  <div style="font-size:17px;font-weight:700;">{r['block_name']}</div>
  <div style="font-size:29px;font-weight:800;color:{r['color']};line-height:1.15;">
      {r['at_rep']}℃</div>
  <div style="font-size:13px;color:{r['color']};font-weight:600;">
      {r['tier_label']} · {r['legal']}</div>
  <div style="font-size:11.5px;color:#888;margin-top:5px;">
      기온 {r['ta_max']}℃ / 습도 {r['rh_mean']}% ·
      블록 내 최고 {r['at_max']}℃({r['peak_hour']}시) vs 평균 {r['at_mean']}℃</div>
  <div style="font-size:12.5px;color:#B91C1C;font-weight:600;">{stop}</div>
</div>"""


def timeline(df: pd.DataFrame, title: str) -> go.Figure:
    fig = go.Figure()
    for d in sorted(df["day"].unique()):
        for b in WORK_BLOCKS:
            if not b.is_work:
                continue
            s = df[(df["day"] == d) & (df["hour"] >= b.start_h) & (df["hour"] < b.end_h)]
            if s.empty:
                continue
            fig.add_vrect(x0=datetime.combine(d, time(b.start_h)),
                          x1=datetime.combine(d, time(b.end_h)),
                          fillcolor=classify(s["at"].max()).color,
                          opacity=0.13, line_width=0, layer="below")
    for t in HEAT_TIERS:
        if t.min_temp < 0:
            continue
        fig.add_hline(y=t.min_temp, line_dash="dot", line_color=t.color, line_width=1.2,
                      annotation_text=f"{t.min_temp:.0f}℃ {t.short}",
                      annotation_position="right",
                      annotation_font=dict(size=10, color=t.color))
    fig.add_trace(go.Scatter(x=df["datetime"], y=df["ta"], name="기온",
                             line=dict(color="#94A3B8", width=1.6, dash="dash")))
    fig.add_trace(go.Scatter(x=df["datetime"], y=df["at"], name="체감온도",
                             line=dict(color="#1E293B", width=3),
                             mode="lines+markers", marker=dict(size=4)))
    fig.update_layout(title=title, height=380, hovermode="x unified",
                      margin=dict(l=10, r=75, t=45, b=10), yaxis_title="℃",
                      legend=dict(orientation="h", y=1.12, x=0))
    return fig


def render_day(day_df: pd.DataFrame, target: date, conservative: bool, lead: int) -> None:
    blocks = build_blocks(day_df, target, conservative)
    if blocks.empty:
        st.warning("해당 일자의 예보 데이터가 없습니다.")
        return

    work = blocks[blocks["is_work"]]
    dmax = day_df["at"].max()
    dt_ = classify(dmax)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("최고 체감온도", f"{dmax:.1f}℃",
              delta=f"기온 대비 +{dmax - day_df['ta'].max():.1f}℃")
    c2.metric("통제 등급", dt_.short, delta=dt_.legal, delta_color="off")
    c3.metric("작업중지 블록", f"{int(work['stop_work'].sum())} / {len(work)}")
    c4.metric("작업시간 손실률", f"{loss_ratio(blocks)}%")

    if dt_.stop_work:
        st.error("⚠️ " + " · ".join(dt_.actions), icon="🚨")
    elif dt_.code != "NORMAL":
        st.warning("📋 " + " · ".join(dt_.actions), icon="⚠️")

    L, R = st.columns([1, 1.35])
    with L:
        st.markdown("##### 공정 블록별 통제 등급")
        for _, r in blocks.iterrows():
            st.markdown(block_card(r), unsafe_allow_html=True)
    with R:
        st.plotly_chart(timeline(day_df, f"{target:%m월 %d일} 체감온도"),
                        use_container_width=True)

        st.markdown("##### 블록별 휴식 계획")
        found = False
        for _, r in blocks.iterrows():
            s = rest_slots(r)
            if s:
                found = True
                st.caption(f"**{r['block_name']}** — {r['tier_label']}")
                st.dataframe(pd.DataFrame(s), hide_index=True, use_container_width=True)
        if not found:
            st.info("정기 휴식 부여 기준(체감온도 33℃) 미도달")

        alarms = build_alarms(blocks, lead)
        if not alarms.empty:
            st.markdown(f"##### T-{lead} 사전 알람")
            st.dataframe(alarms[["발송시각", "대상 블록", "블록 시작", "등급", "체감온도"]],
                         hide_index=True, use_container_width=True)
            for _, a in alarms.iterrows():
                with st.expander(f"{a['발송시각']} → {a['대상 블록']} 메시지"):
                    st.code(a["메시지"], language=None)


def main() -> None:
    st.set_page_config(page_title="Safecast", page_icon="🏗️", layout="wide")

    # secrets.toml 파일 자체가 없으면 st.secrets 접근이 예외를 던진다 (로컬 첫 실행)
    try:
        kakao = st.secrets.get("KAKAO_KEY", "")
        kma = st.secrets.get("KMA_KEY", "")
    except Exception:
        kakao = kma = ""

    with st.sidebar:
        st.header("⚙️ 관제 설정")

        # ---- 모드 ----
        # Streamlit은 사용자별 인증이 없어 URL을 아는 사람은 모두 접근할 수 있다.
        # 민감군 명단이 노출되지 않도록 관리자 모드에 비밀번호를 건다.
        mode = st.radio("모드", ["👷 근로자", "🛡️ 관리자"], horizontal=True)
        is_admin = False
        if mode.startswith("🛡️"):
            try:
                admin_pw = st.secrets.get("ADMIN_PW", "")
            except Exception:
                admin_pw = ""
            if not admin_pw:
                st.warning("secrets에 ADMIN_PW 미설정 — 임시 통과")
                is_admin = True
            else:
                pw = st.text_input("관리자 비밀번호", type="password")
                is_admin = (pw == admin_pw)
                if pw and not is_admin:
                    st.error("비밀번호가 일치하지 않습니다.")
        st.divider()

        place = st.text_input("현장 위치", placeholder="예: 국민대학교")

        st.divider()
        demo = st.toggle("데모 모드 (API 미사용)", value=not kma,
                         help="API 키 없이 시연. 심사 중 API 장애 대비 fallback.")
        peak = st.slider("[데모] 오늘 최고기온", 26.0, 42.0, 36.0, 0.5) if demo else 36.0

        st.divider()
        lead = LEAD_OPTIONS[st.radio("사전 알람 시점", list(LEAD_OPTIONS.keys()),
                                     help="현장이 넓거나 고층일수록 이동·마무리 시간이 길어집니다.")]
        conservative = st.toggle("보수적 MAX 적용", value=True,
                                 help="끄면 블록 평균 기준. A/B 비교 시연용.")

        if not demo and not kma:
            st.error("secrets.toml에 KMA_KEY를 등록하세요.")

    st.title("🏗️ Safecast")
    st.caption("건설현장 폭염 관제 시스템 · 산업안전보건기준에 관한 규칙(2025.7 개정) 기준")

    # ---------- 위치 ----------
    if demo:
        lat, lon, name = 37.4979, 127.0276, place or "데모 현장"
    elif not kakao:
        # 카카오 키가 없으면 데모 좌표로 대체 (기상청 키만으로도 동작)
        lat, lon, name = 37.5665, 126.9780, place or "서울시청(기본)"
    else:
        if not place:
            st.info("사이드바에 현장 위치를 입력하세요.")
            st.stop()
        g = geocode(place, kakao)
        if not g:
            st.error(f"'{place}' 위치를 찾을 수 없습니다.")
            st.stop()
        lat, lon, name = g
    nx, ny = latlon_to_grid(lat, lon)

    now = now_kst()
    today, tomorrow = now.date(), now.date() + timedelta(days=1)

    # ---------- 데이터 ----------
    if demo:
        fc = enrich(demo_forecast(today, 2, peak))
        ncst, ncst_dt, ufc, src = None, None, None, "🟡 데모 데이터"
    else:
        try:
            bd, bt = latest_fcst_base(now)
            fc = enrich(fetch_forecast(nx, ny, kma, bd, bt))
            src = f"🟢 단기예보 {bt[:2]}시 발표"
        except Exception as e:
            st.error(f"예보 API 실패 → 데모 데이터 대체\n\n`{e}`")
            fc, src = enrich(demo_forecast(today, 2, 36.0)), "🔴 API 실패"
        try:
            nb, nt = latest_ncst_base(now)
            ncst = fetch_now(nx, ny, kma, nb, nt)
            ncst_dt = datetime.strptime(nb + nt, "%Y%m%d%H%M")
        except Exception:
            ncst, ncst_dt = None, None
        try:
            ub, ut = latest_ultra_base(now)
            ufc = fetch_ultra_fcst(nx, ny, kma, ub, ut)
        except Exception:
            ufc = None

    fc = fc[fc["day"].isin([today, tomorrow])]
    st.success(f"📍 **{name}** · 격자 (nx={nx}, ny={ny}) · {src}")

    # ---------- 현재 상황 (관측 + 현재시각 추정) ----------
    if ncst and "T1H" in ncst and "REH" in ncst:
        obs_ta, obs_rh = ncst["T1H"], ncst["REH"]
        obs_at = apparent_temp(obs_ta, obs_rh)

        # 실황은 정시 관측 + 40분 지연 → 그 사이는 초단기예보로 메운다
        cur_ta, cur_rh, cur_src, cur_dt = obs_ta, obs_rh, "관측", ncst_dt
        if ufc is not None and not ufc.empty and ncst_dt is not None:
            newer = ufc[(ufc["datetime"] > ncst_dt) &
                        (ufc["datetime"] <= now.replace(minute=0, second=0, microsecond=0))]
            if not newer.empty:
                last = newer.iloc[-1]
                cur_ta, cur_rh = float(last["ta"]), float(last["rh"])
                cur_src, cur_dt = "초단기예보", last["datetime"].to_pydatetime()

        cur_at = apparent_temp(cur_ta, cur_rh)
        ct = classify(cur_at)

        m = st.columns(4)
        m[0].metric("현재 기온", f"{cur_ta}℃")
        m[1].metric("현재 습도", f"{cur_rh}%")
        m[2].metric("현재 체감온도", f"{cur_at}℃", delta=f"+{cur_at - cur_ta:.1f}℃")
        m[3].metric("현재 등급", ct.short, delta=ct.legal, delta_color="off")

        stamp = f"{cur_dt:%H:%M} {cur_src}" if cur_dt else cur_src
        note = f"📡 {stamp} 기준"
        if cur_src == "초단기예보" and ncst_dt:
            note += f" · 최종 관측 {ncst_dt:%H:%M} {obs_ta}℃ (체감 {obs_at}℃)"
        st.caption(
            note + " · 기상청 격자(5km) 값이며 현장 실측이 아닙니다. "
            "철골·콘크리트면은 이보다 높을 수 있습니다."
        )

    today_df, tmr_df = fc[fc["day"] == today], fc[fc["day"] == tomorrow]
    day_max = float(today_df["at"].max()) if not today_df.empty else float(fc["at"].max())
    day_tier = classify(day_max)

    # ---------- 근로자 모드 ----------
    # 지침은 자각증상 점검표를 '근로자 스스로' 체크하도록 정한다.
    # 근로자에게는 남의 건강정보를 일절 보여주지 않는다.
    if not is_admin:
        st.markdown(
            f"""<div style="background:{day_tier.color};color:#fff;padding:18px;
                    border-radius:10px;text-align:center;margin-bottom:14px;">
              <div style="font-size:13px;opacity:.9;">오늘 우리 현장</div>
              <div style="font-size:38px;font-weight:800;line-height:1.2;">
                  {day_max:.1f}℃</div>
              <div style="font-size:17px;font-weight:700;">{day_tier.label}</div>
            </div>""", unsafe_allow_html=True)

        if day_tier.cycle_hours:
            st.info(f"💧 오늘은 **{day_tier.cycle_hours:.0f}시간마다 "
                    f"{day_tier.rest_minutes}분 이상** 휴식이 부여됩니다.")
        if day_tier.stop_work:
            st.error("🚫 " + day_tier.actions[1] if len(day_tier.actions) > 1
                     else "🚫 " + day_tier.actions[0], icon="🚨")

        st.divider()
        T.render_worker_check()

        st.divider()
        st.caption("🛑 몸이 이상하면 즉시 작업을 멈추고 알리세요. "
                   "근로자는 작업중지를 요청할 권리가 있습니다.")
        st.caption("관리자는 사이드바에서 관리자 모드로 전환하세요.")
        return

    # ---------- 이하 관리자 모드 ----------
    # ---------- D+1 사전 경보 ----------
    if not tmr_df.empty and not today_df.empty:
        tt, yt = classify(tmr_df["at"].max()), classify(today_df["at"].max())
        if tt.min_temp > yt.min_temp:
            st.error(
                f"📢 **내일 통제 등급 상향 예상** — 오늘 {yt.short} → 내일 **{tt.short}** "
                f"(최고 체감온도 {tmr_df['at'].max():.1f}℃)\n\n"
                f"오늘 중 조치: 공정계획 조정 · 쉼터/음용수 물량 확보 · "
                f"민감군 배치 재검토 · 조기출근 전환 검토", icon="🚨")

    t1, t2, t4, t3 = st.tabs([f"📅 오늘 ({today:%m/%d})", f"📅 내일 ({tomorrow:%m/%d})",
                              "👷 TBM 타겟 명단", "📖 법적 근거"])

    with t1:
        if today_df.empty:
            st.warning("오늘 잔여 예보가 없습니다.")
        else:
            render_day(today_df, today, conservative, lead)

    with t2:
        if tmr_df.empty:
            st.warning("내일 예보 데이터가 없습니다.")
        else:
            render_day(tmr_df, tomorrow, conservative, lead)

    with t4:
        st.caption("출역 데이터를 연동해 온열질환 민감군·열순응 대상자를 자동 선별합니다.")
        up = st.file_uploader(
            "출역 명부 CSV (미업로드 시 시연용 더미 사용)", type="csv",
            help="컬럼: " + ", ".join(T.ROSTER_COLUMNS))
        if up is not None:
            try:
                roster = T.normalize_roster(pd.read_csv(up))
                st.success(f"출역 명부 {len(roster)}명 로드")
            except Exception as e:
                st.error(f"CSV 읽기 실패 → 더미로 대체\n\n`{e}`")
                roster = T.make_demo_roster()
        else:
            roster = T.make_demo_roster()
            st.caption("🟡 시연용 더미 명부 — 실제 현장에서는 출역시스템 CSV/DB 연동")

        st.divider()
        T.render_tbm_admin(roster, day_tier.code, day_tier.label, day_max)

    with t3:
        st.dataframe(pd.DataFrame([{
            "체감온도": f"{t.min_temp:.0f}℃ 이상", "등급": t.label,
            "휴식": (f"{t.cycle_hours:.0f}시간마다 {t.rest_minutes}분"
                     if t.cycle_hours else "정기휴식 규정 없음"),
            "성격": t.legal, "주요 조치": t.actions[0],
        } for t in HEAT_TIERS if t.min_temp > 0]), hide_index=True,
            use_container_width=True)

        st.markdown("""
#### 산출 근거
- **체감온도** — 기상청 여름철 체감온도식 (습구온도는 Stull 2011 근사).
  법령상 31/33/35/38℃ 기준은 모두 **기온이 아니라 체감온도**.
  미국 NWS Heat Index를 쓰면 같은 조건에서 등급이 1~2단계 어긋난다.
- **보수적 MAX** — 안전보건규칙은 여러 작업장소 중 *가장 높은 온도* 기준 적용(공간축 MAX).
  본 시스템은 인체 열 축적을 근거로 이를 **시간축으로 확장**.
- **측정 원칙** — 주된 작업장소(공정 단위), 바닥 1.2~1.5m 높이, 최고값 적용.
  측정 곤란 시 기상청 체감온도 활용 가능 → 본 시스템의 예보 기반 운용 근거.
- **기록 의무** — 작업장소·시간·체감온도·조치사항 일자별 기록, 해당 연도 12/31까지 보관.

#### 한계
- 기상청 격자는 5km 해상도이며 표준 관측환경(잔디·백엽상) 기준.
  철골 상부·콘크리트면 등 현장 미기후는 반영되지 않는다 → 현장 실측 연동 필요.
- 체감온도는 기온·습도만 반영하며 **복사열을 포함하지 않는다**.

⚠️ 발표 전 고용노동부 최신 보도자료로 기준 재검증 필요 (매년 갱신).
""")
        st.divider()
        T.render_basis()


if __name__ == "__main__":
    main()