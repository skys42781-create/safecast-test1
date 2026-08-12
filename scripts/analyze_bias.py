"""
예보 편의(bias) 분석
=====================
수집된 예보·실황을 대상시각으로 조인해 Δ = 예보 − 실황 을 계산한다.

    python scripts/analyze_bias.py

[설계 원칙]
- 롤링 윈도우: 최근 N일만 사용. 기후변화보다 '수치예보 모델 업데이트'가
  더 급작스러운 위험이며, 최근 데이터만 쓰면 원인을 몰라도 자동으로 따라간다.
- 폭염기 한정: 겨울 Δ와 여름 Δ는 물리가 다르다(복사·증발산 조건).
  31℃ 이상 판정이 목적이므로 더운 날만 학습에 넣는다.
- 중앙값: 표본이 적을 때 회귀는 과적합한다. 중앙값이 이상값에도 강하다.
- 클리핑: Δ가 크게 튀면 학습이 아니라 고장 신호다. 보정은 미세조정이어야 한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"

WINDOW_DAYS = 45        # 롤링 윈도우
HALF_LIFE_DAYS = 14     # 가중치 반감기
MIN_TA = 25.0           # 이 기온 이상인 날만 학습 (폭염기 한정)
CLIP = 2.0              # 보정량 상한 (℃)
MIN_SAMPLES = 5         # 이보다 적으면 보정하지 않음


def load() -> pd.DataFrame:
    f, o = DATA / "forecast_log.csv", DATA / "obs_log.csv"
    if not f.exists() or not o.exists():
        raise SystemExit("데이터가 없습니다. 먼저 scripts/collect.py 를 돌리세요.")

    fc = pd.read_csv(f, parse_dates=["base_dt", "target_dt"])
    ob = pd.read_csv(o, parse_dates=["obs_dt"])

    m = fc.merge(ob, left_on=["site", "target_dt"], right_on=["site", "obs_dt"],
                 suffixes=("_f", "_o"))
    m["d_ta"] = m["ta_f"] - m["ta_o"]
    m["d_at"] = m["at_f"] - m["at_o"]
    m["hour"] = m["target_dt"].dt.hour
    m["age_days"] = (m["target_dt"].max() - m["target_dt"]).dt.total_seconds() / 86400
    return m


def summarize(m: pd.DataFrame) -> None:
    print(f"조인된 예보-실황 쌍: {len(m)}건")
    if m.empty:
        return
    print(f"기간: {m['target_dt'].min():%m/%d} ~ {m['target_dt'].max():%m/%d}")
    print()

    print("── 리드타임별 오차 ──")
    print(f"{'리드(h)':>8}{'N':>6}{'Δ중앙값':>10}{'MAE':>8}{'RMSE':>8}")
    m["lead_bin"] = pd.cut(m["lead_h"], [-1, 6, 12, 24, 36, 48],
                           labels=["0-6", "7-12", "13-24", "25-36", "37-48"])
    for b, g in m.groupby("lead_bin", observed=True):
        if g.empty:
            continue
        print(f"{str(b):>8}{len(g):>6}{g['d_at'].median():>+10.2f}"
              f"{g['d_at'].abs().mean():>8.2f}{np.sqrt((g['d_at']**2).mean()):>8.2f}")
    print()

    print("── 시간대별 체감온도 편의 (Δ = 예보 − 실황) ──")
    print(f"{'시각':>5}{'N':>6}{'Δ중앙값':>10}")
    for h, g in m.groupby("hour"):
        if len(g) >= 3:
            print(f"{h:>4}시{len(g):>6}{g['d_at'].median():>+10.2f}")
    print()


def learn_correction(m: pd.DataFrame) -> pd.DataFrame:
    """시간대 × 리드타임 구간별 보정값. 최근 데이터에 가중치를 둔다."""
    hot = m[(m["age_days"] <= WINDOW_DAYS) & (m["ta_o"] >= MIN_TA)].copy()
    if hot.empty:
        print("⚠️ 학습 조건(폭염기·윈도우)을 만족하는 표본이 없습니다.")
        return pd.DataFrame()

    hot["w"] = 0.5 ** (hot["age_days"] / HALF_LIFE_DAYS)
    hot["lead_bin"] = pd.cut(hot["lead_h"], [-1, 12, 24, 48],
                             labels=["0-12", "13-24", "25-48"])

    rows = []
    for (h, lb), g in hot.groupby(["hour", "lead_bin"], observed=True):
        if len(g) < MIN_SAMPLES:
            continue
        # 가중 중앙값 대신, 가중치 상위 표본의 중앙값으로 근사 (표본이 적을 때 안정적)
        med = float(np.median(np.repeat(g["d_at"].values,
                                        np.maximum((g["w"] * 10).round().astype(int), 1))))
        rows.append({"hour": h, "lead_bin": str(lb), "n": len(g),
                     "correction": round(float(np.clip(-med, -CLIP, CLIP)), 2)})

    out = pd.DataFrame(rows)
    if not out.empty:
        out.to_csv(DATA / "bias_correction.csv", index=False, encoding="utf-8")
        print("── 학습된 보정값 (예보에 더할 값) ──")
        print(out.to_string(index=False))
        print(f"\n→ data/bias_correction.csv 저장")
        print(f"   (표본 {MIN_SAMPLES}건 미만 구간은 보정하지 않음, 상한 ±{CLIP}℃)")
    else:
        print(f"⚠️ 구간별 표본이 {MIN_SAMPLES}건 미만입니다. 더 모아야 합니다.")
    return out


def improvement(m: pd.DataFrame, corr: pd.DataFrame) -> None:
    """보정 전후 RMSE 비교 — 발표에서 쓸 정량적 성과."""
    if corr.empty:
        return
    hot = m[m["ta_o"] >= MIN_TA].copy()
    if hot.empty:
        return
    hot["lead_bin"] = pd.cut(hot["lead_h"], [-1, 12, 24, 48],
                             labels=["0-12", "13-24", "25-48"]).astype(str)
    j = hot.merge(corr[["hour", "lead_bin", "correction"]],
                  on=["hour", "lead_bin"], how="left")
    j["correction"] = j["correction"].fillna(0.0)
    j["d_after"] = j["d_at"] + j["correction"]

    before = np.sqrt((j["d_at"] ** 2).mean())
    after = np.sqrt((j["d_after"] ** 2).mean())
    print()
    print("── 보정 효과 ──")
    print(f"  보정 전 RMSE: {before:.3f}℃")
    print(f"  보정 후 RMSE: {after:.3f}℃")
    print(f"  개선: {before - after:+.3f}℃ ({(before - after) / before * 100:+.1f}%)")
    print("  ⚠️ 같은 데이터로 학습·평가한 값이라 낙관적입니다.")
    print("     발표용으로는 학습기간과 검증기간을 나눠 다시 계산하세요.")


if __name__ == "__main__":
    m = load()
    summarize(m)
    c = learn_correction(m)
    improvement(m, c)
