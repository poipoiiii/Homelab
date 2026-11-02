"""企业微信消息客户端：自建应用（可发给个人）与群机器人（发到群）。

自建应用支持 text / markdown / textcard：
- access_token 进程内缓存，过期前自动刷新；
- token 失效（40014 / 42001 / 41001）时强制刷新并重试一次；
- 所有文本按 UTF-8 字节截断到官方上限，避免中文超长被拒；
- 任何失败只记日志并返回 False，不向调用方抛异常。
"""

import logging
import threading
import time

import httpx

log = logging.getLogger("labtools.wecom")

# httpx 的 INFO 日志会把 gettoken 的 corpsecret、message/send 的 access_token 写进容器日志
logging.getLogger("httpx").setLevel(logging.WARNING)

API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
TIMEOUT = 8

# token 无效 / 过期 / 缺失，需要刷新后重试
TOKEN_ERRCODES = frozenset({40014, 42001, 41001})

# 企业微信官方上限（单位：UTF-8 字节）
TEXT_MAX = 2048
MARKDOWN_MAX = 4096
CARD_TITLE_MAX = 128
CARD_DESC_MAX = 512
CARD_URL_MAX = 2048
CARD_BTN_MAX = 16


def clip_bytes(text: str, limit: int) -> str:
    """按 UTF-8 字节截断，不切断多字节字符。"""
    value = text or ""
    raw = value.encode("utf-8")
    if len(raw) <= limit:
        return value
    return raw[:limit].decode("utf-8", "ignore")


def _json(response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


class WeComWebhook:
    """群机器人：只支持 text / markdown；textcard 退化为 markdown。"""

    def __init__(self, url: str):
        self.url = (url or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def _send(self, payload: dict) -> bool:
        if not self.configured:
            log.info("未配置 WECOM_WEBHOOK，跳过群机器人消息")
            return False
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(self.url, json=payload)
            response.raise_for_status()
            data = _json(response)
            if data.get("errcode") not in (0, None):
                log.warning("企业微信群机器人发送失败：%s", data)
                return False
            return True
        except Exception as exc:  # noqa: BLE001  失败只记日志
            log.warning("企业微信群机器人发送异常：%s", exc)
            return False

    def send_text(self, content: str) -> bool:
        if not (content or "").strip():
            return False
        return self._send({
            "msgtype": "text",
            "text": {"content": clip_bytes(content, TEXT_MAX)},
        })

    def send_markdown(self, content: str) -> bool:
        if not (content or "").strip():
            return False
        return self._send({
            "msgtype": "markdown",
            "markdown": {"content": clip_bytes(content, MARKDOWN_MAX)},
        })

    def send_textcard(self, title: str, description: str, url: str, btntxt: str = "详情") -> bool:
        content = f"**{title or ''}**\n{description or ''}\n[{btntxt or '详情'}]({url or ''})"
        log.info("群机器人不支持 textcard，已降级为 markdown")
        return self.send_markdown(content)


class WeComApp:
    """自建应用：支持 text / markdown / textcard，发给指定成员或 @all。"""

    def __init__(self, corp_id: str = "", agent_id: str = "", secret: str = "",
                 touser: str = "@all", toparty: str = "", totag: str = ""):
        self.corp_id = (corp_id or "").strip()
        self.agent_id = (agent_id or "").strip()
        self.secret = (secret or "").strip()
        self.touser = (touser or "@all").strip()
        self.toparty = (toparty or "").strip()
        self.totag = (totag or "").strip()

        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.corp_id and self.secret and self.agent_id)

    def _agent(self) -> int | None:
        try:
            return int(self.agent_id)
        except (TypeError, ValueError):
            log.warning("WECOM_AGENT_ID 不是数字：%r", self.agent_id)
            return None

    def _fetch_token(self, client: httpx.Client) -> str:
        """调用方需持有 self._lock。"""
        response = client.get(
            f"{API_BASE}/gettoken",
            params={"corpid": self.corp_id, "corpsecret": self.secret},
        )
        response.raise_for_status()
        data = _json(response)
        token = data.get("access_token")
        if data.get("errcode", 0) != 0 or not token:
            log.warning("获取企业微信 access_token 失败：%s", data)
            return ""

        expires_in = int(data.get("expires_in") or 7200)
        self._token = token
        # 提前 5 分钟过期，避免边界上拿到刚失效的 token
        self._expires_at = time.time() + max(60, expires_in - 300)
        return token

    def _access_token(self, client: httpx.Client, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._expires_at:
                return self._token
            return self._fetch_token(client)

    def _post(self, client: httpx.Client, token: str, payload: dict) -> dict:
        response = client.post(
            f"{API_BASE}/message/send",
            params={"access_token": token},
            json=payload,
        )
        response.raise_for_status()
        return _json(response)

    def _send(self, message: dict) -> bool:
        if not self.configured:
            log.info("未配置 WECOM_CORP_ID / WECOM_SECRET / WECOM_AGENT_ID，跳过应用消息")
            return False
        agent = self._agent()
        if agent is None:
            return False

        payload = {
            "touser": self.touser or "@all",
            "toparty": self.toparty,
            "totag": self.totag,
            "agentid": agent,
            "safe": 0,
            **message,
        }
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                token = self._access_token(client)
                if not token:
                    return False

                data = self._post(client, token, payload)
                if data.get("errcode") in TOKEN_ERRCODES:
                    log.info("企业微信 access_token 失效（%s），刷新后重试一次", data.get("errcode"))
                    token = self._access_token(client, force=True)
                    if not token:
                        return False
                    data = self._post(client, token, payload)

                if data.get("errcode") not in (0, None):
                    log.warning("企业微信应用消息发送失败：%s", data)
                    return False
                return True
        except Exception as exc:  # noqa: BLE001  失败只记日志
            log.warning("企业微信应用消息发送异常：%s", exc)
            return False

    def send_text(self, content: str) -> bool:
        if not (content or "").strip():
            return False
        return self._send({
            "msgtype": "text",
            "text": {"content": clip_bytes(content, TEXT_MAX)},
        })

    def send_markdown(self, content: str) -> bool:
        if not (content or "").strip():
            return False
        return self._send({
            "msgtype": "markdown",
            "markdown": {"content": clip_bytes(content, MARKDOWN_MAX)},
        })

    def send_textcard(self, title: str, description: str, url: str, btntxt: str = "详情") -> bool:
        if not (title or "").strip() or not (url or "").strip():
            log.warning("textcard 需要 title 和 url")
            return False
        return self._send({
            "msgtype": "textcard",
            "textcard": {
                "title": clip_bytes(title, CARD_TITLE_MAX),
                "description": clip_bytes(description, CARD_DESC_MAX),
                "url": clip_bytes(url, CARD_URL_MAX),
                "btntxt": clip_bytes(btntxt or "详情", CARD_BTN_MAX),
            },
        })
