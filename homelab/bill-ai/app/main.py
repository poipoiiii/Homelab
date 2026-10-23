import base64
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import time
from datetime import date as date_cls
from datetime import timedelta
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from openpyxl import load_workbook
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app import store

DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEFAULT_ASSET = "现金"
DEFAULT_CATEGORY = "其他"
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# 历史账单里可能出现的旧账户名，导入时自动归到现有账户
LEGACY_ACCOUNTS = {"银行卡": "中国银行", "储蓄卡": "中国银行"}

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
BRANDING_DIR = os.getenv("BRANDING_DIR", "/branding")

app = FastAPI(title="Rong的账单", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if os.path.isdir(BRANDING_DIR):
    app.mount("/branding", StaticFiles(directory=BRANDING_DIR), name="branding")
store.init_db()


@app.middleware("http")
async def static_no_cache(request, call_next):
    """静态资源与页面每次都校验，避免改完样式刷新看不到变化。"""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path in ("/", "/dashboard", "/transactions", "/settings"):
        response.headers["Cache-Control"] = "no-cache"
    return response


class Item(BaseModel):
    type: str = Field(pattern="^(withdrawal|deposit|transfer)$")
    date: str
    time: str = ""
    amount: str
    merchant: str = ""
    description: str = ""
    account: str = ""
    to_account: str = ""
    category: str = ""
    confidence: float = 0
    order_id: str = ""


class CommitPayload(BaseModel):
    items: list[Item]


class AccountPayload(BaseModel):
    name: str
    opening_balance: str = "0"
    opening_date: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    opening_balance: str | None = None
    opening_date: str | None = None
    archived: bool | None = None


class ReconcilePayload(BaseModel):
    balance: str


class CategoryPayload(BaseModel):
    name: str
    kind: str = "expense"


class CategoryUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None


class TransactionPayload(BaseModel):
    date: str
    time: str = "12:00"
    type: str = Field(pattern="^(expense|income|transfer)$")
    amount: str
    account_id: int
    to_account_id: int | None = None
    category_id: int | None = None
    merchant: str = ""
    description: str = ""
    note: str = ""


class TransactionUpdate(BaseModel):
    date: str | None = None
    time: str | None = None
    type: str | None = Field(default=None, pattern="^(expense|income|transfer)$")
    amount: str | None = None
    account_id: int | None = None
    to_account_id: int | None = None
    category_id: int | None = None
    merchant: str | None = None
    description: str | None = None
    note: str | None = None


def meta_payload() -> dict[str, Any]:
    return {
        "assets": [{"id": str(a["id"]), "name": a["name"]} for a in store.list_accounts()],
        "expenses": [{"id": "expense", "name": "支出"}],
        "revenues": [{"id": "income", "name": "收入"}],
        "categories": [{"id": str(c["id"]), "name": c["name"]} for c in store.list_categories()],
    }


def clean_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def normalize_amount(value: Any) -> str:
    raw = str(value or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return "0.00"
    try:
        return f"{abs(float(match.group(0))):.2f}"
    except ValueError:
        return "0.00"


def normalize_date(value: Any) -> str:
    raw = str(value or "").strip()
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if match:
        y, m, d = (int(x) for x in match.groups())
        try:
            return date_cls(y, m, d).isoformat()
        except ValueError:
            pass
    return date_cls.today().isoformat()


def normalize_time(value: Any) -> str:
    raw = str(value or "").strip()
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return ""
    h, m = int(match.group(1)), int(match.group(2))
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return ""


CATEGORY_MAP = {
    "餐饮美食": "餐饮",
    "交通出行": "交通",
    "爱车养车": "交通",
    "日用百货": "购物",
    "服饰装扮": "购物",
    "数码电器": "购物",
    "家居家装": "购物",
    "生活服务": "购物",
    "文化休闲": "娱乐",
    "医疗健康": "医疗",
    "保险": "医疗",
    "住房物业": "居住",
    "充值缴费": "居住",
    "转账红包": "人情",
    "商业服务": "其他",
    "其他": "其他",
}

EXCLUDED_NEUTRAL_CATEGORIES = {"投资理财", "账户存取", "信用借还", "退款", "转账红包"}

SUCCESS_STATUSES = {"交易成功", "支付成功"}


def clean_cell(value: Any) -> str:
    return str(value or "").replace("\t", "").strip()


def map_account(method: str, default: str = "支付宝") -> str:
    value = method or ""
    if "微信" in value or "零钱" in value:
        return "微信零钱"
    if "银行" in value or "储蓄卡" in value or "信用卡" in value or "银联" in value:
        return "中国银行"
    if "现金" in value:
        return "现金"
    return default


def clean_merchant(value: Any, category_raw: str) -> str:
    text = clean_cell(value)
    if category_raw == "转账红包" and ("?" in text or "í" in text):
        masked = re.search(r"\((\*\*[^)]+)\)", text)
        return f"转账对象（{masked.group(1)}）" if masked else "转账对象"
    return text[:120]


def parse_alipay_csv(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("gb18030", errors="replace")

    lines = text.splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if "交易时间" in line and "交易分类" in line),
        None,
    )
    if header_index is None:
        raise HTTPException(400, "没有找到支付宝账单表头，请确认导出的是支付宝交易明细 CSV")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    stats = {
        "rows": 0,
        "included": 0,
        "skipped_status": 0,
        "skipped_internal": 0,
        "skipped_other": 0,
        "skipped_duplicate": 0,
        "total_out": 0.0,
        "total_in": 0.0,
    }
    items = []
    seen_orders = set()

    for row in reader:
        if not clean_cell(row.get("交易时间")):
            continue
        stats["rows"] += 1

        status = clean_cell(row.get("交易状态"))
        if status not in SUCCESS_STATUSES:
            stats["skipped_status"] += 1
            continue

        direction = clean_cell(row.get("收/支"))
        category_raw = clean_cell(row.get("交易分类"))

        if direction == "不计收支" and category_raw in EXCLUDED_NEUTRAL_CATEGORIES:
            stats["skipped_internal"] += 1
            continue

        if direction in {"支出", "不计收支"}:
            txn_type = "withdrawal"
        elif direction == "收入":
            txn_type = "deposit"
        else:
            stats["skipped_other"] += 1
            continue

        amount = normalize_amount(clean_cell(row.get("金额")))
        if amount == "0.00":
            stats["skipped_other"] += 1
            continue

        order_id = clean_cell(row.get("交易订单号"))
        if order_id and order_id in seen_orders:
            stats["skipped_duplicate"] += 1
            continue
        if order_id:
            seen_orders.add(order_id)

        raw_time = clean_cell(row.get("交易时间"))
        item = {
            "type": txn_type,
            "date": normalize_date(raw_time),
            "time": normalize_time(raw_time),
            "amount": amount,
            "merchant": clean_merchant(row.get("交易对方"), category_raw),
            "description": clean_cell(row.get("商品说明"))[:200],
            "account": map_account(clean_cell(row.get("收/付款方式"))),
            "to_account": "",
            "category": CATEGORY_MAP.get(category_raw, "其他"),
            "confidence": 1.0,
            "order_id": order_id[:64],
        }
        items.append(item)
        stats["included"] += 1
        if txn_type == "withdrawal":
            stats["total_out"] += float(amount)
        else:
            stats["total_in"] += float(amount)

    stats["total_out"] = f"{stats['total_out']:.2f}"
    stats["total_in"] = f"{stats['total_in']:.2f}"
    return {"items": items, "stats": stats, "source": "alipay_csv"}


WECHAT_CATEGORY_MAP = {
    "商户消费": "购物",
    "扫二维码付款": "购物",
    "二维码收款": "其他",
    "转账": "人情",
    "红包": "人情",
    "微信红包": "人情",
    "群收款": "人情",
    "信用卡还款": "其他",
    "零钱提现": "其他",
    "充值": "其他",
    "其他": "其他",
}

WECHAT_CATEGORY_RULES = (
    ("交通", ("地铁", "公交", "打车", "出租", "滴滴", "高铁", "火车", "加油", "充电", "停车", "ETC", "单车")),
    ("餐饮", ("餐", "饭", "咖啡", "奶茶", "外卖", "肯德基", "麦当劳", "星巴克", "瑞幸", "火锅", "烧烤", "面包")),
    ("医疗", ("医院", "药", "诊所", "体检")),
    ("居住", ("房租", "物业", "水费", "电费", "燃气", "公寓")),
    ("娱乐", ("电影", "游戏", "KTV", "演出")),
)


def map_wechat_category(raw_type: str, merchant: str, product: str) -> str:
    if raw_type not in {"商户消费", "扫二维码付款"}:
        return WECHAT_CATEGORY_MAP.get(raw_type, "其他")
    text = f"{merchant}{product}"
    for category, keywords in WECHAT_CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return "购物"


def detect_kind(headers: list[str]) -> str | None:
    if "交易分类" in headers and "收/付款方式" in headers:
        return "alipay"
    if "交易类型" in headers and "支付方式" in headers:
        return "wechat"
    return None


def parse_wechat_rows(rows: list[dict[str, str]], source: str) -> dict[str, Any]:
    stats = {
        "rows": 0,
        "included": 0,
        "skipped_status": 0,
        "skipped_internal": 0,
        "skipped_other": 0,
        "skipped_duplicate": 0,
        "total_out": 0.0,
        "total_in": 0.0,
    }
    items = []
    seen_orders = set()

    for row in rows:
        if not clean_cell(row.get("交易时间")):
            continue
        stats["rows"] += 1

        status = clean_cell(row.get("当前状态"))
        if not status or any(key in status for key in ("关闭", "失败", "取消", "过期")):
            stats["skipped_status"] += 1
            continue

        direction = clean_cell(row.get("收/支"))
        if direction in {"不计收支", "/"}:
            stats["skipped_internal"] += 1
            continue
        if direction == "支出":
            txn_type = "withdrawal"
        elif direction == "收入":
            txn_type = "deposit"
        else:
            stats["skipped_other"] += 1
            continue

        amount = normalize_amount(clean_cell(row.get("金额(元)") or row.get("金额")))
        if amount == "0.00":
            stats["skipped_other"] += 1
            continue

        order_id = clean_cell(row.get("交易单号"))
        if order_id and order_id in seen_orders:
            stats["skipped_duplicate"] += 1
            continue
        if order_id:
            seen_orders.add(order_id)

        raw_time = clean_cell(row.get("交易时间"))
        raw_type = clean_cell(row.get("交易类型"))
        merchant = clean_cell(row.get("交易对方"))[:120]
        product = clean_cell(row.get("商品"))[:200]
        item = {
            "type": txn_type,
            "date": normalize_date(raw_time),
            "time": normalize_time(raw_time),
            "amount": amount,
            "merchant": merchant,
            "description": product,
            "account": map_account(clean_cell(row.get("支付方式")), "微信零钱"),
            "to_account": "",
            "category": map_wechat_category(raw_type, merchant, product),
            "confidence": 1.0,
            "order_id": order_id[:64],
        }
        items.append(item)
        stats["included"] += 1
        if txn_type == "withdrawal":
            stats["total_out"] += float(amount)
        else:
            stats["total_in"] += float(amount)

    stats["total_out"] = f"{stats['total_out']:.2f}"
    stats["total_in"] = f"{stats['total_in']:.2f}"
    return {"items": items, "stats": stats, "source": source}


def parse_statement(data: bytes, filename: str, content_type: str | None) -> dict[str, Any]:
    is_xlsx = filename.endswith(".xlsx") or content_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    if is_xlsx:
        try:
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as error:
            raise HTTPException(400, f"Excel 读取失败：{error}")
        sheet = workbook.active
        matrix = [[clean_cell(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
        header_index = next(
            (
                i
                for i, row in enumerate(matrix)
                if any("交易时间" in cell for cell in row) and any("金额" in cell for cell in row)
            ),
            None,
        )
        if header_index is None:
            raise HTTPException(400, "Excel 里没有找到交易表头（需要包含“交易时间”和“金额”）")
        headers = [cell for cell in matrix[header_index] if cell]
        kind = detect_kind(headers)
        if kind == "alipay":
            buffer = io.StringIO()
            csv.writer(buffer).writerows(matrix)
            result = parse_alipay_csv(buffer.getvalue().encode("utf-8"))
            result["source"] = "alipay_xlsx"
            return result
        if kind == "wechat":
            dict_rows = []
            for row in matrix[header_index + 1:]:
                if not any(row):
                    continue
                dict_rows.append({headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))})
            return parse_wechat_rows(dict_rows, "wechat_xlsx")
        raise HTTPException(400, "暂不支持这个 Excel 表头；目前支持支付宝、微信账单")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("gb18030", errors="replace")
    lines = text.splitlines()
    header_index = next(
        (i for i, line in enumerate(lines) if "交易时间" in line and "金额" in line),
        None,
    )
    if header_index is None:
        raise HTTPException(400, "CSV 里没有找到交易表头")
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    headers = [name for name in (reader.fieldnames or []) if name]
    kind = detect_kind(headers)
    if kind == "alipay":
        return parse_alipay_csv(data)
    if kind == "wechat":
        return parse_wechat_rows([row for row in reader if any(row.values())], "wechat_csv")
    raise HTTPException(400, "暂不支持这个 CSV 表头；目前支持支付宝、微信账单")


PROMPT = """你是账单 OCR 引擎。请从截图中提取所有真实发生的交易，只输出 JSON，不要输出解释。

今天的日期是 {today}。

输出格式：
{{
  "transactions": [
    {{
      "type": "withdrawal|deposit|transfer",
      "date": "YYYY-MM-DD",
      "time": "HH:MM",
      "amount": "12.34",
      "merchant": "商户或对方名称",
      "description": "简短用途",
      "account": "付款/收款账户",
      "to_account": "仅转账时填写对方账户",
      "category": "分类",
      "confidence": 0.0
    }}
  ]
}}

规则：
1. 金额一律为正数，保留两位小数；不要输出余额、优惠券、广告、额度。
2. 支出用 withdrawal，收入用 deposit，账户之间互转用 transfer。
3. account 必须从这些资产账户里选：{assets}；看不出来就用「{default_asset}」。
4. transfer 时 to_account 也必须从上面的资产账户里选，且不能和 account 相同。
5. category 必须从这些分类里选：{categories}；不确定就用「{default_category}」。
6. 日期看不清就填今天；时间看不清就留空。
7. 截图里有多笔交易时全部提取，一笔一个对象。
8. 如果截图中没有可识别的交易，返回 {{"transactions": []}}。
"""


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/dashboard")
async def dashboard() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "dashboard.html"))


@app.get("/transactions")
async def transactions_page() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "transactions.html"))


@app.get("/settings")
async def settings_page() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "settings.html"))


@app.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(os.path.join(BRANDING_DIR, "favicon.ico"))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/meta")
async def meta() -> dict[str, Any]:
    return meta_payload()


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = (file.filename or "").lower()
    is_statement = filename.endswith((".csv", ".xlsx")) or file.content_type in {
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    data = await file.read()
    if is_statement:
        result = parse_statement(data, filename, file.content_type)
        result["meta"] = meta_payload()
        return result

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "只支持图片、CSV 或 XLSX 文件")

    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "图片超过 8 MB，请压缩后再试")

    meta_data = meta_payload()
    asset_names = [x["name"] for x in meta_data["assets"]] or [DEFAULT_ASSET]
    category_names = [x["name"] for x in meta_data["categories"]] or [DEFAULT_CATEGORY]

    prompt = PROMPT.format(
        today=date_cls.today().isoformat(),
        assets="、".join(asset_names),
        categories="、".join(category_names),
        default_asset=DEFAULT_ASSET,
        default_category=DEFAULT_CATEGORY,
    )
    mime = file.content_type or "image/png"
    image_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 4000,
    }

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            DEEPSEEK_BASE_URL + "/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"模型接口返回 {response.status_code}: {response.text[:300]}")

    body = response.json()
    content = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    try:
        parsed = clean_json(content)
    except json.JSONDecodeError:
        raise HTTPException(502, "模型没有返回合法 JSON，请换一张更清晰的截图")

    items = []
    allowed_categories = {x["name"] for x in meta_data["categories"]}
    allowed_assets = {x["name"] for x in meta_data["assets"]}
    for raw in parsed.get("transactions", []) or []:
        txn_type = str(raw.get("type", "withdrawal")).lower()
        if txn_type not in {"withdrawal", "deposit", "transfer"}:
            txn_type = "withdrawal"
        account = str(raw.get("account", "")).strip()
        if account not in allowed_assets:
            account = DEFAULT_ASSET if DEFAULT_ASSET in allowed_assets else next(iter(allowed_assets), "")
        category = str(raw.get("category", "")).strip()
        if category not in allowed_categories:
            category = DEFAULT_CATEGORY if DEFAULT_CATEGORY in allowed_categories else next(iter(allowed_categories), "")
        to_account = str(raw.get("to_account", "")).strip()
        if to_account not in allowed_assets:
            to_account = ""
        amount = normalize_amount(raw.get("amount"))
        if amount == "0.00":
            continue
        items.append({
            "type": txn_type,
            "date": normalize_date(raw.get("date")),
            "time": normalize_time(raw.get("time")),
            "amount": amount,
            "merchant": str(raw.get("merchant", "")).strip()[:120],
            "description": str(raw.get("description", "")).strip()[:200],
            "account": account,
            "to_account": to_account,
            "category": category,
            "confidence": max(0.0, min(1.0, float(raw.get("confidence") or 0))),
        })

    return {"items": items, "meta": meta_data}


def item_hash(item: Item) -> str:
    if item.order_id:
        return hashlib.sha256(("order:" + item.order_id).encode()).hexdigest()
    raw = "|".join([
        item.type, item.date, item.amount, item.merchant,
        item.account, item.to_account, item.category,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def resolve_account(name: str) -> dict[str, Any] | None:
    name = (name or "").strip()
    for account in store.list_accounts(include_archived=True):
        if account["name"] == name:
            return account
    mapped = LEGACY_ACCOUNTS.get(name)
    if mapped:
        for account in store.list_accounts(include_archived=True):
            if account["name"] == mapped:
                return account
    return None


def ensure_category(name: str, kind: str) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    existing = store.category_id_by_name(name)
    if existing:
        return existing
    return store.create_category(name, kind)


def commit_items(items: list[Item]) -> dict[str, Any]:
    if not items:
        raise HTTPException(400, "没有可写入的账单")

    con = store.connect()
    committed = skipped = failed = 0
    details: list[dict[str, Any]] = []
    try:
        for item in items:
            digest = item_hash(item)
            if con.execute("select 1 from committed where hash=?", (digest,)).fetchone():
                skipped += 1
                details.append({"status": "skipped", "merchant": item.merchant, "amount": item.amount})
                continue

            source = resolve_account(item.account)
            if not source:
                failed += 1
                details.append({"status": "failed", "merchant": item.merchant,
                                "error": f"未知账户 {item.account}"})
                continue

            type_map = {"withdrawal": "expense", "deposit": "income", "transfer": "transfer"}
            txn_type = type_map[item.type]
            to_account_id = None
            if txn_type == "transfer":
                target = resolve_account(item.to_account)
                if not target or target["id"] == source["id"]:
                    failed += 1
                    details.append({"status": "failed", "merchant": item.merchant,
                                    "error": "转账目标账户无效"})
                    continue
                to_account_id = target["id"]

            amount = normalize_amount(item.amount)
            if amount == "0.00":
                failed += 1
                details.append({"status": "failed", "merchant": item.merchant, "error": "金额为 0"})
                continue

            external_id = item.order_id[:64] if item.order_id else digest[:64]
            try:
                txn_id = store.create_transaction({
                    "date": normalize_date(item.date),
                    "time": item.time or "12:00",
                    "type": txn_type,
                    "amount": amount,
                    "account_id": source["id"],
                    "to_account_id": to_account_id,
                    "category_id": ensure_category(item.category, "income" if txn_type == "income" else "expense"),
                    "merchant": item.merchant or item.description or "未命名交易",
                    "description": item.description,
                    "external_id": external_id,
                })
            except Exception as error:  # 外部订单号重复等
                failed += 1
                details.append({"status": "failed", "merchant": item.merchant,
                                "amount": item.amount, "error": str(error)[:160]})
                continue

            con.execute(
                "insert into committed (hash, group_id, created_at) values (?,?,?)",
                (digest, str(txn_id), int(time.time())),
            )
            con.commit()
            committed += 1
            details.append({"status": "committed", "merchant": item.merchant,
                            "amount": item.amount, "group_id": str(txn_id)})
    finally:
        con.close()

    return {"committed": committed, "skipped": skipped, "failed": failed, "details": details}


@app.post("/api/commit")
async def commit(payload: CommitPayload) -> dict[str, Any]:
    return commit_items(payload.items)


@app.get("/api/accounts")
async def accounts(include_archived: bool = False) -> dict[str, Any]:
    return {"items": store.list_accounts(include_archived=include_archived)}


@app.post("/api/accounts")
async def create_account(payload: AccountPayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise HTTPException(400, "账户名不能为空")
    try:
        account_id = store.create_account(payload.name, payload.opening_balance, payload.opening_date)
    except Exception:
        raise HTTPException(400, "账户名已存在")
    return {"id": account_id}


@app.put("/api/accounts/{account_id}")
async def update_account(account_id: int, payload: AccountUpdate) -> dict[str, bool]:
    try:
        store.update_account(
            account_id,
            name=payload.name,
            opening_balance=payload.opening_balance,
            opening_date=payload.opening_date,
            archived=payload.archived,
        )
    except Exception:
        raise HTTPException(400, "账户名已存在")
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int) -> dict[str, bool]:
    try:
        store.delete_account(account_id)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return {"ok": True}


@app.post("/api/accounts/{account_id}/reconcile")
async def reconcile_account(account_id: int, payload: ReconcilePayload) -> dict[str, str]:
    opening = store.reconcile_account(account_id, payload.balance)
    return {"opening_balance": opening}


@app.get("/api/categories")
async def categories() -> dict[str, Any]:
    return {"items": store.list_categories()}


@app.post("/api/categories")
async def create_category(payload: CategoryPayload) -> dict[str, Any]:
    if not payload.name.strip():
        raise HTTPException(400, "分类名不能为空")
    try:
        category_id = store.create_category(payload.name, payload.kind)
    except Exception:
        raise HTTPException(400, "分类名已存在")
    return {"id": category_id}


@app.put("/api/categories/{category_id}")
async def update_category(category_id: int, payload: CategoryUpdate) -> dict[str, bool]:
    try:
        store.update_category(category_id, name=payload.name, kind=payload.kind)
    except Exception:
        raise HTTPException(400, "分类名已存在")
    return {"ok": True}


@app.delete("/api/categories/{category_id}")
async def delete_category(category_id: int) -> dict[str, bool]:
    try:
        store.delete_category(category_id)
    except ValueError as error:
        raise HTTPException(400, str(error))
    return {"ok": True}


@app.get("/api/transactions")
async def transactions(
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    type: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    return store.list_transactions(
        month=month, start=start, end=end, account_id=account_id,
        category_id=category_id, txn_type=type, query=q, limit=limit, offset=offset,
    )


TYPE_LABEL = {"expense": "支出", "income": "收入", "transfer": "转账"}


@app.get("/api/export.csv")
async def export_csv(
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    type: str | None = None,
    q: str | None = None,
) -> Response:
    data = store.list_transactions(
        month=month, start=start, end=end, account_id=account_id,
        category_id=category_id, txn_type=type, query=q, limit=20000,
    )
    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM，Excel 打开不乱码
    writer = csv.writer(buffer)
    writer.writerow(["日期", "时间", "类型", "金额(元)", "账户", "对方账户",
                     "分类", "商户", "说明", "备注", "外部单号"])
    for item in reversed(data["items"]):
        writer.writerow([
            item["date"], item["time"], TYPE_LABEL.get(item["type"], item["type"]),
            item["amount"], item["account"], item["to_account"], item["category"],
            item["merchant"], item["description"], item["note"], item["external_id"] or "",
        ])
    filename = f"bill-{date_cls.today().isoformat()}.csv"
    return Response(
        content=buffer.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/backup.db")
async def backup_db() -> FileResponse:
    """用 SQLite 在线备份生成一致的快照，供备份脚本拉取。"""
    handle = tempfile.NamedTemporaryFile(prefix="bill-", suffix=".db", delete=False)
    handle.close()
    source = store.connect()
    target = sqlite3.connect(handle.name)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    def cleanup() -> None:
        try:
            os.remove(handle.name)
        except OSError:
            pass

    filename = f"bill-{date_cls.today().isoformat()}.db"
    return FileResponse(
        handle.name,
        media_type="application/octet-stream",
        filename=filename,
        background=BackgroundTask(cleanup),
    )


def _validate_transaction(payload: TransactionPayload) -> None:
    if payload.type == "transfer":
        if not payload.to_account_id or payload.to_account_id == payload.account_id:
            raise HTTPException(400, "转账需要选择不同的对方账户")
    if store.cents(payload.amount) <= 0:
        raise HTTPException(400, "金额必须大于 0")


@app.post("/api/transactions")
async def create_transaction(payload: TransactionPayload) -> dict[str, Any]:
    _validate_transaction(payload)
    txn_id = store.create_transaction({
        "date": normalize_date(payload.date),
        "time": payload.time or "12:00",
        "type": payload.type,
        "amount": payload.amount,
        "account_id": payload.account_id,
        "to_account_id": payload.to_account_id if payload.type == "transfer" else None,
        "category_id": payload.category_id if payload.type != "transfer" else None,
        "merchant": payload.merchant,
        "description": payload.description,
        "note": payload.note,
    })
    return {"id": txn_id}


@app.put("/api/transactions/{txn_id}")
async def update_transaction(txn_id: int, payload: TransactionUpdate) -> dict[str, bool]:
    if not store.get_transaction(txn_id):
        raise HTTPException(404, "流水不存在")
    data = payload.model_dump(exclude_unset=True)
    if data.get("type") == "transfer" and data.get("account_id") == data.get("to_account_id"):
        raise HTTPException(400, "转账需要选择不同的对方账户")
    if "amount" in data and store.cents(data["amount"]) <= 0:
        raise HTTPException(400, "金额必须大于 0")
    store.update_transaction(txn_id, data)
    return {"ok": True}


@app.delete("/api/transactions/{txn_id}")
async def delete_transaction(txn_id: int) -> dict[str, bool]:
    store.delete_transaction(txn_id)
    return {"ok": True}


@app.get("/api/overview")
async def overview(month: str | None = None) -> dict[str, Any]:
    return store.overview(month)


@app.get("/api/month-transactions")
async def month_transactions(month: str) -> dict[str, Any]:
    if not re.match(r"^\d{4}-\d{2}$", month):
        raise HTTPException(400, "month 需要 YYYY-MM 格式")
    return store.month_data(month)


@app.get("/api/summary")
async def summary(month: str | None = None) -> dict[str, Any]:
    data = store.month_data(month or date_cls.today().strftime("%Y-%m"))
    by_category: dict[str, int] = {}
    for item in data["items"]:
        if item["type"] != "expense":
            continue
        name = item["category"] or "未分类"
        by_category[name] = by_category.get(name, 0) + item["amount_cents"]
    return {
        "month": data["month"],
        "total": data["stats"]["out"],
        "count": data["stats"]["count_out"],
        "by_category": [
            {"name": name, "amount": store.yuan(amount)}
            for name, amount in sorted(by_category.items(), key=lambda x: -x[1])
        ],
    }


ANALYSIS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


async def run_analysis(start: date_cls, end: date_cls) -> dict[str, Any]:
    stats = store.aggregate(start, end)
    if stats["count_out"] + stats["count_in"] == 0:
        raise HTTPException(400, "这段时间没有账单，先记几笔再分析")

    cache_key = "|".join([
        "v3",
        stats["range"]["start"], stats["range"]["end"],
        stats["total_out"], stats["total_in"], str(stats["count_out"]),
    ])
    cached = ANALYSIS_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < 3600:
        return {"range": stats["range"], "stats": stats, "analysis": cached[1], "cached": True}

    prompt = f"""以下是 {start.isoformat()} 到 {end.isoformat()} 的个人账单聚合数据（单位：人民币元）：
{json.dumps(stats, ensure_ascii=False)}

请基于这些数据做财务分析，只输出 JSON，格式：
{{
  "summary": "2-4 句话的总体判断，包含收支、结余和主要结构",
  "highlights": [{{"title": "短标题", "detail": "引用具体数字的发现"}}],
  "risks": [{{"title": "短标题", "detail": "可疑或需要留意的地方，没有就给空数组"}}],
  "suggestions": [{{"title": "短标题", "detail": "具体可执行的建议"}}],
  "category_note": "一句话点评分类结构"
}}

要求：
1. highlights 给 3-5 条，点名最高分类、最大单笔、最高频商户、月度趋势中至少三项。
2. suggestions 给 3-5 条，必须结合上面的数字，不要泛泛而谈。
3. 金额保留两位小数并带 ¥；不要编造数据里没有的信息。
4. 不要输出 Markdown 或代码块。
5. 不同统计维度（分类合计、商户合计、笔数）口径不同是正常的，不要因此判定数据异常；只有同一维度内自相矛盾才提示风险。"""

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一名严谨、务实的个人财务分析师。"},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 8000,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            DEEPSEEK_BASE_URL + "/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"模型接口返回 {response.status_code}: {response.text[:300]}")

    body = response.json()
    content = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    try:
        analysis = clean_json(content)
    except json.JSONDecodeError:
        raise HTTPException(502, f"模型返回的分析不是合法 JSON（长度 {len(content)}）：{content[:300]}")

    for key in ("highlights", "risks", "suggestions"):
        if not isinstance(analysis.get(key), list):
            analysis[key] = []
    analysis["summary"] = str(analysis.get("summary") or "")
    analysis["category_note"] = str(analysis.get("category_note") or "")
    ANALYSIS_CACHE[cache_key] = (time.time(), analysis)
    return {"range": stats["range"], "stats": stats, "analysis": analysis, "cached": False}


@app.get("/api/analyze")
async def analyze(days: int = 90, month: str | None = None) -> dict[str, Any]:
    today = date_cls.today()
    if month and re.match(r"^\d{4}-\d{2}$", month):
        start = date_cls(int(month[:4]), int(month[5:7]), 1)
        if start.month == 12:
            next_month = date_cls(start.year + 1, 1, 1)
        else:
            next_month = date_cls(start.year, start.month + 1, 1)
        end = min(next_month - timedelta(days=1), today)
    else:
        days = max(7, min(365, days))
        end = today
        start = end - timedelta(days=days - 1)
    return await run_analysis(start, end)
