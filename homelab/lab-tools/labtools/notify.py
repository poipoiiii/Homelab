"""企业微信通知统一入口。

按配置自动选择后端，两者都配时优先自建应用：

1. 自建应用（推荐，发给个人）：``WECOM_CORP_ID`` + ``WECOM_SECRET`` + ``WECOM_AGENT_ID``，
   默认发给应用可见范围内的全部成员（``WECOM_TOUSER`` 默认 ``@all``）。
2. 群机器人（发给群）：``WECOM_WEBHOOK``，保留兼容原有配置。

注意：后台「接收消息」里的 Token / EncodingAESKey / 回调 URL 只用于校验回调，
与发消息无关。发消息需要的是应用详情页里的 Secret 和「我的企业」里的企业 ID。

未配置任何后端时不报错，只写 info 日志，方便本地调试。
"""

import logging
import os

from labtools.wecom import WeComApp, WeComWebhook

log = logging.getLogger("labtools.notify")


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


APP = WeComApp(
    corp_id=_env("WECOM_CORP_ID"),
    agent_id=_env("WECOM_AGENT_ID"),
    secret=_env("WECOM_SECRET"),
    touser=_env("WECOM_TOUSER") or "@all",
    toparty=_env("WECOM_TOPARTY"),
    totag=_env("WECOM_TOTAG"),
)
WEBHOOK = WeComWebhook(_env("WECOM_WEBHOOK"))


def backend() -> str:
    if APP.configured:
        return "app"
    if WEBHOOK.configured:
        return "webhook"
    return "none"


def enabled() -> bool:
    return backend() != "none"


def _missing_hint() -> str:
    return "未配置企业微信通知（WECOM_CORP_ID/WECOM_SECRET/WECOM_AGENT_ID 或 WECOM_WEBHOOK）"


def send_text(content: str) -> bool:
    """发送纯文本消息；失败只记日志，不影响主流程。"""
    if not content:
        return False
    if APP.configured:
        return APP.send_text(content)
    if WEBHOOK.configured:
        return WEBHOOK.send_text(content)
    log.info("%s，跳过通知：%s", _missing_hint(), content.splitlines()[0])
    return False


def send_markdown(content: str) -> bool:
    """发送 markdown 消息（自建应用与群机器人都支持）。"""
    if not content:
        return False
    if APP.configured:
        return APP.send_markdown(content)
    if WEBHOOK.configured:
        return WEBHOOK.send_markdown(content)
    log.info("%s，跳过通知：%s", _missing_hint(), content.splitlines()[0])
    return False
