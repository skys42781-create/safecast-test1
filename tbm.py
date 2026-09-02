"""
Safecast — TBM(작업 전 안전점검회의) 타겟 관리 모듈
====================================================
아침 조회에서 "오늘 누구를 집중 관리해야 하는가"를 자동 산출한다.

[이 기능이 필요한 이유 — 고용노동부 대응지침 19쪽]
    7년간('18~'24) 온열질환 산재 사망자 31명 중 25명(80.6%)이 투입 후 7일 이내 발생.
    투입 첫날 13명(41.9%), 둘째날 9명(29.0%), 3~7일 3명(9.7%).
    → 사망자의 41.9%가 '첫날'이다. 명단을 아침에 알아야 막을 수 있다.

[설계 원칙]
    ① 시스템은 '선별·기록'하고, '판정'하지 않는다.
       근로 금지·제한은 산업안전보건법 제138조상 의사의 진단 사항이다.
    ② 혈압 등 수치는 수집하지 않는다.
       폭염 관련 법령·지침에 판정 기준이 없고, 활용 못 할 민감정보 보관은
       개인정보 보호법의 최소수집 원칙에 반한다.
    ③ 질환명은 목록에 노출하지 않는다.
       산업안전보건법 제132조제2항 — 개별 근로자의 건강진단 결과는
       본인 동의 없이 공개할 수 없다.

[출처]
    고용노동부, 「온열질환 예방을 위한 폭염 대비 사업장 대응지침」, 2026.5
      · 민감군 대상 및 관리방법 … 18쪽
      · 열순응 프로그램 예시 …… 19쪽
      · 자각증상 점검표(행정안전부) … 18쪽
      · 35℃/38℃ 조치사항 ……… 14쪽
    질병관리청 폭염 취약집단 분석 (고령 65세 기준)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st

# =====================================================================
# SECTION A. 민감군 정의 (대응지침 18쪽 그대로)
# =====================================================================


@dataclass(frozen=True)
class SensitiveType:
    code: str
    no: str          # 지침상 번호
    label: str       # 화면 표시 (질환명 아님)
    detail: str      # 보건관리자용 상세
    auto: bool       # 출역 데이터로 자동 판정 가능한가


SENSITIVE_TYPES: list[SensitiveType] = [
    SensitiveType("chronic", "①", "만성질환 보유",
                  "고혈압, 저혈압, 당뇨, 뇌심혈관질환, 신장질환 등", False),
    SensitiveType("history", "②", "온열질환 기왕력",
                  "과거 온열질환 발생 이력", False),
    SensitiveType("elderly", "③", "고령자",
                  "만 65세 이상 (질병관리청: 65세 이상 중증화 위험 1.99배)", True),
    SensitiveType("medication", "④", "약물 복용",
                  "체온 조절·체액량 등 신체기능에 영향을 미치는 약물", False),
    SensitiveType("alcohol", "⑤", "알코올 의존", "알코올 의존이 있는 사람", False),
    SensitiveType("heavy", "⑥", "고강도 작업",
                  "형틀·철근·콘크리트타설·용접 등 전신 사용, 중량물 반복 취급, "
                  "삽질·망치질·톱질 등 공구 사용작업", True),
    SensitiveType("newcomer", "⑦", "신규배치자",
                  "열순응이 되지 않은 작업자", True),
    SensitiveType("acute", "⑧", "일시적 건강저하",
                  "전날 과음, 탈수 등", False),
]

# 지침 ⑥이 직접 예시로 든 공종. 출역 데이터의 공종만으로 자동 분류된다.
HEAVY_TRADES = ["형틀", "철근", "콘크리트타설", "용접", "비계", "철골"]

ELDERLY_AGE = 65   # 질병관리청 분석 기준 (30~64세 1.48배 → 65세 이상 1.99배)


def type_by_code(code: str) -> SensitiveType:
    return next(t for t in SENSITIVE_TYPES if t.code == code)


# =====================================================================
# SECTION B. 열순응 프로그램 (대응지침 19쪽 표 그대로)
# =====================================================================

# 신규직원(또는 온열질환 민감군)
ACCLIM_NEW = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}
# 복귀직원(이전에 열순응 되었으나 연속 7일 이상 작업하지 않은 근로자)
ACCLIM_RETURN = {1: 50, 2: 60, 3: 70, 4: 80, 5: 100}

ACCLIM_SRC = "고용노동부 대응지침(2026.5) 19쪽 「열순응 프로그램 예시」"


def acclim_ratio(day: int, is_return: bool) -> int | None:
    """투입 n일차의 허용 작업량(%). 6일차 이상은 제한 없음(None)."""
    table = ACCLIM_RETURN if is_return else ACCLIM_NEW
    return table.get(int(day))


# =====================================================================
# SECTION C. 자각증상 점검표 (행정안전부, 지침 18쪽)
# =====================================================================

SYMPTOMS = [
    "평소보다 높은 체온",
    "두통",
    "어지러움",
    "메스꺼움",
    "근육 경련",
    "지나치게 많은 땀을 흘림",
    "구역질",
    "갑작스런 피로감",
]

SYMPTOM_THRESHOLD = 2   # 2개 이상 "예" → 조치

SYMPTOM_ACTIONS = [
    "시원한 장소로 이동하세요",
    "옷을 느슨하게 하고 몸에 시원한 물을 적시고 선풍기 등으로 몸을 식히세요",
    "물을 섭취하도록 하여 수분을 보충하세요",
    "증상이 개선되지 않으면 즉시 119에 신고하세요",
]


# =====================================================================
# SECTION D. 출역 명부
# =====================================================================

ROSTER_COLUMNS = [
    "성명", "공종", "연령", "투입일차", "복귀자",
    "만성질환", "온열질환기왕력", "약물복용", "알코올의존", "일시적건강저하",
    "옥외작업",
]

# ⚠️ 질환명이 아니라 보유 여부(True/False)만 받는다.
#    구체적 병명을 수집하면 개인정보 보호법상 부담만 커지고 판정에는 쓰이지 않는다.


def make_demo_roster(n: int = 45, seed: int = 7) -> pd.DataFrame:
    """시연용 더미 출역 명부.

    실제 현장에서는 출역시스템 CSV/DB와 연동한다.
    학생 신분으로 실제 명부(민감정보)를 취득할 수 없으므로 더미로 대체한다.
    """
    rng = np.random.default_rng(seed)
    trades = HEAVY_TRADES + ["토공", "설비", "전기", "신호수", "조경"]
    return pd.DataFrame({
        "성명": [f"근로자{i:03d}" for i in range(1, n + 1)],
        "공종": rng.choice(trades, n),
        "연령": rng.integers(24, 72, n),
        "투입일차": rng.choice([1, 2, 3, 4, 5, 9, 20, 60], n,
                            p=[.07, .06, .05, .05, .04, .13, .25, .35]),
        "복귀자": rng.choice([True, False], n, p=[.12, .88]),
        "만성질환": rng.choice([True, False], n, p=[.16, .84]),
        "온열질환기왕력": rng.choice([True, False], n, p=[.05, .95]),
        "약물복용": rng.choice([True, False], n, p=[.09, .91]),
        "알코올의존": rng.choice([True, False], n, p=[.03, .97]),
        "일시적건강저하": rng.choice([True, False], n, p=[.08, .92]),
        "옥외작업": rng.choice([True, False], n, p=[.85, .15]),
    })


def normalize_roster(df: pd.DataFrame) -> pd.DataFrame:
    """업로드된 CSV를 표준 컬럼으로 보정. 없는 컬럼은 기본값으로 채운다."""
    out = df.copy()
    defaults = {
        "성명": "", "공종": "미상", "연령": 0, "투입일차": 999, "복귀자": False,
        "만성질환": False, "온열질환기왕력": False, "약물복용": False,
        "알코올의존": False, "일시적건강저하": False, "옥외작업": True,
    }
    for c, d in defaults.items():
        if c not in out.columns:
            out[c] = d
    for c in ["복귀자", "만성질환", "온열질환기왕력", "약물복용",
              "알코올의존", "일시적건강저하", "옥외작업"]:
        out[c] = out[c].astype(str).str.strip().str.lower().isin(
            ["true", "1", "y", "yes", "예", "o", "ㅇ"]) | (out[c] == True)  # noqa: E712
    for c in ["연령", "투입일차"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    return out[ROSTER_COLUMNS]


# =====================================================================
# SECTION E. 민감군 판정
# =====================================================================

def classify_worker(row: pd.Series) -> list[str]:
    """지침 8유형 중 해당하는 코드 목록을 반환."""
    hit = []
    if row["만성질환"]:
        hit.append("chronic")
    if row["온열질환기왕력"]:
        hit.append("history")
    if row["연령"] >= ELDERLY_AGE:
        hit.append("elderly")
    if row["약물복용"]:
        hit.append("medication")
    if row["알코올의존"]:
        hit.append("alcohol")
    if any(t in str(row["공종"]) for t in HEAVY_TRADES):
        hit.append("heavy")
    if acclim_ratio(row["투입일차"], row["복귀자"]) is not None:
        hit.append("newcomer")
    if row["일시적건강저하"]:
        hit.append("acute")
    return hit


def build_tbm(roster: pd.DataFrame, tier_code: str) -> pd.DataFrame:
    """TBM 타겟 명단 생성.

    tier_code: 당일 통제 등급 (CRITICAL=38℃ 이상, SEVERE=35℃ …)
    """
    df = roster[roster["옥외작업"]].copy()
    if df.empty:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        hits = classify_worker(r)
        if not hits:
            continue

        ratio = acclim_ratio(r["투입일차"], r["복귀자"])
        track = "복귀" if r["복귀자"] else "신규"

        # ---- 관리등급 ----
        # 38℃ 이상은 지침상 '민감군 옥외작업 제한'이 명시되어 있다.
        if tier_code == "CRITICAL":
            grade = "옥외작업 제한"
        elif ratio is not None and ratio <= 40:
            grade = "집중관찰"          # 열순응 초기 (사망자 70.9%가 1~2일차)
        elif ratio is not None:
            grade = "열순응 관리"
        else:
            grade = "집중관찰"

        # ---- 조치사항 (질환명 없이) ----
        act = []
        if tier_code == "CRITICAL":
            act.append("옥외작업 제한 [38℃ 이상]")
        if ratio is not None:
            act.append(f"{track} 열순응 {ratio}% ({r['투입일차']}일차)")
        act.append("휴식시간 추가 배정 · 작업시간 단축")

        rows.append({
            "성명": r["성명"],
            "공종": r["공종"],
            "관리등급": grade,
            "해당유형": len(hits),
            "조치사항": " / ".join(act),
            "_codes": ",".join(hits),
            "_ratio": ratio if ratio is not None else "",
            "_track": track if ratio is not None else "",
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {"옥외작업 제한": 0, "집중관찰": 1, "열순응 관리": 2}
    out["_o"] = out["관리등급"].map(order)
    return out.sort_values(["_o", "해당유형"], ascending=[True, False]).drop(columns="_o")


SHORT = {"chronic": "만성질환", "history": "기왕력", "elderly": "고령",
         "medication": "약물", "alcohol": "-", "heavy": "고강도",
         "newcomer": "", "acute": "컨디션"}


def short_reason(row: pd.Series) -> str:
    """명단에 붙일 짧은 사유. 질환명은 쓰지 않는다."""
    parts = []
    if row["_ratio"] != "":
        parts.append(f"{row['_track']} {row['_ratio']}%")
    for c in str(row["_codes"]).split(","):
        lab = SHORT.get(c, "")
        if lab and lab != "-":
            parts.append(lab)
    return " · ".join(parts[:3])


def build_acclim_schedule(tbm: pd.DataFrame, work_start: str, work_hours: float,
                          lead_min: int) -> pd.DataFrame:
    """열순응 대상자별 작업 종료 예정 시각.

    [왜 시각으로 바꾸는가]
      지침은 "1일 정상작업의 20%"라고 정하지만, 현장에서 필요한 것은
      "몇 시에 빼야 하는가"다. 비율만 표시하면 관리자가 매번 환산해야 하고,
      환산하지 않으면 지켜지지 않는다.

    [정상작업 시간]
      지침은 '정상작업'의 시간을 정의하지 않는다. 근로기준법 제50조의
      1일 법정근로시간 8시간을 기본값으로 두되 현장이 조정한다. (설정값)

    [주의]
      휴식시간을 제외한 실작업 기준이 아니라 작업시간대 기준의 단순 환산이다.
      실제 적용 시 휴식 부여분을 반영해 조정할 수 있다.
    """
    if tbm.empty:
        return pd.DataFrame()

    base = pd.Timestamp(f"2000-01-01 {work_start}")
    rows = []
    for _, r in tbm.iterrows():
        if r["_ratio"] == "":
            continue
        ratio = int(r["_ratio"])
        minutes = work_hours * 60 * ratio / 100
        end = base + pd.Timedelta(minutes=minutes)
        rows.append({
            "성명": r["성명"], "공종": r["공종"], "트랙": r["_track"],
            "허용": f"{ratio}%",
            "허용시간": f"{int(minutes // 60)}시간 {int(minutes % 60)}분",
            "종료예정": end.strftime("%H:%M"),
            "알람": (end - pd.Timedelta(minutes=lead_min)).strftime("%H:%M"),
            "_end": end.strftime("%H:%M"),
        })
    out = pd.DataFrame(rows)
    return out.sort_values("_end") if not out.empty else out


def render_acclim_alarm(tbm: pd.DataFrame, work_start: str, work_hours: float,
                        lead_min: int, now_hm: str) -> None:
    """열순응 종료 알람 — 시각별로 누구를 빼야 하는지."""
    sched = build_acclim_schedule(tbm, work_start, work_hours, lead_min)

    st.markdown("##### 🌡️ 열순응 작업 종료 알람")
    if sched.empty:
        st.info("열순응 프로그램 진행 중인 근로자가 없습니다.")
        return

    st.caption(f"정상작업 {work_hours:g}시간 · {work_start} 시작 기준 환산")

    # 종료시각이 같은 사람끼리 묶어서 알람 단위로
    for end, g in sched.groupby("_end", sort=True):
        past = end <= now_hm
        alarm = g.iloc[0]["알람"]
        names = " ".join(f"{r['성명']}({r['트랙']} {r['허용']})"
                         for _, r in g.iterrows())
        color = "#94A3B8" if past else "#B45309"
        tag = "종료됨" if past else f"📢 {alarm} 알람"
        st.markdown(
            f'''<div style="border-left:6px solid {color};background:#FFFBEB;
                    padding:12px 16px;border-radius:8px;margin-bottom:8px;
                    {"opacity:.5;" if past else ""}">
              <div style="font-size:12px;color:#78350F;">{tag}</div>
              <div style="font-size:22px;font-weight:800;color:{color};">
                  {end} 작업 종료 · {len(g)}명</div>
              <div style="font-size:12.5px;color:#78350F;">{names}</div>
            </div>''', unsafe_allow_html=True)

    st.dataframe(sched[["성명", "공종", "트랙", "허용", "허용시간", "종료예정", "알람"]],
                 hide_index=True, use_container_width=True)
    st.download_button("📥 열순응 일정 CSV",
                       sched.drop(columns="_end").to_csv(index=False).encode("utf-8-sig"),
                       file_name="열순응_일정.csv", mime="text/csv")

    st.markdown("###### 📢 전달 문구")
    for end, g in sched.groupby("_end", sort=True):
        alarm = g.iloc[0]["알람"]
        lines = "\n".join(f"  · {r['성명']} ({r['공종']}) — {r['트랙']} {r['허용']}"
                          for _, r in g.iterrows())
        msg = (f"[Safecast] {lead_min}분 후 열순응 대상자 작업 종료\n"
               f"· {end}까지만 폭염작업 후 철수 또는 실내 전환\n"
               f"{lines}\n"
               f"· 근거: 대응지침 19쪽 열순응 프로그램")
        with st.expander(f"{alarm} → {end} 종료 ({len(g)}명)"):
            st.code(msg, language=None)

    st.info("온열질환 산재 사망자의 **41.9%가 투입 첫날**, 29.0%가 둘째날에 "
            "발생했습니다. 1~2일차 대상자를 우선 확인하세요.")


def build_rest_alarms(blocks: pd.DataFrame, tbm: pd.DataFrame,
                      lead_min: int, extra_min: int,
                      rest_slots_fn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """휴식 시각별 알람 + 추가 배정 대상 명단.

    [근거]
      · 전원 휴식 — 체감온도 33℃ 이상 매 2시간 이내 20분 이상
        (안전보건규칙 제560조제3항, 법적 의무)
      · 추가 배정 — 온열질환 민감군·작업강도가 높은 작업자에게는 휴식시간 추가 배정
        (대응지침 14쪽 35·38℃ 조치, 18쪽 민감군 관리방법 ④)
      · 사전 알람 — 작업 마무리·이동·휴게시설 점검 리드타임 확보

    [추가 시간(extra_min)은 설정값]
      지침은 '추가 배정'을 요구하나 구체적 분량을 정하지 않는다. 현장이 정한다.
    """
    if tbm.empty:
        targets = pd.DataFrame(columns=["성명", "공종", "사유"])
    else:
        t = tbm.copy()
        t["사유"] = t.apply(short_reason, axis=1)
        targets = t[["성명", "공종", "사유"]]

    rows = []
    for _, b in blocks.iterrows():
        if not b["is_work"]:
            continue
        for slot in rest_slots_fn(b):
            start, end = slot["휴식 시작"], slot["휴식 종료"]
            ext_end = (pd.Timestamp(f"2000-01-01 {start}") +
                       pd.Timedelta(minutes=int(
                           (pd.Timestamp(f"2000-01-01 {end}") -
                            pd.Timestamp(f"2000-01-01 {start}")).seconds / 60
                           ) + extra_min)).strftime("%H:%M")
            send = (pd.Timestamp(f"2000-01-01 {start}") -
                    pd.Timedelta(minutes=lead_min)).strftime("%H:%M")
            rows.append({
                "발송시각": send, "휴식시작": start, "휴식종료": end,
                "추가종료(설정)": ext_end, "블록": b["block_name"],
                "등급": b["tier_label"], "근거": slot["근거"],
                "추가대상": len(targets),
            })
    return pd.DataFrame(rows), targets


def render_rest_alarm(blocks: pd.DataFrame, tbm: pd.DataFrame, lead_min: int,
                      extra_min: int, rest_slots_fn, now_hm: str) -> None:
    """휴식 알람 화면 — 시각별 대상 명단까지."""
    st.subheader("⏰ 휴식 알람 · 추가 배정 대상")

    alarms, targets = build_rest_alarms(blocks, tbm, lead_min, extra_min,
                                        rest_slots_fn)
    if alarms.empty:
        st.info("정기 휴식 부여 기준(체감온도 33℃) 미도달 — 예정된 휴식 알람이 없습니다.")
        st.caption("31℃ 이상이면 적절한 휴식을 부여해야 하나, 시각이 정해지지 않습니다.")
        return

    # ---- 다음 휴식 ----
    nxt = alarms[alarms["휴식시작"] >= now_hm]
    if not nxt.empty:
        r = nxt.iloc[0]
        st.markdown(
            f'''<div style="background:#1E293B;color:#fff;padding:16px 20px;
                    border-radius:10px;margin-bottom:12px;">
              <div style="font-size:13px;opacity:.85;">다음 휴식 · {r["블록"]}</div>
              <div style="font-size:32px;font-weight:800;line-height:1.2;">
                  {r["휴식시작"]} ~ {r["휴식종료"]}</div>
              <div style="font-size:14px;opacity:.9;">
                  전원 휴식 · 추가 배정 {r["추가대상"]}명은 {r["추가종료(설정)"]}까지</div>
              <div style="font-size:12px;opacity:.75;margin-top:4px;">
                  📢 {r["발송시각"]}에 알람을 전달하세요</div>
            </div>''', unsafe_allow_html=True)
    else:
        st.success("오늘 예정된 휴식이 모두 지났습니다.")

    st.dataframe(
        alarms[["발송시각", "휴식시작", "휴식종료", "추가종료(설정)", "블록", "등급", "근거"]],
        hide_index=True, use_container_width=True)

    # ---- 추가 배정 대상 명단 ----
    st.markdown(f"##### 휴식시간 추가 배정 대상 · {len(targets)}명")
    if targets.empty:
        st.info("추가 배정 대상이 없습니다.")
    else:
        st.dataframe(targets, hide_index=True, use_container_width=True,
                     height=min(320, 40 + 35 * len(targets)))
        st.caption("근거: 대응지침 14쪽(35·38℃ 조치) · 18쪽 민감군 관리방법 ④ "
                   "— 민감군·고강도 작업자는 휴식시간 추가 배정")
        st.caption("🔵 **추가 시간은 설정값** — 지침은 '추가 배정'을 요구하나 분량은 "
                   "미규정. 기본값 10분은 지침 우수사례(조선 A사 10분 연장, "
                   "건설 B사 20→30분)를 따름.")

    # ---- 발송 메시지 ----
    st.markdown("##### 📢 전달 문구")
    st.caption("현장 방송 또는 단톡방에 그대로 붙여넣으세요")
    for _, r in alarms.iterrows():
        names = " ".join(f"{n}({s})" for n, s in
                         zip(targets["성명"], targets["사유"])) if not targets.empty else "없음"
        msg = (f"[Safecast] {lead_min}분 후 휴식시간입니다\n"
               f"· {r['휴식시작']}~{r['휴식종료']} 전원 휴식 ({r['근거']})\n"
               f"· 추가 배정 {len(targets)}명 — {r['추가종료(설정)']}까지\n"
               f"  {names}\n"
               f"· 안전관리자: 휴게시설 냉방·음용수 상태를 지금 점검하세요")
        with st.expander(f"{r['발송시각']} → {r['휴식시작']} 휴식 ({r['블록']})"):
            st.code(msg, language=None)


def public_view(tbm: pd.DataFrame) -> pd.DataFrame:
    """TBM 조회용 — 질환명·상세 사유 없음. 아침 조회에서 화면에 띄우는 표."""
    return tbm[["성명", "공종", "관리등급", "조치사항"]]


def health_view(tbm: pd.DataFrame) -> pd.DataFrame:
    """보건관리자용 — 해당 유형 상세 포함. 열람 권한 분리 필요."""
    out = tbm.copy()
    out["해당유형상세"] = out["_codes"].apply(
        lambda s: " / ".join(f"{type_by_code(c).no}{type_by_code(c).label}"
                             for c in s.split(",") if c))
    return out[["성명", "공종", "관리등급", "해당유형상세", "조치사항"]]


# =====================================================================
# SECTION F. UI
# =====================================================================

BADGE = {
    "의무": ("#B91C1C", "🔴"),
    "권고": ("#C2410C", "🟠"),
    "설정": ("#1D4ED8", "🔵"),
    "미수집": ("#6B7280", "⚪"),
}


def badge(level: str, text: str) -> str:
    c, icon = BADGE[level]
    return (f'<span style="background:{c}18;color:{c};border:1px solid {c}55;'
            f'border-radius:5px;padding:1px 7px;font-size:11.5px;font-weight:600;'
            f'margin-right:5px;">{icon} {level} · {text}</span>')


def render_worker_check(day_tier_code: str = "NORMAL",
                        me: dict | None = None) -> None:
    """근로자 모드 — 자각증상 자가진단 중심.

    [왜 증상 체크를 맨 앞에 두는가]
      열사병 초기 증상은 판단력 저하를 동반한다. 어지러운 사람에게
      3단계 입력을 요구하면 도달하지 못한다. 주 동선은 짧을수록 안전하다.

    [왜 질환·나이·공종을 묻지 않는가]
      관리자가 출역 데이터로 이미 알고 있는 정보다. 근로자에게 다시 묻는 것은
      중복이며, 민감정보를 매번 입력하게 만드는 부담만 남는다.
      → 사전 선별은 TBM 명단(관리자), 실시간 감지는 이 화면(근로자)이 맡는다.

    [저장]
      증상 '개수'만 신고에 담기며, 종류·질환 정보는 저장하지 않는다.
    """
    # ---- 1) 지금 몸 상태 (주 동선) ----
    st.subheader("🩺 지금 몸 상태를 체크하세요")
    st.caption("행정안전부 온열질환 자각증상 점검표 · 10초면 됩니다")

    checked = []
    s1, s2 = st.columns(2)
    for i, sym in enumerate(SYMPTOMS):
        col = s1 if i < 4 else s2
        if col.checkbox(sym, key=f"sym_{i}"):
            checked.append(sym)

    # ⑧ 일시적 건강저하는 매일 바뀌므로 본인만 안다 (명부로 관리 불가)
    acute = st.checkbox("전날 과음했거나 잠을 못 잤음 / 탈수 느낌",
                        help="지침 민감군 ⑧ 일시적 건강상태 저하")

    st.divider()
    n = len(checked)

    # ---- 2) 결과 ----
    if n >= SYMPTOM_THRESHOLD:
        st.error(f"⚠️ 증상 {n}개 — 지금 즉시 아래 조치를 하고 "
                 "관리자·동료에게 알리세요", icon="🚨")
        for i, a in enumerate(SYMPTOM_ACTIONS, 1):
            st.markdown(f"**{i}.** {a}")
        st.markdown(
            '<div style="background:#7F1D1D;color:#fff;padding:16px;'
            'border-radius:8px;text-align:center;font-size:20px;font-weight:800;">'
            '증상이 개선되지 않으면 즉시 119</div>', unsafe_allow_html=True)
        st.caption("증상을 판단하기 어려운 경우에도 즉시 119에 신고 후 응급조치하세요.")
        st.divider()
        st.warning("📢 **지금 바로 관리자 또는 옆 동료에게 알리세요.** "
                   "혼자 참지 마세요.", icon="🗣️")
        st.caption("근거: 대응지침 18쪽 — 2개 이상의 증상이 있는 경우 "
                   "사업주 또는 동료근로자 등에게 알리고, 판단이 어려우면 즉시 119")

    elif n == 1:
        st.warning("증상 1개 — 시원한 곳에서 휴식하고 수분을 보충하세요. "
                   "증상이 하나라도 늘면 즉시 알리세요.")
    elif acute:
        st.warning("컨디션 저하 상태입니다. 오늘은 무리하지 말고 "
                   "휴식을 더 요청하세요. 관리자에게 미리 알리는 것이 좋습니다.")
    else:
        st.success("체크된 증상이 없습니다. 갈증을 느끼기 전에 물을 자주 드세요.")

    # ---- 2-1) 증상 신고 ----
    if n >= SYMPTOM_THRESHOLD and me:
        st.divider()
        try:
            import worker as W
            W.render_report(me, n)
        except Exception:
            pass

    # ---- 3) 내 열순응 단계 ----
    st.divider()
    if me and str(me.get("투입일차", "")).strip():
        # 등록 시 받은 값으로 자동 계산한다. 매번 다시 묻지 않는다.
        try:
            _day = int(float(me["투입일차"]))
            _ret = str(me.get("복귀자", "")).strip() == "예"
            _r = acclim_ratio(_day, _ret)
        except (ValueError, TypeError):
            _r = None
        if _r is not None:
            _tr = "복귀" if _ret else "신규 투입"
            st.markdown(
                f'<div style="background:#FEF3C7;border-left:6px solid #F59E0B;'
                f'padding:14px 16px;border-radius:8px;">'
                f'<div style="font-size:15px;color:#92400E;">오늘 허용 작업량</div>'
                f'<div style="font-size:34px;font-weight:800;color:#B45309;'
                f'line-height:1.2;">{_r}%</div>'
                f'<div style="font-size:13px;color:#78350F;">'
                f'{_tr} {_day}일차 · 정상 작업량의 {_r}%까지만 작업하세요</div>'
                f'</div>', unsafe_allow_html=True)
            if _day <= 2:
                st.error("⚠️ 온열질환 사망자의 **70.9%가 투입 1~2일차**에 "
                         "발생합니다. 무리하지 마세요.", icon="🚨")
            if day_tier_code == "CRITICAL":
                st.error("🚫 체감온도 38℃ 이상 — 민감군 옥외작업 제한 대상입니다. "
                         "관리자에게 배치 조정을 요청하세요.")
            st.caption(f"근거: {ACCLIM_SRC}")

    with st.expander("🔍 내 열순응 단계 직접 확인하기"):
        st.caption("처음 폭염작업을 하거나, 연속 7일 이상 쉬었다가 복귀한 경우")
        c1, c2 = st.columns(2)
        track = c1.radio("구분", ["신규 투입", "복귀(7일 이상 쉼)"], key="acc_track")
        day = c2.number_input("투입 며칠째", 1, 30, 1, key="acc_day")
        ratio = acclim_ratio(day, track.startswith("복귀"))
        if ratio is not None:
            st.markdown(
                f'<div style="background:#FEF3C7;border-left:6px solid #F59E0B;'
                f'padding:14px 16px;border-radius:8px;">'
                f'<div style="font-size:15px;color:#92400E;">오늘 허용 작업량</div>'
                f'<div style="font-size:34px;font-weight:800;color:#B45309;'
                f'line-height:1.2;">{ratio}%</div>'
                f'<div style="font-size:13px;color:#78350F;">'
                f'{track} {day}일차 · 정상 작업량의 {ratio}%까지만 작업하세요</div>'
                f'</div>', unsafe_allow_html=True)
            if day <= 2:
                st.error("⚠️ 온열질환 사망자의 **70.9%가 투입 1~2일차**에 발생합니다. "
                         "무리하지 마세요.", icon="🚨")
            if day_tier_code == "CRITICAL":
                st.error("🚫 체감온도 38℃ 이상 — 민감군 옥외작업 제한 대상입니다. "
                         "관리자에게 배치 조정을 요청하세요.")
        else:
            st.info("6일차 이상 — 열순응 프로그램이 완료되었습니다.")
        st.caption(f"근거: {ACCLIM_SRC}")

    # ---- 4) 권리 고지 ----
    st.info("""**내가 요청할 수 있는 것**

- 만성질환·고령(65세 이상)·신규배치·고강도 작업에 해당하면 **온열질환 민감군**입니다
- 민감군은 체감온도 31℃ 이상에서 **휴식시간 추가 배정**과 **작업시간 단축**을 받을 수 있습니다
- 건강상 이유로 **작업중지를 요청할 권리**가 있습니다""")

    st.caption("체크 내용은 저장되지 않습니다 · "
               "근거: 고용노동부 「폭염 대비 사업장 대응지침」(2026.5) 14·18~19쪽")


def render_tbm_admin(roster: pd.DataFrame, tier_code: str, tier_label: str,
                     day_max: float) -> None:
    """관리자 모드 — TBM 타겟 명단."""
    tbm = build_tbm(roster, tier_code)

    st.markdown(badge("권고", "대응지침 18~19쪽") +
                badge("미수집", "혈압 등 수치"), unsafe_allow_html=True)
    st.caption(f"당일 최고 체감온도 {day_max:.1f}℃ · {tier_label} 기준으로 산출")

    if tbm.empty:
        st.info("옥외작업 대상 중 민감군·열순응 해당자가 없습니다.")
        return

    out_n = int((tbm["관리등급"] == "옥외작업 제한").sum())
    m = st.columns(4)
    m[0].metric("출역 인원", f"{len(roster)}명")
    m[1].metric("옥외작업", f"{int(roster['옥외작업'].sum())}명")
    m[2].metric("TBM 타겟", f"{len(tbm)}명")
    m[3].metric("옥외작업 제한", f"{out_n}명",
                delta="38℃ 이상" if out_n else None, delta_color="off")

    if out_n:
        st.error(f"🚨 체감온도 38℃ 이상 — 민감군 {out_n}명 옥외작업 제한 대상입니다. "
                 "긴급조치 작업 외 옥외작업 중지를 함께 검토하세요.", icon="🚨")

    tab1, tab0, tab2, tab3 = st.tabs(
        ["📋 TBM 조회용", "✅ 컨디션 체크", "🩺 보건관리자용", "🌡️ 열순응 현황"])

    with tab0:
        render_condition_check(roster, tbm)

    with tab1:
        st.caption("아침 조회에서 화면에 띄우는 표 — 질환명·상세 사유 미표시")
        st.dataframe(public_view(tbm), hide_index=True, use_container_width=True,
                     height=420)
        st.download_button("📥 TBM 명단 CSV",
                           public_view(tbm).to_csv(index=False).encode("utf-8-sig"),
                           file_name="TBM_명단.csv", mime="text/csv")
        st.caption("ℹ️ 산업안전보건법 제132조제2항 — 개별 근로자의 건강진단 결과는 "
                   "본인 동의 없이 공개할 수 없습니다.")

    with tab2:
        st.caption("⚠️ 열람 권한 분리 대상 — 보건관리자·산업보건의만 접근")
        st.dataframe(health_view(tbm), hide_index=True, use_container_width=True,
                     height=420)
        st.download_button("📥 보건관리자용 CSV",
                           health_view(tbm).to_csv(index=False).encode("utf-8-sig"),
                           file_name="보건관리자용_명단.csv", mime="text/csv")

    with tab3:
        ac = tbm[tbm["_ratio"] != ""].copy()
        if ac.empty:
            st.info("열순응 프로그램 진행 중인 근로자가 없습니다.")
        else:
            ac["허용 작업량"] = ac["_ratio"].astype(int).astype(str) + "%"
            ac["트랙"] = ac["_track"]
            st.dataframe(ac[["성명", "공종", "트랙", "허용 작업량", "관리등급"]],
                         hide_index=True, use_container_width=True)

        st.markdown("##### 열순응 프로그램 (5일간 단계적 적용)")
        st.dataframe(pd.DataFrame([
            {"구분": "신규직원 (또는 민감군)", **{f"{d}일": f"{v}%"
                                          for d, v in ACCLIM_NEW.items()}},
            {"구분": "복귀직원 (연속 7일 이상 미작업)", **{f"{d}일": f"{v}%"
                                                for d, v in ACCLIM_RETURN.items()}},
        ]), hide_index=True, use_container_width=True)
        st.caption(f"출처: {ACCLIM_SRC}")
        st.info("온열질환 산재 사망자의 41.9%가 투입 첫날, 29.0%가 둘째날에 "
                "발생했습니다. (7년간 31명 중 25명이 7일 이내)")


def render_condition_check(roster: pd.DataFrame, tbm: pd.DataFrame) -> None:
    """TBM 컨디션 체크 — 관리자가 아침 조회에서 일괄 확인.

    [왜 관리자 입력인가]
      작업 중 개별 휴대폰 사용이 제한되는 현장이 많다. TBM은 전원이 모이고
      관리자가 독려할 수 있는 유일한 시점이므로, 입력을 이 시점에 몰아준다.
      (근로자 개별 입력은 시트 연동 후 전환 가능)

    [왜 이상자만 고르는가]
      60명을 한 명씩 체크하면 조회가 늘어지고, 늘어지면 안 하게 된다.
      '이상 없음'을 기본으로 두고 예외만 뽑아내는 것이 현장에서 돌아간다.

    [기록]
      안전보건규칙 제562조제2항제3호 — 체감온도와 조치사항을 일자별로 기록하고
      해당 연도 12월 31일까지 보관해야 한다. CSV로 내려받아 보관한다.
    """
    st.subheader("✅ TBM 컨디션 체크")
    st.caption("아침 조회에서 컨디션 이상자만 선택하세요 · 나머지는 이상 없음으로 처리됩니다")

    if roster.empty:
        st.info("출역 명부가 없습니다.")
        return

    names = roster["성명"].astype(str).tolist()
    target = set(tbm["성명"].tolist()) if not tbm.empty else set()

    picked = st.multiselect(
        "컨디션 이상자", names,
        format_func=lambda n: f"{n} ⚠️" if n in target else n,
        help="⚠️ 표시는 민감군·열순응 대상자입니다")

    if not picked:
        st.success(f"컨디션 이상자 없음 · 출역 {len(roster)}명 전원 정상")
        st.caption("이상자가 있으면 위에서 선택하세요.")
        return

    st.divider()
    REASONS = ["자각증상 있음", "전날 과음 / 수면부족", "몸살·감기 등", "기타"]

    rows = []
    for nm in picked:
        info = roster[roster["성명"].astype(str) == nm].iloc[0]
        flag = " · ⚠️ 민감군/열순응 대상" if nm in target else ""
        with st.container(border=True):
            st.markdown(f"**{nm}** · {info['공종']}{flag}")
            c1, c2 = st.columns([3, 1])
            rs = c1.multiselect("사유", REASONS, key=f"rsn_{nm}",
                                label_visibility="collapsed",
                                placeholder="사유 선택")
            cnt = c2.number_input("자각증상 개수", 0, 8, 0, key=f"cnt_{nm}")

            if cnt >= SYMPTOM_THRESHOLD:
                st.error(f"🚨 자각증상 {cnt}개 — **작업 투입 전 조치 필요**. "
                         "시원한 곳에서 휴식 후 상태 확인, 개선되지 않으면 119.")
                act = "작업 투입 보류 · 즉시 조치"
            elif cnt == 1 or rs:
                st.warning("⚠️ 집중관찰 대상 — 작업 중 주기적으로 상태를 확인하세요.")
                act = "집중관찰 · 휴식 추가 배정"
            else:
                act = "확인"

            rows.append({"성명": nm, "공종": info["공종"],
                         "사유": ", ".join(rs) if rs else "-",
                         "자각증상": cnt, "조치": act})

    st.divider()
    log = pd.DataFrame(rows)
    urgent = int((log["자각증상"] >= SYMPTOM_THRESHOLD).sum())

    m = st.columns(3)
    m[0].metric("이상자", f"{len(log)}명")
    m[1].metric("즉시 조치", f"{urgent}명",
                delta="투입 보류" if urgent else None, delta_color="off")
    m[2].metric("민감군 중복", f"{len(set(picked) & target)}명")

    if urgent:
        st.error(f"🚨 자각증상 2개 이상 {urgent}명 — 작업 투입 전 조치가 필요합니다.",
                 icon="🚨")

    st.dataframe(log, hide_index=True, use_container_width=True)
    st.download_button(
        "📥 TBM 컨디션 기록 CSV",
        log.to_csv(index=False).encode("utf-8-sig"),
        file_name="TBM_컨디션체크.csv", mime="text/csv")
    st.caption("ℹ️ 안전보건규칙 제562조제2항제3호 — 체감온도와 조치사항은 일자별로 "
               "기록하고 해당 연도 12월 31일까지 보관해야 합니다.")
    st.caption("⚠️ 화면을 새로고침하면 초기화됩니다. 조회 직후 CSV로 내려받으세요.")


def render_basis() -> None:
    """근거 탭 — 어떤 항목이 어떤 등급인지 한눈에."""
    st.markdown("#### 판정 근거 등급")
    st.dataframe(pd.DataFrame([
        {"항목": "33℃ 2시간 이내 20분 휴식", "등급": "🔴 의무",
         "근거": "안전보건규칙 제560조제3항"},
        {"항목": "체감온도·조치사항 일자별 기록·보관", "등급": "🔴 의무",
         "근거": "안전보건규칙 제562조제2항제3호"},
        {"항목": "민감군 8유형", "등급": "🟠 권고", "근거": "대응지침 18쪽"},
        {"항목": "열순응 20/40/60/80/100%", "등급": "🟠 권고", "근거": "대응지침 19쪽"},
        {"항목": "복귀자 50/60/70/80/100%", "등급": "🟠 권고", "근거": "대응지침 19쪽"},
        {"항목": "자각증상 2개 이상 조치", "등급": "🟠 권고",
         "근거": "대응지침 18쪽(행정안전부 점검표)"},
        {"항목": "38℃ 민감군 옥외작업 제한", "등급": "🟠 권고", "근거": "대응지침 14쪽"},
        {"항목": "고령 65세", "등급": "🟠 권고",
         "근거": "질병관리청 (65세 이상 중증화 위험 1.99배)"},
        {"항목": "피크 블록 14~17시", "등급": "🟠 권고",
         "근거": "대응지침 14쪽 무더위 시간대"},
        {"항목": "오전 블록 분할(2+2h)", "등급": "🔵 설정",
         "근거": "지침 미규정 · 보수적 MAX의 과대등급 완화 목적"},
        {"항목": "사전 알람 리드타임", "등급": "🔵 설정", "근거": "현장 규모별"},
        {"항목": "혈압 등 수치", "등급": "⚪ 미수집",
         "근거": "법령상 판정 기준 없음 · 제138조상 의사 판단"},
    ]), hide_index=True, use_container_width=True)

    st.markdown("""
#### 왜 혈압 수치를 수집하지 않는가
1. **폭염 관련 법령·지침에 수치 기준이 없다.** 대응지침은 민감군을 진단명으로만 열거한다.
2. **수치가 나오는 조문은 적용 대상이 다르다.** 시행규칙 제221조(고혈압증 등)는
   *고기압 업무*(잠수·압기)용이며, 그마저도 진단명만 열거한다.
3. **판정 권한이 의사에게 있다.** 산업안전보건법 제138조는 근로 금지·제한을
   의사의 진단에 따르도록 한다.

→ 판정할 수 없는 민감정보를 보관하면 개인정보 보호법상 최소수집 원칙에 반하고,
   사고 시 "알고도 방치했다"는 근거가 될 수 있다.

#### 개인정보 처리 근거와 제약
- **처리 근거** — 개인정보 보호법 제23조제1항제2호(법령이 민감정보 처리를 요구·허용).
  대응지침이 "민감군을 선정하고 적정 배치"할 것을 요구하므로 개인 식별이 불가피하다.
- **제약** — 산업안전보건법 제132조: ①본인 동의 없는 공개 금지 ②건강 보호·유지 외
  목적 사용 금지 → 목록에 질환명 미표시, 열람 권한 분리, CSV 2종 분리로 반영.

#### 의무와 권고는 무엇이 다른가
| | 성격 | 위반 시 |
|---|---|---|
| **안전보건규칙** (33℃ 2시간/20분 등) | 의무 | 산안법 제168조 — 5년 이하 징역 또는 5천만원 이하 벌금 |
| **폭염 대응지침** (열순응·민감군·35·38℃ 조치) | 권고 | 직접 처벌 없음 |

지침은 목차에서 스스로 「사업주의 온열질환 예방체계 마련(**권고**)」이라 밝히고 있으며,
문장도 "도입할 필요가 있습니다" 형태다.

#### 그럼에도 지침을 따라야 하는 이유
1. **보건조치 의무의 이행 판단 기준** — 산안법 제39조는 보건조치를 *의무*로 두고
   구체적 내용은 하위 규정에 위임한다. 이행 여부를 판단할 때 노동부 지침이
   사실상 기준으로 참조된다.
2. **예견가능성** — 고용노동부가 *"온열질환 산재 사망자의 41.9%가 투입 첫날"*을
   공개 문서로 공표했다. 그 위험을 알 수 있었다는 뜻이며,
   열순응 미이행 상태에서 신규 투입자가 첫날 사망하면 "몰랐다"는 방어가 어렵다.

→ 본 시스템은 **"권고니까 안 해도 된다"가 아니라 "권고지만 안 하면 위험하다"**를
   전제로 설계했다. 지침에 수치가 있는 항목(열순응 20/40/60/80/100 등)은 그대로 적용하고,
   수치가 없는 항목(민감군 추가 휴식 분량 등)만 현장 설정값으로 분리했다.

⚠️ 법적 논리는 산업보건 분야 전문가(노무사·직업환경의학전문의) 확인을 권장합니다.
""")
