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
    KMA_KEY     = "공공데이터포털 기상청 일반인증키(Decoding)"
    KMA_HUB_KEY = "기상청 API허브 authKey (선택 — 이중화용)"
"""

from __future__ import annotations

import math
import re
import time as _time   # datetime.time 과 이름이 겹쳐 별칭 사용
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import correction as C
import records as R
import snapshot as SNAP
import stations as S
import tbm as T

KST = ZoneInfo("Asia/Seoul")

# ---------------------------------------------------------------------
# 기상청 API 제공처 선택
#   True  → 기상청 API허브 (apihub.kma.go.kr).  인증 파라미터: authKey
#   False → 공공데이터포털 (data.go.kr).        인증 파라미터: serviceKey (Decoding 키)
# 두 곳은 응답 형식이 같고 인증 방식만 다르다.
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# 기상청 API 창구
#
#   같은 데이터를 두 곳에서 제공한다. 서버·IP·인프라가 서로 다르므로
#   한쪽이 막혀도 다른 쪽으로 우회할 수 있다.
#
#   Streamlit Cloud에서 apihub.kma.go.kr 연결이 간헐적으로 ConnectTimeout이
#   나는 것을 확인했다(같은 시각 GitHub Actions·국내 브라우저는 정상).
#   따라서 창구를 하나로 고정하지 않고 순서대로 시도한다.
#
#   키는 창구마다 다르다. secrets에 둘 다 넣어두면 자동으로 골라 쓴다.
#     KMA_KEY      공공데이터포털 일반인증키(Decoding) — serviceKey
#     KMA_HUB_KEY  기상청 API허브 authKey
#   하나만 있으면 그 창구만 쓴다.
# ---------------------------------------------------------------------
ENDPOINTS = [
    {"name": "공공데이터포털",
     "base": "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0",
     "key_param": "serviceKey", "secret": "KMA_KEY"},
    {"name": "기상청 API허브",
     "base": "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0",
     "key_param": "authKey", "secret": "KMA_HUB_KEY"},
]

# 하위 호환 — 아직 이 상수를 참조하는 곳이 있을 수 있다.
BASE_URL = ENDPOINTS[0]["base"]
KEY_PARAM = ENDPOINTS[0]["key_param"]


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
    actions: tuple[tuple[str, str], ...]   # (근거등급, 조치내용)

    @property
    def rest_ratio(self) -> float:
        return self.rest_minutes / (self.cycle_hours * 60) if self.cycle_hours else 0.0

    @property
    def action_texts(self) -> tuple[str, ...]:
        return tuple(t for _, t in self.actions)

    def actions_by(self, strict: bool) -> tuple[tuple[str, str], ...]:
        """strict=True면 법적 의무 항목만."""
        return tuple(a for a in self.actions if a[0] == "의무") if strict else self.actions


# ---------------------------------------------------------------------
# 법정 최소 휴식 — 안전보건규칙 제560조제3항
#   체감온도 33℃ 이상: 매 2시간 이내 20분 이상 (의무)
#   35℃ 매시간 15분은 대응지침 14쪽 '권고'이며, 법적 최소는 여전히 2h/20분이다.
# ---------------------------------------------------------------------
MANDATORY_MIN_TEMP = 33.0
MANDATORY_CYCLE_H = 2.0
MANDATORY_REST_MIN = 20


def effective_rest(tier: "HeatTier", strict: bool) -> tuple[float | None, int, str]:
    """적용할 휴식 (주기, 분, 근거등급). strict=True면 법적 의무 수준만."""
    if strict:
        if tier.min_temp >= MANDATORY_MIN_TEMP:
            return MANDATORY_CYCLE_H, MANDATORY_REST_MIN, "의무"
        return None, 0, "-"
    return tier.cycle_hours, tier.rest_minutes, tier.legal


# ※ 내림차순 정렬 필수 (classify가 위에서부터 검사)
HEAT_TIERS: list[HeatTier] = [
    HeatTier(38.0, "CRITICAL", "위험 (폭염중대경보)", "위험", "#7F1D1D", "권고", 1, 15, True, (
        ("의무", "매 2시간 이내 20분 이상 휴식 (제560조제3항)"),
        ("의무", "체감온도·조치사항 일자별 기록·보관 (제562조제2항제3호)"),
        ("권고", "긴급조치 작업 외 옥외작업 중지"),
        ("권고", "온열질환 민감군 옥외작업 제한"),
        ("권고", "업무담당자 건강상태 확인 강화"),
    )),
    HeatTier(35.0, "SEVERE", "심각 (폭염경보)", "심각", "#DC2626", "권고", 1, 15, True, (
        ("의무", "매 2시간 이내 20분 이상 휴식 (제560조제3항)"),
        ("의무", "체감온도·조치사항 일자별 기록·보관 (제562조제2항제3호)"),
        ("권고", "매시간 15분 이상 휴식"),
        ("권고", "14~17시 옥외작업 중지 (불가피한 경우 제외)"),
        ("권고", "업무담당자 지정 후 근로자 건강상태 확인"),
    )),
    HeatTier(33.0, "ALERT", "경계 (폭염주의보)", "경계", "#EA580C", "의무", 2, 20, False, (
        ("의무", "매 2시간 이내 20분 이상 휴식 (제560조제3항)"),
        ("의무", "체감온도·조치사항 일자별 기록·보관 (제562조제2항제3호)"),
        ("권고", "작업시간대 조정 또는 옥외작업 단축"),
    )),
    HeatTier(31.0, "CAUTION", "주의 (폭염작업)", "주의", "#F59E0B", "의무", None, 0, False, (
        ("의무", "냉방·통풍장치, 작업시간 조정, 휴식 중 1개 이상 (제560조제2항)"),
        ("의무", "작업장소에 온·습도계 상시 비치 (제562조제2항제1호)"),
        ("의무", "증상·예방·응급조치 요령 사전 주지 (제562조제2항제2호)"),
        ("의무", "그늘진 장소 제공 (제567조제2항)"),
        ("의무", "소금과 음료수 비치 (제571조)"),
        ("권고", "2시간 이상 연속작업 지양"),
    )),
    HeatTier(-99.0, "NORMAL", "관심 (평시)", "평시", "#16A34A", "-", None, 0, False, (
        ("권고", "평시 작업 / 수분 섭취 안내"),
    )),
]


@dataclass(frozen=True)
class WorkBlock:
    key: str
    name: str
    start_h: int
    end_h: int
    is_work: bool = True


# ---------------------------------------------------------------------
# 공정 블록 구성
#
#   피크 14~17시 — 대응지침 14쪽 '무더위 시간대'. 법정 구간이므로 쪼개지 않는다.
#   오전 2+2시간 — 지침 미규정 구간. 2시간으로 나눈 근거:
#     ① 보수적 MAX는 블록 내 최고값을 전체에 적용하므로, 블록이 길수록
#        1시간 스파이크의 오염 범위가 넓어진다 (4h → 4시간 전부 상향).
#     ② 법정 휴식 주기가 2시간(제560조제3항)이라 블록 1개 = 휴식 주기 1개로 맞는다.
#     ③ 인체 열 축적 시상수가 1~2시간이므로 2시간이 적정 상한이다.
#     ④ 1시간까지 쪼개면 예보 오차(±1.2℃)가 시간 간 변동폭(0.3℃)보다 커져
#        노이즈가 등급으로 옮겨가고, 알람 피로가 발생한다.
#   → 과대 경보를 줄이는 것이 곧 안전이다. 경보가 반복되면 무시하기 시작한다.
# ---------------------------------------------------------------------
WORK_BLOCKS: list[WorkBlock] = [
    WorkBlock("morning1", "오전 1부", 8, 10),
    WorkBlock("morning2", "오전 2부", 10, 12),
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

# ---------------------------------------------------------------------
# API 호출 공통
#   ⚠️ 예외 메시지에는 요청 URL이 통째로 들어가고, 거기에 인증키가 포함된다.
#      공개 배포된 앱에서 그대로 표시하면 키가 노출되므로 반드시 가린다.
# ---------------------------------------------------------------------
# ⚠️ 연결 타임아웃을 짧게 잡으면 안 된다.
#    기상청 typ02(동네예보)는 해외 IP에서 TCP 연결 수립이 20초 이상 걸리는
#    구간이 실제로 관측된다. GitHub Actions 수집기는 연결 20초로 성공하는 반면
#    앱이 10초로 끊어 ConnectTimeout이 나던 사례가 있었다.
#    → 연결은 넉넉히 기다리고, 응답 대기는 짧게 끊는다.
API_TIMEOUT = (25, 20)   # (연결, 응답)
API_RETRY = 3
API_WAIT = 5


def mask_secret(msg: str) -> str:
    """오류 문자열에서 인증키를 가린다."""
    return re.sub(r"((?:authKey|serviceKey)=)[^&\s\)\']+", r"\1***", str(msg))


def _keys() -> list[dict]:
    """secrets에 들어 있는 창구만 골라 순서대로 돌려준다."""
    out = []
    for ep in ENDPOINTS:
        try:
            k = str(st.secrets.get(ep["secret"], "") or "").strip()
        except Exception:
            k = ""
        if k:
            out.append({**ep, "key": k})
    return out


def call_kma(path: str, params: dict) -> dict:
    """단기예보 계열 호출. 창구를 순서대로 시도한다.

    [왜 창구를 여럿 두는가]
      Streamlit Cloud에서 apihub.kma.go.kr 연결이 간헐적으로 ConnectTimeout이
      난다. 같은 시각 GitHub Actions와 국내 브라우저에서는 정상이므로
      기상청 장애가 아니라 배포 환경의 네트워크 문제다.
      공공데이터포털은 서버·IP가 달라 우회로가 된다.

      한 창구가 실패하면 즉시 다음으로 넘어간다. 재시도는 창구 안에서 한 번만
      하고, 오래 붙들지 않는다. 어차피 다음 창구가 있기 때문이다.
    """
    eps = _keys()
    if not eps:
        raise RuntimeError("사용 가능한 기상청 인증키가 없습니다 "
                           "(secrets의 KMA_KEY / KMA_HUB_KEY 확인)")
    errs = []
    for ep in eps:
        for attempt in range(API_RETRY):
            try:
                r = requests.get(f"{ep['base']}/{path}",
                                 params={ep["key_param"]: ep["key"], **params},
                                 timeout=API_TIMEOUT)
                r.raise_for_status()
                js = r.json()
                # 정상 응답이면 어느 창구를 썼는지 남긴다 (화면 표기용)
                st.session_state["_kma_via"] = ep["name"]
                return js
            except Exception as e:
                if attempt == API_RETRY - 1:
                    errs.append(f"{ep['name']}: {type(e).__name__}")
                else:
                    _time.sleep(API_WAIT)
    raise RuntimeError(mask_secret(" / ".join(errs)))


def api_get(url: str, params: dict) -> dict:
    """하위 호환 래퍼. 새 코드는 call_kma()를 쓴다."""
    path = url.rsplit("/", 1)[-1]
    p = {k: v for k, v in params.items() if k not in ("authKey", "serviceKey")}
    return call_kma(path, p)


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
    js = call_kma("getUltraSrtFcst", {
        "pageNo": 1, "numOfRows": 300, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny})
    items = js["response"]["body"]["items"]["item"]

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
    js = call_kma("getUltraSrtNcst", {
        "pageNo": 1, "numOfRows": 100, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny})
    items = js["response"]["body"]["items"]["item"]
    return {i["category"]: float(i["obsrValue"]) for i in items}


@st.cache_data(ttl=1800, show_spinner="기상청 단기예보 수신 중…")
def fetch_forecast(nx: int, ny: int, key: str, bd: str, bt: str) -> pd.DataFrame:
    """단기예보 → [datetime, ta, rh].

    ⚠️ numOfRows는 1000 이상. 300이면 뒤쪽 시간대가 잘려 0℃로 표시된다.
    """
    js = call_kma("getVilageFcst", {
        "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
        "base_date": bd, "base_time": bt, "nx": nx, "ny": ny})
    items = js["response"]["body"]["items"]["item"]

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


def _ta_for_at(target_at: float, rh: float) -> float:
    """주어진 습도에서 목표 체감온도가 나오는 기온을 역산 (이분법)."""
    lo, hi = 5.0, 55.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if apparent_temp(mid, rh) < target_at:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def demo_forecast(start: date, days: int = 2, peak_at: float = 34.0,
                  rh: float = 60.0) -> pd.DataFrame:
    """API 없이 시연하기 위한 더미. 심사 중 API 장애 대비 fallback.

    peak_at은 '기온'이 아니라 '목표 최고 체감온도'다.
    등급 판정이 체감온도 기준이므로, 슬라이더와 화면이 어긋나지 않도록
    지정한 습도에서 해당 체감온도가 나오는 기온을 역산한다.
    """
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        peak_ta = _ta_for_at(peak_at - d * 1.5, rh)      # 내일은 조금 낮게
        for h in range(24):
            ta = max(peak_ta - 9.5 * (1 - math.sin(math.pi * max(h - 5, 0) / 20)) ** 1.3,
                     peak_ta - 11)
            rows.append({"datetime": datetime.combine(day, time(h)),
                         "ta": round(ta, 1), "rh": round(rh)})
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

def build_blocks(day_df: pd.DataFrame, target: date, conservative: bool = True,
                 blocks_def: list[WorkBlock] | None = None) -> pd.DataFrame:
    """1시간 예보 → 공정 블록 재집계.

    [보수적 MAX]
      안전보건규칙은 여러 작업장소 중 '가장 높은 온도'를 기준으로 적용하도록 한다(공간축 MAX).
      본 시스템은 인체 열 축적을 근거로 같은 원칙을 시간축으로 확장한다.
    """
    rows = []
    for b in (blocks_def or WORK_BLOCKS):
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


def rest_slots(row: pd.Series, strict: bool = False) -> list[dict]:
    """블록 내 휴식 타이밍. 휴식이 블록 안에 온전히 들어가는 것만 채택.

    strict=True → 법정 최소(33℃ 이상 2시간마다 20분)만 산출.
    35℃의 '매시간 15분'은 지침 권고이며, 법적 최소는 여전히 2시간/20분이다.
    """
    t = tier_by_code(row["tier_code"])
    cycle, minutes, level = effective_rest(t, strict)
    if not cycle or not row["is_work"]:
        return []
    out, cur = [], row["start"] + timedelta(hours=cycle)
    while cur + timedelta(minutes=minutes) <= row["end"]:
        out.append({"휴식 시작": cur.strftime("%H:%M"),
                    "휴식 종료": (cur + timedelta(minutes=minutes)).strftime("%H:%M"),
                    "근거": ("제560조제3항 · 의무" if level == "의무"
                            else f"{t.short} · {level}")})
        cur += timedelta(hours=cycle)
    return out


def loss_ratio(blocks: pd.DataFrame, strict: bool = False) -> float:
    """작업시간 손실률. strict=True면 법정 의무 조치만 반영(작업중지 권고 제외)."""
    total = lost = 0.0
    for _, r in blocks[blocks["is_work"]].iterrows():
        h = (r["end"] - r["start"]).seconds / 3600
        t = tier_by_code(r["tier_code"])
        cycle, minutes, _ = effective_rest(t, strict)
        ratio = minutes / (cycle * 60) if cycle else 0.0
        total += h
        if not strict and t.stop_work:
            lost += h                 # 옥외작업 중지(권고)
        else:
            lost += h * ratio
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
                                      legal=t.legal, action=t.action_texts[0]),
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


def timeline(df: pd.DataFrame, title: str,
             blocks_def: list[WorkBlock] | None = None) -> go.Figure:
    fig = go.Figure()
    for d in sorted(df["day"].unique()):
        for b in (blocks_def or WORK_BLOCKS):
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


def render_day(day_df: pd.DataFrame, target: date, conservative: bool, lead: int,
               strict: bool = False,
               blocks_def: list[WorkBlock] | None = None) -> None:
    blocks = build_blocks(day_df, target, conservative, blocks_def)
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
    c4.metric("작업시간 손실률", f"{loss_ratio(blocks, strict)}%",
              delta="의무만" if strict else None, delta_color="off")

    # ---- 조치사항: 의무 / 권고 구분 표시 ----
    acts = dt_.actions_by(strict)
    if acts:
        must = [t for lv, t in acts if lv == "의무"]
        rec = [t for lv, t in acts if lv == "권고"]
        cm, cr = st.columns(2)
        with cm:
            if must:
                st.markdown("🔴 **법적 의무** — 위반 시 5년 이하 징역 또는 5천만원 이하 벌금")
                for t in must:
                    st.markdown(f"- {t}")
        with cr:
            if rec and not strict:
                st.markdown("🟠 **권고** — 고용노동부 대응지침")
                for t in rec:
                    st.markdown(f"- {t}")
            elif strict:
                st.caption("권고 항목은 숨김 (사이드바에서 해제)")

    # ---- 의무 vs 권고 휴식 비교 ----
    if dt_.min_temp >= MANDATORY_MIN_TEMP:
        mc, mm, _ = effective_rest(dt_, True)
        rc, rm, _ = effective_rest(dt_, False)
        if (mc, mm) != (rc, rm):
            st.info(f"🔴 **법적 최소** {mc:.0f}시간마다 {mm}분 (제560조제3항) ／ "
                    f"🟠 **지침 권고** {rc:.0f}시간마다 {rm}분 (대응지침 14쪽)")

    L, R = st.columns([1, 1.35])
    with L:
        st.markdown("##### 공정 블록별 통제 등급")
        for _, r in blocks.iterrows():
            st.markdown(block_card(r), unsafe_allow_html=True)
    with R:
        st.plotly_chart(timeline(day_df, f"{target:%m월 %d일} 체감온도", blocks_def),
                        use_container_width=True)

        st.markdown("##### 블록별 휴식 계획")
        found = False
        for _, r in blocks.iterrows():
            s = rest_slots(r, strict)
            if s:
                found = True
                st.caption(f"**{r['block_name']}** — {r['tier_label']}")
                st.dataframe(pd.DataFrame(s), hide_index=True, use_container_width=True)
        if not found:
            st.info("정기 휴식 부여 기준(체감온도 33℃) 미도달")



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
                # secrets나 입력값 끝에 공백·줄바꿈이 섞이면 조용히 실패한다.
                is_admin = bool(pw) and pw.strip() == str(admin_pw).strip()
                if pw and not is_admin:
                    st.error("비밀번호가 일치하지 않습니다.")
        admin_locked = mode.startswith("🛡️") and not is_admin
        st.divider()

        place = st.text_input("현장 위치", placeholder="예: 국민대학교")

        st.divider()
        demo = st.toggle("데모 모드 (API 미사용)", value=not kma,
                         help="API 키 없이 시연. 심사 중 API 장애 대비 fallback.")
        if demo:
            peak = st.slider("[데모] 오늘 최고 체감온도", 26.0, 42.0, 34.0, 0.5,
                             help="등급 판정 기준인 '체감온도'를 직접 지정합니다")
            demo_rh = st.slider("[데모] 습도(%)", 35, 95, 60, 5,
                                help="같은 기온이라도 습도가 높으면 체감온도가 올라갑니다")
        else:
            peak, demo_rh = 34.0, 60.0

        st.divider()
        lead = LEAD_OPTIONS[st.radio("사전 알람 시점", list(LEAD_OPTIONS.keys()),
                                     help="현장이 넓거나 고층일수록 이동·마무리 시간이 길어집니다.")]
        strict = st.toggle("법적 의무만 보기", value=False,
                           help="켜면 안전보건규칙상 '의무' 조치만 표시합니다. "
                                "35℃ 매시간 15분은 지침 권고이며, 법적 최소는 "
                                "여전히 2시간마다 20분입니다.")

        with st.expander("🏔️ 고도 보정"):
            use_lapse = st.toggle("고도 보정 적용", value=True,
                                  help="기준 관측소와 현장의 고도차를 월별 "
                                       "기온감률로 보정합니다.")
            use_station = st.toggle("관측소 실황 기준", value=True,
                                    help="격자 예보 대신 인근 ASOS/AWS 실측값을 "
                                         "기준으로 씁니다. 관측소는 고도가 명확해 "
                                         "보정식이 정확해집니다.")
            use_aws = st.toggle("AWS 기온 사용", value=True,
                                help="AWS(510지점)가 ASOS(100지점)보다 촘촘합니다. "
                                     "기온은 더 가까운 쪽, 습도는 ASOS를 씁니다.")
            auto_elev = st.toggle("현장 고도 자동 조회", value=True,
                                  help="Open-Elevation API. 실패 시 수동 입력.")
            e1, e2 = st.columns(2)
            manual_site_elev = e1.number_input("현장 고도(m)", 0, 2000, 50, 10,
                                               disabled=auto_elev)
            ref_elev_in = e2.number_input("기준 고도(m)", 0, 2000, 50, 10,
                                          disabled=use_station,
                                          help="관측소 기준을 끄면 직접 입력")

        with st.expander("🔧 현장 설정"):
            conservative = st.toggle("보수적 MAX 적용", value=True,
                                     help="끄면 블록 평균 기준. A/B 비교 시연용.")
            extra_min = st.slider("민감군 추가 휴식(분)", 0, 30, 10, 5,
                                  help="지침은 '추가 배정'을 요구하나 분량 미규정. "
                                       "기본 10분은 지침 우수사례 기준")
            c_a, c_b = st.columns(2)
            work_start = c_a.text_input("작업 시작", "08:00")
            work_hours = c_b.number_input("정상작업(h)", 4.0, 12.0, 8.0, 0.5,
                                          help="근로기준법 제50조 1일 8시간 기준")

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
    # 우선순위: ① 수집 스냅샷 → ② 기상청 라이브 → ③ 데모
    #
    #   ① GitHub Actions가 매시간 수집해 레포에 커밋한 CSV.
    #      기상청 서버 상태와 무관하므로 시연 중 장애에 영향받지 않는다.
    #   ② 스냅샷에 해당 격자가 없을 때만 직접 호출한다.
    #      (collect.py는 SITES에 정의된 격자만 수집한다)
    #   ③ 둘 다 실패하면 데모. 이때는 화면에 명확히 표기해야 한다.
    fc_is_demo = False
    fc_meta, obs_meta = {}, {}

    if demo:
        fc = enrich(demo_forecast(today, 2, peak, demo_rh))
        ncst, ncst_dt, ufc, src = None, None, None, "🟡 데모 데이터"
        fc_is_demo = True
    else:
        fc, src = None, ""

        # ---- ① 라이브 ----
        # 라이브를 먼저 시도한다. 스냅샷을 앞에 두면 항상 스냅샷이 걸려
        # API 창구가 실제로 살아 있는지 확인할 기회가 사라지고,
        # 최대 30분 낡은 값을 쓰게 된다.
        if kma:
            try:
                bd, bt = latest_fcst_base(now)
                fc = enrich(fetch_forecast(nx, ny, kma, bd, bt))
                via = st.session_state.get("_kma_via", "")
                src = f"🟢 단기예보 {bt[:2]}시 발표" + (f" · {via}" if via else "")
            except Exception as e:
                st.session_state["_api_err"] = mask_secret(e)[:500]

        # ---- ② 스냅샷 ----
        fc_meta = {}
        if fc is None:
            snap, fc_meta = SNAP.forecast(nx, ny, now)
            if snap is not None:
                fc = enrich(snap)
                src = f"🗄️ 수집 예보 {fc_meta['base_dt']:%H시} 발표"

        # ---- ③ 데모 ----
        if fc is None:
            st.error("기상청 예보를 가져오지 못했습니다 → **데모 데이터**로 표시합니다. "
                     "실제 작업 통제 판정에 사용하지 마세요.", icon="⚠️")
            if st.session_state.get("_api_err"):
                with st.expander("오류 상세"):
                    st.code(st.session_state["_api_err"], language=None)
            if fc_meta.get("reason"):
                st.caption(f"스냅샷 미사용 사유 — {fc_meta['reason']}")
            fc = enrich(demo_forecast(today, 2, 34.0))
            src = "🔴 데모 (수집·API 모두 실패)"
            fc_is_demo = True

        # ---- 실황 · 초단기예보 ----
        # 실황도 라이브를 먼저 시도하고, 실패하면 스냅샷으로 메운다.
        ncst, ncst_dt = None, None
        if kma:
            try:
                nb, nt = latest_ncst_base(now)
                ncst = fetch_now(nx, ny, kma, nb, nt)
                ncst_dt = datetime.strptime(nb + nt, "%Y%m%d%H%M")
            except Exception:
                ncst, ncst_dt = None, None
        if ncst is None:
            ncst, obs_meta = SNAP.observation(nx, ny, now)
            if ncst is not None:
                ncst_dt = obs_meta["obs_dt"]

        # 초단기예보는 '실황과 현재 사이의 공백'을 메우는 보조 데이터다.
        # 없어도 동작에 지장이 없으므로 실패해도 조용히 넘어간다.
        ufc = None
        if kma:
            try:
                ub, ut = latest_ultra_base(now)
                ufc = fetch_ultra_fcst(nx, ny, kma, ub, ut)
            except Exception:
                ufc = None

    fc = fc[fc["day"].isin([today, tomorrow])]
    if fc.empty:
        # 예보 구간이 통째로 비면 이후 모든 계산이 무의미하다.
        st.error("표시할 예보 구간이 없습니다. 사이드바에서 데모 모드로 전환해 주세요.",
                 icon="⚠️")
        st.stop()

    st.success(f"📍 **{name}** · 격자 (nx={nx}, ny={ny}) · {src}")
    SNAP.render_banner(fc_meta, "예보")
    if obs_meta.get("ok"):
        SNAP.render_banner(obs_meta, "실황")

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

        # ---- 기준값 선정: 관측소 실황 > 격자 실황 ----
        # 관측소는 고도(HT + HT_TA)가 공개되어 보정식이 확정된다.
        # 현장 고도를 먼저 확보한다. 기준 지점 선정에도 쓰이기 때문이다.
        site_elev = None
        elev_failed = False
        if use_lapse:
            if auto_elev:
                try:
                    site_elev = C.get_elevation(lat, lon)
                except Exception:
                    site_elev = None
                if site_elev is None:
                    # 자동 조회가 막히면 보정이 통째로 빠진다.
                    # 조용히 건너뛰지 말고 수동 입력값으로 대체하고 알린다.
                    site_elev = float(manual_site_elev)
                    elev_failed = True
            else:
                site_elev = float(manual_site_elev)

        # 관측소 조회는 별도 API(typ01)를 쓴다. 여기서 예외가 나면
        # 화면 전체가 죽으므로, 실패해도 격자 기준으로 계속 진행한다.
        ref = {"ok": False}
        if use_station and not demo and kma:
            try:
                ref = S.pick_reference(kma, lat, lon,
                                       ncst_dt.strftime("%Y%m%d%H%M") if ncst_dt
                                       else now.strftime("%Y%m%d%H00"),
                                       use_aws, site_elev)
            except Exception:
                ref = {"ok": False}
        if ref.get("ok") and ref.get("ta") is not None:
            raw_ta = ref["ta"]
            raw_rh = ref["rh"] if ref.get("rh") is not None else cur_rh
            ref_elev = ref["ref_elev"]
            cur_src = f"{ref['ta_src']['kind']} 실황"
        else:
            raw_ta, raw_rh = cur_ta, cur_rh
            ref_elev = float(ref_elev_in)

        raw_at = apparent_temp(raw_ta, raw_rh)

        # ---- 고도 보정 ----
        corr = C.apply(raw_ta, raw_rh, site_elev,
                       ref_elev if use_lapse else None, now.month)
        cur_ta, cur_rh = corr["ta"], corr["rh"]

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
        # 기준이 관측소인지 격자인지에 따라 문구가 달라야 한다.
        if ref.get("ok"):
            st.caption(note + " · 인근 관측소 실측값이며 현장 실측이 아닙니다. "
                       "관측소는 잔디·백엽상 환경이라, 철골·콘크리트면은 "
                       "이보다 높을 수 있습니다.")
        else:
            st.caption(note + " · 기상청 격자(5km) 값이며 현장 실측이 아닙니다. "
                       "철골·콘크리트면은 이보다 높을 수 있습니다.")
        # 삼항연산자를 쓰면 결과값 None이 화면에 그대로 출력된다.
        if use_station and not demo:
            S.render_source(ref)
        if elev_failed:
            st.warning(f"고도 자동 조회(Open-Elevation)에 실패해 수동 입력값 "
                       f"{manual_site_elev}m를 사용했습니다. 사이드바 «고도 보정»에서 "
                       f"현장 해발고도를 확인하세요.", icon="⚠️")
        _rname = (f"{ref['ta_src']['name']} ({ref['ta_src']['kind']})"
                  if ref.get("ok") else f"기상청 격자 ({nx}, {ny})")
        _rdist = ref["ta_src"]["dist"] if ref.get("ok") else None
        C.render_panel(corr, raw_ta, raw_rh, raw_at, cur_at,
                       site_elev, ref_elev if use_lapse else None,
                       _rname, _rdist, now.month)

    today_df, tmr_df = fc[fc["day"] == today], fc[fc["day"] == tomorrow]
    day_max = float(today_df["at"].max()) if not today_df.empty else float(fc["at"].max())
    day_tier = classify(day_max)

    # ---------- 근로자 모드 ----------
    # 지침은 자각증상 점검표를 '근로자 스스로' 체크하도록 정한다.
    # 근로자에게는 남의 건강정보를 일절 보여주지 않는다.
    if admin_locked:
        # 관리자 모드를 골랐는데 인증 전이면, 근로자 화면으로 흘려보내지 않는다.
        # 그러면 "관리자 모드가 안 된다"로 보여 원인을 찾기 어렵다.
        st.warning("🔒 **관리자 인증이 필요합니다.** "
                   "사이드바에서 관리자 비밀번호를 입력하세요.", icon="🔒")
        st.caption("비밀번호는 Streamlit Cloud → Manage app → Settings → Secrets 의 "
                   "`ADMIN_PW` 값입니다. 값 앞뒤 공백·따옴표가 섞이지 않았는지 "
                   "확인하세요.")
        st.caption("근로자용 화면을 보시려면 사이드바에서 «👷 근로자»를 선택하세요.")
        st.stop()

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
            st.error("🚫 " + day_tier.action_texts[-1], icon="🚨")

        st.divider()
        T.render_worker_check(day_tier.code)

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

    # ⚠️ Streamlit은 모든 탭 본문을 매 실행마다 위에서부터 평가한다.
    #    명부 로딩을 탭 안에 두면 '휴식 알람'(먼저 평가)이 이전 명부를 쓰게 되므로
    #    탭보다 먼저 한 번만 로드한다.
    roster = st.session_state.get("_roster")
    if roster is None:
        roster = T.make_demo_roster()
        st.session_state["_roster"] = roster
    day_tbm = T.build_tbm(roster, day_tier.code)

    # ---- 격자별 예보 편의 보정 ----
    # 수집 데이터로 학습한 상수를 예보에만 더한다.
    # 현재값은 관측소 실측이므로 예보 오차가 없어 대상이 아니다.
    _nobias = {"applied": False, "correction": 0.0, "reason": "데모 모드"}
    if demo or fc_is_demo:
        fbias = _nobias
    else:
        try:
            fbias = C.forecast_bias(nx, ny)
        except Exception as e:
            fbias = {"applied": False, "correction": 0.0,
                     "reason": f"편의표 로드 실패 ({type(e).__name__})"}
    if fbias["applied"] and fbias["correction"]:
        fc = fc.copy()
        fc["at"] = (fc["at"] + fbias["correction"]).round(1)
        today_df = fc[fc["day"] == today]
        tmr_df = fc[fc["day"] == tomorrow]

    t1, t2, t6, t4, t7, t3 = st.tabs(
        [f"📅 오늘 ({today:%m/%d})", f"📅 내일 ({tomorrow:%m/%d})",
         "⏰ 알람", "👷 TBM 타겟 명단", "📝 조치 기록", "📖 법적 근거"])

    with t1:
        C.render_forecast_bias(fbias)
        if today_df.empty:
            st.warning("오늘 잔여 예보가 없습니다.")
        else:
            render_day(today_df, today, conservative, lead, strict)

    with t2:
        C.render_forecast_bias(fbias)
        if tmr_df.empty:
            st.warning("내일 예보 데이터가 없습니다.")
        else:
            render_day(tmr_df, tomorrow, conservative, lead, strict)

    with t6:
        st.caption("블록 진입 · 휴식 · 열순응 종료 알람을 한 곳에서 관리합니다.")
        _blocks = build_blocks(today_df, today, conservative) \
            if not today_df.empty \
            else pd.DataFrame()
        _tbm = day_tbm
        if _blocks.empty:
            st.warning("오늘 잔여 예보가 없습니다.")
        else:
            ba = build_alarms(_blocks, lead)
            if not ba.empty:
                st.markdown("##### 🚧 블록 진입 알람")
                st.caption("등급이 올라가는 구간에 들어가기 전 사전 통보")
                st.dataframe(ba[["발송시각", "대상 블록", "블록 시작", "등급", "체감온도"]],
                             hide_index=True, use_container_width=True)
                for _, a in ba.iterrows():
                    with st.expander(f"{a['발송시각']} → {a['대상 블록']} 진입"):
                        st.code(a["메시지"], language=None)
                st.divider()

            T.render_rest_alarm(_blocks, _tbm, lead, extra_min,
                                lambda b: rest_slots(b, strict),
                                now.strftime("%H:%M"))
            st.divider()
            T.render_acclim_alarm(_tbm, work_start, work_hours, lead,
                                  now.strftime("%H:%M"))

    with t4:
        st.caption("출역 데이터를 연동해 온열질환 민감군·열순응 대상자를 자동 선별합니다.")
        up = st.file_uploader(
            "출역 명부 CSV (미업로드 시 시연용 더미 사용)", type="csv",
            help="컬럼: " + ", ".join(T.ROSTER_COLUMNS))
        if up is not None:
            try:
                new_roster = T.normalize_roster(pd.read_csv(up))
                if not new_roster.equals(roster):
                    st.session_state["_roster"] = new_roster
                    st.rerun()          # 모든 탭이 같은 명부를 쓰도록 즉시 재실행
                st.success(f"출역 명부 {len(roster)}명 로드")
            except Exception as e:
                st.error(f"CSV 읽기 실패 → 기존 명부 유지\n\n`{e}`")
        else:
            st.caption("🟡 시연용 더미 명부 — 실제 현장에서는 출역시스템 CSV/DB 연동")

        st.divider()
        T.render_tbm_admin(roster, day_tier.code, day_tier.label, day_max)

    with t7:
        _b = build_blocks(today_df, today, conservative) if not today_df.empty \
            else pd.DataFrame()
        # 기록·보관은 법적 의무(제562조제2항제3호)다.
        # 데모 데이터가 실측인 것처럼 기록되면 안 되므로 실제 출처를 그대로 쓴다.
        if fc_is_demo:
            _src = "⚠️ 데모 데이터 (법적 기록 근거 없음)"
        elif fc_meta.get("ok"):
            _src = f"기상청 단기예보 (수집분 {fc_meta['base_dt']:%m/%d %H시} 발표)"
        else:
            _src = "기상청 격자(5km) 단기예보"
        if fbias.get("applied") and fbias.get("correction"):
            _src += f" · 격자 편의보정 {fbias['correction']:+.1f}℃"
        R.render(_b, today_df, today, name, _src,
                 int(roster["옥외작업"].sum()) if not roster.empty else 0,
                 lambda b: rest_slots(b, strict), tier_by_code, classify)

    with t3:
        st.dataframe(pd.DataFrame([{
            "체감온도": f"{t.min_temp:.0f}℃ 이상", "등급": t.label,
            "휴식": (f"{t.cycle_hours:.0f}시간마다 {t.rest_minutes}분"
                     if t.cycle_hours else "정기휴식 규정 없음"),
            "성격": t.legal, "주요 조치": t.action_texts[0],
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
        C.render_basis()
        st.divider()
        S.render_basis()
        st.divider()
        T.render_basis()


if __name__ == "__main__":
    # 어떤 경로로든 예외가 새어나가면 사용자에게는 빨간 트레이스백만 보인다.
    # 현장에서 쓰는 도구이므로 반드시 사람이 읽을 수 있는 안내로 바꾼다.
    try:
        main()
    except Exception as _e:                       # noqa: BLE001
        st.error("일시적인 오류가 발생했습니다. 잠시 후 새로고침해 주세요.\n\n"
                 "계속되면 사이드바에서 «데모 모드»를 켜고 시연을 진행하세요.",
                 icon="⚠️")
        with st.expander("오류 상세 (관리자 확인용)"):
            st.code(mask_secret(_e)[:1000], language=None)
