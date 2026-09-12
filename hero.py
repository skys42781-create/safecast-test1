"""
SAFECASTY — 히어로 컴포넌트
=============================
현재 상태와 오늘의 흐름, 주요 지표를 하나의 카드로 보여준다.

[왜 Streamlit 위젯이 아니라 HTML인가]
  st.metric 여러 개로는 "지금 위험한가"와 "몇 시가 고비인가"가 분리되어
  현장에서 한눈에 읽히지 않는다. 관리자는 숫자를 비교하는 게 아니라
  판단을 해야 한다.

[왜 조작은 여기 없는가]
  st.components.v1.html()은 iframe 안에서 격리되므로 내부 클릭이
  Streamlit으로 전달되지 않는다. 지역 변경·모드 전환·신고처럼 서버 왕복이
  필요한 조작은 Streamlit 위젯에 남기고, 이 컴포넌트는 표시만 담당한다.

[무엇을 숨기고 무엇을 남기는가]
  숨김  출처, 계산 근거, 부연 설명  → ⓘ 패널
  남김  등급, 온도, 주요 지표, 경고
  근거는 감사 대응에 필요하지만 매번 읽을 내용은 아니다. 반면 법적 구분은
  이 시스템의 핵심이므로 숨기지 않는다.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

TIER_COLORS = {
    "평시": {"bg": "#15803D", "accent": "#22C55E"},
    "주의": {"bg": "#B45309", "accent": "#F59E0B"},
    "경계": {"bg": "#C2410C", "accent": "#F97316"},
    "심각": {"bg": "#B91C1C", "accent": "#EF4444"},
    "위험": {"bg": "#7F1D2D", "accent": "#DC2626"},
}

PULSE_TIERS = {"심각", "위험"}

BASE_H = 292        # 히어로 본체
STAT_H = 88         # 지표 줄

# ⓘ 패널은 카드 위에 겹쳐 띄운다.
# 아래로 펼치면 그만큼 iframe 높이를 항상 비워둬야 해서
# 패널을 닫아 둔 평소에도 큰 빈 공간이 남는다.
PANEL_MAX = 268     # 패널 자체의 최대 높이 (iframe 높이에는 더하지 않는다)


def _color(tier_short: str) -> dict:
    for k, v in TIER_COLORS.items():
        if k in tier_short:
            return v
    return TIER_COLORS["평시"]


def render_hero(*, tier_short: str, tier_legal: str,
                ta: float, rh: float, at: float,
                series: list[dict], now_hour: int,
                site_name: str, stamp: str,
                corr_note: str = "",
                details: list[str] | None = None,
                stats: list[dict] | None = None,
                alerts: int = 0,
                demo: bool = False) -> None:
    """히어로 카드.

    series : [{"hour": 8, "at": 31.2}, ...]
    details: 출처·보정 근거. ⓘ 안에만 표시한다.
    stats  : [{"label": "최고 체감온도", "value": "36.2℃", "note": "기온 대비 +2.8"}]
    alerts : 처리 대기 항목 수. 0이면 배지를 띄우지 않는다.
    """
    c = _color(tier_short)
    dl = [d for d in (details or []) if d and str(d).strip()]
    sl = stats or []

    payload = json.dumps({
        "tier": tier_short, "legal": tier_legal,
        "ta": ta, "rh": rh, "at": at,
        "series": series, "nowHour": now_hour,
        "site": site_name, "stamp": stamp,
        "bg": c["bg"], "accent": c["accent"],
        "pulse": any(t in tier_short for t in PULSE_TIERS),
        "corr": corr_note, "details": dl, "stats": sl,
        "alerts": int(alerts), "demo": bool(demo),
    }, ensure_ascii=False)

    h = BASE_H + (STAT_H if sl else 0)
    html = (_HTML.replace("__DATA__", payload)
                 .replace("__PMAX__", str(PANEL_MAX - 60)))
    components.html(html, height=h, scrolling=False)


_HTML = r"""
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans KR',system-ui,sans-serif;background:transparent}
.hero{border-radius:28px;padding:24px 26px 20px;color:#fff;position:relative;
  overflow:hidden;animation:rise .6s cubic-bezier(.22,1.28,.36,1) both}
.hero.pulse::after{content:'';position:absolute;inset:0;border-radius:28px;
  background:radial-gradient(circle at 50% 45%,rgba(255,255,255,.20),transparent 62%);
  animation:breathe 2.6s ease-in-out infinite;pointer-events:none}
@keyframes breathe{0%,100%{opacity:.25}50%{opacity:.85}}
@keyframes rise{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
@keyframes bump{0%{transform:scale(1)}30%{transform:scale(1.13)}55%{transform:scale(.96)}
  78%{transform:scale(1.03)}100%{transform:scale(1)}}
@keyframes pop{0%{transform:scale(.6);opacity:0}40%{transform:scale(1.2)}
  70%{transform:scale(.94)}100%{transform:scale(1);opacity:1}}

.top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;
  position:relative;z-index:3}
.site{font-size:14.5px;font-weight:500;opacity:.92}
.live{display:flex;align-items:center;gap:6px;font-size:11.5px;opacity:.8;margin-top:3px}
.dot{width:6px;height:6px;border-radius:50%;background:#4ADE80;
  animation:blink 1.6s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
.rt{display:flex;align-items:center;gap:8px;flex:none}
.badge{font-size:12.5px;font-weight:700;padding:6px 14px;border-radius:999px;
  background:rgba(255,255,255,.20);white-space:nowrap}
.demo{font-size:11.5px;font-weight:700;padding:5px 11px;border-radius:999px;
  background:#FDE68A;color:#78350F;white-space:nowrap}
.info{position:relative;width:26px;height:26px;border-radius:50%;border:none;
  cursor:pointer;background:rgba(255,255,255,.20);color:#fff;font-size:13px;
  font-weight:700;font-family:inherit;line-height:1;flex:none;
  transition:transform .18s cubic-bezier(.34,1.56,.64,1),background .18s}
.info:hover{background:rgba(255,255,255,.34);transform:scale(1.12)}
.info:active{transform:scale(.92)}
.info.on{background:rgba(255,255,255,.92);color:#111}
.nbadge{position:absolute;top:-3px;right:-3px;min-width:16px;height:16px;padding:0 4px;
  border-radius:999px;background:#EF4444;color:#fff;font-size:10px;font-weight:700;
  line-height:16px;animation:pop .45s cubic-bezier(.34,1.56,.64,1) both}

.main{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap;
  margin:12px 0 2px;position:relative;z-index:2}
.temp{font-size:58px;font-weight:900;line-height:1;letter-spacing:-2px;
  font-variant-numeric:tabular-nums}
.temp.bump{animation:bump .5s cubic-bezier(.34,1.56,.64,1)}
.unit{font-size:22px;font-weight:700;opacity:.85;margin-bottom:7px}
.sub{display:flex;gap:16px;font-size:13.5px;opacity:.9;margin-bottom:9px}
.sub b{font-weight:700}

.spark{margin-top:8px;height:58px;position:relative;z-index:2;cursor:crosshair}
.spark svg{width:100%;height:58px;display:block}
.tip{position:absolute;transform:translate(-50%,-100%);background:rgba(0,0,0,.72);
  padding:5px 10px;border-radius:10px;font-size:12px;white-space:nowrap;
  opacity:0;transition:opacity .16s;pointer-events:none}
.tip.on{opacity:1}
.axis{display:flex;justify-content:space-between;font-size:11.5px;opacity:.66;
  margin-top:2px;position:relative;z-index:2}
.note{font-size:11.5px;opacity:.72;margin-top:8px;position:relative;z-index:2}

.stats{display:flex;gap:10px;margin-top:12px;overflow-x:auto;
  scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;
  padding-bottom:4px;scrollbar-width:none}
.stats::-webkit-scrollbar{display:none}
.stat{flex:1 0 auto;min-width:132px;scroll-snap-align:start;background:#fff;
  border-radius:18px;padding:13px 16px;color:#191F28;
  box-shadow:0 1px 3px rgba(0,0,0,.06);
  animation:rise .5s cubic-bezier(.22,1.28,.36,1) both}
.stat .l{font-size:11.5px;color:#8B95A1;font-weight:500}
.stat .v{font-size:21px;font-weight:800;margin-top:3px;letter-spacing:-.5px}
.stat .n{font-size:11.5px;color:#8B95A1;margin-top:2px}

.panel{position:absolute;top:62px;right:22px;z-index:20;
  width:min(360px,calc(100% - 44px));background:#fff;border-radius:20px;
  box-shadow:0 12px 32px rgba(0,0,0,.22);
  opacity:0;transform:scale(.94) translateY(-8px);pointer-events:none;
  transition:opacity .2s,transform .24s cubic-bezier(.34,1.56,.64,1)}
.panel.on{opacity:1;transform:none;pointer-events:auto}
.pbody{padding:16px 18px;max-height:__PMAX__px;overflow-y:auto;color:#191F28}
.pbody h4{font-size:11.5px;font-weight:700;color:#8B95A1;margin-bottom:8px;
  letter-spacing:.4px}
.pbody li{list-style:none;font-size:13px;line-height:1.6;padding:7px 0;
  border-bottom:1px solid #EEF1F4}
.pbody li:last-child{border-bottom:none}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>

<div style="position:relative">
<div class="hero" id="hero">
  <div class="top">
    <div>
      <div class="site" id="site"></div>
      <div class="live"><span class="dot"></span><span id="stamp"></span></div>
    </div>
    <div class="rt">
      <span class="demo" id="demo" style="display:none">데모</span>
      <div class="badge" id="badge"></div>
      <button class="info" id="info" aria-label="측정 출처와 보정 근거">i</button>
    </div>
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
  <div class="axis"><span id="ax0"></span><span id="ax1"></span><span id="ax2"></span></div>
  <div class="note" id="note"></div>
</div>

<div class="stats" id="stats"></div>

<div class="panel" id="panel"><div class="pbody">
  <h4>측정 출처 · 보정 근거</h4><ul id="plist"></ul>
</div></div>
</div>

<script>
const D = __DATA__;
const hero = document.getElementById('hero');
hero.style.background = D.bg;
if (D.pulse) hero.classList.add('pulse');
if (D.demo) document.getElementById('demo').style.display = '';
document.getElementById('site').textContent = D.site;
document.getElementById('stamp').textContent = D.stamp;
document.getElementById('badge').textContent = D.tier + ' · ' + D.legal;
document.getElementById('ta').textContent = D.ta.toFixed(1);
document.getElementById('rh').textContent = Math.round(D.rh);
document.getElementById('note').textContent = D.corr;

if (D.stats && D.stats.length) {
  document.getElementById('stats').innerHTML = D.stats.map(function(s, i){
    return '<div class="stat" style="animation-delay:' + (0.08 + i*0.06) + 's">' +
      '<div class="l">' + s.label + '</div><div class="v">' + s.value + '</div>' +
      (s.note ? '<div class="n">' + s.note + '</div>' : '') + '</div>';
  }).join('');
}

/* 패널은 카드 위에 겹쳐 띄운다. 아래로 펼치면 닫힌 평소에도
   iframe 높이를 비워둬야 해서 큰 빈 공간이 남는다. */
const info = document.getElementById('info');
const panel = document.getElementById('panel');
if (D.details && D.details.length) {
  document.getElementById('plist').innerHTML =
    D.details.map(function(x){ return '<li>' + x + '</li>'; }).join('');
  if (D.alerts > 0) {
    info.insertAdjacentHTML('beforeend',
      '<span class="nbadge">' + (D.alerts > 9 ? '9+' : D.alerts) + '</span>');
  }
  info.addEventListener('click', function(e){
    e.stopPropagation();
    panel.classList.toggle('on'); info.classList.toggle('on');
    const b = info.querySelector('.nbadge'); if (b) b.remove();
  });
  document.addEventListener('click', function(){
    panel.classList.remove('on'); info.classList.remove('on');
  });
  panel.addEventListener('click', function(e){ e.stopPropagation(); });
} else { info.style.display = 'none'; }

const tempEl = document.getElementById('temp');
const target = D.at, t0 = performance.now();
(function roll(t){
  const p = Math.min(((t || performance.now()) - t0) / 700, 1);
  tempEl.textContent = (target * (1 - Math.pow(1 - p, 3))).toFixed(1);
  if (p < 1) requestAnimationFrame(roll);
  else { tempEl.textContent = target.toFixed(1); tempEl.classList.add('bump'); }
})();

const S = D.series, W = 600, H = 54, PAD = 7;
const vals = S.map(function(s){ return s.at; });
const lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
const rng = (hi - lo) || 1;
const pts = S.map(function(s, i){ return [
  PAD + i * (W - 2*PAD) / Math.max(S.length - 1, 1),
  H - PAD - ((s.at - lo) / rng) * (H - 2*PAD)]; });

document.getElementById('ax0').textContent = S[0].hour + '시';
document.getElementById('ax1').textContent = S[Math.floor(S.length/2)].hour + '시';
document.getElementById('ax2').textContent = S[S.length-1].hour + '시';

let d = 'M ' + pts[0][0] + ' ' + pts[0][1];
for (let i = 0; i < pts.length - 1; i++) {
  const a = pts[i], b = pts[i+1];
  d += ' Q ' + a[0] + ' ' + a[1] + ' ' + ((a[0]+b[0])/2) + ' ' + ((a[1]+b[1])/2);
}
d += ' T ' + pts[pts.length-1][0] + ' ' + pts[pts.length-1][1];
const area = d + ' L ' + pts[pts.length-1][0] + ' ' + H + ' L ' + pts[0][0] + ' ' + H + ' Z';
let nowIdx = S.findIndex(function(s){ return s.hour === D.nowHour; });
if (nowIdx < 0) nowIdx = 0;
const peakIdx = vals.indexOf(hi);

const spark = document.getElementById('spark'), tip = document.getElementById('tip');
spark.insertAdjacentHTML('afterbegin',
  '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
  '<path d="' + area + '" fill="rgba(255,255,255,.16)"/>' +
  '<path d="' + d + '" fill="none" stroke="rgba(255,255,255,.9)" stroke-width="3" stroke-linecap="round"/>' +
  '<circle cx="' + pts[peakIdx][0] + '" cy="' + pts[peakIdx][1] + '" r="3.5" fill="#fff" opacity=".55"/>' +
  '<circle cx="' + pts[nowIdx][0] + '" cy="' + pts[nowIdx][1] + '" r="5" fill="#fff">' +
  '<animate attributeName="r" values="5;7;5" dur="1.8s" repeatCount="indefinite"/></circle>' +
  '<line id="sl" x1="0" y1="0" x2="0" y2="' + H + '" stroke="rgba(255,255,255,.45)" stroke-width="1" opacity="0"/>' +
  '<circle id="sd" r="5" fill="#fff" opacity="0"/></svg>');

const sl = document.getElementById('sl'), sd = document.getElementById('sd');
function scrub(e){
  const r = spark.getBoundingClientRect();
  const cx = e.touches ? e.touches[0].clientX : e.clientX;
  const i = Math.max(0, Math.min(S.length - 1,
    Math.round((cx - r.left) / r.width * (S.length - 1))));
  sl.setAttribute('x1', pts[i][0]); sl.setAttribute('x2', pts[i][0]);
  sl.setAttribute('opacity', '1');
  sd.setAttribute('cx', pts[i][0]); sd.setAttribute('cy', pts[i][1]);
  sd.setAttribute('opacity', '1');
  tip.textContent = S[i].hour + '시 · ' + S[i].at.toFixed(1) + '℃';
  tip.style.left = (pts[i][0] / W * 100) + '%';
  tip.style.top = (pts[i][1] / H * 58 - 6) + 'px';
  tip.classList.add('on');
}
function leave(){ sl.setAttribute('opacity','0'); sd.setAttribute('opacity','0');
  tip.classList.remove('on'); }
spark.addEventListener('mousemove', scrub);
spark.addEventListener('mouseleave', leave);
spark.addEventListener('touchmove', function(e){ e.preventDefault(); scrub(e); }, {passive:false});
spark.addEventListener('touchend', leave);
</script>
"""
