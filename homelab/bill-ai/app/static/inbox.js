/* 待入账：手机上报的短信/通知，确认后才写进流水 */

const state = {
  status: 'pending',
  meta: { assets: [], categories: [] },
  items: [],
};

const listEl = document.getElementById('inboxList');
const emptyEl = document.getElementById('inboxEmpty');
const subEl = document.getElementById('inboxSub');
const updatedEl = document.getElementById('updatedAt');
const refreshBtn = document.getElementById('refreshBtn');

const TYPE_LABEL = { withdrawal: '支出', deposit: '收入', transfer: '转账' };
const STATUS_LABEL = { pending: '待确认', accepted: '已入账', rejected: '已忽略' };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pad(value) {
  return String(value).padStart(2, '0');
}

function formatTime(seconds) {
  const date = new Date(seconds * 1000);
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function dateOf(seconds) {
  const date = new Date(seconds * 1000);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function timeOf(seconds) {
  const date = new Date(seconds * 1000);
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function selectField(label, name, options, value, extraClass) {
  const wrap = el('label', `field ${extraClass || ''}`.trim());
  wrap.append(el('span', null, label));
  const select = el('select');
  select.dataset.field = name;
  for (const option of options) {
    const node = el('option', null, option.label);
    node.value = option.value;
    if (option.value === value) node.selected = true;
    select.append(node);
  }
  wrap.append(select);
  return wrap;
}

function inputField(label, name, value, options = {}) {
  const wrap = el('label', `field ${options.className || ''}`.trim());
  wrap.append(el('span', null, label));
  const input = el('input');
  input.dataset.field = name;
  input.value = value ?? '';
  if (options.type) input.type = options.type;
  if (options.inputmode) input.inputMode = options.inputmode;
  if (options.placeholder) input.placeholder = options.placeholder;
  wrap.append(input);
  return wrap;
}

function buildCard(item) {
  const parsed = item.parsed || {};
  const card = el('article', `inbox-card${item.status === 'pending' ? '' : ' is-done'}`);

  const head = el('div', 'inbox-card-head');
  const tag = el('span', `source-tag${item.source === 'sms' ? '' : ' is-notification'}`,
    item.source === 'sms' ? '短信' : '通知');
  head.append(tag);
  head.append(el('span', 'inbox-sender', item.sender || '未知来源'));
  if (parsed.confidence) {
    const level = parsed.confidence >= 0.85 ? 'high' : parsed.confidence >= 0.6 ? 'mid' : 'low';
    head.append(el('span', `confidence ${level}`, `${Math.round(parsed.confidence * 100)}%`));
  }
  head.append(el('span', 'inbox-time', formatTime(item.received_at)));
  card.append(head);

  const raw = el('p', 'inbox-raw', item.raw_text);
  card.append(raw);

  if (item.status !== 'pending') {
    const foot = el('div', 'inbox-foot');
    const typeLabel = TYPE_LABEL[parsed.type] || '支出';
    const money = parsed.amount ? `¥${parsed.amount}` : '未识别金额';
    foot.append(el('span', 'inbox-state', ''));
    const stateText = foot.lastChild;
    stateText.append(el('strong', null, money));
    stateText.append(document.createTextNode(` · ${typeLabel} · ${parsed.account || '未指定账户'}`));
    if (parsed.merchant) stateText.append(document.createTextNode(` · ${parsed.merchant}`));
    stateText.append(document.createTextNode(` · ${STATUS_LABEL[item.status] || item.status}`));
    foot.append(el('span', 'spacer'));
    if (item.txn_id) {
      const link = el('a', 'btn secondary sm', '查看流水');
      link.href = '/transactions';
      foot.append(link);
    }
    card.append(foot);
    return card;
  }

  const toggle = el('button', 'inbox-raw-btn', '展开原文');
  toggle.type = 'button';
  toggle.addEventListener('click', () => {
    const open = raw.classList.toggle('is-open');
    toggle.textContent = open ? '收起原文' : '展开原文';
  });
  card.append(toggle);

  const fields = el('div', 'inbox-fields');
  const allAssets = state.meta.assets.map((a) => ({ value: a.name, label: a.name }));
  const allCategories = state.meta.categories.map((c) => ({ value: c.name, label: c.name }));
  // 解析不出账户/分类时给一个空选项，避免默认落到列表第一项造成错账
  const assetOptions = parsed.account
    ? allAssets
    : [{ value: '', label: '请选择账户' }, ...allAssets];
  const categoryOptions = parsed.category
    ? allCategories
    : [{ value: '', label: '不分类' }, ...allCategories];
  const typeOptions = Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }));

  fields.append(inputField('金额', 'amount', parsed.amount || '', {
    className: 'field-amount', inputmode: 'decimal', placeholder: '0.00',
  }));
  fields.append(selectField('类型', 'type', typeOptions, parsed.type || 'withdrawal'));
  fields.append(selectField('账户', 'account', assetOptions, parsed.account || ''));
  fields.append(selectField('分类', 'category', categoryOptions, parsed.category || ''));
  fields.append(inputField('商户', 'merchant', parsed.merchant || '', { className: 'field-merchant' }));
  fields.append(inputField('日期', 'date', parsed.date || dateOf(item.received_at), { type: 'date' }));
  fields.append(inputField('时间', 'time', parsed.time || timeOf(item.received_at), { type: 'time' }));

  const toWrap = selectField('对方账户', 'to_account', assetOptions, parsed.to_account || '');
  toWrap.hidden = (parsed.type || 'withdrawal') !== 'transfer';
  fields.append(toWrap);
  card.append(fields);

  const typeSelect = fields.querySelector('[data-field="type"]');
  typeSelect.addEventListener('change', () => {
    toWrap.hidden = typeSelect.value !== 'transfer';
  });

  const foot = el('div', 'inbox-foot');
  const hint = el('span', 'inbox-hint', item.note || (parsed.amount ? '确认后写入流水' : '没认出金额，先补上再确认'));
  foot.append(hint);
  foot.append(el('span', 'spacer'));

  const rejectBtn = el('button', 'btn secondary sm', '忽略');
  rejectBtn.type = 'button';
  rejectBtn.addEventListener('click', () => reject(item, card, rejectBtn, hint));

  const acceptBtn = el('button', 'btn primary sm', '确认入账');
  acceptBtn.type = 'button';
  acceptBtn.addEventListener('click', () => accept(item, card, fields, acceptBtn, hint));

  foot.append(rejectBtn, acceptBtn);
  card.append(foot);
  return card;
}

function collect(card) {
  const payload = {};
  for (const node of card.querySelectorAll('[data-field]')) {
    const value = node.value.trim();
    if (!value) continue;
    payload[node.dataset.field] = value;
  }
  return payload;
}

async function accept(item, card, fields, button, hint) {
  const payload = collect(fields);
  if (!payload.amount) {
    hint.textContent = '先填金额';
    hint.classList.add('is-error');
    return;
  }
  if (!payload.account) {
    hint.textContent = '先选择账户';
    hint.classList.add('is-error');
    return;
  }
  button.disabled = true;
  button.classList.add('is-loading');
  hint.classList.remove('is-error');
  hint.textContent = '正在写入…';
  try {
    const response = await fetch(`/api/inbox/${item.id}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || '入账失败');
    await load();
  } catch (error) {
    hint.textContent = error.message;
    hint.classList.add('is-error');
    button.disabled = false;
    button.classList.remove('is-loading');
  }
}

async function reject(item, card, button, hint) {
  button.disabled = true;
  hint.classList.remove('is-error');
  hint.textContent = '正在忽略…';
  try {
    const response = await fetch(`/api/inbox/${item.id}/reject`, { method: 'POST' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || '操作失败');
    await load();
  } catch (error) {
    hint.textContent = error.message;
    hint.classList.add('is-error');
    button.disabled = false;
  }
}

function render(pending) {
  listEl.textContent = '';
  emptyEl.hidden = state.items.length > 0;
  for (const item of state.items) {
    listEl.append(buildCard(item));
  }

  if (state.status === 'pending') {
    subEl.textContent = pending
      ? `还有 ${pending} 条等待确认`
      : '全部处理完了';
  } else {
    subEl.textContent = `${STATUS_LABEL[state.status]} · 最近 ${state.items.length} 条`;
  }
  updatedEl.textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`;
}

async function load() {
  subEl.textContent = '正在读取…';
  try {
    const response = await fetch(`/api/inbox?status=${state.status}&limit=100`, { cache: 'no-store' });
    if (!response.ok) throw new Error('接口返回异常');
    const data = await response.json();
    state.meta = data.meta;
    state.items = data.items;
    render(data.pending);
  } catch (error) {
    subEl.textContent = `读取失败：${error.message}`;
  }
}

document.querySelectorAll('.inbox-tabs .chip').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.inbox-tabs .chip').forEach((node) => {
      node.classList.toggle('is-on', node === button);
      node.setAttribute('aria-selected', node === button ? 'true' : 'false');
    });
    state.status = button.dataset.status;
    load();
  });
});

refreshBtn.addEventListener('click', load);
load();
