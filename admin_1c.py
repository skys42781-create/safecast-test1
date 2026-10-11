"""
SAFECASTY — 관리자 대시보드 1c (관제 시트)
==========================================
시각별 판정 원본과 근거를 한 화면에. 근로감독·사고 조사 대응 문법.

[이 화면의 목적]
    1a는 아침에 훑는 화면, 1b는 하루를 한 눈에 보는 화면,
    1c는 "그때 왜 그렇게 판정했나"를 보여주는 화면이다.
    모든 숫자에 출처가 있어야 한다는 원칙이 가장 직접적으로 드러난다.

[조치 이행 체크를 표 안에 넣는 방법]
    Streamlit 위젯은 커스텀 HTML 안에 들어가지 못한다.
    그렇다고 HTML로 체크박스를 그리면 눌러도 서버에 아무것도 남지 않는다.
    기록이 법적 의무(제562조제2항제3호)인 이상 흉내만 내는 체크는 쓸 수 없다.

    → 표 본문은 HTML로 그대로 그리고, 체크만 담은 좁은 열을 오른쪽에 붙인다.
      행 높이를 ROW_H로 양쪽 모두 고정하므로 줄이 어긋나지 않는다.
      체크 열에는 라벨을 넣지 않는다. 글자가 줄바꿈되면 정렬이 깨지기 때문이다.

[상태] app.py에 연결되기 전이다. sample_data()는 시안의 예시 값이며
      실제 판정값이 아니다. 단독 확인: streamlit run admin_demo.py

사용:
    import admin_1c as C
    C.render(C.sample_data())
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from admin_1a import (
    ACCENT, FAINT, LINE, LINE_IN, MUTED, NONWORK, TEXT, TIER_COLOR, WEAK,
    _badge, _corners, _e, _w, inject_css,
)

SHEET_CANVAS = 1180

# 표 행 높이. HTML 행과 체크 열이 같은 값을 쓰므로 여기만 바꾸면 함께 움직인다.
ROW_H = 34
HEAD_H = 28

# 이행 열까지 표 안에 포함한다. 상태 표시는 HTML, 입력은 아래 패널이 받는다.
COLS = "38px 60px 44px 50px 46px 1fr 34px"


# =====================================================================
# 위젯 스타일 — 제도 시트 문법에 맞춘다
# =====================================================================

# =====================================================================
# 상단 바
# =====================================================================

# =====================================================================
# 좌: 시각별 판정 원본
# =====================================================================

def _sheet_title(d: dict) -> str:
    return f"""
<div class="sc" style="display:flex;justify-content:space-between;align-items:baseline;
     padding:12px 0 10px">
  <span class="sc-cond" style="font-weight:600;font-size:17px">시각별 판정 원본</span>
  <span style="font-size:11px;color:{WEAK}">{_e(d['retention_note'])}</span>
</div>"""


def _sheet_head() -> str:
    head = "".join(
        f"<span>{c}</span>"
        for c in ("시각", "기온/습도", "체감", "등급", "블록", "조치", "이행"))
    return (f'<div class="sc-label" style="display:grid;grid-template-columns:{COLS};gap:8px;'
            f'height:{HEAD_H}px;align-items:center;padding:0 14px;'
            f'background:rgba(29,31,32,.05);font-size:10.5px;letter-spacing:.1em;'
            f'border-left:1px solid {LINE};border-right:1px solid {LINE};'
            f'border-top:1px solid {LINE}">{head}</div>')


def _sheet_row(r: dict) -> str:
    color = TIER_COLOR.get(r["tier"], NONWORK)
    is_now = r.get("now")
    deciding = r.get("deciding")

    bg = "background:rgba(194,65,12,.06);" if is_now else ""
    weight = "700" if is_now else "400"
    emph_w = "700" if (deciding or is_now) else weight
    emph_c = color if deciding else TEXT

    # 이행 상태 — 체크 대상이 아니면 줄표, 미완료는 빈 네모, 완료는 채운 체크
    if not r.get("checkable"):
        mark, mark_css = "—", f"color:{FAINT}"
    elif r.get("done"):
        mark, mark_css = "✓", f"color:{ACCENT};font-weight:700"
    else:
        mark, mark_css = "□", f"color:{TIER_COLOR['주의']}"

    return f"""
<div style="display:grid;grid-template-columns:{COLS};gap:8px;height:{ROW_H}px;
     align-items:center;padding:0 14px;border-top:1px solid {LINE_IN};
     border-left:1px solid {LINE};border-right:1px solid {LINE};
     {bg}font-size:12px;font-weight:{weight};
     overflow:hidden;white-space:nowrap">
  <span>{_e(r['hour'])}</span>
  <span style="color:{MUTED}">{_e(r['reading'])}</span>
  <span style="font-weight:{emph_w};color:{emph_c}">{_e(r['apparent'])}</span>
  <span style="font-weight:700;color:{color}">{_e(r['tier'])}</span>
  <span style="color:{MUTED}">{_e(r['block'])}</span>
  <span style="text-overflow:ellipsis;overflow:hidden">{_e(r['action'])}</span>
  <span style="text-align:center;font-size:13px;{mark_css}">{mark}</span>
</div>"""


def _sheet_body(d: dict) -> str:
    rows = "".join(_sheet_row(r) for r in d["hourly"])
    return _sheet_head() + rows


def _sheet_foot(d: dict, show_basis: bool) -> str:
    """근거 주석. 데모일 때는 보정 설명이 거짓이 되므로 문장을 갈아끼운다."""
    if not show_basis:
        return ""
    notes = (d["demo_notes"] if d.get("is_demo") else d["basis_notes"])
    color = TIER_COLOR["심각"] if d.get("is_demo") else WEAK
    body = "".join(
        f'<div style="font-size:11px;color:{color};line-height:1.65">{_e(t)}</div>'
        for t in notes)
    return (f'<div class="sc" style="padding:9px 14px 12px;border-top:1px solid {LINE_IN};'
            f'border-left:1px solid {LINE};border-right:1px solid {LINE}">{body}</div>')


# =====================================================================
# 우: 4개 패널
# =====================================================================

def _record_rows(d: dict) -> str:
    """기록 상태를 표에서 직접 센다.

    고정값을 적어 두면 표와 패널의 숫자가 어긋난다.
    근거 화면에서 같은 사실이 두 자리에 다르게 적히면 화면 전체를 못 믿게 되므로
    항상 hourly에서 계산한다.

    자동/수동 구분은 반드시 유지한다 — 판정 원칙 2의 UI 표현이다.
    체감온도는 시스템이 기록하지만 조치 이행은 사람만 체크할 수 있다.
    """
    hours = d["hourly"]
    logged = sum(1 for r in hours if r.get("apparent"))
    ck = [r for r in hours if r.get("checkable")]
    done = sum(1 for r in ck if r.get("done"))

    rows = [
        {"label": "시간별 체감온도 기록", "value": f"자동 {logged}/{len(hours)}",
         "color": TIER_COLOR["평시"] if logged == len(hours) else TIER_COLOR["주의"]},
        {"label": "조치 이행 체크", "value": f"수동 {done}/{len(ck)}",
         "color": TIER_COLOR["평시"] if done == len(ck) else TIER_COLOR["주의"]},
        {"label": "TBM 명단 배포", "value": d.get("tbm_distributed", "미배포"),
         "color": TEXT if d.get("tbm_distributed") else TIER_COLOR["심각"]},
    ]
    out = []
    for r in rows:
        out.append(f"""
<div style="display:flex;justify-content:space-between;padding:5px 0;font-size:12px;
     border-top:1px solid {LINE_IN}">
  <span>{_e(r['label'])}</span>
  <span style="font-weight:700;color:{r['color']}">{_e(r['value'])}</span>
</div>""")
    return "".join(out)


# =====================================================================
# 렌더
# =====================================================================

def render(d: dict, *, show_basis: bool = True) -> dict:
    """시각별 판정 원본.

    관제 화면 안에 접어 넣는 조각이다. 상단 바와 지표는 그리지 않는다.
    이 조각의 값어치는 "그때 왜 그렇게 판정했는가"를 한 줄씩 펼치는 것뿐이다.
    """
    inject_css()

    _w(_sheet_title(d))
    _w(_sheet_body(d))
    _w(_sheet_foot(d, show_basis))

    # ---- 기록 상태 ----
    # 자동과 수동을 구분해 보여주는 것은 판정 원칙 2의 UI 표현이라
    # 다른 화면에 없다. 표와 함께 둔다.
    _w(f'<div class="sc" style="display:flex;justify-content:space-between;'
       f'align-items:baseline;padding:14px 0 8px">'
       f'<span class="sc-cond" style="font-weight:600;font-size:15px">기록 상태</span>'
       f'<span style="font-size:11px;color:{WEAK}">'
       f'제562조제2항제3호 — 일자별 기록·연말까지 보관</span></div>')
    _w(f'<div class="sc" style="border:1px solid {LINE};padding:10px 16px">'
       f'{_record_rows(d)}</div>')

    locked = d.get("is_demo", False)
    if locked:
        st.caption("데모 데이터는 기록으로 내보낼 수 없습니다.")
    export = st.button("오늘 기록 내보내기", key="sc1c_export", disabled=locked)
    return {"export": export, "show_basis": show_basis}


# =====================================================================
# 샘플
# =====================================================================

def sample_data(now: datetime | None = None) -> dict:
    now = now or datetime(2026, 7, 23, 10, 20)
    rows = [
        ("08", "27.9/74", "29.8", "평시", "오전1", "온·습도계 비치 확인", True, "온·습도계 비치"),
        ("09", "29.2/70", "31.6", "주의", "오전1",
         "냉방 송풍기 가동 · 열순응 1명 09:36 종료", True, "냉방 송풍기"),
        ("10", "30.4/66", "33.2", "경계", "오전2", "진행 중 — 11:40 휴식 예정", False, None),
        ("11", "31.8/63", "34.9", "경계", "오전2",
         "블록 판정값 결정 시각 · 11:40–12:00 휴식", False, "11:40 휴식"),
        ("12", "32.4/61", "35.6", "심각", "점심", "그늘 휴게장소 · 소금·음료수 점검", False,
         "휴게장소 점검"),
        ("13", "32.8/60", "36.1", "심각", "점심", "13:40 피크 진입 알람 예정", False, None),
        ("14", "33.1/59", "36.4", "심각", "피크", "오후 옥외작업 중지 검토 · 14:40 휴식",
         False, "14:40 휴식"),
        ("15", "33.0/59", "36.2", "심각", "피크", "민감군 5명 옥외 제외 · 순환 배치", False,
         "민감군 제외"),
        ("16", "32.2/62", "35.1", "심각", "피크", "16:40–17:00 휴식", False, "16:40 휴식"),
        ("17", "31.0/65", "33.4", "경계", "마무리", "17:40–18:00 휴식 후 철수", False,
         "17:40 휴식"),
        ("18", "29.6/69", "31.9", "주의", "—", "작업 종료", False, None),
    ]
    hourly = []
    for h, reading, ap, tier, blk, act, done, label in rows:
        hourly.append({
            "hour": h, "reading": reading, "apparent": ap, "tier": tier,
            "block": blk, "action": act,
            "now": h == "10", "deciding": h == "11",
            "checkable": label is not None, "check_label": label or "", "done": done,
        })

    return {
        "meta_line": ("국민대학교 현장 · 격자 60/128 · 2026-07-23 (목) · 출역 42명 · "
                      "기준 단기예보 10시 발표"),
        "metrics": [
            {"label": "현재", "value": "33.2℃"},
            {"label": "최고", "value": "36.4℃"},
            {"label": "손실률", "value": "12.5%"},
            {"label": "알람", "value": "13:40"},
        ],
        "retention_note": "제562조제2항제3호 — 일자별 기록·연말까지 보관",
        "hourly": hourly,
        "basis_notes": [
            "체감온도 = 기온·습도 기반 산출값에 고도 기온감률 보정(−0.23℃)과 "
            "습도 재계산을 적용, 격자별 상수 편의로 보정.",
            "과소판정 6.6% 방법을 채택(RMSE 최저안은 과소판정 10.2%로 배제). "
            "조치 이행 체크는 관리자 수동 입력.",
        ],
        # 데모일 때는 보정 설명이 사실이 아니므로 다른 문장을 쓴다.
        "demo_notes": [
            "기상청 예보를 받지 못해 데모 데이터로 표시 중입니다. "
            "고도·습도·편의 보정은 적용되지 않았습니다.",
            "이 화면의 값은 실제 판정 근거가 아니며 기록으로 남길 수 없습니다.",
        ],
        "blocks": [
            {"name": "오전 1부", "hours": "08–10", "value": "31.6", "tier": "주의",
             "tier_label": "주의"},
            {"name": "오전 2부", "hours": "10–12", "value": "34.9", "tier": "경계",
             "tier_label": "경계", "running": True},
            {"name": "점심 · 휴게", "hours": "12–14", "value": "36.1", "tier": "심각",
             "tier_label": "비작업", "is_work": False},
            {"name": "피크", "hours": "14–17", "value": "36.4", "tier": "심각",
             "tier_label": "심각"},
            {"name": "마무리", "hours": "17–18", "value": "33.4", "tier": "경계",
             "tier_label": "경계"},
        ],
        "worker_total": 7,
        "workers": [
            {"name": "김O수", "types": "⑦신규 · 20%", "status": "09:36", "risk": "심각"},
            {"name": "박O민", "types": "복귀 · 70%", "status": "14:36", "risk": "경계"},
            {"name": "이O헌", "types": "③고령 · ①만성", "status": "피크 제외", "risk": "주의"},
            {"name": "최O라", "types": "⑥고강도 · ⑧저하", "status": "관찰", "risk": "주의"},
            {"name": "이 외", "types": "3명 · ②기왕력 ④약물", "status": "관찰", "risk": "평시"},
        ],
        "report": {
            "count_open": 1, "when": "10:07", "where": "골조 3층", "who": "정O우", "count": 3,
            "symptoms": "어지러움 · 심한 갈증 · 근육경련 — 2개 이상, 119 안내 노출됨",
        },
        "tbm_distributed": "07:40 완료",
        # 데모 데이터로 돌고 있으면 True — 이행 체크와 내보내기가 잠긴다.
        "is_demo": False,
    }


if __name__ == "__main__":
    st.set_page_config(page_title="SAFECASTY 관제 시트", layout="wide")
    render(sample_data())
