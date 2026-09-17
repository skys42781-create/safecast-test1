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
  --sc-line: rgba(29,31,32,.16);
  --sc-line-soft: rgba(29,31,32,.09);
  --sc-mono: 'IBM Plex Mono', ui-monospace, monospace;
}

html, body, [class*="css"], .stApp, button, input, textarea, select {
  font-family: 'IBM Plex Sans KR', system-ui, sans-serif !important;
}
.stApp { letter-spacing: -0.1px; background: #F2F2F3; }
section[data-testid="stSidebar"] {
  background: #EDEDEE; border-right: 1px solid var(--sc-line);
}
.block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1240px; }

/* ---------- 도면 카드 ---------- */
.bp {
  position: relative; background: #fff;
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

div[data-testid="stDataFrame"] {
  border-radius: 2px; border: 1px solid var(--sc-line); overflow: hidden;
}
div[data-testid="stAlert"] {
  border-radius: 2px; border: 1px solid var(--sc-line);
  border-left-width: 3px; padding: 13px 16px; font-size: 13px;
}

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
.sm-card { background: #fff; padding: 14px 16px; animation: bpIn .4s ease both; }
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
  position: relative; background: #fff; border: 1px solid var(--sc-line);
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
