"""
SAFECASTY — 히어로 컴포넌트 (토스 스타일)
===========================================
현재 체감온도와 오늘의 흐름을 하나의 카드로 보여준다.

[왜 Streamlit 위젯이 아니라 HTML인가]
  st.metric 4개로는 "지금 몇 도인가"와 "오늘 어떻게 흘러가는가"가 분리되어
  현장에서 한눈에 읽히지 않는다. 관리자는 숫자 네 개를 비교하는 게 아니라
  "지금 위험한가, 몇 시가 고비인가"를 알아야 한다.

[왜 조작은 여기 없는가]
  st.components.v1.html()은 iframe 안에서 격리되므로 내부 클릭이
  Streamlit으로 전달되지 않는다. 지역 변경·모드 전환·신고처럼 서버 왕복이
  필요한 조작은 Streamlit 위젯에 남기고, 이 컴포넌트는 표시만 담당한다.

[데이터 주입]
  mock이 아니라 실제 계산값을 JSON으로 넣는다. 스파크라인도 실제 예보다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# 등급별 색 — 히어로 배경(진한 색)과 강조(밝은 색)
TIER_COLORS = {
    "평시": {"bg": "#15803D", "accent": "#22C55E"},
    "주의": {"bg": "#B45309", "accent": "#F59E0B"},
    "경계": {"bg": "#C2410C", "accent": "#F97316"},
    "심각": {"bg": "#B91C1C", "accent": "#EF4444"},
    "위험": {"bg": "#7F1D2D", "accent": "#DC2626"},
}

PULSE_TIERS = {"심각", "위험"}


def _color(tier_short: str) -> dict:
    for k, v in TIER_COLORS.items():
        if k in tier_short:
            return v
    return TIER_COLORS["평시"]


def render_hero(*, tier_short: str, tier_legal: str,
                ta: float, rh: float, at: float,
                series: list[dict], now_hour: int,
                site_name: str, stamp: str,
                corr_note: str = "") -> None:
    """히어로 카드.

    series: [{"hour": 8, "at": 31.2}, ...]  오늘 08~18시 체감온도
    """
    c = _color(tier_short)
    pulse = any(t in tier_short for t in PULSE_TIERS)

    payload = json.dumps({
        "tier": tier_short, "legal": tier_legal,
        "ta": ta, "rh": rh, "at": at,
        "series": series, "nowHour": now_hour,
        "site": site_name, "stamp": stamp,
        "bg": c["bg"], "accent": c["accent"],
        "pulse": pulse, "corr": corr_note,
    }, ensure_ascii=False)

    components.html(_HTML.replace("__DATA__", payload), height=330, scrolling=False)


_HTML = r"""
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans KR',system-ui,sans-serif;background:transparent}
.hero{border-radius:28px;padding:26px 28px 22px;color:#fff;position:relative;
  overflow:hidden;animation:rise .6s cubic-bezier(.22,1.28,.36,1) both}
.hero.pulse::after{content:'';position:absolute;inset:0;border-radius:28px;
  background:radial-gradient(circle at 50% 45%,rgba(255,255,255,.20),transparent 62%);
  animation:breathe 2.6s ease-in-out infinite;pointer-events:none}
@keyframes breathe{0%,100%{opacity:.25}50%{opacity:.85}}
@keyframes rise{from{opacity:0;transform:translateY(14px) scale(.97)}
  to{opacity:1;transform:none}}
@keyframes bump{0%{transform:scale(1)}30%{transform:scale(1.13)}
  55%{transform:scale(.96)}78%{transform:scale(1.03)}100%{transform:scale(1)}}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;
  position:relative;z-index:2}
.site{font-size:14.5px;font-weight:500;opacity:.92}
.badge{font-size:12.5px;font-weight:700;padding:6px 14px;border-radius:999px;
  background:rgba(255,255,255,.20);white-space:nowrap}
.live{display:flex;align-items:center;gap:6px;font-size:11.5px;opacity:.8;
  margin-top:4px}
.dot{width:6px;height:6px;border-radius:50%;background:#4ADE80;
  animation:blink 1.6s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.main{display:flex;align-items:flex-end;gap:16px;margin:14px 0 2px;
  position:relative;z-index:2}
.temp{font-size:62px;font-weight:900;line-height:1;letter-spacing:-2px;
  font-variant-numeric:tabular-nums}
.temp.bump{animation:bump .5s cubic-bezier(.34,1.56,.64,1)}
.unit{font-size:24px;font-weight:700;opacity:.85;margin-bottom:8px}
.sub{display:flex;gap:18px;font-size:13.5px;opacity:.9;margin-bottom:10px}
.sub b{font-weight:700}
.spark{margin-top:10px;height:66px;position:relative;z-index:2;cursor:crosshair}
.spark svg{width:100%;height:66px;display:block}
.tip{position:absolute;transform:translate(-50%,-100%);background:rgba(0,0,0,.72);
  padding:5px 10px;border-radius:10px;font-size:12px;font-weight:500;
  white-space:nowrap;opacity:0;transition:opacity .16s;pointer-events:none}
.tip.on{opacity:1}
.axis{display:flex;justify-content:space-between;font-size:11.5px;opacity:.66;
  margin-top:2px;position:relative;z-index:2}
.note{font-size:11.5px;opacity:.72;margin-top:10px;line-height:1.5;
  position:relative;z-index:2}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
</style>

<div class="hero" id="hero">
  <div class="top">
    <div>
      <div class="site" id="site"></div>
      <div class="live"><span class="dot"></span><span id="stamp"></span></div>
    </div>
    <div class="badge" id="badge"></div>
  </div>
  <div class="main">
    <div class="temp" id="temp">--</div>
    <div class="unit">℃</div>
    <div class="sub">
      <div>기온 <b id="ta">--</b>℃</div>
      <div>습도 <b id="rh">--</b>%</div>
    </div>
  </div>
  <div class="spark" id="spark"><div class="tip" id="tip"></div></div>
  <div class="axis"><span>08시</span><span>13시</span><span>18시</span></div>
  <div class="note" id="note"></div>
</div>

<script>
const D = __DATA__;
const hero = document.getElementById('hero');
hero.style.background = D.bg;
if (D.pulse) hero.classList.add('pulse');
document.getElementById('site').textContent = D.site;
document.getElementById('stamp').textContent = D.stamp;
document.getElementById('badge').textContent = D.tier + ' · ' + D.legal;
document.getElementById('ta').textContent = D.ta.toFixed(1);
document.getElementById('rh').textContent = Math.round(D.rh);
document.getElementById('note').textContent = D.corr;

const tempEl = document.getElementById('temp');
let cur = 0;
const target = D.at;
const t0 = performance.now();
function roll(t){
  const p = Math.min((t - t0) / 700, 1);
  const e = 1 - Math.pow(1 - p, 3);
  cur = target * e;
  tempEl.textContent = cur.toFixed(1);
  if (p < 1) requestAnimationFrame(roll);
  else { tempEl.textContent = target.toFixed(1); tempEl.classList.add('bump'); }
}
requestAnimationFrame(roll);

const S = D.series;
const W = 600, H = 62, PAD = 7;
const vals = S.map(s => s.at);
const lo = Math.min(...vals), hi = Math.max(...vals), rng = (hi - lo) || 1;
const pts = S.map((s, i) => [
  PAD + i * (W - 2 * PAD) / Math.max(S.length - 1, 1),
  H - PAD - ((s.at - lo) / rng) * (H - 2 * PAD)
]);
let d = 'M ' + pts[0][0] + ' ' + pts[0][1];
for (let i = 0; i < pts.length - 1; i++) {
  const a = pts[i], b = pts[i + 1];
  d += ' Q ' + a[0] + ' ' + a[1] + ' ' + ((a[0]+b[0])/2) + ' ' + ((a[1]+b[1])/2);
}
d += ' T ' + pts[pts.length-1][0] + ' ' + pts[pts.length-1][1];
const area = d + ' L ' + pts[pts.length-1][0] + ' ' + H + ' L ' + pts[0][0] + ' ' + H + ' Z';
const nowIdx = Math.max(S.findIndex(s => s.hour === D.nowHour), 0);
const peakIdx = vals.indexOf(hi);

const spark = document.getElementById('spark');
const tip = document.getElementById('tip');
spark.insertAdjacentHTML('afterbegin',
  '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
  '<path d="' + area + '" fill="rgba(255,255,255,.16)"/>' +
  '<path d="' + d + '" fill="none" stroke="rgba(255,255,255,.9)" stroke-width="3" stroke-linecap="round"/>' +
  '<circle cx="' + pts[peakIdx][0] + '" cy="' + pts[peakIdx][1] + '" r="3.5" fill="#fff" opacity=".55"/>' +
  '<circle cx="' + pts[nowIdx][0] + '" cy="' + pts[nowIdx][1] + '" r="5" fill="#fff"><animate attributeName="r" values="5;7;5" dur="1.8s" repeatCount="indefinite"/></circle>' +
  '<line id="sl" x1="0" y1="0" x2="0" y2="' + H + '" stroke="rgba(255,255,255,.45)" stroke-width="1" opacity="0"/>' +
  '<circle id="sd" r="5" fill="#fff" opacity="0"/>' +
  '</svg>');

const sl = document.getElementById('sl'), sd = document.getElementById('sd');
function scrub(e){
  const r = spark.getBoundingClientRect();
  const x = ((e.touches ? e.touches[0].clientX : e.clientX) - r.left) / r.width;
  const i = Math.max(0, Math.min(S.length - 1, Math.round(x * (S.length - 1))));
  sl.setAttribute('x1', pts[i][0]); sl.setAttribute('x2', pts[i][0]);
  sl.setAttribute('opacity', '1');
  sd.setAttribute('cx', pts[i][0]); sd.setAttribute('cy', pts[i][1]);
  sd.setAttribute('opacity', '1');
  tip.textContent = S[i].hour + '시 · ' + S[i].at.toFixed(1) + '℃';
  tip.style.left = (pts[i][0] / W * 100) + '%';
  tip.style.top = (pts[i][1] / H * 66 - 8) + 'px';
  tip.classList.add('on');
}
function leave(){ sl.setAttribute('opacity','0'); sd.setAttribute('opacity','0');
  tip.classList.remove('on'); }
spark.addEventListener('mousemove', scrub);
spark.addEventListener('mouseleave', leave);
spark.addEventListener('touchmove', e => { e.preventDefault(); scrub(e); }, {passive:false});
spark.addEventListener('touchend', leave);
</script>
"""
