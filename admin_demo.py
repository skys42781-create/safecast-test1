"""
SAFECASTY — 관리자 화면 3안 비교
================================
1a / 1b / 1c를 탭으로 나란히 띄운다. 어느 안으로 갈지 정하기 전 비교용이며,
실제 앱에 붙일 때는 고른 것만 app.py에서 import하면 된다.

실행:
    streamlit run admin_demo.py
"""

import streamlit as st

import admin_1a as A
import admin_1b as B
import admin_1c as C

st.set_page_config(page_title="SAFECASTY 관리자 3안", layout="wide")

t1, t2, t3 = st.tabs([
    "1a 블록 스트립",
    "1b 시각 축 타임라인",
    "1c 관제 시트",
])

with t1:
    st.caption("아침에 훑는 순서 그대로 — 판정 → 블록 → 알람·명단")
    A.render(A.sample_data())

with t2:
    st.caption("하루를 한 줄로 — 등급 경계선·블록·휴식·알람이 같은 시각 축 위에")
    B.render(B.sample_data())

with t3:
    st.caption("시각별 판정 원본과 근거를 한 화면에 — 감사 대응 문법")
    C.render(C.sample_data())
