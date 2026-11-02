"""手机上报文本的规则解析。

只依赖标准库：不碰数据库、不调模型，方便单独跑用例验证正则。
账户名、分类由调用方传入，规则命中不了再交给上层走 AI 兜底。
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import date as date_cls
from typing import Any, Iterable

# 非交易消息：验证码、营销、额度提醒等，直接丢弃不占待确认队列
NOISE_PATTERNS = (
    "验证码", "校验码", "动态码", "动态密码", "激活码",
    "登录", "注册", "退订", "回复td", "营销", "优惠券", "抽奖", "问卷",
    "信用卡账单", "账单已出", "还款日", "最低还款",
    "提额", "额度调整", "临时额度", "额度提升",
    "积分兑换", "积分商城", "积分即将", "积分清零",
    "征信", "谨防", "防骗",
)

AMOUNT_PATTERNS = (
    r"(?:消费|支付|付款|扣款|支出|转出|取现|取款|还款|缴费|交易|收款|收入|入账|到账|转入|退款|汇入)"
    r"[^\d¥￥]{0,8}[¥￥]?\s*(?:人民币)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:元|人民币)?",
    r"(?:金额|交易金额|消费金额|支付金额)[:：]?\s*(?:人民币|RMB|CNY)?\s*[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)",
    r"[¥￥]\s*([\d,]+(?:\.\d{1,2})?)",
    r"([\d,]+\.\d{2})\s*元",
)

INCOME_WORDS = ("收入", "存入", "转入", "入账", "到账", "收款", "汇入", "退款", "退货", "工资", "代发", "利息", "返现")
EXPENSE_WORDS = ("消费", "支付", "付款", "支出", "转出", "取款", "取现", "扣款", "还款", "缴费", "购买")

# 常见银行名：命中但账户表里没有时，不硬套到默认账户，交给用户选
BANK_NAMES = (
    "中国银行", "工商银行", "建设银行", "农业银行", "交通银行", "招商银行",
    "邮储银行", "邮政储蓄", "中信银行", "浦发银行", "民生银行", "兴业银行",
    "光大银行", "平安银行", "广发银行", "华夏银行", "北京银行", "上海银行",
    "宁波银行", "江苏银行", "浙商银行", "恒丰银行", "渤海银行",
)

CATEGORY_RULES = (
    ("交通", ("地铁", "公交", "打车", "出租", "滴滴", "高铁", "火车", "加油", "充电", "停车", "ETC", "单车", "机票", "航空")),
    ("餐饮", ("餐", "饭", "咖啡", "奶茶", "外卖", "肯德基", "麦当劳", "星巴克", "瑞幸", "火锅", "烧烤", "面包", "早餐", "食堂")),
    ("购物", ("超市", "便利店", "淘宝", "天猫", "京东", "拼多多", "商城", "百货", "购物", "优衣库", "小米")),
    ("医疗", ("医院", "药房", "诊所", "体检", "挂号", "医疗")),
    ("居住", ("房租", "物业", "水费", "电费", "燃气", "宽带", "话费", "暖气")),
    ("娱乐", ("电影", "游戏", "KTV", "演出", "会员", "网易云")),
    ("人情", ("转账", "红包", "礼金", "随礼")),
)

MERCHANT_PATTERNS = (
    r"(?:向|给)\s*([^\s，,。；;:：]{2,20}?)\s*(?:支付|付款|转账)",
    r"在\s*([^\s，,。；;:：]{2,20}?)\s*(?:消费|支付|购物|用餐|购买)",
    r"(?:商户|特约商户|收款方|收款人|对方户名|对方)[:：]?\s*([^\s，,。；;:：]{2,20})",
)


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


def is_noise(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in NOISE_PATTERNS)


def extract_amount(text: str) -> str:
    """取第一个不像余额/额度的金额。"""
    for pattern in AMOUNT_PATTERNS:
        for match in re.finditer(pattern, text):
            context = text[max(0, match.start() - 6): match.start()]
            if any(word in context for word in ("余额", "可用", "额度", "限额", "剩余")):
                continue
            amount = normalize_amount(match.group(1))
            if amount != "0.00":
                return amount
    return ""


def extract_direction(text: str) -> str:
    if any(word in text for word in ("退款", "退货", "返现")):
        return "deposit"
    income_pos = min((text.find(w) for w in INCOME_WORDS if w in text), default=-1)
    expense_pos = min((text.find(w) for w in EXPENSE_WORDS if w in text), default=-1)
    if income_pos < 0 and expense_pos < 0:
        return ""
    if income_pos < 0:
        return "withdrawal"
    if expense_pos < 0:
        return "deposit"
    return "deposit" if income_pos < expense_pos else "withdrawal"


def extract_account(text: str, source: str, sender: str, account_names: Iterable[str]) -> str:
    names = list(account_names)
    for name in names:
        if name and name in text:
            return name
    for bank in BANK_NAMES:
        if bank in text:
            # 短信写「农业银行」，账户表里可能叫「农业银行卡」
            for name in names:
                if bank in name:
                    return name
            return ""  # 没登记这家银行，不要硬套到别的账户
    if "支付宝" in text:
        return "支付宝"
    if "微信" in text or "零钱" in text:
        return "微信零钱"
    lowered = (sender or "").lower()
    if "alipay" in lowered:
        return "支付宝"
    if "tencent" in lowered or lowered == "mm":
        return "微信零钱"
    bank_accounts = [name for name in names if "银行" in name or "卡" in name]
    if source == "sms" and len(bank_accounts) == 1:
        return bank_accounts[0]
    return ""


def extract_merchant(text: str) -> str:
    for pattern in MERCHANT_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()[:60]
    return ""


def extract_order_id(text: str) -> str:
    match = re.search(r"(?:订单号|交易单号|流水号|凭证号|交易序号)[:：]?\s*([A-Za-z0-9\-]{6,40})", text)
    return match.group(1) if match else ""


def guess_category(text: str) -> str:
    for category, keywords in CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return category
    return ""


def parse_ingest_text(
    text: str,
    source: str,
    sender: str,
    ts: int,
    account_names: Iterable[str],
    default_category: str = "其他",
) -> tuple[dict[str, Any] | None, str]:
    """规则解析。返回 (parsed, 说明)；金额没解析出来时返回 None，交给 AI 兜底。"""
    amount = extract_amount(text)
    if not amount:
        return None, "规则未识别到金额"

    direction = extract_direction(text) or "withdrawal"
    account = extract_account(text, source, sender, account_names)
    merchant = extract_merchant(text)
    category = guess_category(text) or (default_category if direction == "withdrawal" else "")
    moment = time.localtime(ts)
    confidence = 0.72
    if direction:
        confidence += 0.1
    if account:
        confidence += 0.1
    if merchant:
        confidence += 0.05

    parsed = {
        "type": direction,
        "date": time.strftime("%Y-%m-%d", moment),
        "time": time.strftime("%H:%M", moment),
        "amount": amount,
        "merchant": merchant,
        "description": text[:120],
        "account": account,
        "to_account": "",
        "category": category,
        "confidence": round(min(confidence, 0.95), 2),
        "order_id": extract_order_id(text),
    }
    return parsed, "规则解析"


# 微信/支付宝的转账、红包通知只有动作提示，金额在详情页里，通知本身拿不到
NOTIFICATION_HINTS = ("[转账]", "请收款", "已收款", "已退还", "[红包]", "红包", "待收款")


def parse_notification_hint(
    text: str,
    source: str,
    ts: int,
    account_names: Iterable[str],
) -> tuple[dict[str, Any] | None, str]:
    """给转账/红包通知一个半成品：带出对方名字和账户，只留金额待补。"""
    if source != "notification":
        return None, ""
    if not any(hint in text for hint in NOTIFICATION_HINTS):
        return None, ""
    if extract_amount(text):
        return None, ""

    names = list(account_names)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    merchant = ""
    if lines:
        first = re.sub(r"^\[\d+条\]\s*", "", lines[0])
        first = re.sub(r"^[^:：]{2,20}[:：]\s*", "", first)
        merchant = first.split("[")[0].strip()[:60]
    if merchant in {"微信支付", "支付宝", "微信", "服务通知", "WeChat"}:
        merchant = ""

    account = "支付宝" if "支付宝" in text else "微信零钱"
    moment = time.localtime(ts)
    parsed = {
        "type": "",
        "date": time.strftime("%Y-%m-%d", moment),
        "time": time.strftime("%H:%M", moment),
        "amount": "",
        "merchant": merchant,
        "description": text[:120],
        "account": account if account in names else "",
        "to_account": "",
        "category": "人情",
        "confidence": 0.3,
        "order_id": "",
    }
    return parsed, "转账/红包通知不带金额，补上金额再确认"


def ingest_fingerprint(source: str, sender: str, text: str, ts: int) -> str:
    """同一分钟内的相同原文视为同一条，避免重启后重复上报。"""
    normalized = re.sub(r"\s+", " ", text).strip()
    raw = "\x1f".join([source, sender or "", normalized, str(ts // 60)])
    return hashlib.sha256(raw.encode()).hexdigest()
