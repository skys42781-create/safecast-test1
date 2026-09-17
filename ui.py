"""
SAFECASTY — 목록 표시 (카드형)
================================
st.dataframe 대신 행을 카드로 그린다.

[왜 표를 쓰지 않는가]
  st.dataframe 은 엑셀 격자를 그대로 재현한다. 데스크톱에서 여러 열을
  비교할 때는 유용하지만, 이 시스템의 목록은 대부분 "누구를 어떻게 할지"를
  훑는 용도라 비교가 목적이 아니다. 좁은 화면에서는 가로 스크롤이 생겨
  읽을 수도 없다.

[언제 표를 남기는가]
  감사 대응용 원본 기록(시간별 체감온도)은 표가 맞다. 열이 많고
  정렬·복사가 필요하며, 사람이 훑는 게 아니라 근거로 제출하는 자료다.

[구현 메모]
  Streamlit 위젯 안에 HTML을 넣으면 iframe 격리 없이 그려지므로
  버튼 같은 조작은 여전히 Streamlit 위젯으로 따로 두어야 한다.
"""

from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

# 등급·상태별 강조색
ACCENT = {
    "위험": "#7F1D2D", "심각": "#B91C1C", "경계": "#C2410C",
    "주의": "#B45309", "평시": "#15803D",
    "미확인": "#DC2626", "확인함": "#B45309", "조치완료": "#15803D",
    "집중관찰": "#B91C1C", "열순응 관리": "#C2410C", "주의 관찰": "#B45309",
}


def _esc(v) -> str:
    return _html.escape("" if v is None else str(v))


def _accent(*vals: str) -> str:
    for v in vals:
        for k, c in ACCENT.items():
            if v and k in str(v):
                return c
    return "#8B95A1"


def card_list(rows: list[dict], *, title: str, meta: list[str],
              badge: str | None = None, body: str | None = None,
              empty: str = "표시할 항목이 없습니다.",
              limit: int | None = None) -> None:
    """행을 카드로 나열한다.

    title : 카드 제목으로 쓸 키
    meta  : 제목 아래 한 줄에 점으로 이어 붙일 키들
    badge : 우측 알약에 넣을 키 (등급·상태 등). 색은 값에서 추론한다.
    body  : 카드 하단에 줄바꿈해 넣을 키 (조치사항 등)
    limit : 이 수를 넘으면 나머지는 건수만 알린다
    """
    if not rows:
        st.caption(empty)
        return

    shown = rows if limit is None else rows[:limit]
    parts = ['<div style="display:flex;flex-direction:column;gap:6px">']

    for r in shown:
        bv = _esc(r.get(badge, "")) if badge else ""
        col = _accent(r.get(badge, ""), r.get(title, ""))
        ms = " · ".join(_esc(r[k]) for k in meta if k in r and str(r[k]).strip())
        bd = _esc(r.get(body, "")) if body else ""

        parts.append(
            f'<div style="background:#fff;border:1px solid rgba(29,31,32,.16);'
            f'border-left:3px solid {col};border-radius:2px;padding:12px 15px">'
            f'<div style="display:flex;align-items:center;'
            f'justify-content:space-between;gap:10px">'
            f'<div style="font-size:14px;font-weight:600;letter-spacing:-.3px">'
            f'{_esc(r.get(title, ""))}</div>'
            + (f'<div style="font-size:10.5px;font-weight:600;color:{col};'
               f'border:1px solid {col};padding:2px 9px;border-radius:2px;'
               f'letter-spacing:.4px;white-space:nowrap">{bv}</div>'
               if bv else "")
            + '</div>'
            + (f'<div style="font-size:11.5px;opacity:.55;margin-top:3px;'
               f'font-variant-numeric:tabular-nums">{ms}</div>' if ms else "")
            + (f'<div style="font-size:12.5px;opacity:.85;margin-top:6px;'
               f'line-height:1.55">{bd}</div>' if bd else "")
            + '</div>')

    parts.append('</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)

    if limit is not None and len(rows) > limit:
        st.caption(f"이 외 {len(rows) - limit}건")


def df_cards(df: pd.DataFrame, **kw) -> None:
    """DataFrame을 카드 목록으로."""
    if df is None or df.empty:
        st.caption(kw.get("empty", "표시할 항목이 없습니다."))
        return
    card_list(df.to_dict("records"), **kw)


def stat_row(items: list[tuple[str, str]]) -> None:
    """작은 지표 줄. st.metric 여러 개보다 가볍다."""
    if not items:
        return
    cells = "".join(
        f'<div style="flex:1 0 auto;min-width:96px">'
        f'<div style="font-size:11.5px;opacity:.6">{_esc(l)}</div>'
        f'<div style="font-size:19px;font-weight:600;letter-spacing:-.5px;'
        f'margin-top:2px">{_esc(v)}</div></div>'
        for l, v in items)
    st.markdown(
        f'<div style="display:flex;gap:20px;flex-wrap:wrap;background:#fff;'
        f'border:1px solid rgba(29,31,32,.16);border-radius:2px;'
        f'padding:13px 16px;margin-bottom:8px">{cells}</div>',
        unsafe_allow_html=True)


def summary_grid(cards: list[dict]) -> None:
    """첫 화면 요약. 탭을 누르지 않아도 오늘 무슨 일이 있는지 보이게 한다.

    [왜 필요한가]
      핵심 정보가 탭 일곱 개에 흩어져 있으면, 화면을 처음 본 사람에게는
      "카드 하나 있는 앱"으로 보인다. 관리자도 아침에 탭을 하나씩 눌러볼
      게 아니라 한눈에 파악해야 한다.

    cards: [{"icon": "🚧", "label": "다음 알람", "value": "13:40",
             "note": "피크 구간 진입", "accent": "#B91C1C"}]
    """
    if not cards:
        return
    cells = []
    for i, c in enumerate(cards):
        col = c.get("accent") or "#8B95A1"
        cells.append(
            f'<div class="sm-card" style="animation-delay:{0.04 + i*0.05:.2f}s;'
            f'border-left:3px solid {col}">'
            f'<div class="sm-l">{_esc(c.get("icon", ""))} '
            f'{_esc(c.get("label", ""))}</div>'
            f'<div class="sm-v" style="color:{col}">{_esc(c.get("value", ""))}</div>'
            + (f'<div class="sm-n">{_esc(c["note"])}</div>'
               if c.get("note") else '')
            + '</div>')
    st.markdown(
        '<div class="sm-grid">' + "".join(cells) + '</div>',
        unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    """섹션 제목. h5보다 가볍고 위계가 분명하다."""
    st.markdown(
        f'<div class="sec"><span class="sec-t">{_esc(title)}</span>'
        + (f'<span class="sec-n">{_esc(note)}</span>' if note else '')
        + '</div>', unsafe_allow_html=True)


# =====================================================================
# 진입 게이트
# =====================================================================

def mode_gate() -> str | None:
    """처음 접속하면 역할을 먼저 묻는다.

    [왜 게이트를 두는가]
      사이드바 라디오는 열어서 찾아야 하고, 현장에서 QR로 들어온 근로자에게는
      관제 설정이 잔뜩 보이는 화면이 먼저 뜬다. 역할이 다르면 볼 화면도
      달라야 하므로, 선택을 화면 앞으로 끌어낸다.

    반환: "worker" | "admin" | None (아직 선택 안 함)
    """
    picked = st.session_state.get("_mode")
    if picked:
        return picked

    st.markdown("""
<div class="gate">
  <div class="gate-q">어느 쪽으로 접속하시나요?</div>
  <div class="gate-n">역할에 따라 필요한 화면만 표시됩니다</div>
</div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
<div class="gate-card">
  <div class="gate-ic">👷</div>
  <div class="gate-t">근로자</div>
  <div class="gate-d">오늘 등급 확인 · 자각증상 자가진단 · 이상 신고</div>
</div>""", unsafe_allow_html=True)
        if st.button("근로자로 시작", use_container_width=True,
                     key="_g_worker"):
            st.session_state["_mode"] = "worker"
            st.rerun()
    with c2:
        st.markdown("""
<div class="gate-card">
  <div class="gate-ic">🛡️</div>
  <div class="gate-t">관리자</div>
  <div class="gate-d">휴식 계획 · 알람 · TBM 명단 · 조치 기록</div>
</div>""", unsafe_allow_html=True)
        if st.button("관리자로 시작", use_container_width=True,
                     type="primary", key="_g_admin"):
            st.session_state["_mode"] = "admin"
            st.rerun()

    st.caption("관리자 모드는 비밀번호가 필요합니다. "
               "민감군 명단이 포함되므로 접근을 제한합니다.")
    return None


def mode_switch(current: str) -> None:
    """사이드바 상단에 현재 역할과 전환 버튼만 남긴다."""
    label = "👷 근로자" if current == "worker" else "🛡️ 관리자"
    st.markdown(f'<div style="font-size:13px;font-weight:700;'
                f'padding:8px 0 2px">{label} 모드</div>',
                unsafe_allow_html=True)
    if st.button("역할 변경", use_container_width=True, key="_m_switch"):
        for k in ("_mode", "_worker"):
            st.session_state.pop(k, None)
        st.rerun()


# =====================================================================
# 도면 패널 — 제목 + 행 격자
# =====================================================================

def panel_open(title: str, note: str = "") -> str:
    """도면 패널 여는 태그. panel_close() 와 짝으로 쓴다."""
    return (
        '<div style="border:1px solid rgba(29,31,32,.16);background:#fff;'
        'padding:15px 17px 13px;height:100%">'
        '<div style="display:flex;align-items:baseline;'
        'justify-content:space-between;gap:10px;margin-bottom:11px">'
        f'<span style="font-weight:600;font-size:14px;letter-spacing:.04em">'
        f'{_esc(title)}</span>'
        + (f'<span style="font-size:11px;color:#7A7A7D">{_esc(note)}</span>'
           if note else '')
        + '</div><div style="display:flex;flex-direction:column;gap:7px">')


def panel_close() -> str:
    return '</div></div>'


def grid_row(lead: str, body: str, tail: str = "", *,
             accent: str = "", cols: str = "62px 1fr 76px",
             lead_size: int = 18, urgent: bool = False,
             tail_filled: bool = False) -> str:
    """한 줄 = 하나의 항목. 시각·내용·상태가 같은 축에 정렬된다.

    표보다 읽기 쉽고 카드보다 밀도가 높다. 목록이 길어져도 세로로
    늘어지지 않는 게 요점이다.
    """
    col = accent or "#1D1F20"
    border = (f'1px solid {col}' if urgent else '1px solid rgba(29,31,32,.14)')
    bg = (f'background:{col}0D;' if urgent else
          'background:rgba(29,31,32,.02);')

    tail_html = ""
    if tail:
        if tail_filled:
            tail_html = (f'<span style="font-size:10.5px;font-weight:700;'
                         f'color:#F2F2F3;background:{col};padding:2px 6px;'
                         f'text-align:center">{_esc(tail)}</span>')
        else:
            tail_html = (f'<span style="font-size:10.5px;color:{col};'
                         f'border:1px solid {col};padding:2px 6px;'
                         f'text-align:center">{_esc(tail)}</span>')

    return (
        f'<div style="display:grid;grid-template-columns:{cols};gap:11px;'
        f'align-items:center;padding:9px 12px;border:{border};{bg}">'
        f'<span style="font-weight:600;font-size:{lead_size}px;'
        f'font-variant-numeric:tabular-nums;color:{col}">{_esc(lead)}</span>'
        f'<span style="font-size:12px;line-height:1.5">{_esc(body)}</span>'
        + tail_html + '</div>')


def list_row(name: str, detail: str, tail: str = "", accent: str = "") -> str:
    """명단 행 — 좌측 색선으로 등급을 표시한다."""
    col = accent or "#7A7A7D"
    return (
        f'<div style="display:grid;grid-template-columns:76px 1fr 88px;gap:10px;'
        f'padding:8px 12px;border:1px solid rgba(29,31,32,.12);'
        f'border-left:3px solid {col};font-size:12px;align-items:center">'
        f'<span style="font-weight:600">{_esc(name)}</span>'
        f'<span style="line-height:1.5">{_esc(detail)}</span>'
        + (f'<span style="font-weight:600;font-variant-numeric:tabular-nums;'
           f'color:{col};text-align:right">{_esc(tail)}</span>' if tail else
           '<span></span>')
        + '</div>')
