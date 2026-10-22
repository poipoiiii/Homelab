const $ = (id) => document.getElementById(id);
const money = (value) => {
  const number = Number(value);
  const abs = Math.abs(number).toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${number < 0 ? "−" : ""}¥${abs}`;
};

const state = { accounts: [], categories: [], editingAccount: null, editingCategory: null };

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function openSheet(kind) {
  const sheet = $(`${kind}Sheet`);
  sheet.hidden = false;
  void sheet.offsetWidth;
  sheet.classList.add("is-open");
  document.body.classList.add("is-locked");
}

function closeSheet(kind) {
  const sheet = $(`${kind}Sheet`);
  if (sheet.hidden || !sheet.classList.contains("is-open")) return;
  sheet.classList.remove("is-open");
  document.body.classList.remove("is-locked");
  window.setTimeout(() => {
    if (!sheet.classList.contains("is-open")) sheet.hidden = true;
  }, 280);
}

function showError(node, message) {
  node.textContent = message;
  node.hidden = false;
}

/* ---------------- accounts ---------------- */

async function loadAccounts() {
  const data = await api("/api/accounts?include_archived=true");
  state.accounts = data.items;
  const list = $("accountList");
  list.innerHTML = "";
  if (!data.items.length) {
    list.innerHTML = '<p class="empty-state">还没有账户</p>';
    return;
  }
  for (const account of data.items) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "setting-row";

    const name = document.createElement("div");
    name.className = "setting-name";
    const label = document.createElement("span");
    label.textContent = account.name;
    name.appendChild(label);
    if (account.archived) {
      const tag = document.createElement("span");
      tag.className = "setting-tag";
      tag.textContent = "已归档";
      name.appendChild(tag);
    }

    const value = document.createElement("span");
    value.className = "setting-value";
    value.textContent = money(account.balance);

    const count = document.createElement("span");
    count.className = "setting-count";
    count.textContent = `${account.count} 笔`;

    row.append(name, value, count);
    row.addEventListener("click", () => editAccount(account));
    list.appendChild(row);
  }
}

function editAccount(account) {
  state.editingAccount = account || null;
  $("accountSheetTitle").textContent = account ? "编辑账户" : "新增账户";
  $("aName").value = account ? account.name : "";
  $("aOpening").value = account ? account.opening_balance : "0.00";
  $("aOpeningDate").value = account?.opening_date || "";
  $("aArchived").checked = Boolean(account?.archived);
  $("aActual").value = "";
  $("accountDeleteBtn").hidden = !account;
  $("accountError").hidden = true;
  openSheet("account");
  $("aName").focus();
}

async function saveAccount() {
  $("accountError").hidden = true;
  const name = $("aName").value.trim();
  if (!name) return showError($("accountError"), "请填写账户名称");
  const payload = {
    name,
    opening_balance: $("aOpening").value.replace(/[^\d.-]/g, "") || "0",
    opening_date: $("aOpeningDate").value || null,
    archived: $("aArchived").checked,
  };
  $("accountSaveBtn").disabled = true;
  try {
    let accountId = state.editingAccount?.id;
    if (state.editingAccount) {
      await api(`/api/accounts/${accountId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      const created = await api("/api/accounts", {
        method: "POST",
        body: JSON.stringify({ name, opening_balance: payload.opening_balance, opening_date: payload.opening_date }),
      });
      accountId = created.id;
    }
    const actual = $("aActual").value.replace(/[^\d.-]/g, "");
    if (actual) {
      await api(`/api/accounts/${accountId}/reconcile`, {
        method: "POST",
        body: JSON.stringify({ balance: actual }),
      });
    }
    closeSheet("account");
    await loadAccounts();
  } catch (error) {
    showError($("accountError"), error.message);
  } finally {
    $("accountSaveBtn").disabled = false;
  }
}

async function deleteAccount() {
  if (!state.editingAccount) return;
  if (!confirm(`删除账户「${state.editingAccount.name}」？`)) return;
  try {
    await api(`/api/accounts/${state.editingAccount.id}`, { method: "DELETE" });
    closeSheet("account");
    await loadAccounts();
  } catch (error) {
    showError($("accountError"), error.message);
  }
}

/* ---------------- categories ---------------- */

async function loadCategories() {
  const data = await api("/api/categories");
  state.categories = data.items;
  const list = $("categoryList");
  list.innerHTML = "";
  if (!data.items.length) {
    list.innerHTML = '<p class="empty-state">还没有分类</p>';
    return;
  }
  for (const category of data.items) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "setting-row";

    const name = document.createElement("div");
    name.className = "setting-name";
    const label = document.createElement("span");
    label.textContent = category.name;
    name.appendChild(label);
    const tag = document.createElement("span");
    tag.className = "setting-tag";
    tag.textContent = category.kind === "income" ? "收入" : "支出";
    name.appendChild(tag);

    const value = document.createElement("span");
    value.className = "setting-value";

    const count = document.createElement("span");
    count.className = "setting-count";
    count.textContent = `${category.count} 笔`;

    row.append(name, value, count);
    row.addEventListener("click", () => editCategory(category));
    list.appendChild(row);
  }
}

function editCategory(category) {
  state.editingCategory = category || null;
  $("categorySheetTitle").textContent = category ? "编辑分类" : "新增分类";
  $("cName").value = category ? category.name : "";
  $("cKind").value = category ? category.kind : "expense";
  $("categoryDeleteBtn").hidden = !category;
  $("categoryError").hidden = true;
  openSheet("category");
  $("cName").focus();
}

async function saveCategory() {
  $("categoryError").hidden = true;
  const name = $("cName").value.trim();
  if (!name) return showError($("categoryError"), "请填写分类名称");
  const payload = { name, kind: $("cKind").value };
  $("categorySaveBtn").disabled = true;
  try {
    if (state.editingCategory) {
      await api(`/api/categories/${state.editingCategory.id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/api/categories", { method: "POST", body: JSON.stringify(payload) });
    }
    closeSheet("category");
    await loadCategories();
  } catch (error) {
    showError($("categoryError"), error.message);
  } finally {
    $("categorySaveBtn").disabled = false;
  }
}

async function deleteCategory() {
  if (!state.editingCategory) return;
  if (!confirm(`删除分类「${state.editingCategory.name}」？`)) return;
  try {
    await api(`/api/categories/${state.editingCategory.id}`, { method: "DELETE" });
    closeSheet("category");
    await loadCategories();
  } catch (error) {
    showError($("categoryError"), error.message);
  }
}

/* ---------------- events ---------------- */

$("addAccountBtn").addEventListener("click", () => editAccount(null));
$("addCategoryBtn").addEventListener("click", () => editCategory(null));
$("accountSaveBtn").addEventListener("click", saveAccount);
$("categorySaveBtn").addEventListener("click", saveCategory);
$("accountDeleteBtn").addEventListener("click", deleteAccount);
$("categoryDeleteBtn").addEventListener("click", deleteCategory);

document.querySelectorAll("[data-close]").forEach((node) => {
  node.addEventListener("click", () => closeSheet(node.dataset.close));
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("accountSheet").hidden) closeSheet("account");
  else if (!$("categorySheet").hidden) closeSheet("category");
});

/* ---------------- boot ---------------- */

(async function boot() {
  $("updatedAt").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
  try {
    await Promise.all([loadAccounts(), loadCategories()]);
  } catch (error) {
    $("accountList").innerHTML = `<p class="empty-state">读取失败：${error.message}</p>`;
  }
})();
