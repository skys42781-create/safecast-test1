"""
SAFECASTY — 문자 발송
=======================
알람 문구를 수신자에게 문자로 보낸다.

[왜 앱이 아니라 문자인가]
    현장 근로자는 하루 단위로 바뀌고 외국인도 많다. 앱 설치를 전제하면
    정작 보호해야 할 사람에게 알림이 닿지 않는다. 문자는 설치가 필요 없고
    피처폰에도 들어간다.

[왜 이 모듈이 발송 주체가 아닌가]
    Streamlit 앱은 누군가 화면을 보고 있을 때만 돈다. 아무도 안 보면
    잠들기 때문에 정해진 시각에 울려야 하는 알람의 주체가 될 수 없다.
    자동 발송은 GitHub Actions(scripts/send_alarms.py)가 맡고,
    이 모듈은 양쪽이 함께 쓰는 발송·기록 도구다.

[발신번호]
    국내 문자는 전기통신사업법상 사전 등록된 실제 번호로만 보낼 수 있다.
    SAFECASTY 같은 영문 발신자명은 쓸 수 없으므로 문구 맨 앞에 넣는다.

설정 (Streamlit secrets / GitHub Actions secrets):
    SOLAPI_KEY, SOLAPI_SECRET, SMS_FROM
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import requests

API = "https://api.solapi.com"
SEND_PATH = "/messages/v4/send-many/detail"

KST = timezone(timedelta(hours=9))

# SMS는 90바이트까지다. 그보다 길면 LMS로 나가고 단가가 오른다(18원 → 45원).
# 알람 문구는 대부분 넘기므로 LMS가 기본이라고 보면 된다.
SMS_LIMIT = 90
LMS_LIMIT = 2000

TIMEOUT = (5, 15)

# 문구 앞머리. 받는 사람 화면에는 번호만 뜨므로 본문으로 출처를 밝힌다.
PREFIX = "[SAFECASTY]"


# =====================================================================
# 설정
# =====================================================================

def _cfg() -> dict:
    """키를 읽는다. Streamlit secrets → 환경변수 순.

    GitHub Actions에는 streamlit이 없으므로 import 자체를 보호한다.
    """
    out = {"key": "", "secret": "", "sender": "", "why": ""}

    def pick(name: str) -> str:
        try:
            import streamlit as st
            v = str(st.secrets.get(name, "") or "").strip()
            if v:
                return v
        except Exception:
            pass
        return str(os.environ.get(name, "") or "").strip()

    out["key"] = pick("SOLAPI_KEY")
    out["secret"] = pick("SOLAPI_SECRET")
    out["sender"] = only_digits(pick("SMS_FROM"))

    missing = [n for n, v in (("SOLAPI_KEY", out["key"]),
                              ("SOLAPI_SECRET", out["secret"]),
                              ("SMS_FROM", out["sender"])) if not v]
    if missing:
        out["why"] = f"{', '.join(missing)} 가 설정되지 않았습니다"
    return out


def is_enabled() -> bool:
    return not _cfg()["why"]


def diagnose() -> str:
    """설정 상태를 사람이 읽을 수 있게. 키는 가린다."""
    c = _cfg()
    if c["why"]:
        return c["why"]
    k = c["key"]
    return f"발신번호 {fmt_phone(c['sender'])} · 키 {k[:8]}…{k[-4:]}"


# =====================================================================
# 번호
# =====================================================================

def only_digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def fmt_phone(v) -> str:
    """010-1234-5678 꼴로. 화면 표시용."""
    d = only_digits(v)
    if len(d) == 11:
        return f"{d[:3]}-{d[3:7]}-{d[7:]}"
    if len(d) == 10:
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    return d


def valid_phone(v) -> bool:
    """국내 휴대폰 번호인가.

    010은 11자리, 구 번호(011·016~019)는 10자리다.
    잘못된 번호도 접수되면 요금이 나가므로 보내기 전에 걸러낸다.
    """
    d = only_digits(v)
    if d.startswith("010"):
        return len(d) == 11
    if d[:3] in ("011", "016", "017", "018", "019"):
        return len(d) in (10, 11)
    return False


# =====================================================================
# 인증 — HMAC-SHA256
# =====================================================================

def _auth_header(key: str, secret: str) -> str:
    """Authorization 헤더.

    signature = hex(HMAC-SHA256(secret, date + salt))

    [주의]
      서버 시각과 15분 이상 벌어지면 RequestTimeTooSkewed 가 난다.
      같은 서명을 15분 안에 재사용해도 DuplicatedSignature 가 나므로
      salt 는 요청마다 새로 만든다.
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    salt = uuid.uuid4().hex
    sig = hmac.new(secret.encode(), (date + salt).encode(),
                   hashlib.sha256).hexdigest()
    return (f"HMAC-SHA256 ApiKey={key}, Date={date}, "
            f"salt={salt}, signature={sig}")


# =====================================================================
# 발송
# =====================================================================

def body_bytes(text: str) -> int:
    return len(str(text).encode("euc-kr", errors="replace"))


def compose(message: str, prefix: bool = True) -> str:
    """보낼 문구. 길면 자른다.

    LMS 한도를 넘으면 솔라피가 거부하므로 미리 줄인다.
    잘릴 때는 뒤를 버린다 — 알람은 앞쪽(시각·등급)이 핵심이다.
    """
    text = f"{PREFIX} {message}".strip() if prefix else str(message).strip()
    if body_bytes(text) <= LMS_LIMIT:
        return text
    cut = text
    while body_bytes(cut + "…") > LMS_LIMIT and cut:
        cut = cut[:-1]
    return cut + "…"


def send(to: list[str] | str, message: str, *,
         subject: str = "", prefix: bool = True) -> dict:
    """문자 발송.

    반환: {"ok", "sent", "failed", "cost", "detail", "text", "why"}
      ok     : 한 건이라도 접수되었는가
      sent   : 접수 건수
      failed : 실패 건수
      detail : 실패 사유 목록 (번호는 가린 상태)

    예외를 던지지 않는다. 알람 발송이 실패해도 수집·판정은 계속되어야 한다.
    """
    c = _cfg()
    out = {"ok": False, "sent": 0, "failed": 0, "cost": 0.0,
           "detail": [], "text": "", "why": ""}
    if c["why"]:
        out["why"] = c["why"]
        return out

    nums = [to] if isinstance(to, str) else list(to)
    good = [only_digits(n) for n in nums if valid_phone(n)]
    bad = [str(n) for n in nums if not valid_phone(n)]
    if bad:
        out["detail"].append(f"번호 형식 오류 {len(bad)}건 — 발송 대상에서 제외")
    if not good:
        out["why"] = "보낼 수 있는 번호가 없습니다"
        return out

    text = compose(message, prefix)
    out["text"] = text

    payload = {
        "messages": [{"to": n, "from": c["sender"], "text": text,
                      **({"subject": subject} if subject else {})}
                     for n in good],
        # 같은 내용을 여러 번 보낼 수 있어야 한다. 알람은 시각마다 반복된다.
        "allowDuplicates": True,
        "showMessageList": True,
    }

    try:
        r = requests.post(
            API + SEND_PATH, json=payload, timeout=TIMEOUT,
            headers={"Authorization": _auth_header(c["key"], c["secret"]),
                     "Content-Type": "application/json"})
        js = r.json() if r.content else {}
    except Exception as e:
        out["why"] = f"발송 요청 실패 ({type(e).__name__})"
        return out

    if r.status_code >= 400:
        out["why"] = (f"{js.get('errorCode', r.status_code)} "
                      f"{js.get('errorMessage', '')}").strip()
        return out

    info = js.get("groupInfo") or {}
    cnt = info.get("count") or {}
    out["sent"] = int(cnt.get("registeredSuccess", 0) or 0)
    out["failed"] = int(cnt.get("registeredFailed", 0) or 0)
    out["cost"] = float(info.get("price", {}).get("sum", 0) or 0)

    for f in (js.get("failedMessageList") or []):
        out["detail"].append(f"{mask_phone(f.get('to'))} — "
                             f"{f.get('statusMessage') or f.get('statusCode')}")

    out["ok"] = out["sent"] > 0
    if not out["ok"] and not out["why"]:
        out["why"] = "접수된 메시지가 없습니다"
    return out


def mask_phone(v) -> str:
    """010-****-5678. 기록과 화면에 번호를 그대로 남기지 않는다."""
    d = only_digits(v)
    if len(d) < 8:
        return "***"
    return f"{d[:3]}-****-{d[-4:]}"


# =====================================================================
# 문구
# =====================================================================

def alarm_text(block: str, at: str, tier: str, lead: int,
               action: str = "") -> str:
    """블록 진입 사전 알람.

    현장에 그대로 전달되는 문구다. 받는 사람이 무엇을 해야 하는지
    첫 두 줄에서 끝나야 한다.
    """
    lines = [f"{lead}분 후 '{block}' 구간 진입",
             f"판정 {at}℃ · {tier}"]
    if action:
        lines.append(action)
    return "\n".join(lines)


def rest_text(block: str, start: str, end: str) -> str:
    return "\n".join([f"'{block}' 의무 휴식 안내",
                      f"{start}부터 {end}까지",
                      "그늘·냉방 휴게장소로 이동"])


def test_text(now: datetime | None = None) -> str:
    """시연용. 실제 알람과 구분되도록 표시한다."""
    now = now or datetime.now(KST)
    return "\n".join(["테스트 발송입니다 (실제 알람 아님)",
                      f"{now:%m/%d %H:%M} 발송",
                      "건설현장 폭염 관제 시스템"])
