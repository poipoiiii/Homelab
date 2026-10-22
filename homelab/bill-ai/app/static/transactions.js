const state = {
  meta: { accounts: [], categories: [] },
  filters: { month: "", account: "", category: "", type: "", q: "" },
  items: [],
  total: 0,
  offset: 0,
  limit: 100,
  editing: null,
  loading: false,
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
const TYPE_LABEL = { expense: "支出", income: "收入", transfer: "转账" };
const WEEKDAY = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function activeFilterCount() {
  let count = 0;
  if (state.filters.month && state.filters.month !== currentMonth()) count += 1;
  if (state.filters.account) count += 1;
  if (state.filters.category) count += 1;
  if (state.filters.type) count += 1;
  if (state.filters.q) count += 1;
  return count;
}

function syncFilterToggle() {
  const count = activeFilterCount();
  $("filterToggle").textContent = count ? `筛选 · ${count}` : "筛选";
  $("filterToggle").classList.toggle("is-filtered", count > 0);
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function fillSelect(node, items, placeholder, selected) {
  node.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  node.appendChild(first);
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    if (String(item.id) === String(selected ?? "")) option.selected = true;
    node.appendChild(option);
  }
}

async function loadMeta() {
  state.meta = await api("/api/meta");
  fillSelect($("accountFilter"), state.meta.assets, "全部账户", state.filters.account);
  fillSelect($("categoryFilter"), state.meta.categories, "全部分类", state.filters.category);
  fillSelect($("fAccount"), state.meta.assets, "选择账户", "");
  fillSelect($("fToAccount"), state.meta.assets, "选择账户", "");
  fillSelect($("fCategory"), state.meta.categories, "不分类", "");
}

function queryString(offset) {
  const params = new URLSearchParams();
  const { month, account, category, type, q } = state.filters;
  if (month) params.set("month", month);
  if (account) params.set("account_id", account);
  if (category) params.set("category_id", category);
  if (type) params.set("type", type);
  if (q) params.set("q", q);
  params.set("limit", String(state.limit));
  params.set("offset", String(offset));
  return params.toString();
}

async function load(reset = true) {
  if (state.loading) return;
  state.loading = true;
  $("moreBtn").disabled = true;
  try {
    if (reset) state.offset = 0;
    const data = await api(`/api/transactions?${queryString(state.offset)}`);
    state.items = reset ? data.items : state.items.concat(data.items);
    state.total = data.total;
    state.sums = data.sums;
    state.offset = state.items.length;
    render(data);
  } catch (error) {
    $("txGroups").innerHTML = `<p class="empty-state">${error.message}</p>`;
    $("txSub").textContent = "读取失败";
  } finally {
    state.loading = false;
    $("moreBtn").disabled = false;
  }
}

function render(data) {
  const month = state.filters.month;
  $("txTitle").textContent = month ? `${month.slice(0, 4)} 年 ${Number(month.slice(5))} 月` : "全部记录";

  const parts = [`共 ${data.total} 笔`];
  if (state.filters.month) parts.push(`${Number(month.slice(5))} 月`);
  if (state.filters.type) parts.push(TYPE_LABEL[state.filters.type]);
  $("txSub").textContent = parts.join(" · ");
  syncFilterToggle();

  $("txSummary").innerHTML = [
    `<span>支出 <strong>${money(data.sums.out)}</strong></span>`,
    `<span>收入 <strong>${money(data.sums.in)}</strong></span>`,
    `<span>结余 <strong>${money(Number(data.sums.in) - Number(data.sums.out))}</strong></span>`,
  ].join("");

  const box = $("txGroups");
  box.innerHTML = "";
  if (!state.items.length) {
    box.innerHTML = '<p class="empty-state">没有符合条件的流水</p>';
    $("moreBtn").hidden = true;
    return;
  }

  const groups = new Map();
  for (const item of state.items) {
    if (!groups.has(item.date)) groups.set(item.date, []);
    groups.get(item.date).push(item);
  }

  for (const [day, items] of groups) {
    const head = document.createElement("div");
    head.className = "day-head";
    const date = document.createElement("span");
    date.className = "day-date";
    const parsed = new Date(`${day}T00:00:00`);
    date.textContent = `${day.slice(5).replace("-", "月")}日 ${WEEKDAY[parsed.getDay()] || ""}`;
    const sums = document.createElement("span");
    sums.className = "day-sums";
    const out = items.filter((i) => i.type === "expense").reduce((s, i) => s + Number(i.amount), 0);
    const inc = items.filter((i) => i.type === "income").reduce((s, i) => s + Number(i.amount), 0);
    sums.textContent = [out ? `支出 ${money(out)}` : "", inc ? `收入 ${money(inc)}` : ""]
      .filter(Boolean)
      .join(" · ");
    head.append(date, sums);
    box.appendChild(head);

    for (const item of items) {
      box.appendChild(renderRow(item));
    }
  }

  $("moreBtn").hidden = state.items.length >= state.total;
}

function renderRow(item) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = "tx-row";
  row.dataset.id = item.id;

  const time = document.createElement("span");
  time.className = "tx-time";
  time.textContent = item.time || "";

  const main = document.createElement("div");
  main.className = "tx-main";
  const name = document.createElement("div");
  name.className = "tx-name";
  const title = document.createElement("span");
  title.textContent = item.merchant || item.description || "未命名";
  name.appendChild(title);
  const tag = document.createElement("span");
  tag.className = "tx-tag";
  tag.textContent = item.type === "transfer" ? "转账" : item.category || "未分类";
  name.appendChild(tag);
  const meta = document.createElement("span");
  meta.className = "tx-meta";
  meta.textContent =
    item.type === "transfer"
      ? `${item.account} → ${item.to_account}`
      : [item.account, item.description].filter(Boolean).join(" · ");
  main.append(name, meta);

  const amount = document.createElement("span");
  const isIncome = item.type === "income";
  amount.className = "tx-amount" + (isIncome ? " in" : item.type === "transfer" ? " move" : "");
  amount.textContent = item.type === "transfer" ? money(item.amount) : `${isIncome ? "+" : "−"}${money(item.amount)}`;

  row.append(time, main, amount);
  row.addEventListener("click", () => openEditor(item));
  return row;
}

/* ---------------- editor ---------------- */

function setEditorType(type) {
  document.querySelectorAll("[data-etype]").forEach((chip) => {
    chip.classList.toggle("is-on", chip.dataset.etype === type);
  });
  $("toAccountField").hidden = type !== "transfer";
  $("categoryField").hidden = type === "transfer";
  $("accountLabel").textContent = type === "income" ? "收款账户" : "付款账户";
}

function openEditor(item) {
  state.editing = item || null;
  const sheet = $("editor");
  sheet.hidden = false;
  void sheet.offsetWidth;
  sheet.classList.add("is-open");
  document.body.classList.add("is-locked");
  $("editorTitle").textContent = item ? "编辑流水" : "记一笔";
  $("deleteBtn").hidden = !item;
  $("editorError").hidden = true;

  const type = item?.type || "expense";
  setEditorType(type);
  $("fAmount").value = item ? item.amount : "";
  $("fDate").value = item ? item.date : today();
  $("fTime").value = item ? item.time : "";
  $("fAccount").value = item ? String(item.account_id) : String(state.meta.assets[0]?.id ?? "");
  $("fToAccount").value = item?.to_account_id ? String(item.to_account_id) : "";
  $("fCategory").value = item?.category_id ? String(item.category_id) : "";
  $("fMerchant").value = item ? item.merchant : "";
  $("fNote").value = item ? item.note : "";

  $("fAmount").focus();
}

function closeEditor() {
  const sheet = $("editor");
  if (sheet.hidden || !sheet.classList.contains("is-open")) return;
  sheet.classList.remove("is-open");
  document.body.classList.remove("is-locked");
  state.editing = null;
  window.setTimeout(() => {
    if (!sheet.classList.contains("is-open")) sheet.hidden = true;
  }, 280);
}

function formType() {
  return document.querySelector("[data-etype].is-on")?.dataset.etype || "expense";
}

async function save() {
  $("editorError").hidden = true;
  const type = formType();
  const amount = $("fAmount").value.replace(/[^\d.]/g, "");
  if (!amount || Number(amount) <= 0) {
    return showError("请填写大于 0 的金额");
  }
  const payload = {
    date: $("fDate").value || today(),
    time: $("fTime").value || "12:00",
    type,
    amount,
    account_id: Number($("fAccount").value),
    merchant: $("fMerchant").value.trim(),
    note: $("fNote").value.trim(),
  };
  if (!payload.account_id) return showError("请选择账户");
  if (type === "transfer") {
    payload.to_account_id = Number($("fToAccount").value) || null;
  } else {
    payload.category_id = Number($("fCategory").value) || null;
  }

  $("saveBtn").disabled = true;
  try {
    if (state.editing) {
      await api(`/api/transactions/${state.editing.id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/transactions", { method: "POST", body: JSON.stringify(payload) });
    }
    closeEditor();
    await load(true);
  } catch (error) {
    showError(error.message);
  } finally {
    $("saveBtn").disabled = false;
  }
}

function showError(message) {
  $("editorError").textContent = message;
  $("editorError").hidden = false;
}

async function removeTransaction() {
  if (!state.editing) return;
  if (!confirm(`删除这笔 ${money(state.editing.amount)} 的流水？`)) return;
  $("deleteBtn").disabled = true;
  try {
    await api(`/api/transactions/${state.editing.id}`, { method: "DELETE" });
    closeEditor();
    await load(true);
  } catch (error) {
    showError(error.message);
  } finally {
    $("deleteBtn").disabled = false;
  }
}

/* ---------------- events ---------------- */

document.querySelectorAll("[data-type]").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("[data-type]").forEach((node) => node.classList.remove("is-on"));
    chip.classList.add("is-on");
    state.filters.type = chip.dataset.type;
    load(true);
  });
});

document.querySelectorAll("[data-etype]").forEach((chip) => {
  chip.addEventListener("click", () => setEditorType(chip.dataset.etype));
});

$("monthFilter").addEventListener("change", (event) => {
  state.filters.month = event.target.value;
  load(true);
});

$("accountFilter").addEventListener("change", (event) => {
  state.filters.account = event.target.value;
  load(true);
});

$("categoryFilter").addEventListener("change", (event) => {
  state.filters.category = event.target.value;
  load(true);
});

let searchTimer = null;
$("searchInput").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.filters.q = event.target.value.trim();
    load(true);
  }, 300);
});

$("filterToggle").addEventListener("click", () => {
  const open = $("filters").classList.toggle("is-open");
  $("filterToggle").setAttribute("aria-expanded", String(open));
});

$("resetBtn").addEventListener("click", () => {
  state.filters = { month: currentMonth(), account: "", category: "", type: "", q: "" };
  $("monthFilter").value = currentMonth();
  $("accountFilter").value = "";
  $("categoryFilter").value = "";
  $("searchInput").value = "";
  document.querySelectorAll("[data-type]").forEach((chip) => {
    chip.classList.toggle("is-on", chip.dataset.type === "");
  });
  load(true);
});

$("moreBtn").addEventListener("click", () => load(false));
$("addBtn").addEventListener("click", () => openEditor(null));
$("saveBtn").addEventListener("click", save);
$("cancelBtn").addEventListener("click", closeEditor);
$("editorClose").addEventListener("click", closeEditor);
$("editorBackdrop").addEventListener("click", closeEditor);
$("deleteBtn").addEventListener("click", removeTransaction);

$("editorForm").addEventListener("submit", (event) => {
  event.preventDefault();
  save();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("editor").hidden) closeEditor();
});

/* ---------------- boot ---------------- */

(async function boot() {
  state.filters.month = currentMonth();
  $("monthFilter").value = currentMonth();
  try {
    await loadMeta();
  } catch (error) {
    $("txSub").textContent = "账户与分类读取失败";
  }
  await load(true);
})();
