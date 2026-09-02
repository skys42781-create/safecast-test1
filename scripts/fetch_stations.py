"""
지상관측 지점목록 저장
========================
    python scripts/fetch_stations.py

[왜 파일로 내장하는가]
  관측소의 위치·고도는 몇 년에 한 번 바뀔 뿐이다. 매번 API로 받을 이유가 없다.
  그런데 배포 환경(Streamlit Cloud)에서 기상청 API 연결이 간헐적으로 막히고,
  그러면 기준 고도를 알 수 없어 고도 보정이 통째로 빠진다.

  지점목록을 파일로 두면 API 상태와 무관하게 기준 고도를 항상 확보할 수 있다.
  실황만 API로 받으면 되고, 실황이 막혀도 격자 실황 + 관측소 고도로 보정된다.

[기준 고도 = HT + HT_TA]
  HT     노장 해발고도(m)
  HT_TA  온도계 지상높이(m)
  기상청이 지점별로 공개하는 값이라, 격자 대표고도와 달리 확정된 숫자다.

산출:
    data/stations_asos.csv   종관기상관측(ASOS) 약 100지점
    data/stations_aws.csv    방재기상관측(AWS)  약 500지점
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent.parent / "data"
URL = "https://apihub.kma.go.kr/api/typ01/url/stn_inf.php"

# 실제 응답 컬럼 (help=1 헤더로 확인)
#   0 STN_ID  1 LON  2 LAT  3 STN_SP  4 HT  5 HT_PA  6 HT_TA
#   7 HT_WD  8 HT_RN  9 STN_AD  10 STN_KO  11 STN_EN  … 15+ LAW_ADDR
COL_ID, COL_LON, COL_LAT, COL_HT, COL_HT_TA, COL_NAME = 0, 1, 2, 4, 6, 10

DEFAULT_HT_TA = 1.5     # 온도계 높이가 비정상일 때 쓸 표준값


def has_hangul(s: str) -> bool:
    return any("\uac00" <= ch <= "\ud7a3" for ch in str(s))


def fetch(kind: str, key: str) -> pd.DataFrame:
    """kind: SFC(ASOS) 또는 AWS."""
    r = requests.get(URL, params={"inf": kind, "stn": "", "help": "1",
                                  "authKey": key}, timeout=(10, 30))
    r.raise_for_status()

    rows = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        v = line.split()
        try:
            stn = int(v[COL_ID])
            lon, lat = float(v[COL_LON]), float(v[COL_LAT])
            ht, ht_ta = float(v[COL_HT]), float(v[COL_HT_TA])
        except (ValueError, IndexError):
            continue

        # 남한 범위 밖이거나 고도가 비현실적이면 버린다.
        if not (32 < lat < 40 and 124 < lon < 132):
            continue
        if not (-50 <= ht <= 2500):
            continue
        if not (0 < ht_ta <= 30):
            ht_ta = DEFAULT_HT_TA

        name = v[COL_NAME] if len(v) > COL_NAME else f"지점{stn}"
        if not has_hangul(name):
            name = f"지점{stn}"

        rows.append({"stn_id": stn, "name": name, "lat": lat, "lon": lon,
                     "ht": ht, "ht_ta": ht_ta,
                     "ref_elev": round(ht + ht_ta, 2)})

    df = pd.DataFrame(rows).drop_duplicates(subset="stn_id")
    return df.sort_values("stn_id").reset_index(drop=True)


def main() -> int:
    key = os.environ.get("KMA_HUB_KEY", "").strip()
    if not key:
        # secrets.toml 에서 읽어본다 (로컬 실행 편의)
        try:
            import tomllib
            p = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
            with open(p, "rb") as f:
                cfg = tomllib.load(f)
            key = str(cfg.get("KMA_HUB_KEY") or cfg.get("KMA_KEY") or "").strip()
        except Exception:
            key = ""

    if not key:
        print("ERROR: API허브 authKey가 없습니다.", file=sys.stderr)
        print("  방법 1) set KMA_HUB_KEY=발급키   후 다시 실행", file=sys.stderr)
        print("  방법 2) .streamlit/secrets.toml 에 KMA_HUB_KEY 추가", file=sys.stderr)
        return 1

    DATA.mkdir(parents=True, exist_ok=True)
    ok = 0
    for kind, fname, label in [("SFC", "stations_asos.csv", "ASOS(종관)"),
                               ("AWS", "stations_aws.csv", "AWS(방재)")]:
        try:
            df = fetch(kind, key)
            if df.empty:
                print(f"  {label}: 0지점 — 응답을 파싱하지 못했습니다",
                      file=sys.stderr)
                continue
            df.to_csv(DATA / fname, index=False, encoding="utf-8")
            print(f"  {label}: {len(df)}지점 → data/{fname}")
            print(f"    고도 {df['ref_elev'].min():.0f}~{df['ref_elev'].max():.0f}m "
                  f"· 예) {df.iloc[0]['name']} {df.iloc[0]['ref_elev']:.0f}m")
            ok += 1
        except Exception as e:
            print(f"  {label}: 실패 — {type(e).__name__}: {e}", file=sys.stderr)

    if ok == 0:
        return 1
    print("\n→ 두 파일을 커밋하면 배포된 앱이 API 없이 관측소 고도를 읽습니다.")
    print("   git add data/stations_*.csv && git commit -m \"지점목록 내장\" && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
