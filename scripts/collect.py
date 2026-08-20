"""
Safecast 예보·실황 수집기
==========================
기상청 단기예보와 초단기실황을 주기적으로 저장해
'예보 − 실황' 편의(bias)를 학습할 데이터를 만든다.

[왜 지금부터 모아야 하는가]
    관측값은 1904년까지 소급 조회가 되지만, 지난 예보는 어디에도 보관되지 않는다.
    "8월 12일 05시에 발표한 8월 13일 15시 예보"는 오늘 저장하지 않으면 영영 사라진다.
    → 예보-실황 쌍은 수집을 시작한 날부터만 만들어진다.

[왜 같은 격자인가]
    ASOS 관측소를 쓰면 '관측소 위치 ≠ 예보 격자'라는 변수가 추가된다.
    같은 격자의 예보 vs 실황을 비교해야 순수한 예보 오차만 분리된다.

실행:
    KMA_KEY=... python scripts/collect.py

산출물:
    data/forecast_log.csv   예보 (같은 대상시각을 여러 발표본에서 중복 저장 → 리드타임 분석용)
    data/obs_log.csv        실황
"""

from __future__ import annotations

import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

# =====================================================================
# 설정
# =====================================================================

# 수집 대상 현장. 여러 곳을 동시에 모을 수 있다.
# 실제 대상 현장이 정해지면 좌표만 바꾸면 된다.
SITES = [
    {"name": "seoul",  "lat": 37.5665, "lon": 126.9780},
    {"name": "busan",  "lat": 35.1798, "lon": 129.0750},
]

# 예보 중 저장할 구간 (시간). 0~48이면 오늘~모레까지.
# D+1 편의보정이 목적이므로 48시간이면 충분하다.
MAX_LEAD_HOURS = 48

KST = timezone(timedelta(hours=9))
BASE_URL = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"
KEY_PARAM = "authKey"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FCST_CSV = DATA_DIR / "forecast_log.csv"
OBS_CSV = DATA_DIR / "obs_log.csv"

FCST_BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]


# =====================================================================
# 공통 계산 (app.py와 동일한 식을 사용해야 분석 결과가 일치한다)
# =====================================================================

def wet_bulb(ta: float, rh: float) -> float:
    rh = min(max(rh, 1.0), 100.0)
    return (ta * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
            + math.atan(ta + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


def apparent_temp(ta: float, rh: float) -> float:
    tw = wet_bulb(ta, rh)
    return round(-0.2442 + 0.55399 * tw + 0.45535 * ta
                 - 0.0022 * tw ** 2 + 0.00278 * tw * ta + 3.0, 1)


_RE, _GRID = 6371.00877, 5.0
_SLAT1, _SLAT2, _OLON, _OLAT, _XO, _YO = 30.0, 60.0, 126.0, 38.0, 43, 136


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
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
    theta *= sn
    return (int(ra * math.sin(theta) + _XO + 0.5),
            int(ro - ra * math.cos(theta) + _YO + 0.5))


# =====================================================================
# 발표시각 계산
# =====================================================================

def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def latest_fcst_base(now: datetime) -> datetime:
    """단기예보: 가장 최근 제공 완료된 발표시각 (발표 +10분 후 조회 가능)."""
    avail = [h for h in FCST_BASE_HOURS
             if now >= now.replace(hour=h, minute=10, second=0, microsecond=0)]
    if avail:
        return now.replace(hour=max(avail), minute=0, second=0, microsecond=0)
    y = now - timedelta(days=1)
    return y.replace(hour=23, minute=0, second=0, microsecond=0)


def latest_ncst_base(now: datetime) -> datetime:
    """초단기실황: 매시 정시 관측, 40분 이후 제공."""
    t = now - timedelta(hours=1) if now.minute < 40 else now
    return t.replace(minute=0, second=0, microsecond=0)


# =====================================================================
# API 호출
# =====================================================================

REQUEST_TIMEOUT = 10      # 정상 응답은 1~2초. 오래 기다릴 이유가 없다.
RETRY = 2                 # 일시 장애 대비 재시도
RETRY_WAIT = 3            # 재시도 간격(초)
CALL_GAP = 0.4            # 연속 호출 간 간격 — 초당 제한 회피
DEADLINE_SEC = 150        # 전체 예산. 초과하면 남은 지점을 건너뛰고 지금까지 것을 저장


def call(endpoint: str, key: str, **params) -> list[dict]:
    """API 호출. 일시 장애에 대비해 재시도한다.

    [왜 재시도가 필요한가]
      기상청 API는 간헐적으로 응답하지 않는다. 재시도 없이 두면
      그 회차 수집이 통째로 실패하고, 워크플로가 5분간 타임아웃을 기다린다.
    """
    last = None
    for attempt in range(1, RETRY + 1):
        try:
            time.sleep(CALL_GAP)
            r = requests.get(f"{BASE_URL}/{endpoint}", timeout=REQUEST_TIMEOUT,
                             params={KEY_PARAM: key, "pageNo": 1,
                                     "dataType": "JSON", **params})
            r.raise_for_status()
            return r.json()["response"]["body"]["items"]["item"]
        except Exception as e:
            last = e
            if attempt < RETRY:
                print(f"    재시도 {attempt}/{RETRY - 1} ({type(e).__name__})",
                      file=sys.stderr)
                time.sleep(RETRY_WAIT)
    raise last


def fetch_forecast(nx: int, ny: int, key: str, base: datetime) -> pd.DataFrame:
    items = call("getVilageFcst", key, numOfRows=1000,
                 base_date=base.strftime("%Y%m%d"),
                 base_time=base.strftime("%H00"), nx=nx, ny=ny)
    raw = pd.DataFrame(items)
    want = {"TMP": "ta", "REH": "rh"}
    raw = raw[raw["category"].isin(want)]
    w = raw.pivot_table(index=["fcstDate", "fcstTime"], columns="category",
                        values="fcstValue", aggfunc="first").reset_index()
    w.columns.name = None
    w = w.rename(columns=want)
    w["target_dt"] = pd.to_datetime(w["fcstDate"] + w["fcstTime"], format="%Y%m%d%H%M")
    for c in ["ta", "rh"]:
        w[c] = pd.to_numeric(w[c], errors="coerce")
    return w[["target_dt", "ta", "rh"]].dropna()


def fetch_ncst(nx: int, ny: int, key: str, base: datetime) -> dict:
    items = call("getUltraSrtNcst", key, numOfRows=100,
                 base_date=base.strftime("%Y%m%d"),
                 base_time=base.strftime("%H00"), nx=nx, ny=ny)
    return {i["category"]: float(i["obsrValue"]) for i in items}


# =====================================================================
# 저장 (중복 제거 후 append)
# =====================================================================

def append_dedup(path: Path, new: pd.DataFrame, keys: list[str]) -> int:
    """기존 CSV와 합쳐 keys 기준 중복을 제거하고 저장. 신규 행 수를 반환."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path)
        before = len(old)
        merged = pd.concat([old, new], ignore_index=True)
    else:
        before = 0
        merged = new
    merged = merged.drop_duplicates(subset=keys, keep="last")
    merged = merged.sort_values(keys)
    merged.to_csv(path, index=False, encoding="utf-8")
    return len(merged) - before


# =====================================================================
# 메인
# =====================================================================

def main() -> int:
    key = os.environ.get("KMA_KEY", "").strip()
    if not key:
        print("ERROR: 환경변수 KMA_KEY가 없습니다.", file=sys.stderr)
        return 1

    deadline = time.monotonic() + DEADLINE_SEC

    now = now_kst()
    fbase = latest_fcst_base(now)
    nbase = latest_ncst_base(now)
    print(f"[{now:%Y-%m-%d %H:%M} KST] 예보 base={fbase:%m/%d %H시} / 실황 base={nbase:%m/%d %H시}")

    fcst_rows, obs_rows = [], []

    for site in SITES:
        # 예산 초과 시 남은 지점을 포기하고 지금까지 모은 것을 저장한다.
        # 전부 잃는 것보다 일부라도 남기는 편이 낫다.
        if time.monotonic() > deadline:
            print(f"  ⏱ 시간 예산({DEADLINE_SEC}s) 초과 — 남은 지점 건너뜀",
                  file=sys.stderr)
            break
        nx, ny = latlon_to_grid(site["lat"], site["lon"])

        # ---- 예보 ----
        try:
            df = fetch_forecast(nx, ny, key, fbase)
            df["lead_h"] = ((df["target_dt"] - fbase).dt.total_seconds() / 3600).astype(int)
            df = df[(df["lead_h"] >= 0) & (df["lead_h"] <= MAX_LEAD_HOURS)]
            for r in df.itertuples():
                fcst_rows.append({
                    "site": site["name"], "nx": nx, "ny": ny,
                    "base_dt": fbase.strftime("%Y-%m-%d %H:00"),
                    "target_dt": r.target_dt.strftime("%Y-%m-%d %H:00"),
                    "lead_h": r.lead_h, "ta": r.ta, "rh": r.rh,
                    "at": apparent_temp(r.ta, r.rh),
                })
            print(f"  {site['name']}: 예보 {len(df)}건")
        except Exception as e:
            print(f"  {site['name']}: 예보 실패 — {e}", file=sys.stderr)

        # ---- 실황 ----
        try:
            n = fetch_ncst(nx, ny, key, nbase)
            if "T1H" in n and "REH" in n:
                obs_rows.append({
                    "site": site["name"], "nx": nx, "ny": ny,
                    "obs_dt": nbase.strftime("%Y-%m-%d %H:00"),
                    "ta": n["T1H"], "rh": n["REH"],
                    "at": apparent_temp(n["T1H"], n["REH"]),
                })
                print(f"  {site['name']}: 실황 {n['T1H']}℃ / {n['REH']}%")
        except Exception as e:
            print(f"  {site['name']}: 실황 실패 — {e}", file=sys.stderr)

    if not fcst_rows and not obs_rows:
        # 전 지점 실패 = 기상청 API 장애일 가능성이 높다.
        # 다음 회차(30분 뒤)에 같은 시각을 다시 시도하므로 데이터 손실은 제한적이다.
        print("⚠️ 수집된 데이터가 없습니다 — 기상청 API 응답 없음", file=sys.stderr)
        return 1

    if fcst_rows:
        n = append_dedup(FCST_CSV, pd.DataFrame(fcst_rows),
                         ["site", "base_dt", "target_dt"])
        print(f"→ forecast_log.csv  신규 {n}건")
    if obs_rows:
        n = append_dedup(OBS_CSV, pd.DataFrame(obs_rows), ["site", "obs_dt"])
        print(f"→ obs_log.csv  신규 {n}건")

    return 0


if __name__ == "__main__":
    sys.exit(main())
