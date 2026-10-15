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

import math
from datetime import datetime

import streamlit as st

from admin_1a import (
    ACCENT, FAINT, LINE_IN, NONWORK, TEXT, TIER_COLOR, WEAK,
    _corners, _e, _w, inject_css,
)

# =====================================================================
# 좌표 변환
# =====================================================================

X0, X_PER_HOUR = 60.0, 108.0      # 08시 기준
Y0, PLOT_H = 40.0, 260.0          # 38℃ 자리와 그래프 세로 길이
HOUR_MIN, HOUR_MAX = 8, 18
TEMP_TOP, TEMP_BOTTOM = 38.0, 28.0

BLOCK_Y, BLOCK_H = 320, 30
REST_Y, REST_H = 362, 16
ALARM_Y = 306

# 차트 색 — 흰 종이 위에서 또렷하게 읽혀야 한다.
#   옅게 두면 프로젝터나 밝은 현장에서 선이 날아간다.
LINE_COLOR = "#1B2E42"            # 폴리라인 (거의 잉크에 가까운 짙은 남색)
AREA_COLOR = "#44688C"            # 하단 면


def x_at(hour: float) -> float:
    return X0 + (hour - HOUR_MIN) * X_PER_HOUR


def y_at(temp: float, bottom: float = TEMP_BOTTOM) -> float:
    """체감온도 → y좌표. 위는 항상 38℃, 아래만 움직인다.

    [왜 아래만 움직이는가]
      등급 경계(31·33·35·38)는 법이 정한 값이라 늘 보여야 한다. 위를
      고정하면 어느 날 차트를 봐도 경계선이 같은 자리에 있어 두 날을
      겹쳐 읽을 수 있다.

      반대로 아래를 28℃에 못 박아 두면 선선한 날 예보가 바닥 밖으로
      나가 선이 통째로 사라진다. 10월에 16℃가 찍히면 y좌표가 600을
      넘어 viewBox(높이 400) 밖이다. 여름에는 28℃ 밑이 거의 없어
      드러나지 않지만, 봄·가을에는 매일 빈 그래프가 된다.

      그래서 바닥만 데이터에 맞춰 내린다. 더운 날(최저 28℃ 이상)은
      bottom 이 28 그대로라 눈금 간격이 26px — 지금과 완전히 같다.
    """
    return Y0 + (TEMP_TOP - temp) * (PLOT_H / (TEMP_TOP - bottom))


def chart_bottom(hourly: list[dict]) -> float:
    """차트 바닥 온도. 더우면 28℃, 선선하면 최저값보다 한 칸 아래."""
    if not hourly:
        return TEMP_BOTTOM
    lo = min(float(h["apparent"]) for h in hourly)
    return min(TEMP_BOTTOM, float(math.floor(lo)) - 1.0)


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
]
TICKS = [38, 35, 33, 31]


def _bands(bottom: float = TEMP_BOTTOM) -> str:
    """등급 밴드 + 경계선 + 우측 라벨.

    33℃만 실선이다 — 2시간마다 20분 휴식이 시작되는 법적 의무 경계이므로
    다른 경계와 시각적으로 구분한다.

    평시 밴드와 맨 아래 눈금은 bottom 을 따라간다. 선선한 날에는
    평시 구간이 넓어지는데, 그게 사실이다 — 경계까지 여유가 그만큼 있다.
    """
    out = []
    top_y = y_at(TEMP_TOP, bottom) - 24
    for lo, hi, tier in list(BANDS) + [(bottom, 31.0, "평시")]:
        y_lo = y_at(lo, bottom)
        y_hi = top_y if hi is None else y_at(hi, bottom)
        out.append(
            f'<rect x="{X0}" y="{y_hi:.1f}" width="{x_at(HOUR_MAX) - X0}" '
            f'height="{y_lo - y_hi:.1f}" fill="{TIER_COLOR[tier]}" opacity="0.11"/>')
        # 우측 등급명
        if hi is not None or lo == 38.0:
            out.append(
                f'<text x="{x_at(HOUR_MAX) + 10}" y="{(y_lo + y_hi) / 2 + 4:.1f}" '
                f'font-size="12" font-weight="600" fill="{TIER_COLOR[tier]}">{tier}</text>')

    for t in list(TICKS) + [int(bottom)]:
        y = y_at(t, bottom)
        solid = (t == 33)
        dash = "" if solid else ' stroke-dasharray="4 4"'
        color = TIER_COLOR["경계"] if solid else "rgba(29,31,32,.45)"
        out.append(f'<line x1="{X0}" y1="{y:.1f}" x2="{x_at(HOUR_MAX)}" y2="{y:.1f}" '
                   f'stroke="{color}" stroke-width="{1.8 if solid else 1.2}"{dash}/>')
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


def _curve(hourly: list[dict], bottom: float = TEMP_BOTTOM) -> str:
    pts = [(x_at(h["hour"]), y_at(h["apparent"], bottom)) for h in hourly]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    base = y_at(bottom, bottom)
    area = f"{line} {pts[-1][0]:.1f},{base} {pts[0][0]:.1f},{base}"

    out = [f'<polygon points="{area}" fill="{AREA_COLOR}" opacity="0.22"/>',
           f'<polyline points="{line}" fill="none" stroke="{LINE_COLOR}" stroke-width="3"/>']

    peak = max(hourly, key=lambda h: h["apparent"])
    # 최고점 색은 그 온도의 등급을 따른다.
    # 28℃인 날에도 빨간 점이 찍히면 더운 날로 잘못 읽힌다.
    peak_color = TIER_COLOR[_tier_of(peak["apparent"])]
    for h in hourly:
        x, y = x_at(h["hour"]), y_at(h["apparent"], bottom)
        if h is peak:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{peak_color}"/>')
            out.append(f'<text x="{x:.1f}" y="{y - 14:.1f}" text-anchor="middle" '
                       f'font-size="15" font-weight="700" fill="{peak_color}">'
                       f'{h["apparent"]:.1f} 최고</text>')
        else:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="{LINE_COLOR}"/>')
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
        # 시각은 띠 안에 흰 글씨로 넣는다.
        # 띠 아래에 두면 바로 밑 시각축 숫자와 겹쳐 둘 다 못 읽는다.
        out.append(f'<text x="{x1 + w / 2:.1f}" y="{REST_Y + REST_H - 4}" text-anchor="middle" '
                   f'font-size="10" font-weight="600" fill="#ffffff">{_e(r["start"])}</text>')
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
    # now_text 가 비면 '지금' 선을 그리지 않는다.
    #   내일 차트에는 현재 시각이 없다. 빈 값으로 넘어오면 표시를 거른다.
    #   억지로 그리면 내일 08시에 '지금'이 찍혀 오늘로 오해하게 된다.
    now = _now_marker(d["now_text"]) if d.get("now_text") else ""
    # 바닥을 밖에서 정해 줄 수 있다. 오늘·내일 두 장을 같은 자로 재야
    # 선의 높이 차이가 곧 더위의 차이가 된다.
    bottom = d.get("bottom") if d.get("bottom") is not None \
        else chart_bottom(d["hourly"])
    return (
        '<svg viewBox="0 0 1200 400" style="width:100%;height:auto;display:block;'
        "font-family:'Barlow Condensed','IBM Plex Sans KR',sans-serif\">"
        + _bands(bottom)
        + _curve(d["hourly"], bottom)
        + _block_band(d["blocks"])
        + _rest_band(d["rests"], d["alarms"])
        + now
        + _axis()
        + "</svg>")


# =====================================================================
# 화면
# =====================================================================

def _chart(d: dict, show_basis: bool, title: str, note: str) -> str:
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
    <span class="sc-cond" style="font-weight:600;font-size:17px">{_e(title)}</span>
    <span style="font-size:11.5px;color:{WEAK}">{_e(note)}</span>
  </div>
  {build_svg(d)}
  {basis}
</div>"""


def render(d: dict, *, show_basis: bool = True,
           title: str = "오늘 체감온도 · 공정 블록 · 조치 시각",
           note: str = "1시간 예보 → 블록 내 최고값으로 등급 판정") -> dict:
    """시각 축 차트.

    관제 화면 안에 끼워 넣는 조각이다. 상단 바와 지표는 그리지 않는다 —
    바로 위 히어로가 같은 내용을 이미 보여준다.

    제목을 밖에서 넘길 수 있게 열어 둔 것은 같은 그림으로 내일 예보도
    그리기 위해서다. 축과 등급 띠가 오늘과 똑같아야 두 장을 위아래로
    놓고 눈으로 바로 비교할 수 있다.
    """
    inject_css()
    _w(_chart(d, show_basis, title, note))
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
