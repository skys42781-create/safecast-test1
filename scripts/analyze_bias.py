"""
예보 편의(bias) 분석
=====================
수집된 예보·실황을 대상시각으로 조인해 Δ = 예보 − 실황 을 계산한다.

    python scripts/analyze_bias.py

[설계 원칙]
- 롤링 윈도우 — 기후변화보다 '수치예보 모델 업데이트'가 더 급작스러운 위험이며,
  최근 데이터만 쓰면 원인을 몰라도 자동으로 따라간다.
- 폭염기 한정 — 겨울 Δ와 여름 Δ는 물리가 다르다. 31℃ 이상 판정이 목적이므로
  더운 날만 학습에 넣는다.
- 중앙값 — 표본이 적을 때 회귀는 과적합한다. 중앙값이 이상값에도 강하다.
- 클리핑 — Δ가 크게 튀면 학습이 아니라 고장 신호다. 보정은 미세조정이어야 한다.

[진단으로 확인된 사실 — check_data.py]
- 동네예보는 발표본이 갱신되어도 예보값의 54%가 동일하다.
  → 리드타임에 따른 오차 차이가 거의 없고, 오차의 주된 구조는 '시간대'다.
- 수집 초기 지점명이 바뀌어 같은 지점이 두 이름으로 남아 있다(_cityhall 계열).
  → 중복 집계를 막기 위해 제외한다.
- API 실패로 실황에 공백이 있어 일부 시각(특히 9시)의 표본이 크게 부족하다.
  → 표본이 부족한 시간대는 보정하지 않는다.
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
MIN_SAMPLES = 30        # 구간별 최소 표본. 이보다 적으면 보정하지 않는다.
MIN_HOUR_RATIO = 0.5    # 시간대 표본이 평균의 이 비율 미만이면 제외

# 수집 초기에 쓰다가 이름을 바꾼 지점들. 같은 지점이 중복 집계된다.
DEPRECATED_SITES = ["seoul_cityhall", "busan_cityhall", "daegu_cityhall"]

# 검증용으로 떼어 둘 마지막 기간(일). 학습과 검증을 나눠야 정직한 수치가 나온다.
HOLDOUT_DAYS = 4


def load() -> pd.DataFrame:
    f, o = DATA / "forecast_log.csv", DATA / "obs_log.csv"
    if not f.exists() or not o.exists():
        raise SystemExit("데이터가 없습니다. 먼저 git pull 후 다시 실행하세요.")

    fc = pd.read_csv(f, parse_dates=["base_dt", "target_dt"])
    ob = pd.read_csv(o, parse_dates=["obs_dt"])

    # ---- (1) 중복 지점 제거 ----
    n0 = len(fc)
    fc = fc[~fc["site"].isin(DEPRECATED_SITES)]
    ob = ob[~ob["site"].isin(DEPRECATED_SITES)]
    if len(fc) < n0:
        print(f"  중복 지점 제외: {n0 - len(fc):,}행 "
              f"({', '.join(DEPRECATED_SITES)})")

    m = fc.merge(ob, left_on=["site", "target_dt"], right_on=["site", "obs_dt"],
                 suffixes=("_f", "_o"))
    m["d_ta"] = m["ta_f"] - m["ta_o"]
    m["d_at"] = m["at_f"] - m["at_o"]
    m["hour"] = m["target_dt"].dt.hour
    m["age_days"] = (m["target_dt"].max() - m["target_dt"]).dt.total_seconds() / 86400

    # ---- (2) 표본이 부족한 시간대 표시 ----
    cnt = m.groupby("hour").size()
    thin = set(cnt[cnt < cnt.mean() * MIN_HOUR_RATIO].index)
    if thin:
        print(f"  표본 부족 시간대(보정 제외): {sorted(thin)}시 "
              f"— 평균 {cnt.mean():.0f}건 대비 절반 미만")
    m["thin_hour"] = m["hour"].isin(thin)
    return m


def summarize(m: pd.DataFrame) -> None:
    print(f"\n조인된 예보-실황 쌍: {len(m):,}건")
    if m.empty:
        return
    print(f"기간: {m['target_dt'].min():%m/%d} ~ {m['target_dt'].max():%m/%d}")
    print(f"지점: {sorted(m['site'].unique())}")
    print()

    print("── 리드타임별 오차 ──")
    print(f"{'리드(h)':>8}{'N':>7}{'d중앙값':>10}{'MAE':>8}{'RMSE':>8}")
    m = m.copy()
    m["lead_bin"] = pd.cut(m["lead_h"], [-1, 6, 12, 24, 36, 48],
                           labels=["0-6", "7-12", "13-24", "25-36", "37-48"])
    for b, g in m.groupby("lead_bin", observed=True):
        if g.empty:
            continue
        print(f"{str(b):>8}{len(g):>7}{g['d_at'].median():>+10.2f}"
              f"{g['d_at'].abs().mean():>8.2f}{np.sqrt((g['d_at']**2).mean()):>8.2f}")
    print("  ※ 동네예보는 발표본이 갱신되어도 값의 절반 이상이 동일하므로")
    print("     리드타임에 따른 차이가 거의 나타나지 않는다. (check_data.py 참조)")
    print()

    print("── 시간대별 체감온도 편의 (d = 예보 − 실황) ──")
    print(f"{'시각':>5}{'N':>7}{'d중앙값':>10}   비고")
    for h, g in m.groupby("hour"):
        note = "표본부족 → 보정제외" if g["thin_hour"].iloc[0] else ""
        print(f"{h:>4}시{len(g):>7}{g['d_at'].median():>+10.2f}   {note}")
    print()

    print("── 지점별 오차 ──")
    piv = m.pivot_table(index="site", values="d_at",
                        aggfunc=[lambda x: x.median(),
                                 lambda x: np.sqrt((x ** 2).mean())])
    piv.columns = ["d중앙값", "RMSE"]
    print(piv.round(2).to_string())
    print()


def learn(m: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """시간대 x 리드타임 구간별 보정값. 최근 데이터에 가중치를 둔다."""
    hot = m[(m["age_days"] <= WINDOW_DAYS)
            & (m["ta_o"] >= MIN_TA)
            & (~m["thin_hour"])].copy()
    if hot.empty:
        if verbose:
            print("[!] 학습 조건(폭염기·윈도우·표본)을 만족하는 자료가 없습니다.")
        return pd.DataFrame()

    hot["w"] = 0.5 ** (hot["age_days"] / HALF_LIFE_DAYS)
    hot["lead_bin"] = pd.cut(hot["lead_h"], [-1, 12, 24, 48],
                             labels=["0-12", "13-24", "25-48"])

    rows = []
    for (h, lb), g in hot.groupby(["hour", "lead_bin"], observed=True):
        if len(g) < MIN_SAMPLES:
            continue
        med = float(np.median(np.repeat(
            g["d_at"].values,
            np.maximum((g["w"] * 10).round().astype(int), 1))))
        rows.append({"hour": h, "lead_bin": str(lb), "n": len(g),
                     "correction": round(float(np.clip(-med, -CLIP, CLIP)), 2)})
    return pd.DataFrame(rows)


def learn_site_const(m: pd.DataFrame) -> pd.DataFrame:
    """격자별 상수 편의.

    [왜 시간대별이 아니라 상수인가]
      compare_corrections.py 결과, 시간대별 편의는 2주 내에 평균 0.39도 변동했다.
      부호가 바뀌는 시각도 있어, 이는 예보 모델의 구조적 편의가 아니라
      해당 기간의 기상 패턴이다. 학습해도 다음 기간에 맞지 않는다.

      반면 격자별 상수 편의는 지형·토지피복이라는 물리적 원인이 있어 안정적이며,
      롤링 검증에서 RMSE 11.8% 개선, 과소판정 7.7%→6.6% 감소를 보였다.
      시간대별(site_hour)은 RMSE가 더 좋았으나 과소판정이 10.2%로 늘어
      안전 관점에서 채택하지 않았다.

    [왜 격자(nx, ny)를 키로 쓰는가]
      같은 격자면 같은 예보값이 나온다. 지점 이름이 아니라 격자로 묶어야
      임의 좌표의 현장에도 정확히 매칭된다.
    """
    hot = m[(m["age_days"] <= WINDOW_DAYS) & (m["ta_o"] >= MIN_TA)]
    if hot.empty or "nx" not in hot.columns:
        return pd.DataFrame()

    rows = []
    for (nx, ny), g in hot.groupby(["nx", "ny"]):
        if len(g) < MIN_SAMPLES * 10:      # 상수는 표본을 넉넉히 요구한다
            continue
        med = float(g["d_at"].median())
        rows.append({
            "nx": int(nx), "ny": int(ny),
            "site": g["site"].iloc[0],
            "n": len(g),
            "correction": round(float(np.clip(-med, -CLIP, CLIP)), 2),
        })
    return pd.DataFrame(rows)


def rmse(x: pd.Series) -> float:
    return float(np.sqrt((x ** 2).mean()))


def apply_corr(df: pd.DataFrame, corr: pd.DataFrame) -> pd.Series:
    if corr.empty:
        return df["d_at"]
    d = df.copy()
    d["lead_bin"] = pd.cut(d["lead_h"], [-1, 12, 24, 48],
                           labels=["0-12", "13-24", "25-48"]).astype(str)
    j = d.merge(corr[["hour", "lead_bin", "correction"]],
                on=["hour", "lead_bin"], how="left")
    j["correction"] = j["correction"].fillna(0.0)
    return j["d_at"] + j["correction"]


def holdout_eval(m: pd.DataFrame) -> None:
    """학습기간과 검증기간을 나눠 정직한 성능을 낸다.

    같은 데이터로 학습·평가하면 개선폭이 부풀려진다.
    발표에 쓸 수치는 반드시 이 결과여야 한다.
    """
    print("── 학습·검증 분리 평가 ──")
    cut = m["target_dt"].max() - pd.Timedelta(days=HOLDOUT_DAYS)
    tr = m[m["target_dt"] <= cut]
    te = m[m["target_dt"] > cut]
    print(f"  학습 {tr['target_dt'].min():%m/%d} ~ {cut:%m/%d}  ({len(tr):,}건)")
    print(f"  검증 {cut:%m/%d} ~ {te['target_dt'].max():%m/%d}  ({len(te):,}건)")

    if len(te) < 100 or tr.empty:
        print("  [!] 검증 표본이 부족합니다. 데이터가 더 쌓인 뒤 다시 평가하세요.")
        return

    corr = learn(tr, verbose=False)
    if corr.empty:
        print("  [!] 학습기간에서 보정값을 만들지 못했습니다.")
        return

    hot_te = te[te["ta_o"] >= MIN_TA]
    if hot_te.empty:
        print("  [!] 검증기간에 폭염기 자료가 없습니다.")
        return

    before = rmse(hot_te["d_at"])
    after = rmse(apply_corr(hot_te, corr))
    print(f"\n  검증기간 RMSE   보정 전 {before:.3f}도 -> 보정 후 {after:.3f}도")
    print(f"  개선            {before - after:+.3f}도 "
          f"({(before - after) / before * 100:+.1f}%)")
    print("  ※ 학습에 쓰지 않은 기간으로 평가한 값이다. 발표에는 이 수치를 쓴다.")


def main():
    print("데이터 로드")
    m = load()
    summarize(m)

    corr = learn(m)
    if not corr.empty:
        corr.to_csv(DATA / "bias_correction.csv", index=False, encoding="utf-8")
        print("── 학습된 보정값 (예보에 더할 값) ──")
        print(corr.to_string(index=False))
        print(f"\n-> data/bias_correction.csv 저장")
        print(f"   (표본 {MIN_SAMPLES}건 미만 구간·표본부족 시간대는 보정하지 않음, "
              f"상한 ±{CLIP}도)")
    else:
        print(f"[!] 구간별 표본이 {MIN_SAMPLES}건 미만입니다. 더 모아야 합니다.")
    print()

    sc = learn_site_const(m)
    if not sc.empty:
        sc.to_csv(DATA / "site_bias.csv", index=False, encoding="utf-8")
        print("── 격자별 상수 편의 (예보에 더할 값) ──")
        print(sc.to_string(index=False))
        print("-> data/site_bias.csv 저장")
        print("   앱은 현장 좌표의 격자가 이 표에 있을 때만 보정합니다.")
        print("   (없으면 보정량 0 = 원본. 성능 하한이 보장됩니다)")
    print()

    holdout_eval(m)


if __name__ == "__main__":
    main()
