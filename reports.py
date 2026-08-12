"""
Safecast — 증상 신고 연동 (Google Sheets)
==========================================
근로자가 자각증상을 신고하면 구글 시트에 기록되고, 관리자 화면에서 확인·조치한다.

[왜 실명인가]
    지침은 자각증상 2개 이상이면 '사업주 또는 동료근로자에게 알리도록' 규정한다.
    "3공구에 증상자 있음"으로는 조치할 수 없다. 쉬게 하려면 누구인지 알아야 한다.

[그래서 무엇을 저장하지 않는가]
    · 증상의 '종류'  → 개수만 저장. 관리자는 개수만 보고 가서 대면 확인한다.
    · 질환·약물·음주 → 본인 화면에만 표시하고 저장하지 않는다.
    · 혈압 등 수치    → 애초에 수집하지 않는다.
    실명이 남는 만큼 나머지 흔적은 최소화한다.
    (산업안전보건법 제132조제3항 — 건강 보호·유지 외 목적 사용 금지)

[보존]
    폭염대책기간(5.15~9.30) 종료 시 신고 원본은 삭제하고,
    조치 이력(휴식 부여 등)만 남기는 것을 권장한다.

필요 패키지:
    gspread, google-auth
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

HEADERS = ["시각", "이름", "구역", "증상개수", "처리상태"]
STATUS = ["미확인", "확인함", "조치완료"]

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# =====================================================================
# 연결
# =====================================================================

def _secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def is_enabled() -> bool:
    """구글 시트 연동이 설정되어 있는가."""
    return bool(_secret("SHEET_ID")) and bool(_secret("gcp_service_account"))


@st.cache_resource(show_spinner=False)
def _sheet():
    """워크시트 핸들. 자격증명이 없거나 실패하면 None."""
    if not is_enabled():
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=_SCOPES)
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(st.secrets["SHEET_ID"]).sheet1

        # 헤더가 비어 있으면 세팅
        if not ws.row_values(1):
            ws.append_row(HEADERS)
        return ws
    except Exception as e:
        st.session_state["_sheet_error"] = str(e)
        return None


def last_error() -> str:
    return st.session_state.get("_sheet_error", "")


# =====================================================================
# 쓰기 / 읽기
# =====================================================================

def submit_report(name: str, zone: str, symptom_count: int) -> bool:
    """증상 신고 1건 기록. 증상 '종류'는 저장하지 않는다."""
    ws = _sheet()
    if ws is None:
        return False
    try:
        ws.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            name.strip(), zone.strip(), int(symptom_count), STATUS[0],
        ])
        load_reports.clear()          # 캐시 무효화 → 관리자 화면 즉시 반영
        return True
    except Exception as e:
        st.session_state["_sheet_error"] = str(e)
        return False


@st.cache_data(ttl=30, show_spinner=False)
def load_reports() -> pd.DataFrame:
    """신고 목록. 관리자 화면이 30초마다 갱신한다."""
    ws = _sheet()
    if ws is None:
        return pd.DataFrame(columns=HEADERS)
    try:
        rows = ws.get_all_records()
        df = pd.DataFrame(rows)
        return df if not df.empty else pd.DataFrame(columns=HEADERS)
    except Exception as e:
        st.session_state["_sheet_error"] = str(e)
        return pd.DataFrame(columns=HEADERS)


def update_status(row_index: int, status: str) -> bool:
    """처리상태 변경. row_index는 DataFrame 인덱스(0-based)."""
    ws = _sheet()
    if ws is None:
        return False
    try:
        ws.update_cell(row_index + 2, HEADERS.index("처리상태") + 1, status)
        load_reports.clear()
        return True
    except Exception as e:
        st.session_state["_sheet_error"] = str(e)
        return False


# =====================================================================
# UI — 근로자 신고 폼
# =====================================================================

def render_submit(symptom_count: int, default_zone: str = "") -> None:
    """근로자 화면 하단 — 관리자에게 알리기."""
    st.markdown("##### 📢 관리자에게 알리기")

    if not is_enabled():
        st.info("실시간 신고가 설정되지 않았습니다. "
                "이 화면을 관리자에게 직접 보여주세요.")
        return

    st.caption("증상 **개수**만 전달됩니다. 어떤 증상인지, 어떤 질환이 있는지는 "
               "저장되지 않습니다.")

    c1, c2 = st.columns(2)
    name = c1.text_input("이름", placeholder="홍길동")
    zone = c2.text_input("구역 / 공종", value=default_zone, placeholder="3공구 철근")

    disabled = not name.strip()
    if st.button("📢 관리자에게 알리기", type="primary",
                 use_container_width=True, disabled=disabled):
        if submit_report(name, zone, symptom_count):
            st.success("전달되었습니다. 시원한 곳에서 대기하세요.")
            st.balloons()
        else:
            st.error(f"전달 실패 — 구두로 알리세요.\n\n`{last_error()[:200]}`")
    if disabled:
        st.caption("⚠️ 조치를 위해 이름이 필요합니다. "
                   "익명으로는 휴식·배치 조정을 할 수 없습니다.")

    st.caption("ℹ️ 이 기록은 폭염 안전조치 목적으로만 사용되며, "
               "인사·평가에 활용되지 않습니다. (산업안전보건법 제132조제3항)")
    st.caption("🛑 근로자는 건강상 이유로 작업중지를 요청할 권리가 있습니다.")


# =====================================================================
# UI — 관리자 신고 현황
# =====================================================================

def render_admin_reports() -> None:
    """관리자 화면 — 증상 신고 현황 및 처리."""
    st.subheader("🚨 증상 신고 현황")

    if not is_enabled():
        st.info("구글 시트 연동이 설정되지 않았습니다. "
                "secrets에 SHEET_ID와 gcp_service_account를 등록하세요.")
        return

    df = load_reports()
    if last_error():
        st.error(f"시트 연결 오류\n\n`{last_error()[:300]}`")

    if df.empty:
        st.success("접수된 증상 신고가 없습니다.")
        st.caption("근로자가 자각증상 2개 이상을 신고하면 여기에 표시됩니다.")
        return

    # 오늘 것만 기본 표시
    today = datetime.now().strftime("%Y-%m-%d")
    df["_today"] = df["시각"].astype(str).str.startswith(today)
    only_today = st.toggle("오늘 신고만 보기", value=True)
    view = df[df["_today"]] if only_today else df

    pending = int((view["처리상태"] == "미확인").sum())
    m = st.columns(3)
    m[0].metric("신고 건수", f"{len(view)}건")
    m[1].metric("미확인", f"{pending}건",
                delta="즉시 확인" if pending else None, delta_color="off")
    m[2].metric("증상 3개 이상", f"{int((view['증상개수'] >= 3).sum())}건")

    if pending:
        st.error(f"🚨 미확인 신고 {pending}건 — 즉시 현장 확인이 필요합니다.", icon="🚨")

    st.dataframe(view[HEADERS], hide_index=True, use_container_width=True)

    st.markdown("##### 처리상태 변경")
    if view.empty:
        return
    c1, c2, c3 = st.columns([2, 1, 1])
    labels = {i: f"{r['시각']} · {r['이름']} · 증상 {r['증상개수']}개"
              for i, r in view.iterrows()}
    pick = c1.selectbox("대상", list(labels.keys()),
                        format_func=lambda i: labels[i])
    new = c2.selectbox("상태", STATUS)
    if c3.button("변경", use_container_width=True):
        if update_status(pick, new):
            st.success("변경되었습니다.")
            st.rerun()
        else:
            st.error("변경 실패")

    st.caption("ℹ️ 증상 '종류'와 질환 정보는 저장되지 않습니다. "
               "정확한 상태는 현장에서 직접 확인하세요.")
    st.caption("📅 신고 기록은 폭염대책기간(5.15~9.30) 종료 후 삭제를 권장합니다.")
