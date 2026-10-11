"""
SAFECASTY — 문자 수신자 명단
==============================
알람을 받을 사람을 private 레포에 저장하고 읽는다.

[왜 private 레포인가]
    전화번호는 개인정보다. 코드 레포(safecast-test1)는 public이므로
    여기에 두면 누구나 받아갈 수 있다. worker.py 와 같은 저장소
    (secrets 의 GH_REPO = safecast-data)를 쓴다.

[왜 근로자 명부와 따로 두는가]
    알람을 받는 사람과 현장에서 일하는 사람은 겹치지 않는다.
    안전관리자·소장은 출역하지 않아도 알람을 받아야 하고,
    근로자 전원에게 문자를 보내면 비용도 소음도 감당이 안 된다.
    지침도 알람은 관리감독자에게 가고 현장 전파는 사람이 하도록 본다.

사용:
    import recipients as RC
    RC.load()                      # DataFrame
    RC.add(name, phone, role)      # 추가
    RC.remove(phone)               # 삭제
    RC.active_numbers()            # 발송 대상 번호 목록
"""

from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

import sms as SMS

API = "https://api.github.com"
PATH = "data/sms_recipients.csv"
LOG_PATH = "data/sms_log.csv"

COLS = ["등록시각", "이름", "번호", "역할", "수신"]
LOG_COLS = ["발송시각", "종류", "대상", "성공", "실패", "비용", "내용"]

ROLES = ["안전관리자", "현장소장", "관리감독자", "보건관리자", "기타"]

KST = timezone(timedelta(hours=9))
RETRY = 3


def _cfg() -> dict:
    """worker.py 와 같은 GitHub 설정을 쓴다."""
    out = {"token": "", "repo": "", "branch": "main", "why": ""}
    try:
        tok = str(st.secrets.get("GH_TOKEN", "") or "").strip()
        repo = str(st.secrets.get("GH_REPO", "") or "").strip()
        br = str(st.secrets.get("GH_BRANCH", "main") or "main").strip()
    except Exception as e:
        out["why"] = f"secrets를 읽지 못했습니다 ({type(e).__name__})"
        return out
    missing = [k for k, v in (("GH_TOKEN", tok), ("GH_REPO", repo)) if not v]
    if missing:
        out["why"] = f"{', '.join(missing)} 가 secrets에 없습니다"
        return out
    out.update({"token": tok, "repo": repo, "branch": br})
    return out


def is_enabled() -> bool:
    return not _cfg()["why"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}


def _read(path: str, cols: list[str]) -> tuple[pd.DataFrame, str | None]:
    c = _cfg()
    if c["why"]:
        return pd.DataFrame(columns=cols), None
    try:
        r = requests.get(f"{API}/repos/{c['repo']}/contents/{path}",
                         headers=_headers(c["token"]),
                         params={"ref": c["branch"]}, timeout=(5, 10))
        if r.status_code == 404:
            return pd.DataFrame(columns=cols), None
        r.raise_for_status()
        js = r.json()
        raw = base64.b64decode(js["content"]).decode("utf-8-sig")
        if not raw.strip():
            return pd.DataFrame(columns=cols), js["sha"]
        # 번호가 숫자로 읽히면 앞자리 0이 떨어진다. 전부 문자열로 받는다.
        df = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False)
        return df, js["sha"]
    except Exception as e:
        st.session_state["_rc_err"] = str(e)[:200]
        return pd.DataFrame(columns=cols), None


def _write(path: str, df: pd.DataFrame, sha: str | None, msg: str) -> bool:
    c = _cfg()
    if c["why"]:
        return False
    try:
        content = base64.b64encode(
            df.to_csv(index=False).encode("utf-8-sig")).decode()
        body = {"message": msg, "content": content, "branch": c["branch"]}
        if sha:
            body["sha"] = sha
        r = requests.put(f"{API}/repos/{c['repo']}/contents/{path}",
                         headers=_headers(c["token"]), json=body, timeout=(5, 15))
        r.raise_for_status()
        return True
    except Exception as e:
        st.session_state["_rc_err"] = str(e)[:200]
        return False


# =====================================================================
# 명단
# =====================================================================

@st.cache_data(ttl=60, show_spinner=False)
def load() -> pd.DataFrame:
    df, _ = _read(PATH, COLS)
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    return df[COLS]


def active_numbers(df: pd.DataFrame | None = None) -> list[str]:
    """발송 대상 번호. 수신 '아니오'인 사람은 뺀다."""
    df = load() if df is None else df
    if df.empty:
        return []
    on = df[df["수신"].astype(str).str.strip() != "아니오"]
    nums = [SMS.only_digits(v) for v in on["번호"]]
    seen, out = set(), []
    for n in nums:
        if SMS.valid_phone(n) and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def add(name: str, phone: str, role: str) -> tuple[bool, str]:
    """수신자 추가. 반환: (성공, 사유)."""
    name = str(name).strip()
    num = SMS.only_digits(phone)
    if not name:
        return False, "이름을 입력하세요."
    if not SMS.valid_phone(num):
        return False, "휴대폰 번호 형식이 올바르지 않습니다."

    for _ in range(RETRY):
        df, sha = _read(PATH, COLS)
        for c in COLS:
            if c not in df.columns:
                df[c] = ""
        if not df.empty and num in set(SMS.only_digits(v) for v in df["번호"]):
            return False, "이미 등록된 번호입니다."
        row = {"등록시각": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
               "이름": name, "번호": num,
               "역할": str(role).strip() or "기타", "수신": "예"}
        merged = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        if _write(PATH, merged[COLS], sha, f"sms: {name} 수신자 추가"):
            load.clear()
            return True, f"{name} 님을 추가했습니다."
    return False, "저장에 실패했습니다. 잠시 후 다시 시도하세요."


def remove(phone: str) -> tuple[bool, str]:
    num = SMS.only_digits(phone)
    for _ in range(RETRY):
        df, sha = _read(PATH, COLS)
        if df.empty:
            return False, "명단이 비어 있습니다."
        keep = df[df["번호"].map(SMS.only_digits) != num]
        if len(keep) == len(df):
            return False, "해당 번호를 찾을 수 없습니다."
        if _write(PATH, keep[COLS], sha, f"sms: {SMS.mask_phone(num)} 수신자 삭제"):
            load.clear()
            return True, "삭제했습니다."
    return False, "저장에 실패했습니다."


def toggle(phone: str) -> tuple[bool, str]:
    """수신 여부를 뒤집는다. 명단에서 지우지 않고 잠시 끌 때 쓴다."""
    num = SMS.only_digits(phone)
    for _ in range(RETRY):
        df, sha = _read(PATH, COLS)
        if df.empty:
            return False, "명단이 비어 있습니다."
        hit = df["번호"].map(SMS.only_digits) == num
        if not hit.any():
            return False, "해당 번호를 찾을 수 없습니다."
        cur = str(df.loc[hit, "수신"].iloc[0]).strip()
        df.loc[hit, "수신"] = "아니오" if cur != "아니오" else "예"
        if _write(PATH, df[COLS], sha, f"sms: {SMS.mask_phone(num)} 수신 전환"):
            load.clear()
            return True, "변경했습니다."
    return False, "저장에 실패했습니다."


# =====================================================================
# 발송 기록
# =====================================================================
#   [왜 남기는가]
#     체감온도·조치사항 기록은 법적 의무(제562조제2항제3호)다.
#     사람이 전파했다는 것은 시스템이 알 수 없어 기록하지 않지만,
#     문자는 시스템이 실제로 보낸 것이므로 근거로 남길 수 있다.
#     번호는 가려서 저장한다 — 누구에게 갔는지는 명단으로 확인한다.

@st.cache_data(ttl=60, show_spinner=False)
def load_log() -> pd.DataFrame:
    df, _ = _read(LOG_PATH, LOG_COLS)
    for c in LOG_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[LOG_COLS]


def log_send(kind: str, result: dict, targets: list[str]) -> bool:
    """발송 결과를 기록한다."""
    for _ in range(RETRY):
        df, sha = _read(LOG_PATH, LOG_COLS)
        for c in LOG_COLS:
            if c not in df.columns:
                df[c] = ""
        row = {
            "발송시각": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "종류": kind,
            "대상": " ".join(SMS.mask_phone(t) for t in targets[:10]),
            "성공": str(result.get("sent", 0)),
            "실패": str(result.get("failed", 0)),
            "비용": f"{result.get('cost', 0):.0f}",
            "내용": str(result.get("text", "")).replace("\n", " / ")[:120],
        }
        merged = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        if _write(LOG_PATH, merged[LOG_COLS], sha, f"sms: {kind} 발송 기록"):
            load_log.clear()
            return True
    return False


# =====================================================================
# 관리자 화면
# =====================================================================

def render_admin(alarms=None, *, now=None, test_only: bool = False) -> None:
    """문자 알림 설정·수신자 관리·테스트 발송.

    alarms: build_alarms() 결과. 없으면 테스트 발송만 가능하다.
    """
    import ui as UI

    now = now or datetime.now(KST)

    # ---- 설정 상태 ----
    ok_sms, ok_repo = SMS.is_enabled(), is_enabled()
    if not ok_sms:
        st.warning(f"문자 발송이 설정되지 않았습니다 — {SMS.diagnose()}", icon="📵")
        st.caption("Streamlit Cloud → Manage app → Settings → Secrets 에 "
                   "SOLAPI_KEY · SOLAPI_SECRET · SMS_FROM 을 등록하세요.")
    if not ok_repo:
        st.warning(f"수신자 명단을 저장할 수 없습니다 — {_cfg()['why']}", icon="🗄️")

    if ok_sms:
        st.caption(f"📡 {SMS.diagnose()}")

    df = load() if ok_repo else pd.DataFrame(columns=COLS)
    nums = active_numbers(df) if ok_repo else []

    UI.stat_row([("등록 수신자", f"{len(df)}명"),
                 ("발송 대상", f"{len(nums)}명"),
                 ("예상 단가", "건당 18~45원")])

    # ---- 테스트 발송 ----
    # 심사·점검 때 실제 폭염을 기다릴 수 없다. 다만 실제 알람과
    # 구분되도록 문구와 기록에 테스트임을 남긴다.
    st.divider()
    UI.section("테스트 발송", "실제 알람과 구분되는 문구로 나갑니다")
    c1, c2 = st.columns([1, 2])
    with c1:
        go = st.button("지금 테스트 발송", type="primary",
                       use_container_width=True,
                       disabled=not (ok_sms and nums), key="_rc_test")
    with c2:
        if not nums:
            st.caption("수신자를 먼저 등록하세요.")
        else:
            st.caption(f"{len(nums)}명에게 발송됩니다 · "
                       f"약 {len(nums) * 18}원")

    if go:
        res = SMS.send(nums, SMS.test_text(now))
        if res["ok"]:
            st.success(f"{res['sent']}건 발송했습니다. "
                       f"(실패 {res['failed']}건 · {res['cost']:.0f}원)")
            if ok_repo:
                log_send("테스트", res, nums)
        else:
            st.error(f"발송 실패 — {res['why']}")
        for d in res["detail"]:
            st.caption(d)

    # ---- 오늘 알람 발송 ----
    if not test_only and alarms is not None and not alarms.empty:
        st.divider()
        UI.section("오늘 알람", "사전 통보 문구를 그대로 보냅니다")
        for i, (_, a) in enumerate(alarms.head(4).iterrows()):
            cc1, cc2 = st.columns([3, 1])
            with cc1:
                st.caption(f"**{a['발송시각']}** · {a['대상 블록']} — "
                           f"판정 {a['체감온도']} {a['등급']}")
            with cc2:
                if st.button("발송", key=f"_rc_send_{i}",
                             disabled=not (ok_sms and nums),
                             use_container_width=True):
                    txt = SMS.alarm_text(str(a["대상 블록"]), str(a["체감온도"]),
                                         str(a["등급"]), 20)
                    res = SMS.send(nums, txt)
                    if res["ok"]:
                        st.success(f"{res['sent']}건 발송")
                        if ok_repo:
                            log_send("블록 진입", res, nums)
                    else:
                        st.error(res["why"])

    # ---- 수신자 관리 ----
    st.divider()
    UI.section("수신자", "알람을 받을 사람")

    with st.form("_rc_add", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([2, 2, 2, 1])
        name = f1.text_input("이름", placeholder="홍길동")
        phone = f2.text_input("휴대폰", placeholder="010-1234-5678")
        role = f3.selectbox("역할", ROLES)
        f4.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if f4.form_submit_button("추가", use_container_width=True,
                                 disabled=not ok_repo):
            ok, why = add(name, phone, role)
            (st.success if ok else st.error)(why)
            if ok:
                st.rerun()

    if df.empty:
        st.caption("등록된 수신자가 없습니다.")
    else:
        for _, r in df.iterrows():
            on = str(r["수신"]).strip() != "아니오"
            rc1, rc2, rc3 = st.columns([4, 1, 1])
            rc1.markdown(
                f"<div style='padding:6px 0;font-size:13px'>"
                f"<b>{r['이름']}</b> · {SMS.fmt_phone(r['번호'])} "
                f"<span style='color:#7A7A7D'>· {r['역할']}</span>"
                f"{'' if on else ' <span style=\"color:#B91C1C\">· 수신 중지</span>'}"
                f"</div>", unsafe_allow_html=True)
            if rc2.button("중지" if on else "재개",
                          key=f"_rc_t_{r['번호']}", use_container_width=True):
                toggle(r["번호"])
                st.rerun()
            if rc3.button("삭제", key=f"_rc_d_{r['번호']}",
                          use_container_width=True):
                remove(r["번호"])
                st.rerun()

    # ---- 발송 기록 ----
    if ok_repo:
        st.divider()
        log = load_log()
        with st.expander(f"📨 발송 기록 · {len(log)}건", expanded=False):
            if log.empty:
                st.caption("발송 기록이 없습니다.")
            else:
                import theme as TH
                TH.table(log.tail(20).iloc[::-1],
                         align_right=["성공", "실패", "비용"])
                st.caption("제562조제2항제3호 — 조치사항 기록·연말까지 보관")
