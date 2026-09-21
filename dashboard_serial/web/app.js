async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}
function run(action, force) {
  api('/api/action', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, force: !!force})})
    .then(r => { if (!r.ok) alert(r.message || '启动失败'); poll(); });
}
let curPage = 1;

// ── 面板系统 ──────────────────────────────
const PANEL_TITLES = {
  dash:'总览', pages:'页面推送', data:'数据看板', insight:'AI 洞察',
  monitor:'新闻监控', plans:'计划', maint:'维护', logs:'日志',
};
let curPanel = 'dash';
function showPanel(name) {
  curPanel = name;
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + name));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.panel === name));
  document.getElementById('crumb').textContent = PANEL_TITLES[name] || '';
  const dot = document.getElementById('dot-' + name);
  if (dot) dot.classList.remove('on');
  if (name === 'dash') fetchOverview();
  if (name === 'data') fetchData();
  if (name === 'insight') fetchInsights();
  if (name === 'monitor') fetchTask();
}

// ── 热键（保持原有行为） ──────────────────
const PAGE_HOTKEYS = {
  m1: 'page1', m2: 'page2', m3: 'page3', m4: 'page4', m5: 'page5',
  f13: 'page1', f14: 'page2', f15: 'page3', f16: 'page4', f17: 'page5',
  digit1: 'page1', digit2: 'page2', digit3: 'page3', digit4: 'page4', digit5: 'page5',
};
document.addEventListener('keydown', event => {
  const target = event.target;
  if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
  const key = String(event.key || '').toLowerCase();
  const code = String(event.code || '').toLowerCase();
  let action = PAGE_HOTKEYS[key] || PAGE_HOTKEYS[code];
  if (!action && event.ctrlKey && event.altKey) action = PAGE_HOTKEYS[code] || PAGE_HOTKEYS[key.replace(/^digit/, '')];
  if (!action) return;
  event.preventDefault();
  run(action);
});

// ── 小工具 ────────────────────────────────
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function pctHtml(v, digits = 2) {
  if (v === null || v === undefined || isNaN(v)) return '<span class="pct-flat">–</span>';
  const cls = v > 0 ? 'pct-up' : v < 0 ? 'pct-down' : 'pct-flat';
  return `<span class="${cls}">${v > 0 ? '+' : ''}${(+v).toFixed(digits)}%</span>`;
}
const WMO = {0:'☀️',1:'🌤️',2:'⛅',3:'☁️',45:'🌫️',48:'🌫️',51:'🌦️',53:'🌦️',55:'🌦️',61:'🌧️',63:'🌧️',65:'🌧️',66:'🌧️',67:'🌧️',71:'🌨️',73:'🌨️',75:'🌨️',77:'🌨️',80:'🌦️',81:'🌦️',82:'⛈️',85:'🌨️',86:'🌨️',95:'⛈️',96:'⛈️',99:'⛈️'};
const wmo = c => WMO[c] ?? '🌡️';

// ── 计划（原有逻辑） ──────────────────────
function showPlanInputs() {
  const n = parseInt($('planCount').value);
  let h = '';
  for (let i = 1; i <= n; i++) {
    h += '<div class="item"><span>计划' + i + '</span><input id="p' + i + '" maxlength="40" placeholder="输入计划内容"></div>';
  }
  $('planInputs').innerHTML = h;
}
function submitPlans() {
  const n = parseInt($('planCount').value);
  const items = [];
  for (let i = 1; i <= n; i++) {
    const v = $('p' + i).value.trim();
    if (v) items.push(v);
  }
  if (!items.length) { alert('请至少输入一个计划'); return; }
  api('/api/plans', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items})})
    .then(r => { if (!r.ok) alert(r.message || '提交失败'); poll(); });
}

// ── 预览图 ────────────────────────────────
function showImg(id, url) {
  const img = $(id);
  img.src = url + '?t=' + Date.now();
  img.style.display = 'block';
}
const showPreview = () => showImg('preview', '/preview.png');

// 任务完成反馈：动作 → {更新哪张图, 亮哪个面板的点}
function doneFeedback(action) {
  if (['preview', 'preview_page4', 'page4', 'analysis'].includes(action)) { showPreview(); return action === 'analysis' ? 'insight' : 'maint'; }
  if (action === 'stock') { showPreview(); return 'insight'; }
  if (['page1', 'page2', 'page3', 'page5', 'refresh', 'plans'].includes(action)) { showPreview(); return 'maint'; }
  if (action === 'preview_page6') { showImg('imgPage6', '/preview_page6.png'); return 'pages'; }
  if (action.startsWith('landscape_preview_')) { showImg('imgLandscape', '/preview_landscape.png'); return 'pages'; }
  if (action === 'page6' || action.startsWith('landscape_push_')) return 'pages';
  if (action === 'switch_landscape') return 'pages';
  return null;
}

// ── 页4 洞察（状态轮询附带） ──────────────
function showPage4(p) {
  const topic = $('page4Topic'), meta = $('page4Meta'), report = $('page4Report');
  $('p4Updated').textContent = p && p.updated ? '更新 ' + p.updated : '';
  if (!p || !p.available) {
    topic.textContent = p && p.message ? p.message : '暂无页4报告';
    meta.innerHTML = '';
    $('page4Recent').textContent = '';
    report.style.display = 'none';
    report.textContent = '';
    return;
  }
  topic.textContent = '今日主题：' + (p.topic || '未命名') + (p.domain ? '（' + p.domain + '）' : '');
  const chips = [];
  chips.push(p.stale ? '历史报告' : '当前报告');
  if (p.history_count) chips.push('已去重 ' + p.history_count + ' 个主题');
  if (p.model) chips.push(p.model);
  if (p.age_minutes !== null && p.age_minutes !== undefined) chips.push('已生成 ' + p.age_minutes + ' 分钟');
  if (p.prompt_tokens || p.completion_tokens) chips.push('Tokens ' + (p.prompt_tokens || 0) + '/' + (p.completion_tokens || 0));
  meta.innerHTML = '';
  chips.forEach(x => {
    const chip = document.createElement('span');
    chip.className = 'chip' + (x === '历史报告' ? ' warn' : '');
    chip.textContent = x;
    meta.appendChild(chip);
  });
  $('page4Recent').textContent = (p.recent_topics || []).length ? '近期主题：' + p.recent_topics.join(' · ') : '';
  report.textContent = p.text || '';
  report.style.display = 'block';
}

// ── 状态轮询（2s） ────────────────────────
let prevRunning = false;
let shownOnce = false;
function poll() {
  api('/api/status').then(s => {
    curPage = s.page || curPage;
    const el = $('status');
    if (s.running) {
      el.textContent = '⟳ ' + (s.label || '运行中');
      el.className = 'busy';
    } else if (s.ok === null) {
      el.textContent = '○ 空闲';
      el.className = '';
    } else if (s.ok) {
      el.textContent = '✓ 完成';
      el.className = 'ok';
      const justFinished = prevRunning && !s.running;
      if (justFinished) {
        const target = doneFeedback(s.last_action);
        if (target && curPanel !== target) $('dot-' + target).classList.add('on');
        // 报告/数据可能变了，激活面板自刷新
        if (['analysis', 'page4', 'stock'].includes(s.last_action) && curPanel === 'insight') fetchInsights();
        if (curPanel === 'data' && ['refresh', 'page3', 'stock'].includes(s.last_action)) fetchData();
      }
    } else {
      el.textContent = '✕ 失败，看日志';
      el.className = 'bad';
    }
    document.querySelectorAll('.page-btn').forEach(b => {
      b.classList.toggle('active', +b.dataset.page === curPage);
    });
    showPage4(s.page4);
    document.querySelectorAll('.main button').forEach(b => { b.disabled = !!s.running; });
    const h = s.hotkeys || {};
    $('hotkeyStatus').textContent =
      (h.state || '未知') + ' · 已注册 ' + ((h.registered_keys || []).join('/') || '无');
    const logEl = $('log');
    logEl.textContent = (s.log || []).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
    prevRunning = s.running;
  });
}

// ── 总览（6s） ────────────────────────────
function fetchOverview() {
  api('/api/overview').then(renderOverview).catch(() => {});
}
function renderOverview(o) {
  $('ovNext').textContent = o.next_page ? '页' + o.next_page : '–';
  const w = o.weather_now || {};
  $('ovCity').textContent = w.city || '–';
  $('ovWxUpdated').textContent = w.updated ? '更新 ' + w.updated : '';
  $('ovTemp').innerHTML = (w.temperature ?? '–') + '<small>°C</small>';
  $('ovDesc').textContent = w.description ? wmo(w.code) + ' ' + w.description : '–';
  $('ovHL').textContent = w.high != null && w.low != null ? w.high + '° / ' + w.low + '°' : '–';
  $('ovFeels').textContent = w.feels != null ? w.feels + '°C' : '–';
  $('ovWind').textContent = (w.wind != null ? w.wind + ' km/h' : '–') + ' / ' + (w.humidity != null ? w.humidity + '%' : '–');
  const al = $('ovAlert');
  if (w.alert) { al.textContent = '⚠ ' + w.alert; al.style.display = 'inline-flex'; } else al.style.display = 'none';

  const g = o.glm || {};
  $('ovGlmLevel').textContent = g.level ? '档位 ' + g.level : '';
  const q = g.quotas || {};
  $('ovQuotas').innerHTML = Object.entries(q).map(([name, v]) => {
    const pct = v.percent ?? 0;
    const cls = pct > 30 ? 'ok' : 'warn';
    return `<div style="margin-bottom:11px;">
      <div class="row" style="margin:0 0 6px; font-size:13.5px;">
        <b>${esc(name)}</b>
        <span style="margin-left:auto; color:var(--muted); font-variant-numeric:tabular-nums;">${(v.remaining ?? 0).toLocaleString()} / ${(v.total ?? 0).toLocaleString()}</span>
      </div>
      <div class="bar ${cls}"><i style="width:${Math.max(2, pct)}%"></i></div>
      <div style="font-size:11.5px; color:var(--dim); margin-top:4px;">剩 ${pct}% · 重置 ${esc(v.reset || '–')}</div>
    </div>`;
  }).join('') || '<div class="hint" style="margin:0;">暂无额度数据</div>';

  const ins = o.insight || {};
  $('ovTopic').textContent = ins.topic ? '“' + ins.topic + '”' : '–';
  $('ovDomain').innerHTML = ins.domain ? `<span class="chip dim">${esc(ins.domain)}</span>` : '';
  $('ovInsUpdated').textContent = ins.updated || '–';
  const st = o.stock || {};
  $('ovStock').innerHTML = st.price != null ? st.price + ' ' + pctHtml(st.pct) : '–';

  const epd = (o.serial || []).find(p => p.epd);
  $('ovSerial').innerHTML = epd
    ? `<span style="color:var(--ok);">● ${esc(epd.device)} 在线</span>`
    : '<span style="color:var(--bad);">● 驱动板未识别</span>';
  const hk = o.hotkeys || {};
  $('ovHotkey').textContent = hk.state === 'listening' ? '✓ 监听中' : (hk.state || '未知');
  const cnt = Object.values(hk.counts || {}).reduce((a, b) => a + b, 0);
  $('ovHotkeyCnt').textContent = cnt + ' 次';
  const tt = o.temp_task;
  $('ovTask').innerHTML = tt && tt.enabled
    ? `<span class="chip warn" style="font-size:11.5px;">运行中</span> ${esc(tt.query.slice(0, 18))}`
    : '未启用';

  const names = {weather:'天气', news:'新闻', markets:'行情', glm:'GLM 额度', intraday:'分时'};
  $('ovFresh').innerHTML = Object.entries(names).map(([k, label]) => {
    const a = (o.ages || {})[k] || {};
    const ratio = a.age_min == null ? 1 : Math.max(0, 1 - a.age_min / (a.ttl_min || 30));
    const ageTxt = a.age_min == null ? '无数据' : (a.age_min < 1 ? '<1 分钟' : Math.round(a.age_min) + ' 分钟前');
    return `<div class="fresh">
      <div class="fl"><span>${label}</span><b class="${a.fresh ? '' : 'text-warn'}" style="${a.fresh ? '' : 'color:var(--warn);'}">${ageTxt}</b></div>
      <div class="bar ${a.fresh ? 'ok' : 'warn'}"><i style="width:${Math.max(3, ratio * 100)}%"></i></div>
      <div class="fa">TTL ${a.ttl_min ?? '–'} 分钟 · ${a.fresh ? '切页直接用缓存' : '下次切页将联网刷新'}</div>
    </div>`;
  }).join('');
}

// ── 数据看板 ──────────────────────────────
let DATA = null;
function fetchData(manual) {
  api('/api/data').then(d => {
    DATA = d;
    renderData();
    if (manual) showDot('data', false);
  }).catch(() => {});
}
function renderData() {
  if (!DATA) return;
  const w = DATA.weather || {};
  $('dCity').textContent = w.city || '–';
  $('dWxUpdated').textContent = w.updated ? '更新 ' + w.updated : '';
  $('dTemp').innerHTML = (w.temperature ?? '–') + '<small>°C</small>';
  $('dDesc').textContent = w.description ? wmo(w.code) + ' ' + w.description : '–';
  $('dHL').textContent = w.high != null && w.low != null ? w.high + '° / ' + w.low + '°' : '–';
  $('dFeels').textContent = w.feels != null ? w.feels + '°C' : '–';
  $('dWind').textContent = w.wind != null ? w.wind + ' km/h' : '–';
  $('dHum').textContent = w.humidity != null ? w.humidity + '%' : '–';
  $('dPres').textContent = w.pressure != null ? w.pressure + ' hPa' : '–';
  $('dSun').textContent = (w.sunrise || '–') + ' / ' + (w.sunset || '–');
  $('dMoon').textContent = w.moon || '–';
  $('dDays').innerHTML = (w.days || []).map(d =>
    `<div class="day"><div class="dl">${esc(d.label)}</div><div>${wmo(d.code)}</div>
     <div class="dh">${d.high}°</div><div class="dlo">${d.low}°</div><div class="dp">💧${d.pop}%</div></div>`).join('');

  const m = DATA.markets || {};
  $('dMktUpdated').textContent = m.updated ? '更新 ' + m.updated : '';
  const row = (q, ref) => `<tr>
    <td>${esc(q.name)}${ref ? '' : `<span class="mkt">${esc(q.market || '')}</span>`}</td>
    <td>${q.price ?? '–'}</td>
    <td class="${(q.chg || 0) >= 0 ? 'pct-up' : 'pct-down'}">${q.chg > 0 ? '+' : ''}${q.chg ?? '–'}</td>
    <td>${pctHtml(q.pct)}</td></tr>`;
  const head = '<tr><th>名称</th><th>现价</th><th>涨跌</th><th>幅度</th></tr>';
  $('dWatch').innerHTML = head + ((m.quotes || {}).my_watchlist || []).map(q => row(q, false)).join('');
  $('dRef').innerHTML = head + ((m.quotes || {}).market_ref || []).map(q => row(q, true)).join('');
  const sec = m.sectors || {};
  const chipHtml = (list, cls) => (list || []).slice(0, 6).map(s =>
    `<span class="chip ${cls}" style="font-size:11.5px;">${esc(s.name)} ${pctHtml(s.pct, 2)}</span>`).join('');
  $('dSectors').innerHTML = (sec.hot || sec.fall)
    ? '<div class="topic-chips">' + chipHtml(sec.hot, 'bad') + chipHtml(sec.fall, 'ok') + '</div>' : '';

  const n = DATA.news || {};
  $('dNewsUpdated').textContent = n.updated ? '更新 ' + n.updated : '';
  const colDefs = [
    ['domestic', '🇨🇳 国内', n.domestic_source],
    ['international', '🌍 国际', n.international_source],
    ['ai', '🤖 AI', n.ai_source],
  ];
  $('dNews').innerHTML = colDefs.map(([k, label, src]) => {
    const items = n[k] || [];
    const pinned = n[k + '_pinned'];
    const badge = n[k + '_badge'];
    const list = items.map(t => {
      const isPin = pinned && t === pinned;
      const sum = (n.summaries || {})[t];
      return `<div class="news-item${isPin ? ' pin' : ''}">
        <div class="t">${isPin ? `<span class="badge">${esc(badge || '荐')}</span>` : ''}${esc(t)}</div>
        ${sum ? `<div class="s">${esc(sum)}</div>` : ''}</div>`;
    }).join('');
    return `<div class="news-col"><h4>${label} <span class="src">${esc(src || '')}</span></h4>${list}</div>`;
  }).join('');

  const it = DATA.intraday || {};
  $('dIntraUpdated').textContent = it.updated ? '更新 ' + it.updated : '';
  $('dPrevClose').textContent = it.prev_close ?? '–';
  if ((it.points || []).length) {
    const last = it.points[it.points.length - 1][1];
    $('dIntraLast').textContent = last;
    if (it.prev_close != null) {
      const chg = last - it.prev_close;
      $('dIntraChg').innerHTML = `${chg > 0 ? '+' : ''}${chg.toFixed(2)} ${pctHtml(chg / it.prev_close * 100)}`;
    }
    $('dIntraMeta').textContent = `${it.date || ''} · ${it.points.length} 个分时点 · 高 ${it.high ?? '–'} / 低 ${it.low ?? '–'}`;
  }
  drawCharts();
}

// ── 图表（canvas 手绘，无外部依赖） ────────
function setupCanvas(cv) {
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || cv.parentElement.clientWidth || 600;
  const h = parseInt(cv.getAttribute('height')) || 200;
  cv.width = w * dpr; cv.height = h * dpr;
  const ctx = cv.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return {ctx, w, h};
}
function drawCharts() {
  if (!DATA) return;
  drawHourly();
  drawIntraday();
}
function drawHourly() {
  const cv = $('cvHourly');
  if (!cv || !cv.clientWidth) return;
  const hl = ((DATA.weather || {}).hourly) || {};
  const times = hl.time || [], temps = hl.temp || [], pops = hl.pop || [];
  if (!times.length) return;
  const {ctx, w, h} = setupCanvas(cv);
  const padL = 34, padR = 6, padT = 14, padB = 20;
  const iw = w - padL - padR, ih = h - padT - padB;
  const tMin = Math.min(...temps), tMax = Math.max(...temps);
  const span = Math.max(1, tMax - tMin);
  const x = i => padL + (i / (times.length - 1)) * iw;
  const y = t => padT + (1 - (t - tMin) / span) * ih;
  // 降水概率柱
  ctx.fillStyle = 'rgba(34,211,238,.30)';
  pops.forEach((p, i) => {
    const bw = Math.max(2, iw / times.length - 3);
    const bh = (p / 100) * ih * 0.42;
    ctx.fillRect(x(i) - bw / 2, padT + ih - bh, bw, bh);
  });
  // 温度线
  const grad = ctx.createLinearGradient(0, padT, 0, padT + ih);
  grad.addColorStop(0, '#fbbf24'); grad.addColorStop(1, '#f97316');
  ctx.strokeStyle = grad; ctx.lineWidth = 2; ctx.beginPath();
  temps.forEach((t, i) => i ? ctx.lineTo(x(i), y(t)) : ctx.moveTo(x(i), y(t)));
  ctx.stroke();
  // 温度标注（min/max/当前）
  ctx.fillStyle = '#fbbf24'; ctx.font = '11px system-ui'; ctx.textAlign = 'left';
  ctx.fillText(tMax + '°', x(temps.indexOf(tMax)) + 5, y(tMax) + 4);
  ctx.fillStyle = '#f97316';
  ctx.fillText(tMin + '°', x(temps.indexOf(tMin)) + 5, y(tMin) + 4);
  // 时间轴
  ctx.fillStyle = 'rgba(147,157,181,.75)'; ctx.textAlign = 'center';
  times.forEach((t, i) => {
    if (i % 3 === 0) ctx.fillText(parseInt(t.slice(11, 13)) + '时', x(i), h - 6);
  });
}
function drawIntraday() {
  const cv = $('cvIntraday');
  if (!cv || !cv.clientWidth) return;
  const it = DATA.intraday || {};
  const pts = it.points || [];
  if (!pts.length) return;
  const {ctx, w, h} = setupCanvas(cv);
  const padL = 46, padR = 10, padT = 14, padB = 22;
  const iw = w - padL - padR, ih = h - padT - padB;
  const prices = pts.map(p => p[1]);
  const pc = it.prev_close;
  let lo = Math.min(...prices, pc ?? Infinity), hi = Math.max(...prices, pc ?? -Infinity);
  const pad = (hi - lo) * 0.08 || 0.5; lo -= pad; hi += pad;
  const X = i => padL + (i / (pts.length - 1)) * iw;
  const Y = v => padT + (1 - (v - lo) / (hi - lo)) * ih;
  // 网格与Y轴
  ctx.strokeStyle = 'rgba(148,163,184,.10)'; ctx.fillStyle = 'rgba(147,157,181,.7)';
  ctx.font = '11px system-ui'; ctx.textAlign = 'right'; ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const v = lo + (hi - lo) * g / 4, gy = Y(v);
    ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(w - padR, gy); ctx.stroke();
    ctx.fillText(v.toFixed(1), padL - 6, gy + 4);
  }
  ctx.textAlign = 'center';
  pts.forEach((p, i) => { if (i % 60 === 0) ctx.fillText(p[0], X(i), h - 6); });
  // 昨收虚线
  if (pc != null) {
    ctx.strokeStyle = 'rgba(148,163,184,.55)'; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL, Y(pc)); ctx.lineTo(w - padR, Y(pc)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(148,163,184,.8)'; ctx.textAlign = 'left';
    ctx.fillText('昨收 ' + pc, padL + 4, Y(pc) - 5);
  }
  // 价格填充与折线
  const up = prices[prices.length - 1] >= (pc ?? prices[0]);
  const lineColor = up ? '#f87171' : '#34d399';
  const fill = ctx.createLinearGradient(0, padT, 0, padT + ih);
  fill.addColorStop(0, up ? 'rgba(248,113,113,.28)' : 'rgba(52,211,153,.28)');
  fill.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.beginPath();
  pts.forEach((p, i) => i ? ctx.lineTo(X(i), Y(p[1])) : ctx.moveTo(X(i), Y(p[1])));
  ctx.strokeStyle = lineColor; ctx.lineWidth = 1.8; ctx.stroke();
  ctx.lineTo(X(pts.length - 1), padT + ih); ctx.lineTo(X(0), padT + ih); ctx.closePath();
  ctx.fillStyle = fill; ctx.fill();
  // 最新点
  const last = pts[pts.length - 1];
  ctx.beginPath(); ctx.arc(X(pts.length - 1), Y(last[1]), 3.5, 0, Math.PI * 2);
  ctx.fillStyle = lineColor; ctx.fill();
  ctx.font = 'bold 12px system-ui'; ctx.textAlign = 'right';
  ctx.fillText(last[1].toFixed(2), w - padR - 2, Y(last[1]) - 8);
}
window.addEventListener('resize', () => { if (curPanel === 'data') drawCharts(); });

// ── AI 洞察档案 ───────────────────────────
let ARCHIVES = [];
function fetchInsights() {
  api('/api/insights').then(r => {
    ARCHIVES = r.archive || [];
    $('archCount').textContent = ARCHIVES.length + ' 篇';
    $('archList').innerHTML = ARCHIVES.length
      ? ARCHIVES.map((f, i) => `<button class="arch-item" data-i="${i}" onclick="readArchive(${i})"><span>${esc(f.name.replace(/\.md$/, ''))}</span><span class="mt">${esc((f.mtime || '').slice(5, 16))}</span></button>`).join('')
      : '<div class="hint" style="margin:0;">归档目录暂无笔记</div>';
    const st = r.stock || {};
    $('p5Updated').textContent = st.updated ? '更新 ' + st.updated : '';
    $('p5Price').textContent = st.price ?? '–';
    $('p5Pct').innerHTML = pctHtml(st.pct);
    $('p5Stale').style.display = st.stale ? 'inline-flex' : 'none';
    $('p5Report').textContent = st.text || '暂无页5分析，点下方按钮生成。';
  }).catch(() => {});
}
function readArchive(i) {
  const f = ARCHIVES[i];
  if (!f) return;
  api('/api/insights?file=' + encodeURIComponent(f.name)).then(r => {
    if (!r.ok) { alert(r.message); return; }
    document.querySelectorAll('.arch-item').forEach(b => b.classList.toggle('sel', +b.dataset.i === i));
    const box = $('archContent');
    box.style.display = 'block';
    // 剥掉 Obsidian frontmatter，只留正文
    box.textContent = (r.content || '').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trim();
  });
}

// ── 新闻监控任务 ──────────────────────────
function fetchTask() {
  api('/api/tempnews').then(r => {
    const t = r.task;
    const bands = r.bands || {};
    if (!t) {
      $('mtStatus').innerHTML = '<div class="hint" style="margin:0;">当前没有任务，右侧创建一个。</div>';
      return;
    }
    $('mtStatus').innerHTML = `
      <div class="row" style="margin:0 0 10px;"><span class="chip ${t.enabled ? 'ok' : 'dim'}">${t.enabled ? '● 运行中' : '○ 已停用'}</span>
        <span class="chip dim">${esc(bands[t.band] || t.band || '–')}栏</span>
        <span class="chip dim">角标「${esc(t.badge || '–')}」</span>
        <span class="chip dim">${t.require_price ? '要求价格' : '不限价格'}</span></div>
      <dl class="kv">
        <dt>搜索词</dt><dd style="text-align:left;">${esc(t.query || '–')}</dd>
        <dt>匹配正则</dt><dd style="text-align:left; font-family:Consolas,monospace; color:var(--acc2);">${esc(t.match || '–')}</dd>
      </dl>
      ${t.last_hit ? `<div class="news-item pin" style="margin-top:12px;"><div class="t"><span class="badge">${esc(t.badge || '荐')}</span>${esc(t.last_hit)}</div><div class="s">粘性命中 · 轮出后仍置顶，直到停用或规则收紧</div></div>` : '<div class="hint" style="margin:8px 0 0;">尚无命中；每次新闻刷新（约 10 分钟 TTL）自动搜索一次。</div>'}`;
    // 回填表单
    $('mtQuery').value = t.query || '';
    $('mtMatch').value = t.match || '';
    $('mtBadge').value = t.badge || '价';
    $('mtBand').value = t.band || 'domestic';
    $('mtPrice').checked = t.require_price !== false;
  }).catch(() => {});
}
function saveTask() {
  const task = {
    enabled: true,
    query: $('mtQuery').value.trim(),
    match: $('mtMatch').value.trim(),
    badge: $('mtBadge').value.trim(),
    band: $('mtBand').value,
    require_price: $('mtPrice').checked,
  };
  if (!task.query || !task.match) { alert('搜索词和匹配正则都要填'); return; }
  api('/api/tempnews', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op:'save', task})})
    .then(r => { if (!r.ok) alert(r.message || '保存失败'); fetchTask(); });
}
function stopTask() {
  api('/api/tempnews', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op:'stop'})})
    .then(r => { if (!r.ok) alert(r.message || '停用失败'); fetchTask(); });
}

// ── 启动 ──────────────────────────────────
function tickClock() {
  $('clock').textContent = new Date().toLocaleTimeString('zh-CN', {hour12:false});
}
showPlanInputs();
tickClock();
fetchOverview();
poll();
setInterval(poll, 2000);
setInterval(fetchOverview, 6000);
setInterval(() => { if (curPanel === 'data') fetchData(); }, 60000);
setInterval(tickClock, 1000);
