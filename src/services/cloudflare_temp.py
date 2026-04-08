"""
Cloudflare 临时邮箱服务实现
基于 dreamhunter2333/cloudflare_temp_email API
"""

import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from .base import BaseEmailService, EmailServiceError, EmailServiceType
from ..config.constants import OTP_CODE_PATTERN

logger = logging.getLogger(__name__)

OPENAI_SENDER_HINTS = ("openai", "chatgpt", "tm.openai", "system@openai", "noreply@openai.com")
OPENAI_SUBJECT_HINTS = ("openai", "chatgpt", "verification", "verify", "code", "otp", "验证码")


class CloudflareTempService(BaseEmailService):
    """
    Cloudflare 临时邮箱服务
    基于 Cloudflare Workers + Pages 部署的临时邮箱系统
    API: https://tml.yltkj.ggff.net/
    """

    def __init__(self, config: Dict[str, Any] = None, name: str = None):
        super().__init__(EmailServiceType.CLOUDFLARE_TEMP, name)

        default_config = {
            "base_url": "https://tml.yltkj.ggff.net",
            "timeout": 30,
            "poll_interval": 3,
            "mail_limit": 20,
            "max_retries": 3,
            "retry_delay": 1,
            "domain": "yltkj.ggff.net",
        }
        self.config = {**default_config, **(config or {})}
        self.config["base_url"] = str(self.config["base_url"]).rstrip("/")

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "CPA-Codex-Manager/1.0",
        })

        # 缓存邮箱信息: email -> {jwt, address, email_id}
        self._email_cache: Dict[str, Dict[str, Any]] = {}
        # 已见过的邮件 ID，防止重复处理
        self._seen_mail_ids: Dict[str, set] = {}

    def _make_request(
        self,
        method: str,
        path: str,
        email_jwt: str = None,
        **kwargs
    ) -> Any:
        """
        发送请求的封装方法

        Args:
            method: HTTP 方法
            path: API 路径
            email_jwt: 邮箱 JWT token（用于认证）
            **kwargs: 其他请求参数
        """
        url = f"{self.config['base_url']}{path}"
        headers = kwargs.pop("headers", {})
        headers["Accept"] = "application/json"
        headers["Content-Type"] = "application/json"

        # 添加邮箱 JWT 认证
        if email_jwt:
            headers["Authorization"] = f"Bearer {email_jwt}"

        retries = max(0, int(self.config.get("max_retries", 3)))
        retry_delay = max(0, float(self.config.get("retry_delay", 1)))
        last_error: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=self.config.get("timeout", 30),
                    **kwargs
                )
                status_code = int(response.status_code)

                # 5xx 或 429 重试
                if status_code >= 500 or status_code == 429:
                    last_error = EmailServiceError(f"请求失败: {status_code} {method} {path}")
                    if attempt < retries:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    raise last_error

                if status_code >= 400:
                    error_text = str(response.text)[:300]
                    raise EmailServiceError(f"请求失败: {status_code} {method} {path} - {error_text}")

                if not response.text:
                    return {}

                return response.json()

            except requests.RequestException as e:
                last_error = e
                if attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                raise EmailServiceError(f"请求失败: {method} {path} - {e}")

        raise EmailServiceError(f"请求失败: {method} {path} - {last_error}")

    def create_email(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        创建新的临时邮箱

        Args:
            config: 配置参数，支持:
                - name: 邮箱名前缀（可选，不提供则随机生成）
                - domain: 域名（可选，默认使用配置的 domain）

        Returns:
            包含邮箱信息的字典:
            - email: 邮箱地址
            - service_id: 邮箱地址（同 email）
            - jwt: 访问 JWT token
            - created_at: 创建时间戳
        """
        req_config = config or {}
        domain = req_config.get("domain") or self.config.get("domain", "yltkj.ggff.net")
        name = req_config.get("name")

        # 如果没有提供 name，随机生成
        if not name:
            name = self._generate_random_name()

        payload = {
            "name": name,
            "domain": domain,
        }

        try:
            data = self._make_request("POST", "/api/new_address", **payload)
        except Exception as e:
            # 尝试无 body 的创建方式（某些版本兼容）
            try:
                data = self._make_request("POST", "/api/new_address", json={"address": f"{name}@{domain}"})
            except Exception:
                # 直接用 GET 方式
                data = self._make_request("GET", "/api/new_address", params=payload)

        email = str(data.get("address", "")).strip()
        jwt = str(data.get("jwt", "")).strip()

        if not email:
            self.update_status(False, EmailServiceError("Cloudflare 邮箱返回数据中缺少 email"))
            raise EmailServiceError("Cloudflare 邮箱返回数据中缺少 email")

        # 缓存邮箱信息
        email_info = {
            "email": email,
            "service_id": email,
            "id": email,
            "jwt": jwt,
            "created_at": time.time(),
        }
        self._email_cache[email] = email_info
        if email not in self._seen_mail_ids:
            self._seen_mail_ids[email] = set()

        logger.info(f"Cloudflare 临时邮箱创建成功: {email}")
        self.update_status(True)
        return email_info

    def _generate_random_name(self) -> str:
        """生成随机邮箱名"""
        chars = "abcdefghijklmnopqrstuvwxyz0123456789"
        length = random.randint(6, 10)
        return "".join(random.choice(chars) for _ in range(length))

    def get_verification_code(
        self,
        email: str,
        email_id: str = None,
        timeout: int = 120,
        pattern: str = OTP_CODE_PATTERN,
        otp_sent_at: Optional[float] = None,
    ) -> Optional[str]:
        """
        获取 OpenAI 验证码

        Args:
            email: 邮箱地址
            email_id: 邮箱 ID（不使用，直接用 email 查缓存）
            timeout: 超时时间（秒）
            pattern: 验证码正则表达式
            otp_sent_at: OTP 发送时间戳

        Returns:
            验证码字符串，如果超时或未找到返回 None
        """
        # 获取 JWT token
        email_info = self._email_cache.get(email)
        if not email_info:
            logger.warning(f"未找到邮箱 {email} 的缓存信息")
            return None

        jwt = email_info.get("jwt")
        if not jwt:
            logger.warning(f"邮箱 {email} 没有 JWT token")
            return None

        target_email = email
        if target_email not in self._seen_mail_ids:
            self._seen_mail_ids[target_email] = set()
        seen_ids = self._seen_mail_ids[target_email]

        start_time = time.time()
        poll_interval = max(1, int(self.config.get("poll_interval", 3)))

        logger.info(f"正在等待邮箱 {email} 的验证码...")

        while time.time() - start_time < timeout:
            try:
                messages = self._make_request(
                    "GET",
                    f"/api/mails?limit={self.config.get('mail_limit', 20)}&offset=0",
                    email_jwt=jwt
                )

                # 处理响应格式
                if isinstance(messages, dict):
                    email_list = messages.get("mails", messages.get("emails", []))
                    count = messages.get("count", 0)
                elif isinstance(messages, list):
                    email_list = messages
                    count = len(messages)
                else:
                    email_list = []
                    count = 0

                if count == 0 and not email_list:
                    logger.debug(f"邮箱 {email} 暂无新邮件")
                    time.sleep(poll_interval)
                    continue

                for item in email_list:
                    if not isinstance(item, dict):
                        continue

                    mail_id = item.get("id")
                    if not mail_id or mail_id in seen_ids:
                        continue

                    # 解析邮件内容
                    sender = str(item.get("from", item.get("sender", ""))).lower()
                    subject = str(item.get("subject", ""))
                    body = str(item.get("body", item.get("content", "")))
                    html = str(item.get("html", item.get("html_content", "")))
                    received_at = item.get("received_at", item.get("date"))

                    # 检查时间戳，过滤旧邮件
                    if otp_sent_at and received_at:
                        try:
                            received_ts = datetime.strptime(received_at, "%Y-%m-%d %H:%M:%S").timestamp()
                            if received_ts < otp_sent_at:
                                seen_ids.add(mail_id)
                                continue
                        except Exception:
                            pass

                    combined = f"{sender}\n{subject}\n{body}\n{html}"

                    # 检查是否是 OpenAI 相关邮件
                    looks_like_openai = (
                        any(h in sender for h in OPENAI_SENDER_HINTS) or
                        any(h in subject.lower() for h in OPENAI_SUBJECT_HINTS) or
                        "openai" in combined.lower()
                    )
                    if not looks_like_openai:
                        seen_ids.add(mail_id)
                        continue

                    # 尝试从各字段提取验证码
                    code = self._extract_code(str(item.get("verification_code", "")), pattern)
                    if not code:
                        code = self._extract_code(combined, pattern)

                    if code:
                        logger.info(f"已获取验证码: {code}")
                        seen_ids.add(mail_id)
                        self.update_status(True)
                        return code

                    # 标记为已处理
                    seen_ids.add(mail_id)

            except EmailServiceError as e:
                logger.debug(f"获取邮件时出错: {e}")

            time.sleep(poll_interval)

        logger.warning(f"等待验证码超时: {email}")
        return None

    def _extract_code(self, content: str, pattern: str) -> Optional[str]:
        """从内容中提取验证码"""
        if not content:
            return None
        match = re.search(pattern, content)
        return match.group(1) if match else None

    def list_emails(self, **kwargs) -> List[Dict[str, Any]]:
        """列出所有缓存的邮箱"""
        return list(self._email_cache.values())

    def delete_email(self, email_id: str) -> bool:
        """删除邮箱（Cloudflare 临时邮箱通常自动过期，这里仅从缓存移除）"""
        if email_id in self._email_cache:
            del self._email_cache[email_id]
            logger.info(f"从缓存中移除邮箱: {email_id}")
            return True
        return False

    def check_health(self) -> bool:
        """检查服务健康状态"""
        try:
            data = self._make_request("GET", "/open_api/settings")
            if data and isinstance(data, dict):
                self.update_status(True)
                return True
            return False
        except Exception as e:
            logger.warning(f"Cloudflare 临时邮箱健康检查失败: {e}")
            self.update_status(False, e)
            return False

    def get_email_messages(self, email_id: str, **kwargs) -> List[Dict[str, Any]]:
        """获取邮箱中的邮件列表"""
        email_info = self._email_cache.get(email_id)
        if not email_info:
            return []

        jwt = email_info.get("jwt")
        if not jwt:
            return []

        try:
            messages = self._make_request(
                "GET",
                f"/api/mails?limit={kwargs.get('limit', 20)}&offset=0",
                email_jwt=jwt
            )

            if isinstance(messages, dict):
                return messages.get("mails", messages.get("emails", []))
            elif isinstance(messages, list):
                return messages
            return []
        except Exception as e:
            logger.error(f"获取邮件列表失败: {email_id} - {e}")
            return []

    def get_service_info(self) -> Dict[str, Any]:
        """获取服务信息"""
        return {
            "service_type": self.service_type.value,
            "name": self.name,
            "base_url": self.config["base_url"],
            "domain": self.config.get("domain"),
            "cached_emails_count": len(self._email_cache),
            "status": self.status.value,
        }
