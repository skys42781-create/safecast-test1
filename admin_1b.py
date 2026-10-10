"""
SAFECASTY — 관리자 대시보드 1b (시각 축 타임라인)
=================================================
하루를 한 줄로. 등급 경계선·블록·휴식·알람이 같은 시각 축 위에 놓인다.

[좌표계]
    차트는 viewBox 0 0 1200 400 고정. 실제 픽셀이 아니라 SVG 내부 좌표이므로
    컨테이너 폭이 달라져도 비율이 유지된다.

        x(시각) = 60 + (hour - 8) * 108      08시=60, 18시=1140
        y(온도) = 40 + (38 - temp) * 26      38℃=40, 28℃=300

    20분 휴식 = 36px(분당 1.8px). 디자인의 휴식 사각 폭과 일치한다.

[왜 차트 라이브러리를 안 쓰는가]
    등급 밴드, 현재시각 수직선, 블록 띠, 휴식 띠, 알람 마커를 한 축에 겹쳐야 한다.
    plotly·altair로 이걸 다 표현하려면 결국 도형을 직접 얹게 되고,
    그럴 바엔 SVG 문자열을 만드는 편이 짧고 정확하다.

[상태] app.py에 연결되기 전이다. sample_data()는 시안의 예시 값이며
      실제 판정값이 아니다. 단독 확인: streamlit run admin_demo.py

사용:
    import admin_1b as B
    B.render(B.sample_data())
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from admin_1a import (
    ACCENT, FAINT, HERO_BG, LINE, LINE_IN, MUTED, NONWORK, TEXT, TIER_COLOR,
    WEAK, _badge, _corners, _e, _w, inject_css,
)

# =====================================================================
# 좌표 변환
# =====================================================================

X0, X_PER_HOUR = 60.0, 108.0      # 08시 기준
Y0, Y_PER_DEG = 40.0, 26.0        # 38℃ 기준
HOUR_MIN, HOUR_MAX = 8, 18
TEMP_TOP, TEMP_BOTTOM = 38.0, 28.0

BLOCK_Y, BLOCK_H = 320, 30
REST_Y, REST_H = 362, 16
ALARM_Y = 306

LINE_COLOR = "#2c455d"            # 폴리라인
AREA_COLOR = "#5980a6"            # 하단 면


def x_at(hour: float) -> float:
    return X0 + (hour - HOUR_MIN) * X_PER_HOUR


def y_at(temp: float) -> float:
    return Y0 + (TEMP_TOP - temp) * Y_PER_DEG


def _hm(text: str) -> float:
    """'13:40' → 13.667 (시각 실수)."""
    h, m = text.split(":")
    return int(h) + int(m) / 60.0


# =====================================================================
# SVG 조립
# =====================================================================

# 등급 밴드 — (하한, 상한, 등급명). 상한 None이면 차트 top까지.
BANDS = [
    (38.0, None, "위험"),
    (35.0, 38.0, "심각"),
    (33.0, 35.0, "경계"),
    (31.0, 33.0, "주의"),
    (TEMP_BOTTOM, 31.0, "평시"),
]
TICKS = [38, 35, 33, 31, 28]


def _bands() -> str:
    """등급 밴드 + 경계선 + 우측 라벨.

    33℃만 실선이다 — 2시간마다 20분 휴식이 시작되는 법적 의무 경계이므로
    다른 경계와 시각적으로 구분한다.
    """
    out = []
    top_y = y_at(TEMP_TOP) - 24
    for lo, hi, tier in BANDS:
        y_lo = y_at(lo)
        y_hi = top_y if hi is None else y_at(hi)
        out.append(
            f'<rect x="{X0}" y="{y_hi:.1f}" width="{x_at(HOUR_MAX) - X0}" '
            f'height="{y_lo - y_hi:.1f}" fill="{TIER_COLOR[tier]}" opacity="0.065"/>')
        # 우측 등급명
        if hi is not None or lo == 38.0:
            out.append(
                f'<text x="{x_at(HOUR_MAX) + 10}" y="{(y_lo + y_hi) / 2 + 4:.1f}" '
                f'font-size="12" font-weight="600" fill="{TIER_COLOR[tier]}">{tier}</text>')

    for t in TICKS:
        y = y_at(t)
        solid = (t == 33)
        dash = "" if solid else ' stroke-dasharray="4 4"'
        color = TIER_COLOR["경계"] if solid else "rgba(29,31,32,.3)"
        out.append(f'<line x1="{X0}" y1="{y:.1f}" x2="{x_at(HOUR_MAX)}" y2="{y:.1f}" '
                   f'stroke="{color}" stroke-width="{1.4 if solid else 1}"{dash}/>')
        out.append(f'<text x="{X0 - 12}" y="{y + 4:.1f}" text-anchor="end" font-size="13" '
                   f'font-weight="600" fill="{TIER_COLOR.get(_tier_of(t), WEAK)}">{t}</text>')
    return "".join(out)


def _tier_of(temp: float) -> str:
    if temp >= 38:
        return "위험"
    if temp >= 35:
        return "심각"
    if temp >= 33:
        return "경계"
    if temp >= 31:
        return "주의"
    return "평시"


def _curve(hourly: list[dict]) -> str:
    pts = [(x_at(h["hour"]), y_at(h["apparent"])) for h in hourly]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    base = y_at(TEMP_BOTTOM)
    area = f"{line} {pts[-1][0]:.1f},{base} {pts[0][0]:.1f},{base}"

    out = [f'<polygon points="{area}" fill="{AREA_COLOR}" opacity="0.14"/>',
           f'<polyline points="{line}" fill="none" stroke="{LINE_COLOR}" stroke-width="2.5"/>']

    peak = max(hourly, key=lambda h: h["apparent"])
    for h in hourly:
        x, y = x_at(h["hour"]), y_at(h["apparent"])
        if h is peak:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{TIER_COLOR["심각"]}"/>')
            out.append(f'<text x="{x:.1f}" y="{y - 14:.1f}" text-anchor="middle" '
                       f'font-size="15" font-weight="700" fill="{TIER_COLOR["심각"]}">'
                       f'{h["apparent"]} 최고</text>')
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{LINE_COLOR}"/>')
    return "".join(out)


def _now_marker(now_text: str) -> str:
    x = x_at(_hm(now_text))
    label = f"지금 {now_text}"
    w = 8 + len(label) * 7
    return (f'<line x1="{x:.1f}" y1="{y_at(TEMP_TOP) - 24}" x2="{x:.1f}" y2="{BLOCK_Y + BLOCK_H}" '
            f'stroke="{TEXT}" stroke-width="1.5"/>'
            f'<rect x="{x - w / 2:.1f}" y="{y_at(TEMP_TOP) - 42}" width="{w}" height="18" '
            f'fill="{TEXT}"/>'
            f'<text x="{x:.1f}" y="{y_at(TEMP_TOP) - 29}" text-anchor="middle" font-size="12" '
            f'font-weight="600" fill="#f2f2f3">{_e(label)}</text>')


def _block_band(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        x1, x2 = x_at(b["start"]), x_at(b["end"])
        work = b.get("is_work", True)
        color = TIER_COLOR.get(b["tier"], NONWORK) if work else NONWORK
        # 심각 블록만 솔리드 — 훑을 때 먼저 걸리게 한다
        severe = work and b["tier"] in ("심각", "위험")
        if severe:
            out.append(f'<rect x="{x1}" y="{BLOCK_Y}" width="{x2 - x1}" height="{BLOCK_H}" '
                       f'fill="{color}"/>')
            fill = "#f2f2f3"
        else:
            dash = ' stroke-dasharray="4 3"' if not work else ""
            out.append(f'<rect x="{x1}" y="{BLOCK_Y}" width="{x2 - x1}" height="{BLOCK_H}" '
                       f'fill="none" stroke="{color}" stroke-width="1.2"{dash}/>')
            fill = color if work else WEAK
        out.append(f'<text x="{x1 + 8}" y="{BLOCK_Y + 19}" font-size="12.5" font-weight="600" '
                   f'fill="{fill}">{_e(b["label"])}</text>')
    return "".join(out)


def _rest_band(rests: list[dict], alarms: list[dict]) -> str:
    out = []
    for r in rests:
        x1 = x_at(_hm(r["start"]))
        w = r.get("minutes", 20) * 1.8
        color = TIER_COLOR.get(r.get("tier", "경계"), ACCENT)
        out.append(f'<rect x="{x1:.1f}" y="{REST_Y}" width="{w:.1f}" height="{REST_H}" '
                   f'fill="{color}"/>')
        out.append(f'<text x="{x1 + w / 2:.1f}" y="{REST_Y + REST_H + 13}" text-anchor="middle" '
                   f'font-size="11" fill="{MUTED}">{_e(r["start"])}</text>')
    for a in alarms:
        x = x_at(_hm(a["time"]))
        out.append(f'<polygon points="{x:.1f},{ALARM_Y} {x + 8:.1f},{ALARM_Y + 12} '
                   f'{x - 8:.1f},{ALARM_Y + 12}" fill="{TIER_COLOR["심각"]}"/>')
        out.append(f'<text x="{x:.1f}" y="{ALARM_Y - 6}" text-anchor="middle" font-size="11.5" '
                   f'font-weight="700" fill="{TIER_COLOR["심각"]}">알람 {_e(a["time"])}</text>')
    return "".join(out)


def _axis() -> str:
    out = []
    for h in range(HOUR_MIN, HOUR_MAX + 1):
        out.append(f'<text x="{x_at(h):.1f}" y="396" text-anchor="middle" font-size="12" '
                   f'fill="{WEAK}">{h:02d}</text>')
    for label, y in (("블록", BLOCK_Y + 19), ("휴식", REST_Y + 12)):
        out.append(f'<text x="{X0 - 12}" y="{y}" text-anchor="end" font-size="11" '
                   f'letter-spacing="1" fill="{WEAK}">{label}</text>')
    return "".join(out)


def build_svg(d: dict) -> str:
    return (
        '<svg viewBox="0 0 1200 400" style="width:100%;height:auto;display:block;'
        "font-family:'Barlow Condensed','IBM Plex Sans KR',sans-serif\">"
        + _bands()
        + _curve(d["hourly"])
        + _block_band(d["blocks"])
        + _rest_band(d["rests"], d["alarms"])
        + _now_marker(d["now_text"])
        + _axis()
        + "</svg>")


# =====================================================================
# 화면
# =====================================================================

def _topbar(d: dict) -> str:
    return f"""
<div class="sc" style="display:flex;justify-content:space-between;align-items:center;
     padding:11px 26px;border-bottom:1px solid {LINE}">
  <div style="display:flex;align-items:baseline;gap:14px">
    <span class="sc-num" style="font-weight:700;font-size:19px;letter-spacing:.06em">SAFECASTY</span>
    <span style="font-size:12.5px;color:{MUTED}">{_e(d['site'])} · {_e(d['date_text'])}</span>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <span class="sc-num" style="font-weight:600;font-size:19px">{_e(d['now_text'])}</span>
    {_badge(d['tier_chip'], TIER_COLOR[d['tier']], solid=True)}
    {_badge(d['alarm_chip'], TEXT, solid=False)}
  </div>
</div>"""


def _chart(d: dict, show_basis: bool) -> str:
    basis = ""
    if show_basis:
        rows = "".join(
            f'<div style="font-size:11.5px;color:{FAINT};line-height:1.6">{_e(t)}</div>'
            for t in d["basis_notes"])
        basis = f'<div style="margin-top:8px;border-top:1px solid {LINE_IN};padding-top:8px">{rows}</div>'
    return f"""
<div class="sc sc-bp" style="padding:16px 14px 10px;margin-top:18px">
  {_corners()}
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
    <span class="sc-cond" style="font-weight:600;font-size:17px">
      오늘 체감온도 · 공정 블록 · 조치 시각</span>
    <span style="font-size:11.5px;color:{WEAK}">1시간 예보 → 블록 내 최고값으로 등급 판정</span>
  </div>
  {build_svg(d)}
  {basis}
</div>"""


def _metrics(d: dict) -> str:
    cells = []
    for m in d["metrics"]:
        alert = m.get("alert")
        frame = (f"border:1px solid {TIER_COLOR['심각']};background:rgba(185,28,28,.05)"
                 if alert else f"border:1px solid {LINE}")
        vcolor = TIER_COLOR["심각"] if alert else TEXT
        cells.append(f"""
<div class="sc-bp" style="{frame};padding:14px 16px">
  {_corners()}
  <div class="sc-label">{_e(m['label'])}</div>
  <div class="sc-num" style="font-weight:600;font-size:32px;line-height:1.1;color:{vcolor}">
    {_e(m['value'])}</div>
  <div style="font-size:12px;color:{MUTED}">{_e(m['sub'])}</div>
</div>""")
    return (f'<div class="sc" style="display:grid;grid-template-columns:repeat(4,1fr);'
            f'gap:12px;margin-top:18px">{"".join(cells)}</div>')


def render(d: dict) -> dict:
    inject_css()
    _w(_topbar(d))

    _, t1 = st.columns([8, 2])
    show_basis = t1.toggle("근거 표시", value=True, key="sc1b_basis")

    _w(_chart(d, show_basis))
    _w(_metrics(d))
    return {"show_basis": show_basis}


# =====================================================================
# 샘플
# =====================================================================

def sample_data(now: datetime | None = None) -> dict:
    now = now or datetime(2026, 7, 23, 10, 20)
    hourly = [
        (8, 29.8), (9, 31.6), (10, 33.2), (11, 34.9), (12, 35.6), (13, 36.1),
        (14, 36.4), (15, 36.2), (16, 35.1), (17, 33.4), (18, 31.9),
    ]
    return {
        "site": "국민대학교 현장",
        "date_text": f"{now:%Y-%m-%d} (목)",
        "now_text": f"{now:%H:%M}",
        "tier": "경계",
        "tier_chip": "지금 경계 33.2℃",
        "alarm_chip": "다음 알람 13:40",
        "hourly": [{"hour": h, "apparent": t} for h, t in hourly],
        "blocks": [
            {"label": "오전 1부 · 주의 31.6", "start": 8, "end": 10, "tier": "주의"},
            {"label": "오전 2부 · 경계 34.9", "start": 10, "end": 12, "tier": "경계"},
            {"label": "점심 · 휴게", "start": 12, "end": 14, "tier": "심각", "is_work": False},
            {"label": "피크 · 심각 36.4 — 오후 옥외작업 중지 검토",
             "start": 14, "end": 17, "tier": "심각"},
            {"label": "마무리 33.4", "start": 17, "end": 18, "tier": "경계"},
        ],
        "rests": [
            {"start": "11:40", "minutes": 20, "tier": "경계"},
            {"start": "14:40", "minutes": 20, "tier": "심각"},
            {"start": "16:40", "minutes": 20, "tier": "심각"},
            {"start": "17:40", "minutes": 20, "tier": "경계"},
        ],
        "alarms": [{"time": "13:40"}],
        "basis_notes": [
            "판정값 = 블록 내 최고 체감온도 (별표13의2 공간축 MAX를 시간축으로 확장)",
            "고도 기온감률 −0.23℃ · 습도 재계산 · 격자별 상수 편의 보정",
            "등급 경계 31 / 33 / 35 / 38℃ — 제560조, 대응지침(2026.5)",
        ],
        "metrics": [
            {"label": "지금 판정", "value": "33.2℃ 경계", "sub": "기온 30.4 · 습도 66%"},
            {"label": "오늘 의무 휴식", "value": "4회 · 80분", "sub": "권고 포함 시 7회 · 125분"},
            {"label": "관리 대상", "value": "7 / 42명", "sub": "민감군 5 · 열순응 2"},
            {"label": "미확인 신고", "value": "1건", "sub": "10:07 · 자각증상 3개 체크",
             "alert": True},
        ],
    }


if __name__ == "__main__":
    st.set_page_config(page_title="SAFECASTY 타임라인", layout="wide")
    render(sample_data())
