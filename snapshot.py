"""
Safecast — 수집 스냅샷
=======================
GitHub Actions가 30분마다 쌓아 둔 data/*.csv 를 예보·실황의 공급원으로 쓴다.

[왜 필요한가]
  Streamlit Cloud에서 기상청 API로 나가는 연결이 간헐적으로 실패한다
  (ConnectTimeout). 같은 시각 GitHub Actions와 국내 브라우저에서는 정상이므로,
  기상청 장애가 아니라 배포 환경의 네트워크 문제다.

  이때 데모 데이터로 떨어지면 화면은 살지만 값이 가짜다.
  수집 스냅샷은 '실제 기상청 예보'이므로, API가 죽어도 진짜 값으로 동작한다.

    API 실패 → 데모        가짜 값. 판정에 쓸 수 없다.
    API 실패 → 스냅샷      실제 예보. 최대 30분 지연될 뿐이다.

[왜 라이브보다 먼저 시도하는가]
  단기예보는 3시간마다 갱신된다. 30분 전에 수집한 스냅샷과 지금 호출한 라이브는
  같은 발표본일 확률이 높다. 같은 값이라면 외부 호출 없이 즉시 뜨는 쪽이 낫다.
  스냅샷이 낡았거나 구간이 비면 None을 돌려주고 라이브로 넘어간다.

[한계]
  수집 지점(scripts/collect.py의 SITES)의 격자만 커버한다.
  다른 격자는 스냅샷이 없으므로 라이브 API를 써야 한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(__file__).resolve().parent / "data"
FCST_CSV = DATA / "forecast_log.csv"
OBS_CSV = DATA / "obs_log.csv"

# 발표본이 이보다 오래되면 쓰지 않는다.
# 단기예보는 3시간마다 발표되므로, 6시간이면 두 번을 놓친 셈이다.
MAX_FCST_AGE_H = 6

# 실황이 이보다 오래되면 '현재값'으로 부르기 어렵다.
MAX_OBS_AGE_H = 3

# 오늘·내일을 판정하려면 최소 이만큼의 시간이 있어야 한다.
MIN_HOURS = 12


# =====================================================================
# 로드
# =====================================================================

@st.cache_data(ttl=300, show_spinner=False)
def _load(path_str: str, dt_col: str) -> pd.DataFrame:
    """CSV 로드. 5분 캐시 — Actions가 30분마다 쓰므로 충분하다."""
    p = Path(path_str)
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(p)
        df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
        return df.dropna(subset=[dt_col])
    except Exception:
        return pd.DataFrame()


def _grid(df: pd.DataFrame, nx: int, ny: int) -> pd.DataFrame:
    """이 격자의 행만. 예보·실황 양쪽에 nx, ny가 저장되어 있다."""
    if df.empty or "nx" not in df.columns:
        return pd.DataFrame()
    return df[(df["nx"] == nx) & (df["ny"] == ny)]


# =====================================================================
# 예보
# =====================================================================

def forecast(nx: int, ny: int, now: datetime) -> tuple[pd.DataFrame | None, dict]:
    """수집된 최신 발표본의 예보.

    반환: (DataFrame[datetime, ta, rh] 또는 None, meta)
      meta: ok, base_dt, age_h, n, reason
    """
    meta = {"ok": False, "reason": ""}

    df = _load(str(FCST_CSV), "target_dt")
    if df.empty:
        meta["reason"] = "수집 예보 파일이 없습니다"
        return None, meta

    g = _grid(df, nx, ny)
    if g.empty:
        meta["reason"] = f"격자 ({nx}, {ny})는 수집 대상이 아닙니다"
        return None, meta

    g = g.copy()
    g["base_dt"] = pd.to_datetime(g["base_dt"], errors="coerce")
    g = g.dropna(subset=["base_dt"])
    if g.empty:
        meta["reason"] = "발표시각을 읽지 못했습니다"
        return None, meta

    base = g["base_dt"].max()
    age_h = (now - base.to_pydatetime()).total_seconds() / 3600
    meta.update({"base_dt": base.to_pydatetime(), "age_h": round(age_h, 1)})

    if age_h > MAX_FCST_AGE_H:
        meta["reason"] = (f"최신 발표본이 {age_h:.1f}시간 전이라 "
                          f"기준({MAX_FCST_AGE_H}시간)을 넘습니다")
        return None, meta

    # 최신 발표본만. 같은 대상시각이 여러 발표본에 있으므로 하나로 좁힌다.
    latest = g[g["base_dt"] == base]

    # 지금 이후만 쓴다. 지나간 시각은 예보가 아니라 과거다.
    cut = now.replace(minute=0, second=0, microsecond=0)
    fut = latest[latest["target_dt"] >= cut]
    if len(fut) < MIN_HOURS:
        meta["reason"] = (f"남은 예보가 {len(fut)}시간뿐입니다 "
                          f"(최소 {MIN_HOURS}시간 필요)")
        return None, meta

    out = (fut[["target_dt", "ta", "rh"]]
           .rename(columns={"target_dt": "datetime"})
           .drop_duplicates(subset="datetime")
           .sort_values("datetime")
           .reset_index(drop=True))

    meta.update({"ok": True, "n": len(out)})
    return out, meta


# =====================================================================
# 실황
# =====================================================================

def observation(nx: int, ny: int, now: datetime) -> tuple[dict | None, dict]:
    """수집된 최신 실황.

    반환: ({T1H, REH} 또는 None, meta)
      app.py가 fetch_now()와 같은 형식을 기대하므로 키 이름을 맞춘다.
    """
    meta = {"ok": False, "reason": ""}

    df = _load(str(OBS_CSV), "obs_dt")
    if df.empty:
        meta["reason"] = "수집 실황 파일이 없습니다"
        return None, meta

    g = _grid(df, nx, ny)
    if g.empty:
        meta["reason"] = f"격자 ({nx}, {ny})는 수집 대상이 아닙니다"
        return None, meta

    row = g.loc[g["obs_dt"].idxmax()]
    obs_dt = row["obs_dt"].to_pydatetime()
    age_h = (now - obs_dt).total_seconds() / 3600
    meta.update({"obs_dt": obs_dt, "age_h": round(age_h, 1)})

    if age_h > MAX_OBS_AGE_H:
        meta["reason"] = (f"최신 실황이 {age_h:.1f}시간 전이라 "
                          f"기준({MAX_OBS_AGE_H}시간)을 넘습니다")
        return None, meta

    try:
        ta, rh = float(row["ta"]), float(row["rh"])
    except (TypeError, ValueError):
        meta["reason"] = "실황 값을 읽지 못했습니다"
        return None, meta

    meta["ok"] = True
    return {"T1H": ta, "REH": rh}, meta


# =====================================================================
# 표시
# =====================================================================

def render_banner(meta: dict, label: str) -> None:
    """스냅샷을 썼음을 알린다.

    '지금 화면의 숫자가 어디서 왔는가'는 판정 근거의 일부다.
    30분 전 수집값을 실시간으로 오인하면 안 되므로 지연 시간을 함께 보여준다.
    """
    if not meta or not meta.get("ok"):
        return

    age = meta.get("age_h", 0)
    when = meta.get("base_dt") or meta.get("obs_dt")
    when_s = f"{when:%m/%d %H:%M}" if when else "?"

    st.info(
        f"🗄️ **{label}는 수집 스냅샷**입니다 — {when_s} 기준 "
        f"({age:.1f}시간 전). 기상청 API에 직접 연결하지 못해 "
        f"GitHub Actions가 수집해 둔 실제 예보값을 사용했습니다. "
        f"데모 데이터가 아닙니다.",
        icon="🗄️")
