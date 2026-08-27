"""
수집 데이터 진단
=================
    python scripts/check_data.py

[왜 필요한가]
  분석 결과에서 Δ 중앙값이 리드타임과 무관하게 동일하게 나왔다.
  예보는 보통 대상시각이 멀수록 오차가 커지므로, 이는 둘 중 하나다.
    (a) 기상청 예보가 실제로 그만큼 안정적이다
    (b) 조인이 잘못되어 같은 값이 반복 집계되고 있다
  데이터가 틀렸다면 보정값도 전부 무의미하므로, 분석보다 먼저 확인한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"


def load():
    f, o = DATA / "forecast_log.csv", DATA / "obs_log.csv"
    if not f.exists() or not o.exists():
        raise SystemExit("data/ 에 CSV가 없습니다. git pull 후 다시 실행하세요.")
    fc = pd.read_csv(f, parse_dates=["base_dt", "target_dt"])
    ob = pd.read_csv(o, parse_dates=["obs_dt"])
    return fc, ob


def section(t):
    print(f"\n{'=' * 62}\n{t}\n{'=' * 62}")


def main():
    fc, ob = load()

    # ---------------------------------------------------------------
    section("1. 수집 규모")
    print(f"  예보 {len(fc):,}행 · 실황 {len(ob):,}행")
    print(f"  예보 기간  {fc['target_dt'].min():%m/%d %H시} ~ "
          f"{fc['target_dt'].max():%m/%d %H시}")
    print(f"  실황 기간  {ob['obs_dt'].min():%m/%d %H시} ~ "
          f"{ob['obs_dt'].max():%m/%d %H시}")
    print(f"  지점  {sorted(fc['site'].unique())}")

    # ---------------------------------------------------------------
    section("2. 발표시각(base_dt)이 실제로 여러 개인가")
    # 같은 대상시각을 여러 발표본이 예보해야 리드타임 비교가 성립한다.
    nb = fc.groupby(["site", "target_dt"])["base_dt"].nunique()
    print(f"  대상시각당 발표본 수 — 평균 {nb.mean():.1f} · "
          f"최소 {nb.min()} · 최대 {nb.max()}")
    print(f"  전체 발표시각 종류: {fc['base_dt'].nunique()}개")
    print("  발표시각 분포:")
    print(fc["base_dt"].dt.hour.value_counts().sort_index().to_string())
    if nb.max() <= 1:
        print("  ⚠️ 대상시각마다 발표본이 1개뿐 → 리드타임 비교가 불가능합니다.")

    # ---------------------------------------------------------------
    section("3. 리드타임이 실제로 분포하는가")
    print(fc["lead_h"].describe().round(1).to_string())
    print("\n  리드타임 구간별 행 수:")
    b = pd.cut(fc["lead_h"], [-1, 6, 12, 24, 36, 48])
    print(b.value_counts().sort_index().to_string())

    # ---------------------------------------------------------------
    section("4. 같은 대상시각의 예보값이 발표본마다 다른가")
    # 발표본이 달라도 값이 똑같다면 리드타임 효과가 안 보이는 게 당연하다.
    g = fc.groupby(["site", "target_dt"])["ta"]
    spread = (g.max() - g.min())
    multi = nb[nb > 1].index
    if len(multi):
        sp = spread.loc[multi]
        print(f"  발표본 2개 이상인 대상시각: {len(sp):,}건")
        print(f"  같은 시각 예보값의 최대-최소 차이")
        print(f"    평균 {sp.mean():.2f}℃ · 중앙값 {sp.median():.2f}℃ · "
              f"최대 {sp.max():.2f}℃")
        print(f"    차이가 0인 비율: {(sp == 0).mean() * 100:.1f}%")
        if (sp == 0).mean() > 0.8:
            print("  ⚠️ 대부분의 발표본이 동일한 값 → 리드타임 효과가 나타날 수 없습니다.")
    else:
        print("  ⚠️ 발표본이 2개 이상인 대상시각이 없습니다.")

    # ---------------------------------------------------------------
    section("5. 조인 결과 점검")
    m = fc.merge(ob, left_on=["site", "target_dt"],
                 right_on=["site", "obs_dt"], suffixes=("_f", "_o"))
    print(f"  조인된 쌍: {len(m):,}건 (예보 {len(fc):,}행 중 "
          f"{len(m) / len(fc) * 100:.0f}%)")
    dup = m.duplicated(subset=["site", "base_dt", "target_dt"]).sum()
    print(f"  중복 행: {dup}건" + ("  ⚠️ 중복이 있습니다" if dup else ""))

    m["d_ta"] = m["ta_f"] - m["ta_o"]
    m["d_at"] = m["at_f"] - m["at_o"]
    print(f"\n  Δ기온  중앙값 {m['d_ta'].median():+.2f} · "
          f"RMSE {np.sqrt((m['d_ta'] ** 2).mean()):.2f}")
    print(f"  Δ체감  중앙값 {m['d_at'].median():+.2f} · "
          f"RMSE {np.sqrt((m['d_at'] ** 2).mean()):.2f}")

    # ---------------------------------------------------------------
    section("6. 리드타임별 오차 — 지점별로 분리")
    # 전체를 뭉치면 지점 간 차이에 가려질 수 있다.
    m["lead_bin"] = pd.cut(m["lead_h"], [-1, 6, 12, 24, 36, 48],
                           labels=["0-6", "7-12", "13-24", "25-36", "37-48"])
    piv = m.pivot_table(index="site", columns="lead_bin", values="d_at",
                        aggfunc=lambda x: np.sqrt((x ** 2).mean()),
                        observed=True).round(2)
    print(piv.to_string())

    # ---------------------------------------------------------------
    section("7. 시간대별 표본 균형")
    # 특정 시각의 표본이 유독 적으면 그 시간대 보정값을 신뢰하기 어렵다.
    cnt = m.groupby(m["target_dt"].dt.hour).size()
    print(f"  시간대별 표본 — 평균 {cnt.mean():.0f} · 최소 {cnt.min()}"
          f"({cnt.idxmin()}시) · 최대 {cnt.max()}({cnt.idxmax()}시)")
    thin = cnt[cnt < cnt.mean() * 0.5]
    if len(thin):
        print(f"  ⚠️ 표본이 평균의 절반 미만인 시각: "
              f"{[f'{h}시({n})' for h, n in thin.items()]}")
        print("     해당 시간대 보정값은 신뢰도가 낮습니다.")

    # ---------------------------------------------------------------
    section("8. 실황 결측·중복")
    print(f"  실황 시각 종류 {ob['obs_dt'].nunique():,} · "
          f"지점×시각 조합 {len(ob):,}")
    d2 = ob.duplicated(subset=["site", "obs_dt"]).sum()
    print(f"  중복 {d2}건" + ("  ⚠️" if d2 else ""))
    # 시간 연속성
    for s in sorted(ob["site"].unique()):
        t = ob[ob["site"] == s]["obs_dt"].sort_values()
        if len(t) < 2:
            continue
        gaps = t.diff().dt.total_seconds().div(3600).dropna()
        miss = int((gaps > 1.5).sum())
        print(f"    {s:<10} {len(t):>5}시각 · 1시간 초과 공백 {miss}회")

    # ---------------------------------------------------------------
    section("9. 판정")
    ok = True
    if nb.max() <= 1:
        print("  ❌ 발표본이 1개뿐 — 리드타임 분석 불가"); ok = False
    elif len(multi) and (spread.loc[multi] == 0).mean() > 0.8:
        print("  ❌ 발표본 간 값이 동일 — 리드타임 효과가 나타날 수 없음"); ok = False
    if dup:
        print("  ❌ 조인 결과에 중복 존재"); ok = False
    if ok:
        print("  ✅ 데이터 구조에 문제 없음")
        print("     리드타임별 오차가 비슷한 것은 기상청 예보의 실제 특성일 수 있습니다.")


if __name__ == "__main__":
    main()
