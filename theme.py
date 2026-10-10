"""
SAFECASTY — 전역 테마 (Blueprint)
===================================
건설 도면 문법으로 화면을 구성한다.

[왜 청사진인가]
  토목·건설 현장의 문서는 도면이다. 각진 모서리, 가는 실선, 모눈 위의
  배치가 이 분야의 시각 언어이며, 둥글고 부드러운 소비자 앱 문법보다
  주제에 맞는다. 화면을 처음 본 사람이 "이 분야를 이해하고 만들었다"고
  느끼는 차이가 여기서 난다.

[색 운용]
  구조는 스틸블루 단색으로 조용히 두고, 판정 등급에만 색을 쓴다.
  화면에서 색이 보이면 그것은 곧 위험 신호다.

[폰트]
  원본 시스템은 Barlow Condensed를 쓰나 한글 글자가 없어, 제목이 한글이면
  fallback으로 떨어져 자간이 어긋난다. IBM Plex Sans KR은 성격이 비슷하면서
  한글을 온전히 담고 있다.

[다크모드를 지원하지 않는 이유]
  이 화면은 흰 종이 위의 도면이다. 카드 배경을 #fff로 고정해 두었는데
  보는 사람이 다크모드를 쓰면 Streamlit이 글자만 흰색으로 바꾸어
  흰 바탕에 흰 글자가 된다. 배경을 고정한 이상 글자색도 함께 고정해야 한다.

  .streamlit/config.toml 에서 base="light" 로 못박고, 여기서는 그 설정이
  없거나 무시되는 경우에도 글자가 사라지지 않도록 색을 직접 지정한다.
  표(st.dataframe)는 캔버스로 그려져 CSS가 닿지 않으므로 config.toml 만이
  유일한 수단이다.
"""

from __future__ import annotations

import streamlit as st

TIER = {
    "평시": "#15803D", "주의": "#B45309", "경계": "#C2410C",
    "심각": "#B91C1C", "위험": "#7F1D2D",
}

ACCENT = "#5980A6"
INK = "#1D1F20"
GROUND = "#F2F2F3"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --sc-ink: #1D1F20;
  --sc-ground: #F2F2F3;
  --sc-accent: #5980A6;
  /* 실선 — 도면의 뼈대. 너무 옅으면 표가 안 읽힌다. */
  --sc-line: rgba(29,31,32,.30);       /* 바깥 테두리 */
  --sc-line-soft: rgba(29,31,32,.16);  /* 행 구분선 */
  --sc-rule: rgba(29,31,32,.22);       /* 표 격자 */
  --sc-head: #E4E6E8;                  /* 표 머리행 */
  --sc-mono: 'IBM Plex Mono', ui-monospace, monospace;
}

html, body, [class*="css"], .stApp, button, input, textarea, select {
  font-family: 'IBM Plex Sans KR', system-ui, sans-serif !important;
}
/* 브라우저·OS가 다크모드여도 폼 컨트롤이 어두워지지 않게 한다 */
:root { color-scheme: light; }

/* 배경을 고정했으므로 글자색도 함께 고정한다.
   하나만 고정하면 다크모드에서 흰 바탕에 흰 글자가 된다. */
.stApp { letter-spacing: -0.1px; background: #F2F2F3; color: var(--sc-ink); }
.stApp, .stApp p, .stApp li, .stApp span, .stApp label,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stMarkdown, .stMarkdown *, div[data-testid="stMarkdownContainer"],
div[data-testid="stMarkdownContainer"] * {
  color: var(--sc-ink);
}
/* 단, 색을 직접 지정한 요소는 건드리지 않는다 — 등급색이 살아야 한다 */
.stApp [style*="color:"] { color: revert; }
section[data-testid="stSidebar"] {
  background: #EDEDEE; border-right: 1px solid var(--sc-line);
}
section[data-testid="stSidebar"], section[data-testid="stSidebar"] * {
  color: var(--sc-ink);
}
section[data-testid="stSidebar"] [style*="color:"] { color: revert; }
.block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1240px; }

/* ---------- 도면 카드 ---------- */
.bp {
  position: relative; background: #fff; color: var(--sc-ink);
  border: 1px solid var(--sc-line); border-radius: 2px; padding: 14px 16px;
}
.bp::before, .bp::after,
.bp > .bpc::before, .bp > .bpc::after {
  content: ''; position: absolute; background: #5980A6; opacity: .55;
}
.bp::before { top: -1px; left: -1px; width: 9px; height: 1px; }
.bp::after  { top: -1px; left: -1px; width: 1px; height: 9px; }
.bp > .bpc::before { bottom: -1px; right: -1px; width: 9px; height: 1px; }
.bp > .bpc::after  { bottom: -1px; right: -1px; width: 1px; height: 9px; }

/* ---------- 탭 ---------- */
.stTabs [data-baseweb="tab-list"] {
  gap: 0; border-bottom: 1px solid var(--sc-line); padding: 0;
  background: transparent; overflow-x: auto; scrollbar-width: none;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
.stTabs [data-baseweb="tab"] {
  height: 40px; padding: 0 18px; border-radius: 0; border: none;
  background: transparent; font-size: 13.5px; font-weight: 500;
  white-space: nowrap; color: rgba(29,31,32,.55);
  border-bottom: 2px solid transparent; transition: color .15s, border-color .15s;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--sc-ink); }
.stTabs [aria-selected="true"] {
  color: var(--sc-ink) !important; font-weight: 600;
  border-bottom-color: #5980A6 !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- 지표 ---------- */
div[data-testid="stMetric"] {
  background: #fff; border: 1px solid var(--sc-line);
  border-radius: 2px; padding: 14px 16px;
}
div[data-testid="stMetricLabel"] p {
  font-size: 11px !important; opacity: .55; font-weight: 500; letter-spacing: .3px;
}
div[data-testid="stMetricValue"] {
  font-size: 26px !important; font-weight: 600; letter-spacing: -.8px;
  font-variant-numeric: tabular-nums;
}
div[data-testid="stMetricDelta"] { font-size: 11px !important; opacity: .6; }

/* ---------- 버튼 ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 2px; border: 1px solid var(--sc-line);
  padding: 9px 18px; font-weight: 500; font-size: 13px;
  background: #fff; color: var(--sc-ink);
  transition: background .15s, border-color .15s;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: #EFF3F7; border-color: #5980A6;
}
.stButton > button:active { background: #DFE8F0; }
.stButton > button[kind="primary"], .stFormSubmitButton > button {
  background: #5980A6; color: #fff; border-color: #5980A6;
}
.stButton > button[kind="primary"]:hover { background: #4A6E92; }
button:focus-visible { outline: 2px solid #5980A6 !important; outline-offset: 2px; }

/* ---------- 입력 ---------- */
.stTextInput input, .stNumberInput input, .stDateInput input,
div[data-baseweb="select"] > div, .stTextArea textarea {
  border-radius: 2px !important; border: 1px solid var(--sc-line) !important;
  background: #fff !important; font-size: 13.5px !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
  border-color: #5980A6 !important; box-shadow: 0 0 0 1px #5980A6 !important;
}
.stFileUploader > section {
  border-radius: 2px; border: 1px dashed var(--sc-line); background: #fff;
}

/* ---------- 라디오 ---------- */
div[role="radiogroup"] { gap: 0; }
div[role="radiogroup"] label {
  border-radius: 0; padding: 7px 14px; font-size: 13px; font-weight: 500;
  border: 1px solid var(--sc-line); margin-right: -1px; background: #fff;
}
div[role="radiogroup"] label:hover { background: #EFF3F7; }

/* ---------- expander ---------- */
div[data-testid="stExpander"] {
  border: 1px solid var(--sc-line) !important; border-radius: 2px;
  background: #fff; margin-bottom: 8px;
}
div[data-testid="stExpander"] summary {
  padding: 12px 16px; font-weight: 600; font-size: 13.5px;
}
div[data-testid="stExpander"] summary:hover { background: #EFF3F7; }
div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] {
  padding: 2px 16px 14px; border-top: 1px solid var(--sc-line-soft);
}

/* ---------- 표 ----------
   st.dataframe 은 캔버스로 그려져 셀 격자선까지 CSS로 칠할 수 없다.
   배경·글자·격자 색은 .streamlit/config.toml 의 테마 값을 따른다.
   여기서는 바깥 테두리처럼 CSS가 닿는 부분만 또렷하게 만든다. */
div[data-testid="stDataFrame"] {
  border-radius: 2px; border: 1px solid var(--sc-line); overflow: hidden;
}

/* 직접 그린 표 — 이쪽은 CSS가 온전히 닿으므로 격자를 분명히 세운다 */
.sc-table {
  width: 100%; border-collapse: collapse; background: #fff;
  border: 1px solid var(--sc-line); font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}
.sc-table thead th {
  background: var(--sc-head); color: var(--sc-ink);
  font-size: 11px; font-weight: 600; letter-spacing: .6px; text-transform: uppercase;
  text-align: left; padding: 8px 10px;
  border-bottom: 1px solid var(--sc-line);
  border-right: 1px solid var(--sc-rule);
}
.sc-table tbody td {
  padding: 8px 10px; color: var(--sc-ink);
  border-top: 1px solid var(--sc-line-soft);
  border-right: 1px solid var(--sc-rule);
}
.sc-table thead th:last-child, .sc-table tbody td:last-child { border-right: none; }
/* 줄이 길어져도 눈이 행을 놓치지 않게 한 줄 걸러 옅게 깐다 */
.sc-table tbody tr:nth-child(even) td { background: rgba(29,31,32,.025); }
.sc-table tbody tr:hover td { background: #EFF3F7; }
div[data-testid="stAlert"] {
  border-radius: 2px; border: 1px solid var(--sc-line);
  border-left-width: 3px; padding: 13px 16px; font-size: 13px;
}
div[data-testid="stAlert"], div[data-testid="stAlert"] * { color: var(--sc-ink); }

/* ---------- 섹션 제목 ---------- */
.sec {
  display: flex; align-items: baseline; gap: 10px;
  margin: 26px 0 10px; padding-bottom: 7px;
  border-bottom: 1px solid var(--sc-line);
}
.sec-t {
  font-size: 13px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase;
}
.sec-n { font-size: 11.5px; opacity: .5; }

/* ---------- 요약 그리드 ---------- */
.sm-grid {
  display: grid; gap: 1px; margin: 2px 0 6px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  border: 1px solid var(--sc-line); background: var(--sc-line);
}
.sm-card { background: #fff; color: var(--sc-ink); padding: 14px 16px;
            animation: bpIn .4s ease both; }
.sm-l {
  font-size: 10.5px; opacity: .55; font-weight: 500; letter-spacing: .6px;
  text-transform: uppercase;
}
.sm-v {
  font-size: 25px; font-weight: 600; letter-spacing: -1px; line-height: 1.15;
  margin-top: 5px; font-variant-numeric: tabular-nums;
}
.sm-n { font-size: 11px; opacity: .55; margin-top: 3px; line-height: 1.45; }
@keyframes bpIn { from { opacity: 0; } to { opacity: 1; } }

hr { margin: 1.4rem 0; opacity: .14; }
.stMarkdown p, .stMarkdown li { line-height: 1.6; font-size: 14px; }
.stCaption, div[data-testid="stCaptionContainer"] p {
  font-size: 11.5px !important; line-height: 1.55; opacity: .58;
}
h1, h2, h3, h4, h5 { letter-spacing: -.4px; font-weight: 600; }
code, pre, .stCode { font-family: var(--sc-mono) !important; font-size: 12px !important; }
.stCode, pre { border-radius: 2px !important; border: 1px solid var(--sc-line); }

/* ---------- 진입 게이트 ---------- */
.gate { text-align: center; margin: 44px 0 26px; }
.gate-q { font-size: 22px; font-weight: 600; letter-spacing: -.6px; }
.gate-n { font-size: 12.5px; opacity: .55; margin-top: 7px; }
.gate-card {
  position: relative; background: #fff; color: var(--sc-ink);
  border: 1px solid var(--sc-line);
  border-radius: 2px; padding: 28px 22px 22px; text-align: center;
  margin-bottom: 10px; transition: border-color .18s, background .18s;
}
.gate-card:hover { border-color: #5980A6; background: #EFF3F7; }
.gate-ic { font-size: 38px; line-height: 1; }
.gate-t { font-size: 18px; font-weight: 600; margin-top: 12px; }
.gate-d { font-size: 12px; opacity: .55; margin-top: 7px; line-height: 1.55; }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
</style>
"""


def apply() -> None:
    """페이지 설정 직후 한 번 호출한다."""
    st.markdown(CSS, unsafe_allow_html=True)


def table(df, *, align_right: list[str] | None = None) -> None:
    """DataFrame을 직접 그린 표로 표시한다.

    [왜 st.dataframe 대신인가]
      st.dataframe 은 캔버스로 그려져 격자선 색을 CSS로 바꿀 수 없고,
      테마 설정이 어긋나면 표만 어둡게 뜬다. 감사 대응용 기록처럼
      화면에 그대로 남아야 하는 표는 직접 그리는 편이 확실하다.

      대신 정렬·크기 조절·복사 기능은 없어진다. 사람이 훑고 인쇄하는
      표에는 문제가 없지만, 열이 아주 많은 자료에는 st.dataframe 이 낫다.

    align_right: 우측 정렬할 열 이름들 (숫자 열)
    """
    import html as _h

    if df is None or len(df) == 0:
        st.caption("표시할 항목이 없습니다.")
        return

    right = set(align_right or [])
    cols = list(df.columns)

    head = "".join(
        f'<th style="text-align:{"right" if c in right else "left"}">'
        f'{_h.escape(str(c))}</th>' for c in cols)

    body = []
    for _, row in df.iterrows():
        cells = "".join(
            f'<td style="text-align:{"right" if c in right else "left"}">'
            f'{_h.escape("" if row[c] is None else str(row[c]))}</td>'
            for c in cols)
        body.append(f"<tr>{cells}</tr>")

    st.markdown(
        f'<table class="sc-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>',
        unsafe_allow_html=True)
