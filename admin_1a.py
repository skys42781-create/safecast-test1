"""
SAFECASTY — 관리자 대시보드 1a (블록 스트립)
============================================
Claude Design 핸드오프의 1a안을 Streamlit으로 옮긴 렌더러.

[구조 원칙]
    표시 전용 영역은 HTML 한 덩어리로 주입하고,
    사람이 눌러야 하는 것만 Streamlit 위젯으로 뺀다.

    Streamlit 위젯은 커스텀 HTML 안에 넣을 수 없다. 그래서 카드 안에
    체크박스를 박는 대신, 카드 바로 아래 행에 실제 위젯을 놓는다.

[왜 그렇게까지 하는가 — 판정 원칙 2]
    조치 이행 체크와 알람 전파는 관리자가 직접 눌러야 한다.
    HTML로 그린 체크박스는 눌러도 서버에 아무것도 남지 않으므로
    "했다"는 표시만 남는 허위 기록이 된다.
    → 기록에 남아야 하는 동작은 반드시 진짜 위젯을 쓴다.

[상태 — 아직 app.py에 연결되지 않았다]
    sample_data()는 시안 문서의 예시 값을 그대로 옮긴 더미다.
    화면 모양을 확인하려고 넣어 둔 것이지 실제 판정값이 아니다.
    app.py에 붙일 때 실제 예보·블록·알람·명단을 채우는 변환 함수를 만들고,
    sample_data()는 아래 __main__ 블록에서만 쓰도록 남긴다.

    단독 확인:  streamlit run admin_demo.py

사용:
    import admin_1a as A
    A.render(A.sample_data())
"""

from __future__ import annotations

import html as _html
import re
from datetime import datetime
from typing import Any

import streamlit as st

import theme as TH

# =====================================================================
# 토큰
# =====================================================================

# 등급 색은 theme.py 한 곳에서만 정의한다.
# 두 군데 적어 두면 한쪽만 고쳤을 때 같은 등급이 화면마다 다른 색으로 나온다.
# 색맹 대응으로 등급명 텍스트를 항상 색과 함께 노출한다.
TIER_COLOR = TH.TIER
TIER_ORDER = ["평시", "주의", "경계", "심각", "위험"]
HIGHLIGHT = "#F97316"          # 현재 등급 배지 강조에만 1회 사용
NONWORK = "#b7b7ba"            # 점심 등 비작업 블록

BG = "#f2f2f3"
TEXT = "#1d1f20"
ACCENT = "#5980a6"
MUTED = "#5d5d60"
WEAK = "#7a7a7d"
FAINT = "#98989b"
LINE = "rgba(29,31,32,.16)"
LINE_IN = "rgba(29,31,32,.10)"

HERO_BG = "#1d2d3d"
HERO_LABEL = "#9ebbd8"
HERO_SUB = "#bdd8f2"
HERO_BASIS = "#d6ebff"

CANVAS = 1360                  # 데스크톱 고정 폭


# =====================================================================
# CSS
# =====================================================================

def inject_css() -> None:
    """폰트·리셋·블루프린트 프레임을 한 번만 주입한다."""
    if st.session_state.get("_sc_css_done"):
        return
    st.session_state["_sc_css_done"] = True

    # 본문 폰트·기본 스타일은 theme.py가 담당한다. 여기서 다시 정의하면
    # 같은 앱 안에서 화면마다 글꼴이 달라진다.
    TH.apply()

    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&display=swap');

/* Streamlit 기본 여백 제거 + 캔버스 폭 고정 */
.block-container {{
    max-width: {CANVAS}px !important;
    padding: 0.6rem 1rem 3rem !important;
}}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}

.stApp {{ background: {BG}; }}

.sc, .sc * {{
    font-family: 'IBM Plex Sans KR', system-ui, sans-serif;
    color: {TEXT};
    box-sizing: border-box;
}}
/* 숫자는 표에서 흔들리면 안 된다 */
.sc, .sc * {{ font-variant-numeric: tabular-nums; }}

/* 한글이 섞이는 제목 — Barlow Condensed 에는 한글 글자가 없어
   fallback 으로 떨어지면 자간이 어긋난다. 본문 폰트를 좁혀 쓴다. */
.sc-cond {{ font-family: 'IBM Plex Sans KR', sans-serif; letter-spacing: -.3px; }}
/* 숫자·영문 전용 — 한글이 섞이지 않는 곳에서만 Barlow Condensed 를 쓴다 */
.sc-num {{ font-family: 'Barlow Condensed', sans-serif; font-variant-numeric: tabular-nums; }}
.sc-label {{
    font-family: 'Barlow Condensed',sans-serif;
    text-transform: uppercase;
    letter-spacing: .16em;
    font-size: 11px;
    color: {WEAK};
}}

/* ---- 블루프린트 프레임 : 각 모서리에 + 등록 마크 ---- */
.sc-bp {{ position: relative; border: 1px solid {LINE}; background: transparent; }}
.sc-bp > i.c {{ position: absolute; width: 9px; height: 9px; pointer-events: none; }}
.sc-bp > i.c::before {{ content:''; position:absolute; left:0; top:4px; width:9px; height:1px; background:{TEXT}; opacity:.55; }}
.sc-bp > i.c::after  {{ content:''; position:absolute; top:0; left:4px; width:1px; height:9px; background:{TEXT}; opacity:.55; }}
.sc-bp > i.tl {{ left:-5px;  top:-5px;    }}
.sc-bp > i.tr {{ right:-5px; top:-5px;    }}
.sc-bp > i.bl {{ left:-5px;  bottom:-5px; }}
.sc-bp > i.br {{ right:-5px; bottom:-5px; }}

/* 모서리는 각. 카드는 선 그림. */
.sc [class*="sc-"] {{ border-radius: 0; }}

/* ---- Streamlit 위젯을 디자인에 맞춘다 ---- */
.stButton > button {{
    border-radius: 0 !important;
    border: 1px solid {ACCENT} !important;
    background: {ACCENT} !important;
    color: #fff !important;
    font-family: 'IBM Plex Sans KR',sans-serif !important;
    font-size: 12.5px !important;
    font-weight: 700 !important;
    padding: 6px 14px !important;
    box-shadow: none !important;
}}
.stButton > button:hover {{ background: #4a6d90 !important; border-color: #4a6d90 !important; }}
.stButton > button:focus-visible {{ outline: 2px solid {ACCENT} !important; outline-offset: 2px !important; }}
.stButton > button[kind="secondary"] {{
    background: transparent !important; color: {TEXT} !important; border-color: {LINE} !important;
}}
.stCheckbox, .stToggle {{ font-size: 12.5px; }}
div[data-testid="stCheckbox"] label p, div[data-testid="stToggle"] label p {{
    font-family: 'IBM Plex Sans KR',sans-serif !important; font-size: 12.5px !important;
}}
</style>""", unsafe_allow_html=True)


# =====================================================================
# HTML 유틸
# =====================================================================

def _w(html_str: str) -> None:
    """HTML을 한 줄로 눌러 주입한다.

    st.markdown은 줄바꿈이 섞이면 일부를 마크다운으로 해석해
    <p> 태그를 끼워 넣는다. 레이아웃이 깨지므로 개행을 먼저 제거한다.
    """
    st.markdown(re.sub(r">\s+<", "><", html_str).strip(), unsafe_allow_html=True)


def _e(v: Any) -> str:
    return _html.escape(str(v))


def _corners() -> str:
    return ('<i class="c tl"></i><i class="c tr"></i>'
            '<i class="c bl"></i><i class="c br"></i>')


def _badge(text: str, color: str, solid: bool = True) -> str:
    if solid:
        css = f"background:{color};color:#fff"
    else:
        css = f"background:transparent;color:{color};border:1px solid {color}"
    return (f'<span style="{css};font-size:11.5px;font-weight:700;'
            f'padding:2px 9px;white-space:nowrap">{_e(text)}</span>')


# =====================================================================
# 1. 상단 바
# =====================================================================

def _topbar(d: dict) -> str:
    return f"""
<div class="sc" style="display:flex;justify-content:space-between;align-items:flex-end;
     padding:14px 26px;border-bottom:1px solid {LINE}">
  <div>
    <div class="sc-num" style="font-weight:700;font-size:21px;letter-spacing:.06em;line-height:1">
      SAFECASTY</div>
    <div class="sc-label" style="margin-top:3px">heat safety control</div>
  </div>
  <div style="text-align:right;line-height:1.7">
    <div style="font-size:12.5px;color:{MUTED}">{_e(d['site'])} · 격자 {_e(d['grid'])}</div>
    <div style="font-size:12.5px;font-weight:700">{_e(d['now_text'])}</div>
    <div style="font-size:12px;color:{WEAK};display:flex;align-items:center;
         justify-content:flex-end;gap:6px">
      <span style="width:6px;height:6px;background:{TIER_COLOR['평시']};display:inline-block"></span>
      {_e(d['source_text'])}
    </div>
  </div>
</div>"""


# =====================================================================
# 2. 히어로 밴드
# =====================================================================

def _metric_cell(m: dict, border_l: bool, border_t: bool) -> str:
    bl = f"border-left:1px solid rgba(255,255,255,.14);" if border_l else ""
    bt = f"border-top:1px solid rgba(255,255,255,.14);" if border_t else ""
    return f"""
<div style="padding:20px 24px;{bl}{bt}">
  <div class="sc-cond" style="font-size:11px;letter-spacing:.16em;text-transform:uppercase;
       color:{HERO_LABEL}">{_e(m['label'])}</div>
  <div class="sc-num" style="font-weight:600;font-size:34px;line-height:1.15;color:#f2f2f3">
    {_e(m['value'])}</div>
  <div style="font-size:12px;color:{HERO_SUB}">{_e(m['sub'])}</div>
</div>"""


def _hero(d: dict) -> str:
    h = d["hero"]
    cells = "".join(
        _metric_cell(m, border_l=(i % 2 == 1), border_t=(i >= 2))
        for i, m in enumerate(d["metrics"])
    )
    return f"""
<div class="sc" style="display:grid;grid-template-columns:1fr 1fr;background:{HERO_BG};
     color:#f2f2f3;margin-top:0">
  <div style="padding:22px 26px 18px;display:flex;flex-direction:column;justify-content:space-between">
    <div>
      <div class="sc-cond" style="font-size:11px;letter-spacing:.16em;text-transform:uppercase;
           color:{HERO_LABEL};margin-bottom:8px">현재 체감온도</div>
      <div style="display:flex;align-items:flex-end;gap:14px;flex-wrap:wrap">
        <span style="background:{HIGHLIGHT};color:{TEXT};font-size:11.5px;font-weight:700;
              padding:2px 9px;margin-bottom:14px">{_e(h['tier_label'])}</span>
        <span class="sc-num" style="font-weight:700;font-size:78px;line-height:.86;
              letter-spacing:-.02em;color:#f2f2f3">{_e(h['apparent'])}</span>
        <span class="sc-num" style="font-size:26px;margin-bottom:8px;color:#f2f2f3">℃</span>
        <span style="font-size:13px;color:{HERO_SUB};margin-bottom:10px">{_e(h['reading'])}</span>
      </div>
      <div style="font-size:13px;color:{HERO_SUB};margin-top:6px">{_e(h['correction'])}</div>
    </div>
    <div style="border-top:1px solid rgba(255,255,255,.16);margin-top:16px;padding-top:10px;
         font-size:13px;color:{HERO_BASIS}">{_e(h['legal'])}</div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr">{cells}</div>
</div>"""


# =====================================================================
# 3. 공정 블록 5칸
# =====================================================================

def _block_card(b: dict, show_basis: bool, legal_only: bool) -> str:
    work = b.get("is_work", True)
    color = TIER_COLOR.get(b["tier"], NONWORK) if work else NONWORK
    value_color = color if work else WEAK
    unit = "℃ 판정값" if work else "℃ 참고값"

    # 심각 이상은 카드 전체를 등급색으로 — 훑을 때 먼저 걸리게 한다
    severe = work and TIER_ORDER.index(b["tier"]) >= TIER_ORDER.index("심각")
    frame = f"border:1px solid {color};background:rgba(185,28,28,.05)" if severe else \
            (f"border:1px solid {LINE};background:rgba(29,31,32,.03)" if not work
             else f"border:1px solid {LINE}")
    shadow = "box-shadow:0 3px 10px rgba(43,43,45,.16);" if b.get("running") else ""

    badge_text = b["tier"] + (" · 진행중" if b.get("running") else "")
    badge = _badge("비작업", NONWORK, solid=False) if not work \
        else _badge(badge_text, color, solid=True)

    # 조치 문구 — 법적 의무만 보기가 켜지면 권고 항목을 숨긴다
    lines = []
    for a in b.get("actions", []):
        if legal_only and a.get("kind") == "권고":
            continue
        weight = "700" if a.get("strong") else "400"
        lines.append(f'<div style="font-weight:{weight}">{_e(a["text"])}</div>')
    actions = "".join(lines) or f'<div style="color:{WEAK}">—</div>'

    basis = ""
    if show_basis and b.get("basis"):
        basis = (f'<div style="font-size:11px;color:{FAINT};margin-top:8px;line-height:1.5">'
                 f'{_e(b["basis"])}</div>')

    return f"""
<div class="sc-bp" style="{frame};border-top:3px solid {color};{shadow}padding:16px 16px 14px">
  {_corners()}
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
    <span class="sc-cond" style="font-weight:600;font-size:16px">{_e(b['name'])}</span>
    {badge}
  </div>
  <div style="font-size:12px;color:{WEAK};margin-top:4px">{_e(b['hours'])}</div>
  <div style="margin-top:10px;display:flex;align-items:baseline;gap:6px">
    <span class="sc-num" style="font-weight:600;font-size:30px;color:{value_color};
          line-height:1">{_e(b['value'])}</span>
    <span style="font-size:11.5px;color:{WEAK}">{unit}</span>
  </div>
  <div style="border-top:1px solid {LINE_IN};margin-top:12px;padding-top:10px;
       font-size:12.5px;line-height:1.6">{actions}</div>
  {basis}
</div>"""


def _blocks(d: dict, show_basis: bool, legal_only: bool) -> str:
    cards = "".join(_block_card(b, show_basis, legal_only) for b in d["blocks"])
    return f"""
<div class="sc" style="margin-top:22px">
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:4px">
    {cards}
  </div>
</div>"""


# =====================================================================
# 4. 하단 2열 — 알람 / TBM
# =====================================================================

def _alarm_row(a: dict) -> str:
    pending = a["status"] != "sent"
    frame = (f"border:1px solid {TIER_COLOR['심각']};background:rgba(185,28,28,.05)"
             if pending else f"border-top:1px solid {LINE_IN}")
    badge = _badge("대기", TIER_COLOR["심각"], solid=True) if pending \
        else _badge("전파 완료", TIER_COLOR["평시"], solid=False)
    return f"""
<div style="display:grid;grid-template-columns:62px 1fr 76px;gap:12px;padding:10px 12px;
     align-items:center;{frame}">
  <span class="sc-num" style="font-weight:600;font-size:19px">{_e(a['time'])}</span>
  <span style="font-size:12.5px;line-height:1.5">{_e(a['message'])}</span>
  <span style="text-align:right">{badge}</span>
</div>"""


def _worker_row(w: dict) -> str:
    color = TIER_COLOR.get(w.get("risk", "주의"), NONWORK)
    return f"""
<div style="display:grid;grid-template-columns:78px 1fr 92px;gap:10px;padding:9px 12px;
     align-items:center;border-left:3px solid {color};border-top:1px solid {LINE_IN}">
  <span style="font-weight:700;font-size:12.5px">{_e(w['name'])}</span>
  <span style="font-size:12px;color:{MUTED}">{_e(w['types'])}</span>
  <span style="font-size:12.5px;font-weight:700;color:{color};text-align:right">
    {_e(w['status'])}</span>
</div>"""


def _bottom(d: dict) -> str:
    alarms = "".join(_alarm_row(a) for a in d["alarms"])
    workers = "".join(_worker_row(w) for w in d["workers"])
    return f"""
<div class="sc" style="display:grid;grid-template-columns:1.15fr 1fr;gap:12px;margin-top:22px">
  <div class="sc-bp" style="padding:14px 16px 12px">
    {_corners()}
    <div style="display:flex;justify-content:space-between;align-items:baseline">
      <span class="sc-cond" style="font-weight:600;font-size:17px">오늘 알람</span>
      <span style="font-size:11.5px;color:{WEAK}">사전 통보 20분 · 문구 그대로 전파</span>
    </div>
    <div style="margin-top:10px;display:flex;flex-direction:column;gap:6px">{alarms}</div>
  </div>
  <div class="sc-bp" style="padding:14px 16px 12px">
    {_corners()}
    <div style="display:flex;justify-content:space-between;align-items:baseline">
      <span class="sc-cond" style="font-weight:600;font-size:17px">TBM 관리 대상</span>
      <span style="font-size:11.5px;color:{WEAK}">선별·기록만 — 근로 제한 판단은 관리자</span>
    </div>
    <div style="margin-top:10px">{workers}</div>
  </div>
</div>"""


# =====================================================================
# 렌더
# =====================================================================

def render(d: dict) -> dict:
    """1a 화면을 그리고, 관리자가 누른 동작을 돌려준다.

    반환: {"sent": [전파된 알람 시각], "legal_only": bool, "show_basis": bool}
    """
    inject_css()

    _w(_topbar(d))
    _w(_hero(d))

    # 토글은 진짜 위젯이어야 한다 — 화면 상태를 바꾸므로
    head, t1, t2 = st.columns([6, 2, 2])
    with head:
        st.markdown(
            f'<div class="sc" style="padding-top:6px">'
            f'<span class="sc-cond" style="font-weight:600;font-size:17px">오늘 공정 블록</span>'
            f'<span style="font-size:11.5px;color:{WEAK};margin-left:10px">'
            f'{len([b for b in d["blocks"] if b.get("is_work", True)])}개 작업 구간 · '
            f'블록 내 최고값 기준(보수적 MAX)</span></div>',
            unsafe_allow_html=True)
    legal_only = t1.toggle("법적 의무만 보기", value=False, key="sc_legal_only")
    show_basis = t2.toggle("근거 표시", value=True, key="sc_show_basis")

    _w(_blocks(d, show_basis, legal_only))
    _w(_bottom(d))

    # ---- 사람이 눌러야 하는 것 ----
    # 자동 전파 금지. 버튼을 눌러야만 상태가 바뀌고 기록에 남는다.
    sent = []
    pending = [a for a in d["alarms"] if a["status"] != "sent"]
    if pending:
        st.markdown(
            f'<div class="sc" style="margin-top:18px;font-size:12.5px;color:{MUTED}">'
            f'대기 중 알람 {len(pending)}건 — 문구를 확인하고 전파하세요.</div>',
            unsafe_allow_html=True)
        cols = st.columns(min(len(pending), 4))
        for col, a in zip(cols, pending):
            if col.button(f"{a['time']} 전파", key=f"sc_send_{a['time']}"):
                sent.append(a["time"])

    return {"sent": sent, "legal_only": legal_only, "show_basis": show_basis}


# =====================================================================
# 샘플 데이터 — 실제 값은 app.py에서 예보·명부로 채운다
# =====================================================================

def sample_data(now: datetime | None = None) -> dict:
    now = now or datetime(2026, 7, 23, 10, 20)
    return {
        "site": "국민대학교 현장",
        "grid": "60/128",
        "now_text": f"{now:%Y-%m-%d} (목) {now:%H:%M}",
        "source_text": "단기예보 10시 발표 · 공공데이터포털",
        "hero": {
            "tier_label": "경계 · 법적 의무",
            "apparent": "33.2",
            "reading": "기온 30.4℃ · 습도 66%",
            "correction": "고도 보정 −0.23℃ · 습도 재계산 적용",
            "legal": "2시간마다 20분 이상 휴식 — 안전보건규칙 제560조제3항",
        },
        "metrics": [
            {"label": "오늘 최고 체감", "value": "36.4℃", "sub": "14시 · 심각 구간"},
            {"label": "다음 알람", "value": "13:40", "sub": "피크 진입 20분 전"},
            {"label": "관리 대상", "value": "7 / 42", "sub": "민감군 5 · 열순응 2"},
            {"label": "작업시간 손실률", "value": "12.5%", "sub": "의무 휴식 + 옥외 중지"},
        ],
        "blocks": [
            {"name": "오전 1부", "hours": "08:00 – 10:00", "tier": "주의", "value": "31.6",
             "actions": [{"text": "냉방·시간조정·휴식 중 1개 이상", "kind": "의무"},
                         {"text": "휴식 미배정 — 조치 선택 필요", "kind": "의무"}],
             "basis": "의무 · 제560조제2항"},
            {"name": "오전 2부", "hours": "10:00 – 12:00", "tier": "경계", "value": "34.9",
             "running": True,
             "actions": [{"text": "2시간마다 20분 휴식", "kind": "의무"},
                         {"text": "11:40 – 12:00 (점심 연결)", "kind": "의무", "strong": True}],
             "basis": "의무 · 제560조제3항 · 11시 34.9℃가 블록 결정"},
            {"name": "점심 · 휴게", "hours": "12:00 – 14:00", "tier": "심각", "value": "36.1",
             "is_work": False,
             "actions": [{"text": "그늘·냉방 휴게장소 확보", "kind": "의무"},
                         {"text": "소금·음료수 비치 점검", "kind": "의무"}],
             "basis": "의무 · 제567조제2항 · 제571조"},
            {"name": "피크", "hours": "14:00 – 17:00 · 무더위 시간대", "tier": "심각",
             "value": "36.4",
             "actions": [{"text": "오후 옥외작업 중지 검토", "kind": "의무"},
                         {"text": "14:40–15:00 · 16:40–17:00 법정 최소", "kind": "의무",
                          "strong": True},
                         {"text": "권고: 매시간 15분 — 14:45 · 15:45 · 16:45", "kind": "권고"}],
             "basis": "의무 제560조제3항 + 권고 지침 14쪽"},
            {"name": "마무리 · 철수", "hours": "17:00 – 18:00", "tier": "경계", "value": "33.4",
             "actions": [{"text": "2시간마다 20분 휴식", "kind": "의무"},
                         {"text": "17:40 – 18:00 (작업 종료 연결)", "kind": "의무",
                          "strong": True}],
             "basis": "의무 · 제560조제3항"},
        ],
        "alarms": [
            {"time": "11:20", "status": "sent",
             "message": "오전 2부 의무 휴식 20분 전 — 11:40부터 20분, 그늘 휴게장소 집합"},
            {"time": "13:40", "status": "pending",
             "message": "20분 후 ‘피크’ 구간 진입 — 판정 36.4℃ 심각, 옥외작업 중지 검토 대상"},
            {"time": "09:16", "status": "sent",
             "message": "열순응 대상 1명 작업 종료 20분 전 — 김O수(1일차 20%), 09:36 종료"},
        ],
        "workers": [
            {"name": "김O수", "types": "⑦신규배치 · 열순응 1일차 20%",
             "status": "09:36 종료", "risk": "심각"},
            {"name": "박O민", "types": "복귀(7일↑) · 열순응 3일차 70%",
             "status": "14:36 종료", "risk": "경계"},
            {"name": "이O헌", "types": "③고령(67) · ①만성질환",
             "status": "피크 제외", "risk": "주의"},
        ],
    }


if __name__ == "__main__":
    st.set_page_config(page_title="SAFECASTY 관리자", layout="wide")
    render(sample_data())
