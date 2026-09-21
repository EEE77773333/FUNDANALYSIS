"""
多通道通知推送系统
==================
支持企业微信、飞书、邮件三种通知渠道。
每个通道独立配置，支持广播发送。

架构:
    NotificationSender (ABC)
    ├── WechatWorkSender   — 企业微信机器人 Webhook
    ├── FeishuSender       — 飞书机器人 Webhook（支持签名校验）
    └── EmailSender        — SMTP 邮件

    NotificationManager    — 通道管理 + 配置持久化

使用方式:
    from core.notifications import get_notification_manager

    nm = get_notification_manager()
    nm.broadcast("基金预警", "华夏成长混合净值跌破止损线")
    nm.send_to_channel("my_wechat", "测试", "这是一条测试消息")
"""

import json
import time
import hashlib
import hmac
import base64
import smtplib
from abc import ABC, abstractmethod
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, List, Any
from pathlib import Path

import requests

from .persistence import load_notification_config, save_notification_config


# ============================================================
# 抽象基类
# ============================================================

class NotificationSender(ABC):
    """通知发送器抽象基类"""

    def __init__(self, config: dict):
        """
        Args:
            config: 通道配置字典，内容因通道类型而异
        """
        self.config = config

    @abstractmethod
    def send(self, title: str, content: str) -> bool:
        """
        发送通知。

        Args:
            title: 通知标题
            content: 通知正文（Markdown 格式）

        Returns:
            bool: 发送成功返回 True
        """

    @classmethod
    def create(cls, channel_type: str, config: dict) -> Optional['NotificationSender']:
        """
        工厂方法：根据类型字符串创建对应的发送器。

        Args:
            channel_type: "wechat_work" | "feishu" | "email"
            config: 通道配置

        Returns:
            NotificationSender 实例，类型未知时返回 None
        """
        type_map = {
            "wechat_work": WechatWorkSender,
            "feishu": FeishuSender,
            "email": EmailSender,
        }
        sender_cls = type_map.get(channel_type)
        if sender_cls:
            return sender_cls(config)
        return None


# ============================================================
# 企业微信
# ============================================================

class WechatWorkSender(NotificationSender):
    """
    企业微信机器人 Webhook 发送器。

    Config keys:
        webhook_url: str (必填) — Webhook 地址
    """

    def send(self, title: str, content: str) -> bool:
        webhook_url = self.config.get("webhook_url", "")
        if not webhook_url:
            return False

        # 格式化：title 加粗 + content
        markdown_text = f"## {title}\n\n{content}"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": markdown_text,
            },
        }

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            result = resp.json()
            return result.get("errcode") == 0
        except Exception:
            return False


# ============================================================
# 飞书
# ============================================================

class FeishuSender(NotificationSender):
    """
    飞书机器人 Webhook 发送器。

    Config keys:
        webhook_url: str (必填) — Webhook 地址
        secret: str (可选) — 签名校验密钥
    """

    def send(self, title: str, content: str) -> bool:
        webhook_url = self.config.get("webhook_url", "")
        if not webhook_url:
            return False

        # 飞书支持 Markdown 内容
        markdown_content = f"**{title}**\n\n{content}"

        payload: Dict[str, Any] = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title,
                    },
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }

        # 签名校验（可选）
        secret = self.config.get("secret", "")
        if secret:
            timestamp = str(int(time.time()))
            sign = self._gen_sign(timestamp, secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            result = resp.json()
            return result.get("code") == 0 or result.get("StatusCode") == 0
        except Exception:
            return False

    @staticmethod
    def _gen_sign(timestamp: str, secret: str) -> str:
        """生成飞书签名"""
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            key=secret.encode("utf-8"),
            msg=string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")


# ============================================================
# 邮件
# ============================================================

class EmailSender(NotificationSender):
    """
    SMTP 邮件发送器。

    Config keys:
        smtp_host: str   — SMTP 服务器地址
        smtp_port: int   — SMTP 端口（默认 587）
        username: str    — 发件人邮箱地址
        password: str    — SMTP 密码/授权码
        to_addresses: str — 收件人（逗号分隔）
        use_tls: bool    — 是否启用 TLS（默认 True）
    """

    def send(self, title: str, content: str) -> bool:
        smtp_host = self.config.get("smtp_host", "")
        smtp_port = int(self.config.get("smtp_port", 587))
        username = self.config.get("username", "")
        password = self.config.get("password", "")
        to_str = self.config.get("to_addresses", "")
        use_tls = self.config.get("use_tls", True)

        if not smtp_host or not username or not to_str:
            return False

        to_addresses = [a.strip() for a in to_str.split(",") if a.strip()]

        # 构建邮件
        msg = MIMEMultipart("alternative")
        msg["Subject"] = title
        msg["From"] = username
        msg["To"] = ", ".join(to_addresses)

        # 纯文本 + HTML 两个版本
        text_part = MIMEText(content, "plain", "utf-8")
        html_content = self._markdown_to_html(title, content)
        html_part = MIMEText(html_content, "html", "utf-8")
        msg.attach(text_part)
        msg.attach(html_part)

        try:
            # 端口 465 → SSL 直连；其他端口 → STARTTLS（勾选）或明文（不勾选）
            if smtp_port == 465:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if use_tls:
                    server.starttls()
            server.login(username, password)
            server.sendmail(username, to_addresses, msg.as_string())
            server.quit()
            return True
        except Exception:
            return False

    @staticmethod
    def _markdown_to_html(title: str, content: str) -> str:
        """将 Markdown 内容转为简易 HTML 邮件"""
        # 简易转换：标题 -> h2, 换行 -> <br>, 列表保留
        lines = content.split("\n")
        html_lines = [
            "<html><body>",
            f"<h2>{title}</h2>",
        ]
        for line in lines:
            line = line.strip()
            if line.startswith("### "):
                html_lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("- "):
                html_lines.append(f"<li>{line[2:]}</li>")
            elif line:
                html_lines.append(f"<p>{line}</p>")
        html_lines.append("</body></html>")
        return "\n".join(html_lines)


# ============================================================
# 通知管理器
# ============================================================

class NotificationManager:
    """
    管理所有通知通道。

    配置存储在 data/notification_config.json，格式:
    {
        "channels": {
            "my_wechat": {
                "type": "wechat_work",
                "enabled": true,
                "config": {"webhook_url": "https://..."}
            },
            "my_feishu": {
                "type": "feishu",
                "enabled": true,
                "config": {"webhook_url": "https://...", "secret": "..."}
            },
            "my_email": {
                "type": "email",
                "enabled": true,
                "config": {"smtp_host": "smtp.gmail.com", ...}
            }
        }
    }
    """

    def __init__(self):
        self._senders: Dict[str, NotificationSender] = {}
        self._channel_configs: Dict[str, dict] = {}
        self.reload()

    def reload(self):
        """重新加载配置并初始化发送器"""
        config = load_notification_config()
        self._channel_configs = config.get("channels", {})
        self._senders = {}

        for name, ch in self._channel_configs.items():
            if not ch.get("enabled", True):
                continue
            sender = NotificationSender.create(
                ch.get("type", ""),
                ch.get("config", {}),
            )
            if sender:
                self._senders[name] = sender

    def _save(self):
        """保存当前配置"""
        save_notification_config({
            "channels": self._channel_configs,
        })

    def add_channel(self, name: str, channel_type: str, config: dict):
        """
        添加或更新一个通知通道。

        Args:
            name: 通道名称（唯一标识）
            channel_type: 通道类型（wechat_work / feishu / email）
            config: 通道配置字典
        """
        self._channel_configs[name] = {
            "type": channel_type,
            "enabled": True,
            "config": config,
        }
        self._save()
        self.reload()

    def remove_channel(self, name: str):
        """删除一个通知通道"""
        self._channel_configs.pop(name, None)
        self._save()
        self.reload()

    def toggle_channel(self, name: str, enabled: bool):
        """启用/禁用一个通道"""
        if name in self._channel_configs:
            self._channel_configs[name]["enabled"] = enabled
            self._save()
            self.reload()

    def get_channels(self) -> dict:
        """返回所有配置的通道"""
        return self._channel_configs

    def send_to_channel(self, name: str, title: str, content: str) -> bool:
        """
        向指定通道发送通知。

        Args:
            name: 通道名称
            title: 通知标题
            content: 通知正文

        Returns:
            bool: 发送成功返回 True
        """
        sender = self._senders.get(name)
        if not sender:
            return False
        return sender.send(title, content)

    def broadcast(self, title: str, content: str) -> Dict[str, bool]:
        """
        向所有已启用通道广播通知。

        Returns:
            dict: {通道名称: 是否成功}
        """
        results = {}
        for name, sender in self._senders.items():
            results[name] = sender.send(title, content)
        return results


# ============================================================
# 单例
# ============================================================

import threading as _threading

_notification_manager: Optional[NotificationManager] = None
_notification_manager_lock = _threading.Lock()


def get_notification_manager() -> NotificationManager:
    """获取 NotificationManager 全局单例（线程安全）"""
    global _notification_manager
    if _notification_manager is None:
        with _notification_manager_lock:
            if _notification_manager is None:
                _notification_manager = NotificationManager()
    return _notification_manager
