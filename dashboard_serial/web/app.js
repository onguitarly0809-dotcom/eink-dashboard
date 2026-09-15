async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}
function run(action, force) {
  api('/api/action', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, force: !!force})})
    .then(r => { if (!r.ok) alert(r.message || '启动失败'); poll(); });
}
let curPage = 1;
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

function showPlanInputs() {
  const n = parseInt(document.getElementById('planCount').value);
  let h = '';
  for (let i = 1; i <= n; i++) {
    h += '<div class="item"><span>计划' + i + '</span><input id="p' + i + '" maxlength="40" placeholder="输入计划内容"></div>';
  }
  document.getElementById('planInputs').innerHTML = h;
}
function submitPlans() {
  const n = parseInt(document.getElementById('planCount').value);
  const items = [];
  for (let i = 1; i <= n; i++) {
    const v = document.getElementById('p' + i).value.trim();
    if (v) items.push(v);
  }
  if (!items.length) { alert('请至少输入一个计划'); return; }
  api('/api/plans', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items})})
    .then(r => { if (!r.ok) alert(r.message || '提交失败'); poll(); });
}
function showPreview() {
  const img = document.getElementById('preview');
  img.src = '/preview.png?t=' + Date.now();
  img.style.display = 'block';
}

function showPage4(p) {
  const topic = document.getElementById('page4Topic');
  const meta = document.getElementById('page4Meta');
  const report = document.getElementById('page4Report');
  if (!p || !p.available) {
    topic.textContent = p && p.message ? p.message : '暂无页4报告';
    meta.innerHTML = '';
    document.getElementById('page4Recent').textContent = '';
    report.style.display = 'none';
    report.textContent = '';
    return;
  }
  topic.textContent = '今日主题：' + (p.topic || '未命名') + (p.domain ? '（' + p.domain + '）' : '');
  const chips = [];
  chips.push(p.stale ? '历史报告' : '当前报告');
  if (p.history_count) chips.push('已去重 ' + p.history_count + ' 个主题');
  if (p.updated) chips.push('更新 ' + p.updated);
  if (p.model) chips.push(p.model);
  if (p.age_minutes !== null && p.age_minutes !== undefined) chips.push('已生成 ' + p.age_minutes + ' 分钟');
  if (p.prompt_tokens || p.completion_tokens) chips.push('Tokens ' + (p.prompt_tokens || 0) + '/' + (p.completion_tokens || 0));
  meta.textContent = '';
  chips.forEach(x => {
    const chip = document.createElement('span');
    if (x === '历史报告') chip.className = 'bad';
    chip.textContent = x;
    meta.appendChild(chip);
  });
  const recent = document.getElementById('page4Recent');
  recent.textContent = (p.recent_topics || []).length ? '近期主题：' + p.recent_topics.join(' · ') : '';
  report.textContent = p.text || '';
  report.style.display = 'block';
}
function poll() {
  api('/api/status').then(s => {
    curPage = s.page || curPage;
    const el = document.getElementById('status');
    if (s.running) {
      el.textContent = '运行中：' + s.label;
      el.className = 'busy';
    } else if (s.ok === null) {
      el.textContent = '空闲';
      el.className = '';
    } else if (s.ok) {
      el.textContent = '完成';
      el.className = 'ok';
      if (['preview', 'preview_page4', 'page4', 'analysis'].includes(s.last_action)) showPreview();
    } else {
      el.textContent = '失败，请查看日志';
      el.className = 'bad';
    }
    document.querySelectorAll('.page-btn').forEach(b => {
      b.classList.toggle('active', +b.dataset.page === curPage);
    });
    showPage4(s.page4);
    document.querySelectorAll('button').forEach(b => { b.disabled = !!s.running; });
    const h = s.hotkeys || {};
    document.getElementById('hotkeyStatus').textContent =
      (h.state || '未知') + ' · 已注册 ' + ((h.registered_keys || []).join('/') || '无');
    const logEl = document.getElementById('log');
    logEl.textContent = (s.log || []).join('\n');
    logEl.scrollTop = logEl.scrollHeight;
  });
}
showPlanInputs();
poll();
setInterval(poll, 2000);
