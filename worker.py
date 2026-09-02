"""
Safecast — 근로자 설문·신고 (GitHub 저장소)
==============================================
근로자가 입력한 내용을 레포의 CSV에 커밋하고, 관리자 화면이 그것을 읽는다.

[왜 구글 시트가 아닌가]
  서비스 계정 JSON 키 발급이 조직 정책(iam.disableServiceAccountKeyCreation)으로
  차단되었고, 개인 계정에는 조직이 없어 정책을 해제할 수 없다.
  GitHub는 이미 30분마다 수집 데이터를 커밋하고 있어 인프라가 검증되어 있다.

[왜 이 방식이 오히려 나은가]
  · 데이터가 프로젝트 레포에 남아 관리 주체가 명확하다
  · 커밋 이력이 곧 감사 로그다 (언제 무엇이 기록되었는지 되돌릴 수 없이 남는다)
  · 별도 계정·과금·조직 정책이 필요 없다

[저장하는 것 / 저장하지 않는 것]
  저장       이름 · 소속 · 구역 · 공종 · 투입일차 · 복귀여부
             신고 시각 · 증상 개수 · 처리상태
  저장 안 함 증상의 '종류', 만성질환·약물·음주 등 건강 정보
  → 건강 항목은 본인 화면에서 민감군 여부를 알려주는 데만 쓰고 버린다.
    민감정보를 외부 저장소에 두면 보관·동의·파기 의무가 따라붙는다.

[한계]
  GitHub API는 커밋마다 왕복이 필요해 즉시성이 떨어진다(수 초).
  동시에 여러 명이 제출하면 충돌이 날 수 있어 재시도로 처리한다.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

API = "https://api.github.com"

SURVEY_PATH = "data/worker_survey.csv"
REPORT_PATH = "data/worker_reports.csv"

SURVEY_COLS = ["등록시각", "이름", "생년월일", "소속", "작업구역", "공종",
               "연령", "투입일차", "복귀자"]
REPORT_COLS = ["시각", "이름", "생년월일", "소속", "작업구역",
               "증상개수", "처리상태"]

STATUS = ["미확인", "확인함", "조치완료"]

# 충돌(다른 제출이 먼저 커밋됨) 시 재시도 횟수
RETRY = 3


# =====================================================================
# 설정
# =====================================================================

def _cfg() -> dict:
    """secrets에서 GitHub 설정을 읽는다.

    실패 이유를 함께 담는다. 그냥 빈 값을 돌려주면
    "키가 없는 것"과 "secrets 자체를 못 읽는 것"이 구분되지 않아
    원인을 찾을 수 없다.
    """
    out = {"token": "", "repo": "", "branch": "main", "why": ""}
    try:
        tok = str(st.secrets.get("GH_TOKEN", "") or "").strip()
        repo = str(st.secrets.get("GH_REPO", "") or "").strip()
        br = str(st.secrets.get("GH_BRANCH", "main") or "main").strip()
    except Exception as e:
        out["why"] = (f"secrets를 읽지 못했습니다 ({type(e).__name__}). "
                      "TOML 문법 오류일 수 있습니다.")
        return out

    missing = [k for k, v in [("GH_TOKEN", tok), ("GH_REPO", repo)] if not v]
    if missing:
        out["why"] = f"{', '.join(missing)} 가 secrets에 없습니다"
        return out
    if "/" not in repo:
        out["why"] = (f"GH_REPO 형식이 잘못되었습니다 — 현재 «{repo}». "
                      "«사용자명/저장소명» 형태여야 합니다.")
        return out

    out.update({"token": tok, "repo": repo, "branch": br})
    return out


def diagnose() -> str:
    """설정 상태를 사람이 읽을 수 있게."""
    c = _cfg()
    if c["why"]:
        return c["why"]
    tok = c["token"]
    masked = f"{tok[:10]}…{tok[-4:]}" if len(tok) > 14 else "설정됨"
    return f"저장소 {c['repo']} · 브랜치 {c['branch']} · 토큰 {masked}"


def is_enabled() -> bool:
    c = _cfg()
    return bool(c["token"] and c["repo"])


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}


# =====================================================================
# 읽기 / 쓰기
# =====================================================================

def _read(path: str, cols: list[str]) -> tuple[pd.DataFrame, str | None]:
    """CSV 읽기. 반환: (DataFrame, sha). 파일이 없으면 (빈 DF, None)."""
    c = _cfg()
    try:
        r = requests.get(f"{API}/repos/{c['repo']}/contents/{path}",
                         headers=_headers(c["token"]),
                         params={"ref": c["branch"]}, timeout=(5, 10))
        if r.status_code == 404:
            return pd.DataFrame(columns=cols), None
        r.raise_for_status()
        js = r.json()
        raw = base64.b64decode(js["content"]).decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(raw)) if raw.strip() else pd.DataFrame(columns=cols)
        return df, js["sha"]
    except Exception as e:
        st.session_state["_gh_err"] = str(e)[:200]
        return pd.DataFrame(columns=cols), None


def _write(path: str, df: pd.DataFrame, sha: str | None, msg: str) -> bool:
    c = _cfg()
    try:
        content = base64.b64encode(
            df.to_csv(index=False).encode("utf-8-sig")).decode()
        body = {"message": msg, "content": content, "branch": c["branch"]}
        if sha:
            body["sha"] = sha
        r = requests.put(f"{API}/repos/{c['repo']}/contents/{path}",
                         headers=_headers(c["token"]), json=body,
                         timeout=(5, 15))
        r.raise_for_status()
        return True
    except Exception as e:
        st.session_state["_gh_err"] = str(e)[:200]
        return False


def _append(path: str, cols: list[str], row: dict, msg: str) -> bool:
    """행 추가. 다른 제출과 충돌하면 다시 읽어 재시도한다."""
    for _ in range(RETRY):
        df, sha = _read(path, cols)
        merged = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        for c in cols:
            if c not in merged.columns:
                merged[c] = ""
        if _write(path, merged[cols], sha, msg):
            load_survey.clear()
            load_reports.clear()
            return True
    return False


# =====================================================================
# 설문
# =====================================================================

@st.cache_data(ttl=60, show_spinner=False)
def load_survey() -> pd.DataFrame:
    df, _ = _read(SURVEY_PATH, SURVEY_COLS)
    return df


def age_from(birth: str) -> int:
    """생년월일(YYYYMMDD) → 만 나이."""
    try:
        b = datetime.strptime(str(birth).strip(), "%Y%m%d")
    except ValueError:
        return 0
    t = datetime.now()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def valid_birth(birth: str) -> bool:
    """입력된 생년월일이 쓸 수 있는 값인가.

    strptime("%Y%m%d")는 7자리(예: 1970031)도 받아들이므로
    길이를 따로 검사해야 오입력이 걸러진다.
    """
    b = str(birth).strip()
    if len(b) != 8 or not b.isdigit():
        return False
    a = age_from(b)
    return 15 <= a <= 95


def find_worker(name: str, birth: str) -> dict | None:
    """이름 + 생년월일로 찾는다.

    [왜 이름만으로는 안 되는가]
      건설현장 60명 규모면 동명이인이 나온다. 이름만으로 찾으면
      다른 사람의 등록 정보를 자기 것으로 쓰게 되고, 그 사람 이름으로
      증상이 신고된다. 엉뚱한 사람이 조치 대상이 되므로 안전 문제다.
    """
    df = load_survey()
    if df.empty or "이름" not in df.columns or "생년월일" not in df.columns:
        return None
    hit = df[(df["이름"].astype(str).str.strip() == name.strip())
             & (df["생년월일"].astype(str).str.strip() == str(birth).strip())]
    return hit.iloc[-1].to_dict() if not hit.empty else None


def register(name: str, birth: str, org: str, zone: str, trade: str,
             day: int | None, is_return: bool) -> bool:
    """연령은 생년월일에서 계산한다. 따로 묻지 않는다."""
    return _append(SURVEY_PATH, SURVEY_COLS, {
        "등록시각": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "이름": name.strip(), "생년월일": str(birth).strip(),
        "소속": org.strip(),
        "작업구역": zone.strip(), "공종": trade.strip(),
        "연령": age_from(birth),
        "투입일차": day if day else "",
        "복귀자": "예" if is_return else "아니오",
    }, f"survey: {name.strip()} 등록")


# =====================================================================
# 신고
# =====================================================================

@st.cache_data(ttl=30, show_spinner=False)
def load_reports() -> pd.DataFrame:
    df, _ = _read(REPORT_PATH, REPORT_COLS)
    return df


def submit_report(worker: dict, symptom_count: int) -> bool:
    """증상 신고. 증상의 '종류'는 저장하지 않는다.

    관리자는 개수만 보고 현장에서 직접 확인한다. 어차피 대면 확인이 필요한
    상황이므로, 종류까지 남겨 흔적을 늘릴 이유가 없다.
    """
    return _append(REPORT_PATH, REPORT_COLS, {
        "시각": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "이름": str(worker.get("이름", "")),
        "생년월일": str(worker.get("생년월일", "")),
        "소속": str(worker.get("소속", "")),
        "작업구역": str(worker.get("작업구역", "")),
        "증상개수": int(symptom_count),
        "처리상태": STATUS[0],
    }, f"report: {worker.get('이름', '')} 증상 {symptom_count}개")


def update_status(idx: int, status: str) -> bool:
    df, sha = _read(REPORT_PATH, REPORT_COLS)
    if df.empty or idx >= len(df):
        return False
    df.loc[idx, "처리상태"] = status
    if _write(REPORT_PATH, df, sha, f"report: {idx}번 → {status}"):
        load_reports.clear()
        return True
    return False


def last_error() -> str:
    return st.session_state.get("_gh_err", "")


# =====================================================================
# UI — 근로자
# =====================================================================

def render_worker_entry() -> dict | None:
    """근로자 진입. 등록되어 있으면 본인 정보를, 아니면 설문을 띄운다.

    [왜 이름 입력인가]
      Streamlit 세션은 탭을 닫으면 사라진다. 개인별 QR을 쓰면 자동 인식이
      가능하나, 60명분 인쇄·배포라는 현실 절차가 앞에 붙는다.
      공용 QR 하나 + 이름 입력이 시연과 실사용 모두에서 단순하다.
      (실운영에서는 개인별 QR 발급으로 확장 가능)
    """
    if not is_enabled():
        st.info("근로자 등록이 아직 설정되지 않았습니다. "
                "증상이 있으면 관리자나 동료에게 직접 알리세요.", icon="ℹ️")
        st.caption(f"(관리자용 정보: {diagnose()})")
        return None

    me = st.session_state.get("_worker")
    if me:
        c1, c2 = st.columns([4, 1])
        c1.success(f"**{me['이름']}** · {me.get('소속', '')} "
                   f"{me.get('작업구역', '')}", icon="👷")
        if c2.button("변경", use_container_width=True):
            st.session_state.pop("_worker", None)
            st.rerun()
        return me

    st.subheader("👷 근로자 확인")
    c1, c2 = st.columns(2)
    name = c1.text_input("이름", placeholder="홍길동")
    birth = c2.text_input("생년월일 8자리", placeholder="19700315", max_chars=8,
                          help="동명이인 구분과 연령(민감군 ③고령) 판정에 사용합니다")

    if not name.strip() or not birth.strip():
        st.caption("이름과 생년월일을 입력하면 등록 여부를 확인합니다.")
        return None
    if not valid_birth(birth):
        st.error("생년월일을 8자리로 정확히 입력하세요. 예) 19700315")
        return None

    found = find_worker(name, birth)
    if found:
        st.session_state["_worker"] = found
        st.rerun()

    # ---- 미등록 → 최초 설문 ----
    st.info("처음 오셨네요. 아래 정보를 한 번만 입력하면 "
            "다음부터는 바로 이용할 수 있습니다.", icon="📝")

    st.caption(f"**{name.strip()}** · 만 {age_from(birth)}세")
    c1, c2 = st.columns(2)
    org = c1.text_input("소속 (협력사)", placeholder="○○건설")
    zone = c2.text_input("작업구역", placeholder="3공구")
    trade = c1.text_input("공종", placeholder="철근")

    st.markdown("##### 폭염작업 투입")
    t1, t2 = st.columns(2)
    track = t1.radio("구분", ["해당 없음", "신규 투입", "복귀(7일 이상 쉼)"],
                     help="처음 폭염작업을 하거나, 연속 7일 이상 쉬었다가 복귀한 경우")
    day = None
    if track != "해당 없음":
        day = t2.number_input("투입 며칠째", 1, 30, 1)

    st.caption("ℹ️ 이 정보는 폭염 안전조치 목적으로만 사용되며, 비공개 "
               "저장소에 보관됩니다. 질환·약물 등 건강 정보는 이 앱에 "
               "저장하지 않으며 보건관리자가 별도로 관리합니다. "
               "(산업안전보건법 제132조제2항)")

    if st.button("등록하고 시작하기", type="primary", use_container_width=True,
                 disabled=not (org.strip() and zone.strip())):
        if register(name, birth, org, zone, trade, day,
                    track.startswith("복귀")):
            st.session_state["_worker"] = {
                "이름": name.strip(), "생년월일": birth.strip(),
                "소속": org.strip(),
                "작업구역": zone.strip(), "공종": trade.strip(),
                "연령": age_from(birth), "투입일차": day if day else "",
                "복귀자": "예" if track.startswith("복귀") else "아니오",
            }
            st.rerun()
        else:
            st.error(f"등록에 실패했습니다. 관리자에게 알리세요.\n\n"
                     f"`{last_error()}`")
    if not (org.strip() and zone.strip()):
        st.caption("소속과 작업구역은 조치 전달에 필요합니다.")
    return None


def render_report(me: dict, symptom_count: int) -> None:
    """증상 신고 버튼."""
    st.markdown("##### 📢 관리자에게 알리기")
    st.caption("증상 **개수**만 전달됩니다. 어떤 증상인지는 저장되지 않습니다.")

    if st.button("📢 관리자에게 알리기", type="primary",
                 use_container_width=True):
        if submit_report(me, symptom_count):
            st.success("전달되었습니다. 시원한 곳에서 대기하세요.")
            st.balloons()
        else:
            st.error(f"전달 실패 — 구두로 알리세요.\n\n`{last_error()}`")

    st.caption("ℹ️ 이 기록은 폭염 안전조치 목적으로만 사용되며, "
               "인사·평가에 활용되지 않습니다. (산업안전보건법 제132조제3항)")
    st.caption("🛑 근로자는 건강상 이유로 작업중지를 요청할 권리가 있습니다.")


# =====================================================================
# UI — 관리자
# =====================================================================

def render_admin() -> None:
    """신고 현황 + 등록 명부."""
    st.subheader("🚨 근로자 신고 현황")

    if not is_enabled():
        st.warning(f"근로자 신고 저장소가 설정되지 않았습니다 — {diagnose()}",
                   icon="⚠️")
        with st.expander("설정 방법"):
            st.code('''GH_TOKEN  = "github_pat_..."
GH_REPO   = "사용자명/저장소명"
GH_BRANCH = "main"''', language="toml")
            st.caption("Streamlit Cloud → Manage app → Settings → Secrets 에 "
                       "위 세 줄을 추가하고 Save 하세요. 저장 후 앱이 자동으로 "
                       "재시작됩니다.")
            st.caption("토큰은 GitHub → Settings → Developer settings → "
                       "Personal access tokens → Fine-grained tokens 에서 "
                       "발급하며, 해당 저장소에 Contents: Read and write "
                       "권한이 필요합니다.")
        return

    df = load_reports()
    if last_error():
        st.caption(f"⚠️ 최근 오류: `{last_error()}`")

    if df.empty:
        st.success("접수된 신고가 없습니다.")
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        only_today = st.toggle("오늘 신고만 보기", value=True)
        view = df[df["시각"].astype(str).str.startswith(today)] if only_today else df

        pending = int((view["처리상태"] == "미확인").sum()) if not view.empty else 0
        m = st.columns(3)
        m[0].metric("신고 건수", f"{len(view)}건")
        m[1].metric("미확인", f"{pending}건",
                    delta="즉시 확인" if pending else None, delta_color="off")
        m[2].metric("증상 3개 이상",
                    f"{int((view['증상개수'] >= 3).sum()) if not view.empty else 0}건")

        if pending:
            st.error(f"🚨 미확인 신고 {pending}건 — 즉시 현장 확인이 필요합니다.",
                     icon="🚨")

        rv = view.copy()
        if "생년월일" in rv.columns:
            rv = rv.drop(columns=["생년월일"])
        st.dataframe(rv, hide_index=True, use_container_width=True)

        if not view.empty:
            st.markdown("##### 처리상태 변경")
            c1, c2, c3 = st.columns([2, 1, 1])
            labels = {i: f"{r['시각']} · {r['이름']} · 증상 {r['증상개수']}개"
                      for i, r in view.iterrows()}
            pick = c1.selectbox("대상", list(labels.keys()),
                                format_func=lambda i: labels[i])
            new = c2.selectbox("상태", STATUS)
            if c3.button("변경", use_container_width=True):
                if update_status(pick, new):
                    st.success("변경되었습니다.")
                    st.rerun()
                else:
                    st.error("변경 실패")

        st.download_button("📥 신고 기록 CSV",
                           df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"근로자신고_{datetime.now():%Y%m%d}.csv",
                           mime="text/csv")

    st.divider()
    st.markdown("##### 👷 등록 근로자")
    sv = load_survey()
    if sv.empty:
        st.caption("등록된 근로자가 없습니다. "
                   "근로자 모드에서 QR로 접속해 등록합니다.")
    else:
        # 생년월일은 화면에 그대로 띄우지 않는다. 조치에는 연령이면 충분하고,
        # 어깨너머로 노출될 이유가 없다.
        view = sv.copy()
        if "생년월일" in view.columns:
            view["생년월일"] = view["생년월일"].astype(str).str[:4] + "****"
        st.dataframe(view, hide_index=True, use_container_width=True,
                     height=min(320, 40 + 35 * len(view)))
        st.download_button("📥 등록 명부 CSV (TBM 명단 업로드용)",
                           sv.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"근로자명부_{datetime.now():%Y%m%d}.csv",
                           mime="text/csv")
        st.caption("ℹ️ 건강 관련 항목은 저장하지 않습니다. "
                   "민감군 판정에 필요한 질환 정보는 보건관리자가 별도로 관리합니다.")
