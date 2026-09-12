"""
SAFECASTY — 전역 테마
=======================
Streamlit 기본 위젯을 모바일 앱 톤으로 맞춘다.

[왜 필요한가]
  히어로만 카드형으로 바꾸면 나머지 Streamlit 기본 위젯과 대비가 커져
  오히려 아래쪽이 더 낡아 보인다. 톤은 화면 전체가 같아야 한다.

[Streamlit 기본이 낡아 보이는 원인]
  · 테두리 1px + 라운드 4px    → 2010년대 웹 폼 문법
  · 라벨이 위에 작은 회색 글씨   → 데스크톱 소프트웨어 문법
  · 좁은 여백                  → 정보 밀도는 높지만 읽기 힘들다
  · 한글 폰트 미지정            → fallback으로 자간이 어긋난다

[CSS로 할 수 없는 것]
  st.dataframe 을 카드 목록으로 바꾸는 것. 구조 자체가 표라서
  스타일만으로는 형태를 바꿀 수 없다. 필요하면 st.markdown 으로
  직접 그려야 한다.
"""

from __future__ import annotations

import streamlit as st

CSS = """
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* ---------- 폰트 ---------- */
html, body, [class*="css"], .stApp, button, input, textarea, select {
  font-family: 'Noto Sans KR', -apple-system, system-ui, sans-serif !important;
}
.stApp { letter-spacing: -0.2px; }

/* ---------- 여백 ---------- */
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1180px; }
section[data-testid="stSidebar"] > div { padding-top: 1.6rem; }

/* ---------- 탭: 밑줄 → 알약 ---------- */
.stTabs [data-baseweb="tab-list"] {
  gap: 6px; border-bottom: none; padding: 4px;
  background: rgba(128,128,128,.07); border-radius: 999px;
  overflow-x: auto; scrollbar-width: none;
}
.stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
.stTabs [data-baseweb="tab"] {
  height: 38px; padding: 0 16px; border-radius: 999px; border: none;
  background: transparent; font-size: 13.5px; font-weight: 600;
  white-space: nowrap; transition: background .18s, color .18s;
}
.stTabs [data-baseweb="tab"]:hover { background: rgba(128,128,128,.10); }
.stTabs [aria-selected="true"] {
  background: var(--text-color) !important;
  color: var(--background-color) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- 지표 ---------- */
div[data-testid="stMetric"] {
  background: var(--secondary-background-color);
  border-radius: 18px; padding: 16px 18px; border: none;
}
div[data-testid="stMetricLabel"] p { font-size: 12px !important; opacity: .62; }
div[data-testid="stMetricValue"] {
  font-size: 26px !important; font-weight: 800; letter-spacing: -0.8px;
}
div[data-testid="stMetricDelta"] { font-size: 11.5px !important; opacity: .7; }

/* ---------- 버튼: 알약 ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 999px; border: none; padding: 10px 20px;
  font-weight: 600; font-size: 13.5px;
  background: rgba(128,128,128,.11); color: var(--text-color);
  transition: transform .16s cubic-bezier(.34,1.56,.64,1),
              background .16s, box-shadow .16s;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: rgba(128,128,128,.18); transform: translateY(-1px);
}
.stButton > button:active, .stDownloadButton > button:active {
  transform: scale(.97);
}
.stButton > button[kind="primary"], .stFormSubmitButton > button {
  background: #3182F6; color: #fff;
  box-shadow: 0 3px 12px rgba(49,130,246,.28);
}
.stButton > button[kind="primary"]:hover { background: #2272E6; }

/* ---------- 입력 ---------- */
.stTextInput input, .stNumberInput input, .stDateInput input,
div[data-baseweb="select"] > div, .stTextArea textarea {
  border-radius: 14px !important; border: none !important;
  background: rgba(128,128,128,.08) !important;
  font-size: 14px !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
  box-shadow: 0 0 0 2px #3182F6 !important;
}
.stFileUploader > section {
  border-radius: 18px; border: 1.5px dashed rgba(128,128,128,.28);
  background: rgba(128,128,128,.04);
}

/* ---------- 라디오 · 세그먼트 ---------- */
div[role="radiogroup"] { gap: 6px; }
div[role="radiogroup"] label {
  border-radius: 999px; padding: 7px 15px;
  background: rgba(128,128,128,.08); font-size: 13.5px; font-weight: 500;
  transition: background .16s;
}
div[role="radiogroup"] label:hover { background: rgba(128,128,128,.15); }

/* ---------- 토글 ---------- */
div[data-testid="stToggle"] label { font-size: 13.5px; }

/* ---------- expander: 카드 ---------- */
div[data-testid="stExpander"] {
  border: none !important; border-radius: 18px;
  background: var(--secondary-background-color); margin-bottom: 10px;
}
div[data-testid="stExpander"] summary {
  padding: 14px 18px; font-weight: 600; font-size: 14px;
}
div[data-testid="stExpander"] summary:hover { background: rgba(128,128,128,.06); }
div[data-testid="stExpander"] div[data-testid="stExpanderDetails"] {
  padding: 2px 18px 16px;
}

/* ---------- 표: 격자감 완화 ---------- */
div[data-testid="stDataFrame"] { border-radius: 16px; overflow: hidden; }
div[data-testid="stDataFrame"] [data-testid="stTable"] { border: none; }

/* ---------- 알림 ---------- */
div[data-testid="stAlert"] {
  border-radius: 16px; border: none; padding: 14px 18px; font-size: 13.5px;
}

/* ---------- 구분선 · 본문 ---------- */
hr { margin: 1.6rem 0; opacity: .16; }
.stMarkdown p, .stMarkdown li { line-height: 1.62; font-size: 14.5px; }
.stCaption, div[data-testid="stCaptionContainer"] p {
  font-size: 12px !important; line-height: 1.55; opacity: .66;
}
h1, h2, h3, h4, h5 { letter-spacing: -0.6px; font-weight: 700; }

/* ---------- 체크박스 ---------- */
.stCheckbox label { font-size: 14px; }
.stCheckbox label span:first-child { border-radius: 7px !important; }

/* ---------- 코드 블록 ---------- */
.stCode, pre { border-radius: 14px !important; font-size: 12.5px !important; }

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
</style>
"""


def apply() -> None:
    """페이지 설정 직후 한 번 호출한다."""
    st.markdown(CSS, unsafe_allow_html=True)
