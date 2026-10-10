"""
SAFECASTY — 시각별 판정 원본 (관제 시트)
=========================================
1시간 단위 예보와 그로부터 나온 판정·조치를 한 줄씩 펼친다.

[왜 이 화면이 필요한가]
    다른 화면은 "지금 무엇을 해야 하는가"를 보여준다.
    이 화면은 "그때 왜 그렇게 판정했는가"를 보여준다.

    체감온도·조치사항 기록은 법적 의무(제562조제2항제3호)이고,
    사고 조사나 근로감독에서 요구받는 것도 결국 이 형태다.
    블록 판정값이 어느 시각에서 나왔는지가 줄 위에 드러나야
    보수적 MAX가 왜 그 등급을 냈는지 설명할 수 있다.

[표를 직접 그리는 이유]
    st.dataframe은 캔버스로 그려져 등급색을 셀마다 칠할 수 없고,
    테마가 어긋나면 표만 어둡게 뜬다. 근거로 제출하는 자료이므로
    화면에 보이는 그대로가 확실한 편이 낫다.

사용:
    import sheet as SH
    SH.render(day_df, blocks, now=now, is_demo=demo, source=src)
"""

from __future__ import annotations

import html as _html
from datetime import datetime

import pandas as pd
import streamlit as st

import theme as TH

ROW_H = 34
HEAD_H = 28
COLS = "44px 76px 54px 56px 86px 1fr"

LINE = "rgba(29,31,32,.30)"
LINE_IN = "rgba(29,31,32,.16)"
MUTED = "#5D5D60"
WEAK = "#7A7A7D"
FAINT = "#98989B"
NONWORK = "#B7B7BA"


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _w(html_str: str) -> None:
    """HTML을 한 줄로 눌러 주입한다.

    st.markdown은 줄바꿈이 섞이면 일부를 마크다운으로 해석해 <p>를 끼워 넣는다.
    """
    import re
    st.markdown(re.sub(r">\s+<", "><", html_str).strip(), unsafe_allow_html=True)


# =====================================================================
# 행 만들기
# =====================================================================

def build_rows(day_df: pd.DataFrame, blocks: pd.DataFrame,
               now: datetime | None = None,
               action_of=None) -> list[dict]:
    """시간별 예보 + 블록 판정을 한 줄씩 합친다.

    day_df : enrich() 결과 (datetime, ta, rh, at, hour, day)
    blocks : build_blocks() 결과
    action_of : (block_row) -> str. 블록의 조치 요약 문구를 만드는 함수.
                넘기지 않으면 법적 근거(legal)를 쓴다.
    """
    if day_df is None or day_df.empty:
        return []

    now = now or datetime.now()
    rows = []

    # 블록 판정값을 결정한 시각 — 보수적 MAX가 어디서 나왔는지 표시한다
    deciding = set()
    if blocks is not None and not blocks.empty:
        for _, b in blocks.iterrows():
            if b.get("is_work", True):
                deciding.add(int(b["peak_hour"]))

    for _, r in day_df.sort_values("datetime").iterrows():
        h = int(r["hour"])

        # 공정 블록 밖의 시각은 싣지 않는다.
        #   판정도 조치도 없는 줄이 밤 시간까지 붙으면 표가 길어지기만 하고,
        #   정작 근거로 봐야 할 작업 구간이 묻힌다.
        if blocks is None or blocks.empty:
            continue
        hit = blocks[(blocks["start"].dt.hour <= h) & (blocks["end"].dt.hour > h)]
        if hit.empty:
            continue
        blk = hit.iloc[0]

        work = bool(blk.get("is_work", True))
        # tier_label 은 "심각 (폭염경보)" 처럼 길어 열을 넘친다.
        # 다른 화면과 같은 약칭을 쓴다 — 괄호 앞을 자르면 "관심 (평시)"가
        # "관심"이 되어 히어로의 "평시" 배지와 어긋난다.
        tier = str(blk.get("tier_short") or blk["tier_label"]).strip()
        color = str(blk["color"])
        # "피크 (무더위 시간대)" 처럼 긴 이름은 열을 넘친다. 괄호 앞만 쓴다.
        bname = str(blk["block_name"]).split("(")[0].strip()
        action = action_of(blk) if action_of else str(blk.get("legal", ""))

        rows.append({
            "hour": f"{h:02d}",
            "reading": f"{r['ta']:.1f}/{int(round(r['rh']))}",
            "at": f"{r['at']:.1f}",
            "tier": tier, "color": color, "is_work": work,
            "block": bname, "action": action,
            "now": h == now.hour and r["day"] == now.date(),
            "deciding": h in deciding,
        })
    return rows


# =====================================================================
# 그리기
# =====================================================================

def _head() -> str:
    cells = "".join(f"<span>{c}</span>" for c in
                    ("시각", "기온/습도", "체감", "등급", "블록", "조치"))
    return (f'<div class="sc-sheet-h" style="display:grid;grid-template-columns:{COLS};'
            f'gap:8px;height:{HEAD_H}px;align-items:center;padding:0 14px;'
            f'background:#E4E6E8;font-size:10.5px;letter-spacing:.1em;font-weight:600;'
            f'text-transform:uppercase;color:{MUTED};'
            f'border:1px solid {LINE};border-bottom:none">{cells}</div>')


def _row(r: dict) -> str:
    color = r["color"] if r["is_work"] else NONWORK
    bg = "background:rgba(194,65,12,.07);" if r["now"] else ""
    weight = "700" if r["now"] else "400"
    # 판정값을 결정한 시각은 체감을 등급색으로 세운다
    at_w = "700" if (r["deciding"] or r["now"]) else weight
    at_c = color if r["deciding"] else "#1D1F20"

    return f"""
<div style="display:grid;grid-template-columns:{COLS};gap:8px;height:{ROW_H}px;
     align-items:center;padding:0 14px;border-left:1px solid {LINE};
     border-right:1px solid {LINE};border-top:1px solid {LINE_IN};{bg}
     font-size:12px;font-weight:{weight};overflow:hidden;white-space:nowrap">
  <span style="font-variant-numeric:tabular-nums">{_e(r['hour'])}</span>
  <span style="color:{MUTED};font-variant-numeric:tabular-nums">{_e(r['reading'])}</span>
  <span style="font-weight:{at_w};color:{at_c};font-variant-numeric:tabular-nums">
    {_e(r['at'])}</span>
  <span style="font-weight:700;color:{color}">{_e(r['tier'])}</span>
  <span style="color:{MUTED};text-overflow:ellipsis;overflow:hidden">{_e(r['block'])}</span>
  <span style="text-overflow:ellipsis;overflow:hidden">{_e(r['action'])}</span>
</div>"""


def _foot(notes: list[str], is_demo: bool) -> str:
    color = "#B91C1C" if is_demo else WEAK
    body = "".join(f'<div style="font-size:11px;color:{color};line-height:1.65">'
                   f'{_e(t)}</div>' for t in notes)
    return (f'<div style="padding:9px 14px 11px;border:1px solid {LINE};'
            f'border-top:1px solid {LINE_IN}">{body}</div>')


def render(day_df: pd.DataFrame, blocks: pd.DataFrame, *,
           now: datetime | None = None,
           is_demo: bool = False,
           source: str = "",
           correction_note: str = "",
           action_of=None) -> None:
    """시각별 판정 원본을 그린다.

    is_demo: 데모 데이터면 보정 설명이 사실이 아니므로 주석을 갈아끼운다.
    source : 기준 발표본 등 출처 한 줄.
    """
    TH.apply()

    rows = build_rows(day_df, blocks, now, action_of)
    if not rows:
        st.caption("표시할 예보 구간이 없습니다.")
        return

    meta = []
    if source:
        meta.append(_e(source))
    meta.append("제562조제2항제3호 — 일자별 기록·연말까지 보관")

    _w(f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
       f'padding:2px 0 8px"><span style="font-weight:600;font-size:14px;'
       f'letter-spacing:.04em">시각별 판정 원본</span>'
       f'<span style="font-size:11px;color:{WEAK}">{" · ".join(meta)}</span></div>')

    _w(_head() + "".join(_row(r) for r in rows))

    if is_demo:
        notes = ["기상청 예보를 받지 못해 데모 데이터로 표시 중입니다. "
                 "고도·습도·편의 보정은 적용되지 않았습니다.",
                 "이 화면의 값은 실제 판정 근거가 아니며 기록으로 남길 수 없습니다."]
    else:
        notes = ["판정값 = 블록 내 최고 체감온도 "
                 "(별표13의2 공간축 MAX를 시간축으로 확장). "
                 "체감이 굵게 표시된 시각이 그 블록의 등급을 결정했습니다."]
        if correction_note:
            notes.append(correction_note)
    _w(_foot(notes, is_demo))
