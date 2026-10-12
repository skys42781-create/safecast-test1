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


def section(title: str, note: str = "") -> None:
    """섹션 제목. h5보다 가볍고 위계가 분명하다."""
    st.markdown(
        f'<div class="sec"><span class="sec-t">{_esc(title)}</span>'
        + (f'<span class="sec-n">{_esc(note)}</span>' if note else '')
        + '</div>', unsafe_allow_html=True)


# =====================================================================
# 진입 게이트
# =====================================================================

def mode_gate(admin_pw: str = "") -> str | None:
    """처음 접속하면 역할을 먼저 묻는다.

    [왜 게이트를 두는가]
      사이드바 라디오는 열어서 찾아야 하고, 현장에서 QR로 들어온 근로자에게는
      관제 설정이 잔뜩 보이는 화면이 먼저 뜬다. 역할이 다르면 볼 화면도
      달라야 하므로, 선택을 화면 앞으로 끌어낸다.

    [왜 비밀번호를 여기서 받는가]
      관리자 화면에는 민감군 명단이 들어간다. 역할만 고르면 통과시키고
      비밀번호를 사이드바에서 따로 받으면, 게이트에 "비밀번호가 필요합니다"라고
      적어 놓고 실제로는 묻지 않는 상태가 된다. 잠금은 들어가는 문에 있어야 한다.

    admin_pw: secrets의 ADMIN_PW. 비어 있으면 경고와 함께 통과시킨다.
    반환: "worker" | "admin" | None (아직 선택 안 함)
    """
    picked = st.session_state.get("_mode")
    if picked:
        return picked

    # 관리자를 고른 뒤 비밀번호 단계
    if st.session_state.get("_gate_admin"):
        return _admin_gate(admin_pw)

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
            st.session_state["_gate_admin"] = True
            st.rerun()

    st.caption("관리자 모드는 비밀번호가 필요합니다. "
               "민감군 명단이 포함되므로 접근을 제한합니다.")
    return None


def _admin_gate(admin_pw: str) -> str | None:
    """관리자 비밀번호 확인 화면."""
    st.markdown("""
<div class="gate">
  <div class="gate-q">관리자 인증</div>
  <div class="gate-n">민감군 명단이 포함된 화면입니다</div>
</div>""", unsafe_allow_html=True)

    def _back() -> None:
        st.session_state.pop("_gate_admin", None)
        st.session_state.pop("_gate_err", None)
        st.rerun()

    # 비밀번호가 설정돼 있지 않으면 막을 방법이 없다.
    # 조용히 통과시키면 잠겨 있다고 오해하므로 상태를 분명히 알린다.
    if not admin_pw:
        st.warning("secrets에 ADMIN_PW가 설정되지 않았습니다 — 인증 없이 들어갑니다. "
                   "실제 운영 전에 반드시 설정하세요.", icon="🔓")
        c1, c2 = st.columns([1, 1])
        if c1.button("그래도 들어가기", use_container_width=True,
                     type="primary", key="_g_nopw"):
            st.session_state["_mode"] = "admin"
            st.session_state.pop("_gate_admin", None)
            st.rerun()
        if c2.button("뒤로", use_container_width=True, key="_g_back0"):
            _back()
        return None

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("_gate_pw_form"):
            pw = st.text_input("관리자 비밀번호", type="password",
                               key="_g_pw")
            ok = st.form_submit_button("확인", use_container_width=True,
                                       type="primary")
        if ok:
            # secrets나 입력값 끝에 공백·줄바꿈이 섞이면 조용히 실패한다.
            if pw and pw.strip() == str(admin_pw).strip():
                st.session_state["_mode"] = "admin"
                st.session_state.pop("_gate_admin", None)
                st.session_state.pop("_gate_err", None)
                st.rerun()
            else:
                st.session_state["_gate_err"] = True

        if st.session_state.get("_gate_err"):
            st.error("비밀번호가 일치하지 않습니다.")

        if st.button("뒤로", use_container_width=True, key="_g_back1"):
            _back()

    st.caption("비밀번호는 Streamlit Cloud → Manage app → Settings → Secrets 의 "
               "`ADMIN_PW` 값입니다. 값 앞뒤 공백·따옴표가 섞이지 않았는지 확인하세요.")
    return None


def mode_switch(current: str) -> None:
    """사이드바 상단에 현재 역할과 전환 버튼만 남긴다."""
    label = "👷 근로자" if current == "worker" else "🛡️ 관리자"
    st.markdown(f'<div style="font-size:13px;font-weight:700;'
                f'padding:8px 0 2px">{label} 모드</div>',
                unsafe_allow_html=True)
    if st.button("역할 변경", use_container_width=True, key="_m_switch"):
        for k in ("_mode", "_worker", "_gate_admin", "_gate_err"):
            st.session_state.pop(k, None)
        st.rerun()


# =====================================================================
# 도면 패널 — 제목 + 행 격자
# =====================================================================

# =====================================================================
# 화면 전환
# =====================================================================

def _st_minor() -> tuple[int, int]:
    """설치된 Streamlit 의 (major, minor). 읽을 수 없으면 (0, 0)."""
    try:
        a, b = st.__version__.split(".")[:2]
        return int(a), int(b)
    except Exception:
        return 0, 0


# st-key-{key} 클래스는 Streamlit 1.39 에서 생겼다. 그 아래 버전에서는
# key 로 버튼을 집어낼 수 없으므로 CSS 로 탭을 그릴 수 없다.
_KEY_CLASS = _st_minor() >= (1, 39)

# 1.39 미만에서 쓰는 대체 배지. 숫자가 파인 검은 원 글리프라서
# 글자색을 빨강으로 주면 카톡 배지와 비슷하게 읽힌다.
_GLYPH = "❶❷❸❹❺❻❼❽❾❿"

_BADGE_BG = "#B91C1C"   # 심각 등급과 같은 빨강 — 앱 안에서 빨강의 뜻을 하나로 유지


def _nav_css(key: str, counts: list[int]) -> None:
    """탭 CSS. 배지 숫자를 content 로 찍기 때문에 건수를 받아야 한다."""
    base = f'[class*="st-key-{key}_"]'
    css = f"""
<style>
/* 탭 — 테두리와 배경을 지우고 밑줄만 남긴다 */
{base} button {{
  border: none !important; background: transparent !important;
  border-radius: 0 !important; box-shadow: none !important;
  padding: 9px 4px !important; font-size: 13.5px !important;
  color: rgba(29,31,32,.5) !important; font-weight: 500 !important;
  border-bottom: 2px solid transparent !important;
  transition: color .15s, border-color .15s;
}}
{base} button:hover {{
  background: transparent !important; color: var(--sc-ink) !important;
}}
{base} button p {{ display: inline !important; }}
/* 선택된 탭 */
[class*="st-key-{key}_on"] button {{
  color: var(--sc-ink) !important; font-weight: 600 !important;
  border-bottom-color: var(--sc-accent) !important;
}}
/* 탭 사이 간격을 없애 한 줄로 붙인다 */
div[data-testid="stHorizontalBlock"]:has({base}) {{ gap: 0 !important; }}
"""
    # 경보 배지 — 빨간 동그라미 안에 흰 숫자. 버튼 라벨에는 HTML을
    # 넣을 수 없으므로 ::after 로 그리고 숫자는 content 로 찍는다.
    for n in sorted(set(counts)):
        txt = str(n) if n < 100 else "99+"
        css += f"""
[class*="st-key-{key}_on_n{n}_"] button::after,
[class*="st-key-{key}_off_n{n}_"] button::after {{
  content: "{txt}";
  display: inline-flex; align-items: center; justify-content: center;
  box-sizing: border-box; min-width: 18px; height: 18px;
  padding: 0 {5 if n > 9 else 0}px; margin-left: 6px;
  border-radius: 9px; background: {_BADGE_BG}; color: #fff;
  font-size: 11px; font-weight: 700; line-height: 1;
  font-variant-numeric: tabular-nums; vertical-align: middle;
}}
[class*="st-key-{key}_on_n{n}_"] button {{
  border-bottom-color: {_BADGE_BG} !important;
}}
"""
    st.markdown(css + "</style>", unsafe_allow_html=True)


def nav(views: list[str] | tuple[str, ...], *, key: str = "_nav",
        alert: dict[str, int] | None = None) -> str:
    """밑줄 탭 형태의 화면 선택기.

    [왜 라디오가 아닌가]
      st.radio 는 동그라미가 붙어 설문 문항처럼 읽힌다. 화면을 고르는
      일은 선택지를 묻는 것이 아니라 탭을 넘기는 것에 가깝다.
      라디오의 동그라미를 CSS로 숨기려면 Streamlit 내부 DOM을 깊이
      파고들어야 하는데, 그 구조는 버전마다 달라 쉽게 깨진다.

      버튼은 다르다. .stButton > button 하나로 닿고, 그 선택자는
      오래 유지돼 왔다. 선택 여부와 경보 건수를 key 에 담아 두면
      CSS에서 상태를 구분할 수 있다(st-key-* 클래스, 1.39+).

    alert: {화면명: 건수}. 0보다 크면 그 탭에 빨간 동그라미 배지가 붙는다.
           놓치면 안 되는 화면(미확인 신고)을 탭 줄에서 바로 알리기 위한 것이다.

    [버전이 낮으면]
      1.39 미만에서는 st-key-* 가 없어 CSS가 닿지 않는다. 그때는
      라벨에 ❷ 같은 글리프를 넣고 선택된 탭을 primary 버튼으로
      칠한다. 모양은 투박해도 어느 탭이 선택됐고 몇 건이 밀렸는지는
      그대로 보인다.
    """
    views = list(views)
    alert = alert or {}
    cur = st.session_state.get(key)
    if cur not in views:
        cur = views[0]
        st.session_state[key] = cur

    nums = [int(alert.get(v, 0) or 0) for v in views]
    if _KEY_CLASS:
        _nav_css(key, [n for n in nums if n > 0])

    cols = st.columns(len(views), gap="small")
    for i, (col, v) in enumerate(zip(cols, views)):
        on = (v == cur)
        n = nums[i]

        if _KEY_CLASS:
            # 상태와 건수를 key 에 담는다 → CSS가 셋을 구분한다
            k = f"{key}_{'on' if on else 'off'}" + (f"_n{n}" if n else "") \
                + f"_{i}"
            label, kind = v, "secondary"
        else:
            k = f"{key}_{i}"
            badge = (_GLYPH[n - 1] if 1 <= n <= len(_GLYPH)
                     else f"({n})") if n else ""
            label = f"{v} {badge}".strip()
            kind = "primary" if on else "secondary"

        if col.button(label, key=k, type=kind, use_container_width=True):
            st.session_state[key] = v
            st.rerun()

    st.markdown(
        '<div style="border-bottom:1px solid var(--sc-line);'
        'margin:-10px 0 18px"></div>', unsafe_allow_html=True)
    return cur
