"""
보정 방법 비교 실험
====================
    python scripts/compare_corrections.py

[왜 필요한가]
  전국 단일 시간대별 보정은 학습·검증 분리 평가에서 오히려 나빠졌다(-3.9%).
  원인 후보가 여럿이므로, 추측 대신 여러 방법을 같은 조건에서 비교한다.

[비교하는 방법]
  none         보정 없음 (기준선)
  global_const 전국 상수 하나
  site_const   지점별 상수      ← 지점마다 편의 부호가 반대라는 관찰에서 나옴
  global_hour  전국 시간대별     (현재 analyze_bias.py 방식)
  site_hour    지점별 시간대별
  site_hour_lead 지점별 시간대x리드

[왜 롤링 검증인가]
  홀드아웃 한 번은 그 기간이 특이했을 뿐일 수 있다.
  잘라내는 시점을 옮겨가며 반복해야 우연과 실력이 구분된다.

[왜 등급 정확도도 보는가]
  RMSE를 줄이는 것이 목적이 아니다. 32.9도를 33.1도로 맞추는 것은 등급을 바꾸지만
  28.0도를 27.8도로 맞추는 것은 아무 의미가 없다.
  법정 판정은 31/33/35/38 경계이므로, 그 경계를 제대로 넘는지가 진짜 지표다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"

MIN_TA = 25.0
CLIP = 2.0
MIN_SAMPLES = 30
DEPRECATED_SITES = ["seoul_cityhall", "busan_cityhall", "daegu_cityhall"]

# 롤링 검증: 마지막 N일을 하루씩 옮겨가며 검증
FOLDS = 6
TEST_DAYS = 2
MIN_TRAIN_DAYS = 7

TIERS = [31.0, 33.0, 35.0, 38.0]


# =====================================================================
def load() -> pd.DataFrame:
    f, o = DATA / "forecast_log.csv", DATA / "obs_log.csv"
    if not f.exists() or not o.exists():
        raise SystemExit("데이터가 없습니다. git pull 후 다시 실행하세요.")
    fc = pd.read_csv(f, parse_dates=["base_dt", "target_dt"])
    ob = pd.read_csv(o, parse_dates=["obs_dt"])
    fc = fc[~fc["site"].isin(DEPRECATED_SITES)]
    ob = ob[~ob["site"].isin(DEPRECATED_SITES)]

    m = fc.merge(ob, left_on=["site", "target_dt"],
                 right_on=["site", "obs_dt"], suffixes=("_f", "_o"))
    m["d_at"] = m["at_f"] - m["at_o"]
    m["hour"] = m["target_dt"].dt.hour
    m["lead_bin"] = pd.cut(m["lead_h"], [-1, 12, 24, 48],
                           labels=["0-12", "13-24", "25-48"]).astype(str)

    # 표본이 심하게 적은 시간대는 어떤 방법에서도 제외
    cnt = m.groupby("hour").size()
    m = m[~m["hour"].isin(cnt[cnt < cnt.mean() * 0.5].index)]
    return m[m["ta_o"] >= MIN_TA].copy()


def tier_of(at: float) -> int:
    """체감온도 → 등급 인덱스 (0=평시 … 4=위험)."""
    return int(sum(at >= t for t in TIERS))


# =====================================================================
# 보정 방법들 — 학습 데이터에서 보정표를 만들고, 검증 데이터에 적용
# =====================================================================

def _median_table(tr: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    g = tr.groupby(keys, observed=True)["d_at"]
    tbl = g.agg(["median", "size"]).reset_index()
    tbl = tbl[tbl["size"] >= MIN_SAMPLES]
    tbl["corr"] = (-tbl["median"]).clip(-CLIP, CLIP)
    return tbl[keys + ["corr"]]


def fit_apply(name: str, tr: pd.DataFrame, te: pd.DataFrame) -> pd.Series:
    """방법 이름에 따라 학습·적용. 반환은 보정된 예보 체감온도."""
    if name == "none":
        return te["at_f"]

    if name == "global_const":
        c = float(np.clip(-tr["d_at"].median(), -CLIP, CLIP))
        return te["at_f"] + c

    keys = {"site_const": ["site"],
            "global_hour": ["hour"],
            "site_hour": ["site", "hour"],
            "site_hour_lead": ["site", "hour", "lead_bin"]}[name]

    tbl = _median_table(tr, keys)
    if tbl.empty:
        return te["at_f"]
    j = te.merge(tbl, on=keys, how="left")
    return te["at_f"].values + j["corr"].fillna(0.0).values


# =====================================================================
def evaluate(m: pd.DataFrame) -> pd.DataFrame:
    """롤링 검증. 각 폴드에서 학습·적용하고 지표를 모은다."""
    methods = ["none", "global_const", "site_const",
               "global_hour", "site_hour", "site_hour_lead"]
    end = m["target_dt"].max().normalize()
    acc = {k: {"se": [], "ae": [], "hit": [], "n": 0,
               "under": [], "over": []} for k in methods}
    used = 0

    for i in range(FOLDS):
        te_hi = end - pd.Timedelta(days=i * TEST_DAYS)
        te_lo = te_hi - pd.Timedelta(days=TEST_DAYS)
        tr = m[m["target_dt"] < te_lo]
        te = m[(m["target_dt"] >= te_lo) & (m["target_dt"] < te_hi)]
        if te.empty or tr.empty:
            continue
        span = (tr["target_dt"].max() - tr["target_dt"].min()).days
        if span < MIN_TRAIN_DAYS or len(te) < 200:
            continue
        used += 1

        true_tier = te["at_o"].map(tier_of).values
        for k in methods:
            pred = np.asarray(fit_apply(k, tr, te), dtype=float)
            err = pred - te["at_o"].values
            acc[k]["se"].extend(err ** 2)
            acc[k]["ae"].extend(np.abs(err))
            pt = np.array([tier_of(v) for v in pred])
            acc[k]["hit"].extend(pt == true_tier)
            # 안전 관점: 실제보다 낮은 등급으로 판정한 비율(과소평가)이 위험하다
            acc[k]["under"].extend(pt < true_tier)
            acc[k]["over"].extend(pt > true_tier)
            acc[k]["n"] += len(te)

    if used == 0:
        raise SystemExit("검증할 폴드를 만들지 못했습니다. 데이터가 더 필요합니다.")

    rows = []
    for k in methods:
        a = acc[k]
        rows.append({
            "방법": k,
            "RMSE": np.sqrt(np.mean(a["se"])),
            "MAE": np.mean(a["ae"]),
            "등급정확도%": np.mean(a["hit"]) * 100,
            "과소판정%": np.mean(a["under"]) * 100,
            "과대판정%": np.mean(a["over"]) * 100,
        })
    print(f"  롤링 검증 {used}회 · 폴드당 {TEST_DAYS}일")
    return pd.DataFrame(rows)


def per_site_bias(m: pd.DataFrame) -> None:
    """지점별로 편의 부호가 다른지 확인 — 전국 단일 보정이 실패하는 주된 이유."""
    print("\n── 지점별 편의 (전국 하나로 묶으면 상쇄된다) ──")
    t = m.groupby("site")["d_at"].agg(["median", "mean", "size"]).round(2)
    t.columns = ["Δ중앙값", "Δ평균", "N"]
    print(t.to_string())
    med = t["Δ중앙값"]
    if med.max() > 0 and med.min() < 0:
        print(f"  → 부호가 갈린다 (최대 {med.max():+.2f} / 최소 {med.min():+.2f}).")
        print("     전국 단일 보정은 서로 상쇄되어 어느 지점에도 맞지 않는다.")


def bias_stability(m: pd.DataFrame) -> None:
    """편의가 기간에 따라 변하는가 — 변하면 학습해도 검증기간에 안 맞는다."""
    print("\n── 편의의 시간적 안정성 (전반부 vs 후반부) ──")
    mid = m["target_dt"].min() + (m["target_dt"].max() - m["target_dt"].min()) / 2
    a = m[m["target_dt"] < mid].groupby("hour")["d_at"].median()
    b = m[m["target_dt"] >= mid].groupby("hour")["d_at"].median()
    j = pd.DataFrame({"전반부": a, "후반부": b}).dropna()
    j["차이"] = (j["후반부"] - j["전반부"]).round(2)
    print(j.round(2).to_string())
    inst = j["차이"].abs().mean()
    print(f"  평균 절대 변화 {inst:.2f}℃")
    if inst > 0.3:
        print("  → 편의가 기간에 따라 크게 변한다. 이는 예보 모델의 구조적 편의가")
        print("     아니라 해당 기간의 기상 패턴을 반영한 것일 가능성이 높다.")
    else:
        print("  → 편의가 비교적 안정적이다. 학습한 보정이 다른 기간에도 통할 여지가 있다.")


def main():
    m = load()
    print(f"분석 대상: {len(m):,}건 "
          f"({m['target_dt'].min():%m/%d} ~ {m['target_dt'].max():%m/%d}, "
          f"기온 {MIN_TA}℃ 이상)")

    per_site_bias(m)
    bias_stability(m)

    print("\n── 보정 방법 비교 (롤링 검증) ──")
    r = evaluate(m)
    base = r[r["방법"] == "none"].iloc[0]
    r["RMSE개선%"] = (base["RMSE"] - r["RMSE"]) / base["RMSE"] * 100
    r["등급개선%p"] = r["등급정확도%"] - base["등급정확도%"]
    print(r.round(3).to_string(index=False))

    best = r.loc[r["등급정확도%"].idxmax()]
    print(f"\n  등급정확도 최고: {best['방법']} "
          f"({best['등급정확도%']:.1f}%, 기준선 대비 {best['등급개선%p']:+.1f}%p)")
    print("\n  ※ 과소판정은 실제보다 낮은 등급으로 본 경우다. 휴식 미부여로 이어지므로")
    print("     과대판정보다 위험하며, RMSE가 같다면 과소판정이 적은 쪽을 택해야 한다.")


if __name__ == "__main__":
    main()
