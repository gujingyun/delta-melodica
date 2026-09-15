"""对桌面端用户可见的错误文本进行统一脱敏。"""
from __future__ import annotations

import re
import socket
import ssl
import urllib.error


_URL_RE = re.compile(r"\b(?:https?|wss?)://[^\s)]+", re.IGNORECASE)
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6_RE = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")
_DOMAIN_RE = re.compile(
    r"(?<![\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)
_PORT_RE = re.compile(r"(?i)(?<![\w])port\s+\d{1,5}(?!\w)")

_NETWORK_TYPES = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    socket.timeout,
    ssl.SSLError,
)
_NETWORK_MARKERS = (
    "failed to connect",
    "urlopen error",
    "timed out",
    "timeout",
    "connection",
    "network is unreachable",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "ssl",
    "socket",
)


def _is_network_error(error) -> bool:
    """判断异常是否属于不应把底层连接细节展示给用户的网络错误。"""
    if isinstance(error, _NETWORK_TYPES):
        return True
    name = type(error).__name__.lower()
    if any(marker in name for marker in ("timeout", "connect", "socket", "network", "ssl", "urlerror")):
        return True
    text = str(error).lower()
    return any(marker in text for marker in _NETWORK_MARKERS)


def redact_error(value) -> str:
    """隐藏异常文本中的 URL、IP、域名和端口，保留其余本地错误说明。"""
    if value is None:
        return ""
    text = str(value)
    text = _URL_RE.sub("[网络地址已隐藏]", text)
    text = _IPV6_RE.sub("[地址已隐藏]", text)
    text = _IPV4_RE.sub("[地址已隐藏]", text)
    text = _DOMAIN_RE.sub("[域名已隐藏]", text)
    text = _PORT_RE.sub("端口已隐藏", text)
    return text.strip()


def user_error(error, fallback="操作失败") -> str:
    """生成适合界面展示的错误信息，网络异常统一使用通用提示。"""
    if error is None:
        return fallback
    if _is_network_error(error):
        return fallback
    return redact_error(error) or fallback
