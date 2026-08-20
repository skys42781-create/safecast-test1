"""
Safecast — 폭염 조치 기록
==========================
안전보건규칙 제562조제2항제3호
  "체감온도 및 조치사항을 일자별로 기록하여 해당 연도 12월 31일까지 보관"

[기록이 방어가 되는 두 갈래]
  ① 의무 이행 증명 — 기록 자체가 법적 요구사항이다. 없으면 그 자체로 위반.
  ② 예견가능성 방어 — 사고 시 "몰랐다"가 아니라 "알았고, 알았을 때 조치했다"를
     시각 순서로 보여줄 수 있어야 한다.
     온도만 적힌 기록은 오히려 '알고도 방치했다'의 증거가 된다.

[자동 / 수동의 경계]
  자동 — 시각·장소·출처·기온·습도·체감온도·등급·근거조문·조치사항·대상인원
  수동 — 조치 완료 확인, 미이행 사유
    ※ '조치를 실제로 했는가'는 물리적 사실이므로 시스템이 알 수 없다.
      시스템이 스스로 "이행함"이라 기록하면 그것은 허위 기록이며,
      근로 관련 판단은 법령상 사람의 영역이다. 의도적으로 남긴 수동 단계다.

[저장]
  현재는 세션 보관 + CSV 다운로드. Streamlit 세션은 새로고침 시 소멸하므로
  화면에 다운로드를 안내한다. 실운영 시 DB/시트 연동으로 대체.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

# =====================================================================
# 상수
# =====================================================================

# 시간별 원본 + 블록 판정값을 한 줄에 함께 남긴다.
#   원본  — 그 시각 실제로 얼마였는가 (감독 질의 대응)
#   판정  — 우리가 어떤 값으로 조치를 결정했는가 (보수적 MAX 적용 근거)
TEMP_LOG_COLS = ["일자", "시각", "작업장소", "측정출처", "기온", "습도",
                 "체감온도", "등급", "블록", "블록판정값", "블록등급",
                 "등급변동", "근거조문"]

ACTION_LOG_COLS = ["일자", "예정시각", "작업장소", "체감온도", "등급", "조치사항",
                   "근거조문", "대상인원", "이행여부", "조치시각", "미이행사유", "조치자"]

# 지침은 35℃ 옥외작업 중지에 "불가피한 경우 제외"를 허용한다.
# 미이행 사유를 남기지 않으면 단순 미이행으로 읽히므로, 사유 기록이 곧 면책 근거다.
NONCOMPLIANCE_REASONS = [
    "콘크리트 타설 연속작업 (중단 시 품질 결함)",
    "긴급 안전조치 수행 중",
    "크레인 인양 작업 진행 중",
    "고소작업 하강 불가 상황",
    "정전·설비 복구 등 긴급작업",
    "기타 (직접 입력)",
]

STATUS_DONE = "이행"
STATUS_NOT = "미이행"
STATUS_PENDING = "대기"


# =====================================================================
# 세션 저장소
# =====================================================================

def _init() -> None:
    st.session_state.setdefault("temp_log", [])
    st.session_state.setdefault("action_log", {})   # key: 예정시각+조치사항
    st.session_state.setdefault("officer", "")


def record_temp(target_date, hhmm: str, place: str, source: str,
                ta: float, rh: float, at: float, tier,
                block: str = "-", block_at: str = "-", block_tier: str = "-",
                changed: str = "") -> None:
    """시간별 온도 기록 1행. 같은 일자·시각·장소는 덮어쓴다."""
    _init()
    row = {
        "일자": str(target_date), "시각": hhmm, "작업장소": place,
        "측정출처": source, "기온": ta, "습도": rh, "체감온도": at,
        "등급": tier.label,
        "블록": block, "블록판정값": block_at, "블록등급": block_tier,
        "등급변동": changed,
        "근거조문": _article_of(tier),
    }
    log = st.session_state["temp_log"]
    for i, r in enumerate(log):
        if r["일자"] == row["일자"] and r["시각"] == row["시각"] \
                and r["작업장소"] == row["작업장소"]:
            log[i] = row
            return
    log.append(row)


def _article_of(tier) -> str:
    """등급별 근거 조문. 기록에 자동으로 붙어 '왜 이 조치인가'가 남는다."""
    if tier.min_temp >= 33.0:
        return "안전보건규칙 제560조제3항 (의무)"
    if tier.min_temp >= 31.0:
        return "안전보건규칙 제560조제2항 (의무)"
    return "-"


def temp_log_df() -> pd.DataFrame:
    _init()
    df = pd.DataFrame(st.session_state["temp_log"])
    return df[TEMP_LOG_COLS] if not df.empty else pd.DataFrame(columns=TEMP_LOG_COLS)


# =====================================================================
# 조치 항목 생성 (자동)
# =====================================================================

def build_action_items(blocks: pd.DataFrame, place: str, headcount: int,
                       rest_slots_fn, tier_by_code_fn) -> list[dict]:
    """블록·휴식 계획에서 '이행해야 할 조치' 목록을 자동 생성한다.

    관리자는 이 목록에 대해 완료 여부만 표시하면 된다.
    """
    items = []
    for _, b in blocks.iterrows():
        if not b["is_work"]:
            continue
        tier = tier_by_code_fn(b["tier_code"])

        # ---- 휴식 부여 ----
        for slot in rest_slots_fn(b):
            items.append({
                "예정시각": slot["휴식 시작"],
                "작업장소": f"{place} · {b['block_name']}",
                "체감온도": b["at_rep"],
                "등급": b["tier_label"],
                "조치사항": f"휴식 부여 ({slot['휴식 시작']}~{slot['휴식 종료']})",
                "근거조문": "안전보건규칙 제560조제3항 (의무)",
                "대상인원": headcount,
            })

        # ---- 옥외작업 중지 (35℃ 이상 권고) ----
        if b["stop_work"]:
            items.append({
                "예정시각": b["start"].strftime("%H:%M"),
                "작업장소": f"{place} · {b['block_name']}",
                "체감온도": b["at_rep"],
                "등급": b["tier_label"],
                "조치사항": "옥외작업 중지",
                "근거조문": "폭염 대응지침(2026.5) 14쪽 (권고)",
                "대상인원": headcount,
            })

    items.sort(key=lambda x: x["예정시각"])
    return items


def _key(item: dict) -> str:
    return f"{item['예정시각']}|{item['조치사항']}|{item['작업장소']}"


def get_status(item: dict) -> dict:
    _init()
    return st.session_state["action_log"].get(
        _key(item), {"이행여부": STATUS_PENDING, "조치시각": "",
                     "미이행사유": "", "조치자": ""})


def set_status(item: dict, status: str, reason: str = "") -> None:
    _init()
    st.session_state["action_log"][_key(item)] = {
        "이행여부": status,
        "조치시각": datetime.now().strftime("%H:%M") if status == STATUS_DONE else "",
        "미이행사유": reason,
        "조치자": st.session_state.get("officer", ""),
    }


def action_log_df(items: list[dict], target_date) -> pd.DataFrame:
    rows = []
    for it in items:
        s = get_status(it)
        rows.append({"일자": str(target_date), **it, **s})
    return pd.DataFrame(rows)[ACTION_LOG_COLS] if rows \
        else pd.DataFrame(columns=ACTION_LOG_COLS)


# =====================================================================
# UI
# =====================================================================

def render(blocks: pd.DataFrame, hourly: pd.DataFrame, target_date,
           place: str, source: str, headcount: int,
           rest_slots_fn, tier_by_code_fn, classify_fn) -> None:
    _init()
    st.subheader("📝 폭염 조치 기록")
    st.caption("안전보건규칙 제562조제2항제3호 — 체감온도·조치사항을 일자별로 기록하고 "
               "해당 연도 12월 31일까지 보관")

    # ---- 조치자 ----
    if not st.session_state["officer"]:
        st.warning("조치자를 먼저 입력하세요. 이후 모든 기록에 자동으로 기재됩니다.")
    c1, c2 = st.columns([2, 3])
    st.session_state["officer"] = c1.text_input(
        "조치자 (직책 + 성명)", value=st.session_state["officer"],
        placeholder="안전관리자 홍길동")
    c2.caption("‎")
    officer = st.session_state["officer"]

    st.divider()

    # ---- 1) 온도·등급 기록 (자동) ----
    st.markdown("##### ① 체감온도 기록 · 자동")
    st.caption("법령은 '일자별' 기록만 요구하나(제562조제2항제3호), 온열질환은 특정 "
               "시각에 발생하므로 **시간별 원본**과 **블록 판정값**을 함께 남깁니다.")

    if hourly.empty:
        st.info("예보 데이터가 없어 기록할 내용이 없습니다.")
    else:
        # 시각 → 소속 블록 매핑
        blk = {}
        if not blocks.empty:
            for _, b in blocks.iterrows():
                for h in range(b["start"].hour, b["end"].hour):
                    blk[h] = b

        prev = None
        for r in hourly.sort_values("hour").itertuples():
            t = classify_fn(r.at)
            b = blk.get(r.hour)

            # 등급 변동 표시 — "언제 알았는가"가 남아야 방어가 된다
            changed = ""
            if prev is not None and t.code != prev[0]:
                changed = f"{prev[1]} → {t.short}"
            prev = (t.code, t.short)

            record_temp(
                target_date, f"{r.hour:02d}:00", place, source,
                float(r.ta), float(r.rh), float(r.at), t,
                block=(b["block_name"] if b is not None else "-"),
                block_at=(f"{b['at_rep']}" if b is not None else "-"),
                block_tier=(tier_by_code_fn(b["tier_code"]).short
                            if b is not None else "-"),
                changed=changed)

        df = temp_log_df()
        st.dataframe(df, hide_index=True, use_container_width=True, height=320)

        n_change = int((df["등급변동"] != "").sum()) if not df.empty else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("기록 행수", f"{len(df)}행")
        c2.metric("등급 변동", f"{n_change}회")
        c3.metric("최고 체감온도", f"{df['체감온도'].max():.1f}℃" if not df.empty else "-")

        st.caption(f"측정출처: **{source}** · "
                   + ("현장 실측 (제562조제2항제1호 온·습도계)" if "실측" in source else
                      "현장 측정이 곤란하여 기상청 체감온도를 활용 "
                      "(안전보건규칙 제559조제4항)"))
        st.caption("**블록판정값**은 보수적 MAX를 적용한 조치 결정 기준입니다. "
                   "그 시각 실측값(체감온도 열)과 다를 수 있으며, 두 값을 모두 "
                   "남겨 판정 근거를 추적할 수 있게 했습니다.")

    st.divider()

    # ---- 2) 조치 이행 (반자동) ----
    st.markdown("##### ② 조치 이행 · 완료 확인만 수동")
    st.caption("시스템이 조치 항목·시각·근거를 자동 생성합니다. "
               "실제 이행 여부는 사람이 확인해야 기록의 신뢰성이 유지됩니다.")

    items = build_action_items(blocks, place, headcount,
                               rest_slots_fn, tier_by_code_fn) if not blocks.empty else []

    if not items:
        st.success("금일 이행할 법정 조치가 없습니다 (체감온도 33℃ 미도달).")
    else:
        done = sum(1 for it in items if get_status(it)["이행여부"] == STATUS_DONE)
        notd = sum(1 for it in items if get_status(it)["이행여부"] == STATUS_NOT)
        pend = len(items) - done - notd

        m = st.columns(4)
        m[0].metric("조치 항목", f"{len(items)}건")
        m[1].metric("이행", f"{done}건")
        m[2].metric("미이행", f"{notd}건")
        m[3].metric("대기", f"{pend}건",
                    delta="확인 필요" if pend else None, delta_color="off")

        if not officer:
            st.info("조치자를 입력하면 완료 처리를 할 수 있습니다.")

        for it in items:
            s = get_status(it)
            icon = {"이행": "✅", "미이행": "⚠️", "대기": "⬜"}[s["이행여부"]]
            with st.container(border=True):
                a, b_, c = st.columns([4, 2, 2])
                a.markdown(f"{icon} **{it['예정시각']} · {it['조치사항']}**")
                a.caption(f"{it['작업장소']} · {it['체감온도']}℃ {it['등급']} · "
                          f"대상 {it['대상인원']}명")
                a.caption(f"근거: {it['근거조문']}")

                if s["이행여부"] == STATUS_DONE:
                    b_.success(f"{s['조치시각']} 이행")
                    b_.caption(s["조치자"])
                elif s["이행여부"] == STATUS_NOT:
                    b_.error("미이행")
                    b_.caption(s["미이행사유"][:20])

                if c.button("✅ 완료", key=f"d_{_key(it)}",
                            use_container_width=True, disabled=not officer):
                    set_status(it, STATUS_DONE)
                    st.rerun()
                if c.button("⚠️ 미이행", key=f"n_{_key(it)}",
                            use_container_width=True, disabled=not officer):
                    st.session_state["pending_reason"] = _key(it)
                    st.rerun()

                # 미이행 사유 선택
                if st.session_state.get("pending_reason") == _key(it):
                    rs = st.selectbox("미이행 사유", NONCOMPLIANCE_REASONS,
                                      key=f"r_{_key(it)}")
                    extra = ""
                    if rs.startswith("기타"):
                        extra = st.text_input("사유 입력", key=f"e_{_key(it)}")
                    if st.button("사유 저장", key=f"s_{_key(it)}", type="primary"):
                        set_status(it, STATUS_NOT, extra or rs)
                        st.session_state.pop("pending_reason", None)
                        st.rerun()
                    st.caption("⚠️ 지침은 35℃ 옥외작업 중지에 '불가피한 경우 제외'를 "
                               "허용합니다. 사유를 남기지 않으면 단순 미이행으로 "
                               "기록됩니다.")

    st.divider()

    # ---- 3) 내보내기 ----
    st.markdown("##### ③ 기록 보관")
    t_df = temp_log_df()
    a_df = action_log_df(items, target_date)

    c1, c2 = st.columns(2)
    c1.download_button("📥 체감온도 기록 CSV",
                       t_df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"체감온도기록_{target_date}.csv",
                       mime="text/csv", use_container_width=True,
                       disabled=t_df.empty)
    c2.download_button("📥 조치 기록 CSV",
                       a_df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"조치기록_{target_date}.csv",
                       mime="text/csv", use_container_width=True,
                       disabled=a_df.empty)

    st.download_button("📄 일일 종합 기록 (온도 + 조치)",
                       _daily_report(t_df, a_df, target_date, place, officer),
                       file_name=f"폭염관리일지_{target_date}.csv",
                       mime="text/csv", use_container_width=True,
                       disabled=t_df.empty and a_df.empty)

    st.error("⚠️ **화면을 새로고침하면 기록이 초기화됩니다.** "
             "작업 종료 시 반드시 CSV를 내려받아 보관하세요. "
             "(실운영 시에는 DB 연동으로 자동 보관되어야 합니다.)")
    st.caption("보관 기한: 해당 연도 12월 31일 (안전보건규칙 제562조제2항제3호)")


def _daily_report(t_df: pd.DataFrame, a_df: pd.DataFrame, d, place: str,
                  officer: str) -> bytes:
    """감독 제출용 일일 종합. 두 기록을 한 파일에 담는다."""
    head = pd.DataFrame([{
        "구분": "일지 정보", "내용": f"일자 {d} / 현장 {place} / 작성자 {officer or '-'}"
    }, {
        "구분": "근거", "내용": "산업안전보건기준에 관한 규칙 제562조제2항제3호"
    }, {"구분": "", "내용": ""}])

    buf = head.to_csv(index=False)
    buf += "\n[체감온도 기록]\n" + t_df.to_csv(index=False)
    buf += "\n[조치 기록]\n" + a_df.to_csv(index=False)
    return buf.encode("utf-8-sig")