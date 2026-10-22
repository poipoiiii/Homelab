const state = {
  file: null,
  meta: { assets: [], categories: [], expenses: [], revenues: [] },
  items: [],
  stats: null,
  isCsv: false,
  previewUrl: null,
  busy: false,
};

const el = {
  dropzone: document.getElementById("dropzone"),
  file: document.getElementById("file"),
  dropEmpty: document.getElementById("dropEmpty"),
  preview: document.getElementById("preview"),
  fileChip: document.getElementById("fileChip"),
  fileName: document.getElementById("fileName"),
  fileMeta: document.getElementById("fileMeta"),
  extractBtn: document.getElementById("extractBtn"),
  clearBtn: document.getElementById("clearBtn"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  resultsTitle: document.getElementById("resultsTitle"),
  resultsSummary: document.getElementById("resultsSummary"),
  rows: document.getElementById("rows"),
  commitBtn: document.getElementById("commitBtn"),
  commitCount: document.getElementById("commitCount"),
  commitTotal: document.getElementById("commitTotal"),
  done: document.getElementById("done"),
  doneTitle: document.getElementById("doneTitle"),
  doneText: document.getElementById("doneText"),
  againBtn: document.getElementById("againBtn"),
  analysisRange: document.getElementById("analysisRange"),
  analyzeBtn: document.getElementById("analyzeBtn"),
  analysisStatus: document.getElementById("analysisStatus"),
  analysisResult: document.getElementById("analysisResult"),
  analysisStats: document.getElementById("analysisStats"),
  analysisSummary: document.getElementById("analysisSummary"),
  analysisNote: document.getElementById("analysisNote"),
  analysisGrid: document.getElementById("analysisGrid"),
};

const TYPE_LABELS = {
  withdrawal: "支出",
  deposit: "收入",
  transfer: "转账",
};

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

function setStatus(text, kind = "") {
  el.status.textContent = text;
  el.status.className = "status" + (kind ? " " + kind : "");
}

function options(list, selected) {
  return list
    .map((x) => `<option value="${esc(x.name)}"${x.name === selected ? " selected" : ""}>${esc(x.name)}</option>`)
    .join("");
}

function confidenceClass(value) {
  if (value >= 0.85) return "high";
  if (value >= 0.6) return "mid";
  return "low";
}

function render() {
  if (!state.items.length) {
    el.results.hidden = true;
    return;
  }
  el.results.hidden = false;
  el.resultsTitle.textContent = state.stats ? "账单解析结果" : "识别结果";

  el.rows.innerHTML = state.items
    .map((item, index) => {
      const transferField =
        item.type === "transfer"
          ? `<div class="field span-2">
               <label for="to-${index}">转入账户</label>
               <select id="to-${index}" data-field="to_account">${options(state.meta.assets, item.to_account)}</select>
             </div>`
          : "";

      return `<article class="row" data-index="${index}">
        <div class="row-head">
          <span class="row-index">${String(index + 1).padStart(2, "0")}</span>
          <select class="type-select" data-field="type" aria-label="交易类型">
            ${Object.entries(TYPE_LABELS)
              .map(([value, label]) => `<option value="${value}"${item.type === value ? " selected" : ""}>${label}</option>`)
              .join("")}
          </select>
          <span class="confidence ${confidenceClass(item.confidence)}">置信度 ${Math.round(item.confidence * 100)}%</span>
          <button class="remove-btn" type="button" data-remove="${index}" aria-label="删除这笔">×</button>
        </div>
        <div class="row-grid">
          <div class="field">
            <label for="date-${index}">日期</label>
            <input id="date-${index}" type="date" value="${esc(item.date)}" data-field="date">
          </div>
          <div class="field">
            <label for="amount-${index}">金额</label>
            <input id="amount-${index}" type="number" min="0" step="0.01" value="${esc(item.amount)}" data-field="amount">
          </div>
          <div class="field span-2">
            <label for="merchant-${index}">商户 / 对方</label>
            <input id="merchant-${index}" type="text" value="${esc(item.merchant)}" data-field="merchant" placeholder="例如：瑞幸咖啡">
          </div>
          <div class="field">
            <label for="account-${index}">付款账户</label>
            <select id="account-${index}" data-field="account">${options(state.meta.assets, item.account)}</select>
          </div>
          <div class="field">
            <label for="category-${index}">分类</label>
            <select id="category-${index}" data-field="category">${options(state.meta.categories, item.category)}</select>
          </div>
          ${transferField}
          <div class="field span-3">
            <label for="desc-${index}">说明</label>
            <input id="desc-${index}" type="text" value="${esc(item.description)}" data-field="description" placeholder="可选">
          </div>
        </div>
      </article>`;
    })
    .join("");

  const total = state.items
    .filter((x) => x.type === "withdrawal")
    .reduce((sum, x) => sum + (Number.parseFloat(x.amount) || 0), 0);
  el.commitCount.textContent = `${state.items.length} 笔 · 支出合计`;
  el.commitTotal.textContent = `¥${total.toFixed(2)}`;
  if (state.stats) {
    const skipped = state.stats.rows - state.stats.included;
    el.resultsSummary.textContent =
      `共 ${state.stats.rows} 行 · 导入 ${state.stats.included} 笔 · 跳过 ${skipped} 笔 · 收入 ¥${state.stats.total_in}`;
  } else {
    el.resultsSummary.textContent = `已提取 ${state.items.length} 笔，可直接修改后写入`;
  }
  updateBusy();
}

function updateBusy() {
  el.extractBtn.disabled = state.busy || !state.file;
  el.commitBtn.disabled = state.busy || !state.items.length;
  el.clearBtn.disabled = state.busy;
}

function setPreview(file) {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;

  if (file && state.isCsv) {
    el.preview.hidden = true;
    el.preview.removeAttribute("src");
    el.dropEmpty.hidden = true;
    el.fileChip.hidden = false;
    el.fileName.textContent = file.name;
    el.fileMeta.textContent = `${(file.size / 1024).toFixed(1)} KB · 账单文件`;
    return;
  }

  el.fileChip.hidden = true;
  if (file) {
    state.previewUrl = URL.createObjectURL(file);
    el.preview.src = state.previewUrl;
    el.preview.hidden = false;
    el.dropEmpty.hidden = true;
  } else {
    el.preview.removeAttribute("src");
    el.preview.hidden = true;
    el.dropEmpty.hidden = false;
  }
}

function setFile(file) {
  if (!file) return;
  const name = file.name.toLowerCase();
  const isStatement =
    name.endsWith(".csv") ||
    name.endsWith(".xlsx") ||
    ["text/csv", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"].includes(file.type);
  if (!isStatement && !file.type.startsWith("image/")) {
    setStatus("请选择图片、CSV 或 XLSX 文件", "error");
    return;
  }
  const limit = isStatement ? 20 * 1024 * 1024 : 8 * 1024 * 1024;
  if (file.size > limit) {
    setStatus(isStatement ? "账单文件超过 20 MB" : "图片超过 8 MB，请压缩后再试", "error");
    return;
  }
  state.file = file;
  state.isCsv = isStatement;
  state.items = [];
  state.stats = null;
  el.results.hidden = true;
  el.done.hidden = true;
  setPreview(file);
  el.clearBtn.hidden = false;
  setStatus(isStatement ? "账单文件已就绪，点击「解析账单」" : "截图已就绪，点击「识别账单」");
  el.extractBtn.textContent = isStatement ? "解析账单" : "识别账单";
  updateBusy();
}

function resetAll() {
  state.file = null;
  state.items = [];
  state.stats = null;
  state.isCsv = false;
  setPreview(null);
  el.file.value = "";
  el.clearBtn.hidden = true;
  el.results.hidden = true;
  el.done.hidden = true;
  el.rows.innerHTML = "";
  el.resultsTitle.textContent = "识别结果";
  el.extractBtn.textContent = "识别账单";
  setStatus("");
  updateBusy();
}

async function loadMeta() {
  try {
    const response = await fetch("/api/meta");
    if (!response.ok) throw new Error(await response.text());
    state.meta = await response.json();
  } catch (error) {
    setStatus("读取账户与分类失败，请稍后重试", "error");
    throw error;
  }
}

async function extract() {
  if (!state.file || state.busy) return;
  state.busy = true;
  updateBusy();
  const verb = state.isCsv ? "解析" : "识别";
  el.extractBtn.innerHTML = `<span class="spinner"></span>${verb}中`;
  setStatus(state.isCsv ? "正在解析 CSV…" : "正在读取截图，通常需要 5–20 秒…");

  try {
    const form = new FormData();
    form.append("file", state.file);
    const response = await fetch("/api/extract", { method: "POST", body: form });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `${verb}失败`);

    state.items = data.items || [];
    state.stats = data.stats || null;
    if (!state.items.length) {
      setStatus(
        state.isCsv ? "文件里没有可导入的交易（可能全是投资理财、转账或退款）" : "没有识别到交易，换一张更清晰或包含金额的截图试试",
        "error",
      );
      el.results.hidden = true;
    } else if (state.stats) {
      const skipped = state.stats.rows - state.stats.included;
      setStatus(
        `账单共 ${state.stats.rows} 行，导入 ${state.stats.included} 笔，跳过 ${skipped} 笔；请核对后写入`,
        "ok",
      );
      render();
    } else {
      setStatus(`识别到 ${state.items.length} 笔，请核对后写入`, "ok");
      render();
    }
  } catch (error) {
    setStatus(String(error.message || error), "error");
  } finally {
    state.busy = false;
    el.extractBtn.textContent = state.isCsv ? "解析账单" : "识别账单";
    updateBusy();
  }
}

async function commit() {
  if (!state.items.length || state.busy) return;
  state.busy = true;
  updateBusy();
  el.commitBtn.innerHTML = '<span class="spinner"></span>写入中';
  setStatus("正在写入账本…");

  try {
    const response = await fetch("/api/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: state.items }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "写入失败");

    const parts = [`写入 ${data.committed} 笔`];
    if (data.skipped) parts.push(`跳过重复 ${data.skipped} 笔`);
    if (data.failed) parts.push(`失败 ${data.failed} 笔`);

    el.doneTitle.textContent = data.failed ? "部分写入完成" : "已写入账本";
    el.doneText.textContent = parts.join("，") + (data.failed ? "。失败项已在下方保留，可修改后重试。" : "。");
    el.done.hidden = false;
    el.results.hidden = data.failed === 0;
    setStatus(parts.join(" · "), data.failed ? "error" : "ok");

    if (data.failed) {
      const failedItems = data.details.filter((x) => x.status === "failed");
      state.items = state.items.filter((item) =>
        failedItems.some((fail) => fail.merchant === item.merchant && fail.amount === item.amount),
      );
      render();
    }
    el.done.scrollIntoView({ behavior: "smooth", block: "nearest" });
    if (data.committed > 0) void analyze();
  } catch (error) {
    setStatus(String(error.message || error), "error");
  } finally {
    state.busy = false;
    el.commitBtn.textContent = "写入账本";
    updateBusy();
  }
}

const money = (value) =>
  `¥${Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function renderAnalysisItems(items) {
  return items
    .map(
      (item) => `<div class="analysis-item">
        <strong>${esc(item.title || "")}</strong>
        <p>${esc(item.detail || "")}</p>
      </div>`,
    )
    .join("");
}

function renderAnalysis(data) {
  const stats = data.stats;
  el.analysisStats.innerHTML = [
    ["总支出", money(stats.total_out)],
    ["总收入", money(stats.total_in)],
    ["日均支出", money(stats.daily_avg)],
    ["支出笔数", String(stats.count_out)],
  ]
    .map(([label, value]) => `<div class="analysis-stat"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");

  el.analysisSummary.textContent = data.analysis.summary || "";
  el.analysisNote.textContent = data.analysis.category_note
    ? `${data.range.start} ~ ${data.range.end} · ${data.analysis.category_note}`
    : `${data.range.start} ~ ${data.range.end}`;

  const risks = data.analysis.risks || [];
  el.analysisGrid.innerHTML = [
    `<div class="analysis-col"><h3>主要发现</h3>${renderAnalysisItems(data.analysis.highlights || [])}</div>`,
    `<div class="analysis-col risks"><h3>需要留意</h3>${
      risks.length ? renderAnalysisItems(risks) : '<div class="analysis-item"><p>暂无明显异常。</p></div>'
    }</div>`,
    `<div class="analysis-col suggestions"><h3>可以这样做</h3>${renderAnalysisItems(data.analysis.suggestions || [])}</div>`,
  ].join("");

  el.analysisResult.hidden = false;
}

async function analyze() {
  const value = el.analysisRange.value;
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const query = value === "month" ? `month=${month}` : `days=${value}`;

  el.analyzeBtn.disabled = true;
  el.analyzeBtn.textContent = "分析中…";
  el.analysisStatus.textContent = "正在聚合账本数据并请求模型分析…";
  el.analysisStatus.className = "status";

  try {
    const response = await fetch(`/api/analyze?${query}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "分析失败");
    renderAnalysis(data);
    el.analysisStatus.textContent = data.cached ? "已使用 1 小时内的分析缓存" : "分析完成";
    el.analysisStatus.className = "status ok";
  } catch (error) {
    el.analysisStatus.textContent = String(error.message || error);
    el.analysisStatus.className = "status error";
  } finally {
    el.analyzeBtn.disabled = false;
    el.analyzeBtn.textContent = "开始分析";
  }
}

el.analyzeBtn.addEventListener("click", analyze);

el.dropzone.addEventListener("click", () => el.file.click());
el.dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    el.file.click();
  }
});
el.file.addEventListener("change", (event) => setFile(event.target.files?.[0]));

["dragenter", "dragover"].forEach((name) =>
  el.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    el.dropzone.classList.add("is-over");
  }),
);
["dragleave", "drop"].forEach((name) =>
  el.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    el.dropzone.classList.remove("is-over");
  }),
);
el.dropzone.addEventListener("drop", (event) => setFile(event.dataTransfer?.files?.[0]));

document.addEventListener("paste", (event) => {
  const image = [...(event.clipboardData?.items || [])].find((item) => item.type.startsWith("image/"));
  if (image) setFile(image.getAsFile());
});

el.extractBtn.addEventListener("click", extract);
el.clearBtn.addEventListener("click", resetAll);
el.commitBtn.addEventListener("click", commit);
el.againBtn.addEventListener("click", resetAll);

el.rows.addEventListener("input", (event) => {
  const row = event.target.closest(".row");
  if (!row) return;
  const index = Number(row.dataset.index);
  const field = event.target.dataset.field;
  if (!state.items[index] || !field) return;
  state.items[index][field] = event.target.value;
  if (field === "amount" || field === "type") {
    if (field === "type") {
      state.items[index].to_account = "";
      render();
    } else {
      const total = state.items
        .filter((x) => x.type === "withdrawal")
        .reduce((sum, x) => sum + (Number.parseFloat(x.amount) || 0), 0);
      el.commitTotal.textContent = `¥${total.toFixed(2)}`;
    }
  }
});

el.rows.addEventListener("click", (event) => {
  const target = event.target.closest("[data-remove]");
  if (!target) return;
  state.items.splice(Number(target.dataset.remove), 1);
  render();
});

loadMeta()
  .then(() => setStatus(""))
  .catch(() => {});
updateBusy();
