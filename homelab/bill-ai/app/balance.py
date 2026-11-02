"""短信 / 通知里的账户余额识别。

规则集中在这个模块：关键词、金额模板、卡号尾号模板、来源过滤、去重窗口。
只依赖标准库，不碰数据库也不调模型，方便单独跑用例；账户匹配与入库在 store.py。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# 命中任意一个关键词才继续找金额；「余额宝」这类理财词不会被下面的模板命中
BALANCE_KEYWORDS = ("可用余额", "账户余额", "余额", "剩余")

# 余额 + 金额：支持「余额人民币12,345.67元」「可用余额 ¥1,234.5」「剩余 999.00 元」
BALANCE_PATTERN = (
    r"(?:可用余额|账户余额|余额|剩余)(?:为|是|[:：])?\s*"
    r"(?:人民币|RMB|CNY)?\s*[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:元|块钱)?"
)

# 只取卡号后 4 位：尾号1234 / 尾号 1234 / ****1234 / 卡号后四位1234
CARD_TAIL_PATTERNS = (
    r"尾号(?:为)?\s*(\d{4})(?!\d)",
    r"[*＊]{2,}\s*(\d{4})(?!\d)",
    r"卡号(?:后四位|末四位)(?:为)?\s*(\d{4})(?!\d)",
)

# 营销短信号段（106 开头）与关键词直接跳过，避免把广告里的「余额」当余额
IGNORED_SENDER_PREFIXES = ("106",)
IGNORED_SENDER_KEYWORDS = ("积分", "商城", "营销", "活动")

# 同一张卡同一金额在 5 分钟窗口内只留一条候选
DEDUP_WINDOW_SECONDS = 300

# 服务端时区（容器内 TZ=Asia/Shanghai），输出带偏移的 ISO8601
LOCAL_TZ = datetime.now().astimezone().tzinfo


@dataclass(frozen=True)
class BalanceCandidate:
    balance: str
    card_tail: str
    observed_at: str
    raw_hash: str
    dedup_key: str
    currency: str = "CNY"
    source: str = "sms"


def iso_time(ts: int) -> str:
    """Unix 秒 → 带时区的 ISO8601，精确到秒。"""
    return datetime.fromtimestamp(int(ts), tz=LOCAL_TZ).isoformat(timespec="seconds")


def normalize_balance(value: Any) -> str:
    """去掉千分位与货币符号，按两位小数输出；解析失败返回 "0.00"。"""
    text = str(value or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return "0.00"
    try:
        return f"{abs(float(match.group(0))):.2f}"
    except ValueError:
        return "0.00"


def extract_balance_amount(text: str) -> str:
    """取第一个「余额」后面的金额；没命中返回空串。"""
    match = re.search(BALANCE_PATTERN, text or "")
    if not match:
        return ""
    amount = normalize_balance(match.group(1))
    return "" if amount == "0.00" else amount


def extract_card_tail(text: str) -> str:
    for pattern in CARD_TAIL_PATTERNS:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1)
    return ""


def sender_ignored(sender: str) -> bool:
    value = (sender or "").strip().lower()
    if not value:
        return False
    if value.startswith(IGNORED_SENDER_PREFIXES):
        return True
    return any(word in value for word in IGNORED_SENDER_KEYWORDS)


def raw_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def dedup_key(card_tail: str, balance: str, ts: int, account_id: int | None = None) -> str:
    """(卡尾号或账户, 金额, 5 分钟窗口) 相同的记录只保留一条。"""
    anchor = f"acc:{account_id}" if account_id else f"card:{card_tail}"
    window = int(ts) // DEDUP_WINDOW_SECONDS
    return f"{anchor}|{balance}|{window}"


def parse_balance(text: str, source: str, sender: str, ts: int) -> BalanceCandidate | None:
    """识别一条余额短信/通知；缺关键词、金额或尾号时返回 None。"""
    if not text or not any(keyword in text for keyword in BALANCE_KEYWORDS):
        return None
    if sender_ignored(sender):
        return None
    balance = extract_balance_amount(text)
    card_tail = extract_card_tail(text)
    if not balance or not card_tail:
        return None
    return BalanceCandidate(
        balance=balance,
        card_tail=card_tail,
        observed_at=iso_time(ts),
        raw_hash=raw_hash(text),
        dedup_key=dedup_key(card_tail, balance, ts),
        source="sms" if source == "sms" else "notification",
    )
