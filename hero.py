"""
SAFECASTY — 헤더 · 히어로 (Blueprint)
=======================================
도면 표제란과 판정 패널.

[구성]
  표제란  현장 · 격자 · 시각 · 데이터 출처를 한 줄로. 도면의 타이틀 블록.
  판정    짙은 남색 바탕에 현재 체감온도. 화면에서 가장 무거운 단 하나의 면.
  지표    같은 남색 면을 격자로 나눠 오늘 요약을 넣는다.

[왜 Streamlit 위젯이 아닌가]
  st.metric 을 늘어놓으면 "지금 위험한가"와 "오늘 어떻게 흐르는가"가 분리되어
  아침에 훑기 어렵다. 판정은 하나의 면 위에 모여 있어야 한다.

[조작은 여기 없다]
  components.html 은 iframe 안에서 격리되어 내부 클릭이 서버로 오지 않는다.
  지역 변경·모드 전환·신고처럼 왕복이 필요한 조작은 Streamlit 위젯에 둔다.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

TIER_COLORS = {
    "평시": "#15803D", "주의": "#B45309", "경계": "#C2410C",
    "심각": "#B91C1C", "위험": "#7F1D2D",
}

PANEL_BG = "#1D2D3D"      # 판정 면
PANEL_SUB = "#9EBBD8"     # 라벨
PANEL_TXT = "#BDD8F2"     # 보조 텍스트
PANEL_HI = "#D6EBFF"      # 조치 문구

BASE_H = 300
STAT_ROWS = 1


def tier_color(tier_short: str) -> str:
    for k, v in TIER_COLORS.items():
        if k in tier_short:
            return v
    return "#15803D"


def render_hero(*, tier_short: str, tier_legal: str,
                ta: float, rh: float, at: float,
                series: list[dict], now_hour: int,
                site_name: str, stamp: str,
                grid: str = "",
                today_str: str = "",
                corr_note: str = "",
                action_note: str = "",
                details: list[str] | None = None,
                stats: list[dict] | None = None,
                alerts: int = 0,
                demo: bool = False) -> None:
    """표제란 + 판정 패널.

    stats: [{"label": "오늘 최고 체감", "value": "36.4℃", "note": "14시 · 심각"}]
    """
    payload = json.dumps({
        "tier": tier_short, "legal": tier_legal,
        "ta": ta, "rh": rh, "at": at,
        "series": series, "nowHour": now_hour,
        "site": site_name, "stamp": stamp, "grid": grid, "today": today_str,
        "color": tier_color(tier_short),
        "corr": corr_note, "action": action_note,
        "details": [d for d in (details or []) if d and str(d).strip()],
        "stats": (stats or [])[:4],
        "alerts": int(alerts), "demo": bool(demo),
        "bg": PANEL_BG, "sub": PANEL_SUB, "txt": PANEL_TXT, "hi": PANEL_HI,
    }, ensure_ascii=False)
    components.html(_HTML.replace("__DATA__", payload),
                    height=BASE_H, scrolling=False)


_HTML = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'IBM Plex Sans KR',system-ui,sans-serif;background:transparent;
  color:#1D1F20;-webkit-font-smoothing:antialiased}
.wrap{border:1px solid rgba(29,31,32,.16);background:#fff;position:relative}

/* 도면 코너 마크 */
.reg::before,.reg::after,.reg>.rg::before,.reg>.rg::after{
  content:'';position:absolute;background:#5980A6;opacity:.6}
.reg::before{top:-1px;left:-1px;width:10px;height:1px}
.reg::after{top:-1px;left:-1px;width:1px;height:10px}
.reg>.rg::before{bottom:-1px;right:-1px;width:10px;height:1px}
.reg>.rg::after{bottom:-1px;right:-1px;width:1px;height:10px}

/* 표제란 */
.title{display:flex;align-items:center;justify-content:space-between;gap:20px;
  padding:11px 22px;border-bottom:1px solid rgba(29,31,32,.16);flex-wrap:wrap}
.brand{display:flex;align-items:baseline;gap:12px}
.bn{font-weight:700;font-size:19px;letter-spacing:.06em}
.bs{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:#7A7A7D}
.meta{display:flex;align-items:center;gap:18px;font-size:12px;color:#5D5D60;
  flex-wrap:wrap}
.meta .num{font-variant-numeric:tabular-nums}
.live{display:flex;align-items:center;gap:6px}
.led{width:6px;height:6px;display:block;background:#15803D;
  animation:blink 2s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
.demo{font-size:10.5px;font-weight:600;padding:2px 8px;background:#B45309;color:#fff;
  letter-spacing:.4px}

/* 판정 패널 */
.panel{display:grid;grid-template-columns:1fr 1fr}
.judge{padding:20px 22px 17px;border-right:1px solid rgba(255,255,255,.14)}
.jhd{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.jlabel{font-size:10.5px;letter-spacing:.18em;text-transform:uppercase}
.jbadge{font-size:11px;font-weight:700;padding:2px 9px;color:#1D1F20}
.jmain{display:flex;align-items:flex-end;gap:12px;margin-top:7px;flex-wrap:wrap}
.jtemp{font-weight:700;font-size:62px;line-height:.9;letter-spacing:-.03em;
  font-variant-numeric:tabular-nums}
.junit{font-size:22px;margin-bottom:8px}
.jsub{margin-bottom:9px;font-size:12.5px;line-height:1.5}
.jact{margin-top:13px;padding-top:11px;border-top:1px solid rgba(255,255,255,.16);
  font-size:12.5px;line-height:1.5}

/* 지표 격자 */
.stats{display:grid;grid-template-columns:1fr 1fr}
.stat{padding:15px 18px;border-bottom:1px solid rgba(255,255,255,.14)}
.stat:nth-child(odd){border-right:1px solid rgba(255,255,255,.14)}
.stat:nth-last-child(-n+2){border-bottom:none}
.sl{font-size:10.5px;letter-spacing:.16em;text-transform:uppercase}
.sv{font-weight:600;font-size:29px;line-height:1.15;font-variant-numeric:tabular-nums}
.sn{font-size:11.5px}

/* 근거 패널 */
.info{width:22px;height:22px;border:1px solid rgba(255,255,255,.4);background:none;
  color:inherit;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit;
  line-height:1;position:relative;transition:background .15s}
.info:hover{background:rgba(255,255,255,.16)}
.info.on{background:#fff;color:#1D2D3D}
.nb{position:absolute;top:-5px;right:-5px;min-width:14px;height:14px;padding:0 3px;
  background:#DC2626;color:#fff;font-size:9.5px;font-weight:700;line-height:14px}
.sheet{position:absolute;top:44px;right:20px;z-index:30;width:min(390px,calc(100% - 40px));
  background:#fff;border:1px solid rgba(29,31,32,.24);
  box-shadow:0 12px 30px rgba(43,43,45,.2);opacity:0;pointer-events:none;
  transform:translateY(-6px);transition:opacity .16s,transform .18s}
.sheet.on{opacity:1;pointer-events:auto;transform:none}
.sheet h4{font-size:10.5px;font-weight:600;letter-spacing:.9px;text-transform:uppercase;
  color:#7A7A7D;padding:12px 16px 8px}
.sheet li{list-style:none;font-size:12px;line-height:1.6;padding:8px 16px;
  border-top:1px solid rgba(29,31,32,.09)}

/* 스파크라인 */
.spark{position:relative;height:40px;margin-top:11px;cursor:crosshair}
.spark svg{width:100%;height:40px;display:block}
.tip{position:absolute;transform:translate(-50%,-100%);background:rgba(0,0,0,.8);
  color:#fff;padding:3px 8px;font-size:11px;white-space:nowrap;opacity:0;
  transition:opacity .14s;pointer-events:none;font-variant-numeric:tabular-nums}
.tip.on{opacity:1}
.axis{display:flex;justify-content:space-between;font-size:10.5px;margin-top:3px}
@media (max-width:900px){
  .panel{grid-template-columns:1fr}
  .judge{border-right:none;border-bottom:1px solid rgba(255,255,255,.14)}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>

<div class="wrap reg"><span class="rg"></span>
  <div class="title">
    <div class="brand">
      <span class="bn">SAFECASTY</span>
      <span class="bs">heat safety control</span>
      <span class="demo" id="demo" style="display:none">DEMO</span>
    </div>
    <div class="meta">
      <span id="site"></span>
      <span class="num" id="today"></span>
      <span class="live"><span class="led"></span><span id="stamp"></span></span>
    </div>
  </div>

  <div class="panel" id="pnl">
    <div class="judge">
      <div class="jhd">
        <span class="jlabel" id="jl">현재 체감온도</span>
        <span class="jbadge" id="badge"></span>
        <button class="info" id="btn" aria-label="측정 출처와 보정 근거">i</button>
      </div>
      <div class="jmain">
        <span class="jtemp" id="temp">--</span>
        <span class="junit">℃</span>
        <div class="jsub" id="sub"></div>
      </div>
      <div class="spark" id="spark"><div class="tip" id="tip"></div></div>
      <div class="axis"><span id="ax0"></span><span id="ax1"></span><span id="ax2"></span></div>
      <div class="jact" id="act"></div>
    </div>
    <div class="stats" id="stats"></div>
  </div>

  <div class="sheet" id="sheet"><h4>측정 출처 · 보정 근거</h4><ul id="list"></ul></div>
</div>

<script>
const D = __DATA__;
const pnl = document.getElementById('pnl');
pnl.style.background = D.bg; pnl.style.color = '#F2F2F3';
document.getElementById('jl').style.color = D.sub;
document.getElementById('site').textContent =
  D.site + (D.grid ? ' · 격자 ' + D.grid : '');
document.getElementById('today').textContent = D.today;
document.getElementById('stamp').textContent = D.stamp;
if (D.demo) document.getElementById('demo').style.display = '';

const badge = document.getElementById('badge');
badge.textContent = D.tier + (D.legal ? ' · ' + D.legal : '');
badge.style.background = D.color;
badge.style.color = '#F2F2F3';

document.getElementById('sub').style.color = D.txt;
document.getElementById('sub').innerHTML =
  '기온 ' + D.ta.toFixed(1) + '℃ · 습도 ' + Math.round(D.rh) + '%' +
  (D.corr ? '<br>' + D.corr : '');
const act = document.getElementById('act');
act.style.color = D.hi;
act.textContent = D.action || '';
if (!D.action) act.style.display = 'none';

/* 지표 */
document.getElementById('stats').innerHTML = (D.stats || []).map(function(s){
  return '<div class="stat">' +
    '<div class="sl" style="color:' + D.sub + '">' + s.label + '</div>' +
    '<div class="sv">' + s.value + '</div>' +
    '<div class="sn" style="color:' + D.txt + '">' + (s.note || '') + '</div></div>';
}).join('');

/* 근거 */
const btn = document.getElementById('btn'), sheet = document.getElementById('sheet');
if (D.details && D.details.length) {
  document.getElementById('list').innerHTML =
    D.details.map(function(x){ return '<li>' + x + '</li>'; }).join('');
  if (D.alerts > 0) btn.insertAdjacentHTML('beforeend',
    '<span class="nb">' + (D.alerts > 9 ? '9+' : D.alerts) + '</span>');
  btn.addEventListener('click', function(e){
    e.stopPropagation();
    sheet.classList.toggle('on'); btn.classList.toggle('on');
    const b = btn.querySelector('.nb'); if (b) b.remove();
  });
  document.addEventListener('click', function(){
    sheet.classList.remove('on'); btn.classList.remove('on');
  });
  sheet.addEventListener('click', function(e){ e.stopPropagation(); });
} else { btn.style.display = 'none'; }

/* 숫자 */
const el = document.getElementById('temp'), t0 = performance.now();
(function roll(t){
  const p = Math.min(((t || performance.now()) - t0) / 620, 1);
  el.textContent = (D.at * (1 - Math.pow(1 - p, 3))).toFixed(1);
  if (p < 1) requestAnimationFrame(roll); else el.textContent = D.at.toFixed(1);
})();

/* 스파크라인 */
const S = D.series, W = 480, H = 38, P = 5;
const v = S.map(function(x){ return x.at; });
const lo = Math.min.apply(null, v), hi = Math.max.apply(null, v), rg = (hi - lo) || 1;
const pt = S.map(function(x, i){ return [
  P + i * (W - 2*P) / Math.max(S.length - 1, 1),
  H - P - ((x.at - lo) / rg) * (H - 2*P)]; });
document.getElementById('ax0').textContent = S[0].hour + '시';
document.getElementById('ax1').textContent = S[Math.floor(S.length/2)].hour + '시';
document.getElementById('ax2').textContent = S[S.length-1].hour + '시';
['ax0','ax1','ax2'].forEach(function(id){
  document.getElementById(id).style.color = D.sub; });

let d = 'M ' + pt[0][0] + ' ' + pt[0][1];
for (let i = 1; i < pt.length; i++) d += ' L ' + pt[i][0] + ' ' + pt[i][1];
let ni = S.findIndex(function(x){ return x.hour === D.nowHour; });
if (ni < 0) ni = 0;
const pi = v.indexOf(hi);
const sp = document.getElementById('spark'), tip = document.getElementById('tip');
sp.insertAdjacentHTML('afterbegin',
  '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' +
  '<path d="' + d + ' L ' + pt[pt.length-1][0] + ' ' + H + ' L ' + pt[0][0] + ' ' + H + ' Z" fill="rgba(255,255,255,.10)"/>' +
  '<path d="' + d + '" fill="none" stroke="' + D.sub + '" stroke-width="1.6"/>' +
  '<rect x="' + (pt[pi][0]-2.5) + '" y="' + (pt[pi][1]-2.5) + '" width="5" height="5" fill="' + D.txt + '" opacity=".7"/>' +
  '<rect x="' + (pt[ni][0]-3) + '" y="' + (pt[ni][1]-3) + '" width="6" height="6" fill="#fff"/>' +
  '<line id="sl" x1="0" y1="0" x2="0" y2="' + H + '" stroke="rgba(255,255,255,.4)" stroke-width="1" opacity="0"/>' +
  '</svg>');
const sl = document.getElementById('sl');
function scrub(e){
  const r = sp.getBoundingClientRect();
  const cx = e.touches ? e.touches[0].clientX : e.clientX;
  const i = Math.max(0, Math.min(S.length-1,
    Math.round((cx - r.left) / r.width * (S.length - 1))));
  sl.setAttribute('x1', pt[i][0]); sl.setAttribute('x2', pt[i][0]);
  sl.setAttribute('opacity', '1');
  tip.textContent = S[i].hour + '시 ' + S[i].at.toFixed(1) + '℃';
  tip.style.left = (pt[i][0] / W * 100) + '%';
  tip.style.top = (pt[i][1] / H * 40 - 4) + 'px';
  tip.classList.add('on');
}
sp.addEventListener('mousemove', scrub);
sp.addEventListener('mouseleave', function(){
  sl.setAttribute('opacity','0'); tip.classList.remove('on'); });
sp.addEventListener('touchmove', function(e){ e.preventDefault(); scrub(e); }, {passive:false});
sp.addEventListener('touchend', function(){
  sl.setAttribute('opacity','0'); tip.classList.remove('on'); });
</script>
"""
