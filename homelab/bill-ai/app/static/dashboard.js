const state = {
  month: "",
  data: null,
  currentMonth: "",
};

const $ = (id) => document.getElementById(id);
const money = (value) => {
  const number = Number(value);
  const abs = Math.abs(number).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${number < 0 ? "−" : ""}¥${abs}`;
};
const compact = (value) => {
  const number = Number(value);
  if (number >= 10000) return (number / 10000).toFixed(number >= 100000 ? 0 : 1) + "万";
  if (number >= 1000) return Math.round(number / 100) / 10 + "k";
  return String(Math.round(number));
};
const monthLabel = (month) => {
  const [year, m] = month.split("-");
  return `${year} 年 ${Number(m)} 月`;
};

function setText(id, text) {
  const node = $(id);
  if (node) node.textContent = text;
}

function showEmpty(node, text) {
  node.innerHTML = "";
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = text;
  node.appendChild(p);
}

async function load(month) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  try {
    const response = await fetch(`/api/overview${query}`, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    state.month = state.data.month;
    const now = new Date();
    state.currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    render();
  } catch (error) {
    setText("toolbarNote", "读取失败，稍后再试");
    showEmpty($("kpis"), "读不到数据");
    showEmpty($("cats"), "读不到数据");
    showEmpty($("recent"), "读不到数据");
    $("chart").innerHTML = '<p class="empty">读不到数据</p>';
  }
}

function renderAccounts() {
  const box = $("accounts");
  box.innerHTML = "";
  const accounts = (state.data.accounts || []).filter((item) => Number(item.balance) !== 0);
  if (!accounts.length) {
    showEmpty(box, "还没有资产账户");
    return;
  }
  for (const account of accounts) {
    const cell = document.createElement("div");
    cell.className = "account";
    const name = document.createElement("span");
    name.className = "account-name";
    name.textContent = account.name;
    const balance = document.createElement("span");
    balance.className = "account-balance";
    balance.textContent = money(account.balance);
    cell.append(name, balance);
    box.appendChild(cell);
  }
}

function renderKpis() {
  const stats = state.data.month_stats;
  const box = $("kpis");
  box.innerHTML = "";
  const items = [
    { label: "本月支出", value: money(stats.out), note: `${stats.count_out} 笔` },
    { label: "本月收入", value: money(stats.in), note: "含退款与补贴" },
    {
      label: "本月结余",
      value: money(stats.net),
      note: Number(stats.net) >= 0 ? "收大于支" : "支大于收",
      positive: Number(stats.net) >= 0,
    },
    { label: "日均支出", value: money(stats.daily_avg), note: `活跃 ${stats.active_days} 天` },
  ];
  for (const item of items) {
    const cell = document.createElement("div");
    cell.className = "kpi";
    const label = document.createElement("p");
    label.className = "kpi-label";
    label.textContent = item.label;
    const value = document.createElement("p");
    value.className = "kpi-value" + (item.positive ? " is-positive" : "");
    value.textContent = item.value;
    const note = document.createElement("p");
    note.className = "kpi-note";
    note.textContent = item.note;
    cell.append(label, value, note);
    box.appendChild(cell);
  }
}

function renderChart() {
  const months = state.data.months || [];
  const chart = $("chart");
  chart.innerHTML = "";
  if (!months.length) {
    showEmpty(chart, "还没有足够的记录");
    return;
  }

  const max = Math.max(
    1,
    ...months.map((m) => Math.max(Number(m.in), Number(m.out))),
  );
  const ticks = [max, max * 0.5, 0];

  const plot = document.createElement("div");
  plot.className = "chart-plot";

  ticks.forEach((tick, index) => {
    const line = document.createElement("div");
    line.className = "chart-grid" + (index === ticks.length - 1 ? " is-base" : "");
    line.style.bottom = `${(1 - index / (ticks.length - 1)) * 100}%`;
    plot.appendChild(line);

    const label = document.createElement("span");
    label.className = "chart-tick" + (index === 0 ? " is-top" : index === ticks.length - 1 ? " is-base" : "");
    label.style.bottom = `${(1 - index / (ticks.length - 1)) * 100}%`;
    label.textContent = compact(tick);
    plot.appendChild(label);
  });

  const cols = document.createElement("div");
  cols.className = "chart-cols";

  for (const month of months) {
    const out = Number(month.out);
    const incom = Number(month.in);

    const col = document.createElement("button");
    col.type = "button";
    col.className = "chart-col";
    col.dataset.month = month.month;
    col.title = `${month.month} · 支出 ${money(out)} · 收入 ${money(incom)}`;
    col.setAttribute(
      "aria-label",
      `${monthLabel(month.month)} 支出 ${money(out)}，收入 ${money(incom)}，查看流水明细`,
    );

    const bars = document.createElement("div");
    bars.className = "chart-bars";
    for (const [kind, value] of [["out", out], ["in", incom]]) {
      const bar = document.createElement("i");
      bar.className = `chart-bar ${kind}` + (value > 0 ? "" : " is-empty");
      bar.style.height = `${Math.max((value / max) * 100, value > 0 ? 1.5 : 0.5)}%`;
      bars.appendChild(bar);
    }
    col.appendChild(bars);

    const label = document.createElement("span");
    label.className = "chart-col-label";
    label.textContent = `${Number(month.month.slice(5))}月`;
    col.appendChild(label);

    cols.appendChild(col);
  }

  plot.appendChild(cols);
  chart.appendChild(plot);

  cols.addEventListener("click", (event) => {
    const button = event.target.closest(".chart-col");
    if (button) openSheet(button.dataset.month, button);
  });
}

function renderCategories() {
  const box = $("cats");
  const categories = state.data.by_category || [];
  box.innerHTML = "";
  if (!categories.length) {
    showEmpty(box, "这个月还没有支出记录");
    setText("catsMeta", "");
    return;
  }

  const top = categories.slice(0, 7);
  const rest = categories.slice(7);
  if (rest.length) {
    const amount = rest.reduce((sum, item) => sum + Number(item.amount), 0);
    top.push({ name: "其他", amount: amount.toFixed(2) });
  }
  const total = top.reduce((sum, item) => sum + Number(item.amount), 0) || 1;
  const max = Math.max(...top.map((item) => Number(item.amount)), 1);
  setText("catsMeta", `共 ${categories.length} 类`);

  for (const item of top) {
    const amount = Number(item.amount);
    const row = document.createElement("div");
    row.className = "cat-row";

    const name = document.createElement("span");
    name.className = "cat-name";
    name.textContent = item.name;
    name.title = item.name;

    const track = document.createElement("div");
    track.className = "cat-track";
    const fill = document.createElement("div");
    fill.className = "cat-fill";
    fill.style.width = `${Math.max((amount / max) * 100, 2)}%`;
    track.appendChild(fill);

    const amountNode = document.createElement("span");
    amountNode.className = "cat-amount";
    amountNode.textContent = money(amount);
    const pct = document.createElement("em");
    const ratio = amount / total;
    pct.textContent = ratio > 0 && ratio < 0.005 ? "<1%" : `${Math.round(ratio * 100)}%`;
    amountNode.appendChild(pct);

    row.append(name, track, amountNode);
    box.appendChild(row);
  }
}

function renderRecent() {
  const list = $("recent");
  const items = state.data.recent || [];
  list.innerHTML = "";
  if (!items.length) {
    showEmpty(list, "这个月还没有交易");
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.className = "tx";

    const date = document.createElement("span");
    date.className = "tx-date";
    date.textContent = item.date.slice(5).replace("-", "/");

    const main = document.createElement("div");
    main.className = "tx-main";
    const desc = document.createElement("span");
    desc.className = "tx-desc";
    desc.textContent = item.description;
    desc.title = item.description;
    const meta = document.createElement("span");
    meta.className = "tx-meta";
    meta.textContent =
      item.type === "transfer"
        ? `${item.account} → ${item.to_account}`
        : [item.account, item.category].filter(Boolean).join(" · ");
    main.append(desc, meta);

    li.append(date, main, amountNode(item));
    list.appendChild(li);
  }
}

function amountNode(item) {
  const node = document.createElement("span");
  if (item.type === "transfer") {
    node.className = "tx-amount move";
    node.textContent = `⇄ ${money(item.amount)}`;
    return node;
  }
  const income = item.type === "income";
  node.className = "tx-amount" + (income ? " in" : "");
  node.textContent = `${income ? "+" : "−"}${money(item.amount)}`;
  return node;
}

function render() {
  const data = state.data;
  const visibleAccounts = data.accounts.filter((item) => Number(item.balance) !== 0);
  setText("networth", money(data.net_worth));
  setText(
    "heroSub",
    `${visibleAccounts.length} 个账户 · 数据截至 ${data.range.end}`,
  );
  setText("monthLabel", monthLabel(data.month));
  setText(
    "toolbarNote",
    `${data.month_stats.count_out} 笔支出 · 活跃 ${data.month_stats.active_days} 天`,
  );
  setText("updatedAt", `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`);

  const next = $("nextMonth");
  next.disabled = data.month >= state.currentMonth;

  renderAccounts();
  renderKpis();
  renderChart();
  renderCategories();
  renderRecent();
}

function shiftMonth(delta) {
  const [year, month] = state.month.split("-").map(Number);
  const index = year * 12 + (month - 1) + delta;
  const next = `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
  if (next > state.currentMonth) return;
  state.month = next;
  load(next);
}

$("prevMonth").addEventListener("click", () => shiftMonth(-1));
$("nextMonth").addEventListener("click", () => shiftMonth(1));

/* ---------- 自定义模块 ---------- */

const CARDS_KEY = "billai.dash.cards";
const cards = { kpis: true, trend: true, cats: true, recent: true };

try {
  Object.assign(cards, JSON.parse(localStorage.getItem(CARDS_KEY) || "{}"));
} catch (error) {
  /* 忽略损坏的本地配置 */
}

function applyCards() {
  for (const [name, visible] of Object.entries(cards)) {
    const node = document.querySelector(`[data-card="${name}"]`);
    if (node) node.hidden = !visible;
    const input = document.querySelector(`[data-toggle="${name}"]`);
    if (input) input.checked = visible;
  }
}

function placePop() {
  const pop = $("customPop");
  const button = $("customizeBtn");
  const rect = button.getBoundingClientRect();
  const below = rect.bottom + 8;
  const above = rect.top - pop.offsetHeight - 8;
  const fits = below + pop.offsetHeight <= window.innerHeight - 8;
  pop.style.top = `${Math.max(8, fits ? below : above)}px`;
  pop.style.left = `${Math.max(12, rect.right - pop.offsetWidth)}px`;
}

const customizeBtn = $("customizeBtn");
customizeBtn.addEventListener("click", () => {
  const pop = $("customPop");
  const willOpen = pop.hidden;
  pop.hidden = !willOpen;
  customizeBtn.setAttribute("aria-expanded", String(willOpen));
  if (willOpen) placePop();
});

document.addEventListener("click", (event) => {
  const pop = $("customPop");
  if (pop.hidden) return;
  if (pop.contains(event.target) || customizeBtn.contains(event.target)) return;
  pop.hidden = true;
  customizeBtn.setAttribute("aria-expanded", "false");
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  const sheet = $("txSheet");
  if (sheet && !sheet.hidden) {
    closeSheet();
    return;
  }
  const pop = $("customPop");
  if (!pop.hidden) {
    pop.hidden = true;
    customizeBtn.setAttribute("aria-expanded", "false");
    customizeBtn.focus();
  }
});

document.querySelectorAll("[data-toggle]").forEach((input) => {
  input.addEventListener("change", () => {
    cards[input.dataset.toggle] = input.checked;
    localStorage.setItem(CARDS_KEY, JSON.stringify(cards));
    applyCards();
  });
});

/* ---------- 月度流水明细 ---------- */

const sheetState = { data: null, filter: "all", account: "", category: "" };
let sheetTrigger = null;

function markActiveMonth(month) {
  document.querySelectorAll(".chart-col").forEach((button) => {
    const active = Boolean(month) && button.dataset.month === month;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function sheetMessage(text) {
  const list = $("sheetList");
  list.innerHTML = "";
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = text;
  list.appendChild(li);
}

function renderSheetStats() {
  const stats = sheetState.data.stats;
  const box = $("sheetStats");
  box.innerHTML = "";
  const rows = [
    { label: `支出 · ${stats.count_out} 笔`, value: money(stats.out) },
    { label: `收入 · ${stats.count_in} 笔`, value: money(stats.in) },
    { label: "结余", value: money(stats.net), positive: Number(stats.net) >= 0 },
  ];
  for (const row of rows) {
    const cell = document.createElement("div");
    cell.className = "sheet-stat";
    const label = document.createElement("span");
    label.textContent = row.label;
    const value = document.createElement("strong");
    value.textContent = row.value;
    if (row.positive) value.classList.add("is-positive");
    cell.append(label, value);
    box.appendChild(cell);
  }
}

function fillSheetSelect(node, placeholder, entries) {
  node.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  node.appendChild(first);
  for (const [id, name] of entries) {
    const option = document.createElement("option");
    option.value = String(id);
    option.textContent = name;
    node.appendChild(option);
  }
  node.value = "";
}

function buildSheetFilters() {
  const items = sheetState.data?.items || [];
  const accounts = new Map();
  const categories = new Map();
  for (const item of items) {
    if (item.account_id) accounts.set(item.account_id, item.account);
    if (item.category_id) categories.set(item.category_id, item.category);
  }
  fillSheetSelect($("sheetAccount"), "全部账户", accounts);
  fillSheetSelect($("sheetCategory"), "全部分类", categories);
}

function renderSheetList() {
  const list = $("sheetList");
  const items = (sheetState.data.items || []).filter((item) => {
    if (sheetState.filter === "out" && item.type !== "expense") return false;
    if (sheetState.filter === "in" && item.type !== "income") return false;
    if (sheetState.account && String(item.account_id) !== sheetState.account) return false;
    if (sheetState.category && String(item.category_id) !== sheetState.category) return false;
    return true;
  });
  list.innerHTML = "";
  list.scrollTop = 0;
  const filtered = Boolean(sheetState.account || sheetState.category || sheetState.filter !== "all");
  $("sheetEmpty").hidden = items.length > 0;
  $("sheetEmpty").textContent = filtered ? "没有符合条件的记录" : "这个月没有记录";
  if (!items.length) return;

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "tx";

    const date = document.createElement("span");
    date.className = "tx-date";
    date.textContent = item.date.slice(5).replace("-", "/");

    const main = document.createElement("div");
    main.className = "tx-main";
    const desc = document.createElement("span");
    desc.className = "tx-desc";
    desc.textContent = item.description;
    desc.title = item.description;
    const meta = document.createElement("span");
    meta.className = "tx-meta";
    meta.textContent =
      item.type === "transfer"
        ? [item.time, `${item.account} → ${item.to_account}`].filter(Boolean).join(" · ")
        : [item.time, item.account, item.category].filter(Boolean).join(" · ");
    main.append(desc, meta);

    li.append(date, main, amountNode(item));
    list.appendChild(li);
  }
}

function setSheetFilter(filter) {
  sheetState.filter = filter;
  document.querySelectorAll(".chip[data-filter]").forEach((chip) => {
    const on = chip.dataset.filter === filter;
    chip.classList.toggle("is-on", on);
    chip.setAttribute("aria-pressed", String(on));
  });
  if (sheetState.data) renderSheetList();
}

async function openSheet(month, trigger) {
  sheetTrigger = trigger || null;
  sheetState.data = null;
  sheetState.account = "";
  sheetState.category = "";
  $("sheetAccount").innerHTML = '<option value="">全部账户</option>';
  $("sheetCategory").innerHTML = '<option value="">全部分类</option>';
  setSheetFilter("all");
  $("sheetTitle").textContent = monthLabel(month);
  $("sheetStats").innerHTML = "";
  $("sheetEmpty").hidden = true;
  const sheet = $("txSheet");
  sheet.hidden = false;
  void sheet.offsetWidth;
  sheet.classList.add("is-open");
  document.body.classList.add("is-locked");
  markActiveMonth(month);
  sheetMessage("正在读取…");
  $("sheetClose").focus();

  try {
    const response = await fetch(`/api/month-transactions?month=${encodeURIComponent(month)}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    sheetState.data = await response.json();
    buildSheetFilters();
    renderSheetStats();
    renderSheetList();
  } catch (error) {
    sheetMessage("读取失败，稍后再试");
  }
}

function closeSheet() {
  const sheet = $("txSheet");
  if (sheet.hidden || !sheet.classList.contains("is-open")) return;
  sheet.classList.remove("is-open");
  document.body.classList.remove("is-locked");
  sheetState.data = null;
  markActiveMonth("");
  if (sheetTrigger && document.contains(sheetTrigger)) sheetTrigger.focus();
  sheetTrigger = null;
  window.setTimeout(() => {
    if (!sheet.classList.contains("is-open")) sheet.hidden = true;
  }, 280);
}

$("sheetClose").addEventListener("click", closeSheet);
$("sheetBackdrop").addEventListener("click", closeSheet);
document.querySelectorAll(".chip[data-filter]").forEach((chip) => {
  chip.addEventListener("click", () => setSheetFilter(chip.dataset.filter));
});
$("sheetAccount").addEventListener("change", (event) => {
  sheetState.account = event.target.value;
  renderSheetList();
});
$("sheetCategory").addEventListener("change", (event) => {
  sheetState.category = event.target.value;
  renderSheetList();
});

applyCards();
load("");
