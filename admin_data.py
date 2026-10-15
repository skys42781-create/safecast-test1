"""
SAFECASTY — 관리자 화면 데이터 어댑터
=======================================
app.py가 계산한 실제 판정값을 admin_1a / 1b / 1c 가 요구하는 모양으로 옮긴다.

[왜 따로 두는가]
    화면 모듈은 그리기만 하고, app.py는 판정만 한다.
    둘을 직접 붙이면 화면을 바꿀 때마다 app.py를 건드리게 되고,
    같은 값을 세 화면이 제각각 꺼내 쓰면 숫자가 어긋나기 시작한다.
    변환을 한곳에 모아 세 화면이 같은 원본을 보도록 한다.

ctx 에 담겨 오는 것 (app.py 에서 조립):
    now, site, grid, source_text, demo
    cur_ta, cur_rh, cur_at, cur_tier, corr_note
    today_df, blocks, alarms, tbm_public, roster_n, day_max, day_tier
    lead, strict, loss, alerts, report, fbias
    tier_by_code, rest_slots
"""

from __future__ import annotations

from datetime import datetime, timedelta


from recipients import sent_at_map, sent_today

WEEK = "월화수목금토일"

# TBM 관리등급 → 등급 색 키. admin_* 모듈은 등급명으로 색을 찾는다.
RISK = {"집중관찰": "심각", "열순응 관리": "경계", "주의 관찰": "주의"}


def _now_text(now: datetime) -> str:
    return f"{now:%Y-%m-%d} ({WEEK[now.weekday()]}) {now:%H:%M}"


def _basis_notes(ctx: dict) -> list[str]:
    """보정 근거 문구. 데모면 보정 설명이 사실이 아니므로 바뀐다."""
    if ctx.get("demo"):
        return ["기상청 예보를 받지 못해 데모 데이터로 표시 중입니다. "
                "고도·습도·편의 보정은 적용되지 않았습니다.",
                "이 화면의 값은 실제 판정 근거가 아니며 기록으로 남길 수 없습니다."]
    notes = ["판정값 = 블록 내 최고 체감온도 "
             "(별표13의2 공간축 MAX를 시간축으로 확장)",
             ctx.get("corr_note", "")]
    fb = ctx.get("fbias") or {}
    if fb.get("applied") and fb.get("correction"):
        notes.append(f"격자 편의 보정 {fb['correction']:+.1f}℃ 적용")
    else:
        notes.append(f"편의 보정 미적용 — {fb.get('reason', '사유 없음')}")
    notes.append("등급 경계 31 / 33 / 35 / 38℃ — 제560조, 대응지침(2026.5)")
    return [n for n in notes if n]


# =====================================================================
# 공통 조각
# =====================================================================

def next_alarm(ctx: dict):
    """아직 오지 않은 첫 알람. 없으면 None.

    지나간 알람을 '다음 알람'으로 띄우면 관리자가 이미 끝난 통보를
    기다리게 된다. 발송시각이 현재 이후인 것만 고른다.
    """
    al = ctx.get("alarms")
    if al is None or al.empty:
        return None
    hm = ctx["now"].strftime("%H:%M")
    up = al[al["발송시각"].astype(str) > hm]
    return up.iloc[0] if not up.empty else None


def _metrics(ctx: dict) -> list[dict]:
    """네 화면이 공유하는 지표 4칸."""
    df = ctx["today_df"]
    nxt = next_alarm(ctx)
    peak_h = (int(df.loc[df["at"].idxmax(), "hour"]) if not df.empty else None)
    return [
        {"label": "오늘 최고 체감", "value": f"{ctx['day_max']:.1f}℃",
         "sub": (f"{peak_h}시 · {ctx['day_tier'].short} 구간"
                 if peak_h is not None else "예보 없음")},
        {"label": "다음 알람",
         "value": (str(nxt["발송시각"]) if nxt is not None else "없음"),
         "sub": (f"{nxt['대상 블록']} 진입 {ctx['lead']}분 전"
                 if nxt is not None else "남은 사전 통보 없음")},
        {"label": "관리 대상",
         "value": f"{len(ctx['tbm_public'])} / {ctx['roster_n']}명",
         "sub": "민감군 · 열순응 대상"},
        {"label": "작업시간 손실률", "value": f"{ctx['loss']}%",
         "sub": "법적 의무만" if ctx["strict"] else "의무 휴식 + 옥외 중지"},
    ]


def _workers(ctx: dict, limit: int) -> list[dict]:
    pv = ctx["tbm_public"]
    if pv is None or pv.empty:
        return []
    out = []
    for _, t in pv.head(limit).iterrows():
        out.append({"name": str(t["성명"]),
                    "types": str(t["조치사항"])[:30],
                    "status": str(t["공종"]),
                    "risk": RISK.get(str(t["관리등급"]), "평시")})
    return out


def _alarms(ctx: dict, limit: int = 4) -> list[dict]:
    """알람 목록에 실제 발송 여부를 함께 싣는다.

    [시각 경과가 아니라 기록으로 판단한다]
      예전에는 발송시각이 지나면 전파 완료로 보였다. 아무도 보내지
      않았어도 그랬기 때문에 놓친 알람이 처리된 것처럼 묻혔다.
      문자가 붙은 지금은 시스템이 보낸 사실을 확실히 알 수 있으므로,
      발송 기록이 있을 때만 발송됨으로 표시한다.
    """
    al = ctx["alarms"]
    if al is None or al.empty:
        return []
    hm = ctx["now"].strftime("%H:%M")

    done, when = set(), {}
    try:
        done = sent_today(ctx["now"])
        when = sent_at_map(ctx["now"])
    except Exception:
        pass

    out = []
    for _, a in al.head(limit).iterrows():
        t = str(a["발송시각"])
        out.append({"time": t,
                    "sent": t in done,
                    "sent_at": when.get(t, ""),
                    "overdue": t <= hm,
                    "status": "sent" if t in done else "pending",
                    "message": f"{a['대상 블록']} 진입 — "
                               f"판정 {a['체감온도']} {a['등급']}"})
    return out


# =====================================================================
# 1a — 블록 스트립
# =====================================================================

def build_1a(ctx: dict) -> dict:
    ct, strict = ctx["cur_tier"], ctx["strict"]
    acts = ct.actions_by(strict)

    blocks = []
    for _, r in ctx["blocks"].iterrows():
        t = ctx["tier_by_code"](r["tier_code"])
        sl = ctx["rest_slots"](r, strict) if r["is_work"] else []

        if r["is_work"]:
            a = [{"text": tx, "kind": lv, "strong": (lv == "의무" and i == 0)}
                 for i, (lv, tx) in enumerate(t.actions_by(strict))][:3]
        elif t.short == "평시":
            # 평시에는 그늘 제공·음료 비치가 의무가 아니다(제567조제2항은 주의부터).
            # 할 일이 없는데 굵게 띄우면 다른 카드의 굵은 글씨까지 무게를 잃는다.
            a = [{"text": "휴게 구간 · 별도 조치 없음", "kind": "권고", "strong": False}]
        else:
            # 점심·휴게처럼 작업하지 않는 구간에 휴식을 또 배정할 수는 없다.
            # 이 시간에 관리자가 할 일은 쉴 자리를 갖춰 두는 것이다.
            a = [{"text": "그늘·냉방 휴게장소 확보", "kind": "의무", "strong": True},
                 {"text": "소금·음료수 비치 점검", "kind": "의무", "strong": True}]

        if sl:
            a.append({"text": " · ".join(f"{x['휴식 시작']}–{x['휴식 종료']}"
                                         for x in sl[:2]),
                      "kind": "의무", "strong": True})
        blocks.append({
            "name": str(r["block_name"]).split("(")[0].strip(),
            "hours": f"{r['start']:%H:%M} – {r['end']:%H:%M}",
            "tier": t.short, "value": f"{r['at_rep']:.1f}",
            "is_work": bool(r["is_work"]),
            "running": bool(r["start"] <= ctx["now"] < r["end"]),
            "actions": a,
            "basis": f"{int(r['peak_hour'])}시 {r['at_max']:.1f}℃가 블록 결정",
        })

    return {
        "site": ctx["site"], "grid": ctx["grid"],
        "now_text": _now_text(ctx["now"]),
        "source_text": ctx["source_text"],
        "hero": {
            "tier_label": (f"{ct.short} · {ct.legal}" if ct.legal != "-" else ct.short),
            "apparent": f"{ctx['cur_at']:.1f}",
            "reading": f"기온 {ctx['cur_ta']:.1f}℃ · 습도 {int(round(ctx['cur_rh']))}%",
            "correction": ctx["corr_note"],
            "legal": acts[0][1] if acts else "",
        },
        "metrics": _metrics(ctx),
        "blocks": blocks,
        "alarms": _alarms(ctx),
        "workers": _workers(ctx, 3),
    }


# =====================================================================
# 1b — 시각 축 타임라인
# =====================================================================

def build_1b(ctx: dict, *, day: str = "today") -> dict:
    """시각 축 차트용 데이터.

    day="tomorrow" 면 내일 예보로 같은 그림을 만든다.
    내일은 '지금'이 없으므로 now_text 를 비우고, 알람 표시도 넣지 않는다.
    내일 몇 시에 보낼지는 오늘 밤 다시 계산되므로 지금 찍어 두면 틀린다.
    """
    tmr = (day == "tomorrow")
    # 그래프는 오늘 하루 전체를 그린다. 최신 발표본이 오후부터만 담고
    # 있어도 아침까지 이어 보여야 하루 흐름이 읽힌다.
    # 등급 판정은 today_df 로 따로 하므로 여기 값이 등급을 바꾸지 않는다.
    df = ctx["tmr_df"] if tmr else ctx.get("today_full")
    if df is None or df.empty:
        df = ctx["today_df"]
    ct = ctx["cur_tier"]
    _nxt = None if tmr else next_alarm(ctx)

    # 차트 x축은 08~18시 고정. 그 밖의 시각은 선이 밖으로 나가므로 자른다.
    hourly = [{"hour": int(h), "apparent": float(a)}
              for h, a in zip(df["hour"], df["at"]) if 8 <= int(h) <= 18]
    if not hourly:
        if tmr:
            return {}          # 내일 예보가 없으면 차트를 그리지 않는다
        hourly = [{"hour": max(8, min(18, ctx["now"].hour)),
                   "apparent": float(ctx["cur_at"])}]

    src_blocks = ctx["blocks_tmr"] if tmr else ctx["blocks"]
    blocks, rests = [], []
    for _, r in src_blocks.iterrows():
        t = ctx["tier_by_code"](r["tier_code"])
        nm = str(r["block_name"]).split("(")[0].strip()
        label = nm if not r["is_work"] else f"{nm} · {t.short} {r['at_rep']:.1f}"
        blocks.append({"label": label,
                       "start": max(8, int(r["start"].hour)),
                       "end": min(18, int(r["end"].hour)),
                       "tier": t.short, "is_work": bool(r["is_work"])})
        for x in (ctx["rest_slots"](r, ctx["strict"]) if r["is_work"] else []):
            rests.append({"start": str(x["휴식 시작"]), "minutes": 20,
                          "tier": t.short})

    when = ctx["now"] + timedelta(days=1) if tmr else ctx["now"]
    return {
        "site": ctx["site"],
        "date_text": f"{when:%Y-%m-%d} ({WEEK[when.weekday()]})",
        "now_text": "" if tmr else f"{ctx['now']:%H:%M}",
        "tier": ct.short,
        "tier_chip": f"지금 {ct.short} {ctx['cur_at']:.1f}℃",
        "alarm_chip": (f"다음 알람 {_nxt['발송시각']}"
                       if _nxt is not None else "예정 알람 없음"),
        "hourly": hourly,
        "blocks": blocks,
        "rests": rests[:6],
        "alarms": ([{"time": str(_nxt["발송시각"])}] if _nxt is not None else []),
        "basis_notes": _basis_notes(ctx),
    }


# =====================================================================
# 1c — 관제 시트
# =====================================================================

def build_1c(ctx: dict) -> dict:
    df, now = ctx["today_df"], ctx["now"]
    blocks = ctx["blocks"]

    deciding = {int(b["peak_hour"]) for _, b in blocks.iterrows()
                if b.get("is_work", True)} if not blocks.empty else set()

    hourly = []
    for _, r in df.sort_values("datetime").iterrows():
        h = int(r["hour"])
        if blocks.empty:
            continue
        hit = blocks[(blocks["start"].dt.hour <= h) & (blocks["end"].dt.hour > h)]
        if hit.empty:
            continue
        b = hit.iloc[0]
        t = ctx["tier_by_code"](b["tier_code"])
        if not b["is_work"]:
            act = "비작업 — 그늘·냉방 휴게장소 및 소금·음료수 비치 점검"
        else:
            must = [tx for lv, tx in t.actions if lv == "의무"]
            act = must[0] if must else (t.action_texts[0] if t.action_texts else "")
            if t.stop_work:
                act += " · 권고 옥외작업 중지 검토"
        hourly.append({
            "hour": f"{h:02d}",
            "reading": f"{r['ta']:.1f}/{int(round(r['rh']))}",
            "apparent": f"{r['at']:.1f}",
            "tier": t.short, "block": str(b["block_name"]).split("(")[0].strip(),
            "action": act,
            "now": h == now.hour, "deciding": h in deciding,
            # 이행 체크는 기록 저장소가 생기기 전까지 비워 둔다.
            # 눌러도 남지 않는 체크는 기록 의무를 지키는 척만 하게 된다.
            "checkable": False, "check_label": "", "done": False,
        })

    _nxt1c = next_alarm(ctx)
    return {
        "meta_line": (f"{ctx['site']} · 격자 {ctx['grid']} · "
                      f"{now:%Y-%m-%d} ({WEEK[now.weekday()]}) · "
                      f"출역 {ctx['roster_n']}명 · 기준 {ctx['source_text']}"),
        "metrics": [
            {"label": "현재", "value": f"{ctx['cur_at']:.1f}℃"},
            {"label": "최고", "value": f"{ctx['day_max']:.1f}℃"},
            {"label": "손실률", "value": f"{ctx['loss']}%"},
            {"label": "알람", "value": (str(_nxt1c["발송시각"])
                                      if _nxt1c is not None else "없음")},
        ],
        "retention_note": "제562조제2항제3호 — 일자별 기록·연말까지 보관",
        "hourly": hourly,
        "basis_notes": _basis_notes(ctx),
        "demo_notes": _basis_notes({**ctx, "demo": True}),
        "tbm_distributed": ctx.get("tbm_distributed", "미배포"),
        "is_demo": bool(ctx.get("demo")),
    }
