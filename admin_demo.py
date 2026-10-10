"""
SAFECASTY — 관리자 화면 3안 비교
================================
1a / 1b / 1c를 나란히 띄운다. 어느 안으로 갈지 정하기 전 비교용이며,
실제 앱에 붙일 때는 고른 것만 app.py에서 import하면 된다.

[왜 탭이 아니라 라디오인가]
    theme.py가 탭 목록에 가로 스크롤을 걸면서 스크롤바를 숨긴다.
    창이 좁으면 두 번째·세 번째 탭이 오른쪽으로 밀려 보이지 않는다.
    라디오는 줄바꿈되므로 어떤 폭에서도 세 안이 모두 보인다.

실행:
    streamlit run admin_demo.py
"""

import streamlit as st

import admin_1a as A
import admin_1b as B
import admin_1c as C
import theme as TH

st.set_page_config(page_title="SAFECASTY 관리자 3안", layout="wide")
TH.apply()

VIEWS = {
    "1a 블록 스트립": (
        "아침에 훑는 순서 그대로 — 판정 → 블록 → 알람·명단",
        lambda: A.render(A.sample_data()),
    ),
    "1b 시각 축 타임라인": (
        "하루를 한 줄로 — 등급 경계선·블록·휴식·알람이 같은 시각 축 위에",
        lambda: B.render(B.sample_data()),
    ),
    "1c 관제 시트": (
        "시각별 판정 원본과 근거를 한 화면에 — 감사 대응 문법",
        lambda: C.render(C.sample_data()),
    ),
}

st.markdown(
    '<div style="font-size:12px;letter-spacing:.14em;text-transform:uppercase;'
    'opacity:.55;padding:4px 0 8px">관리자 화면 시안 비교 · 데이터는 예시값</div>',
    unsafe_allow_html=True)

picked = st.radio("화면", list(VIEWS), horizontal=True,
                  label_visibility="collapsed", key="_demo_view")

note, draw = VIEWS[picked]
st.caption(note)
st.divider()
draw()
