"""
Freemail 邮箱服务实现
"""

import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from curl_cffi import requests as cffi_requests

from .base import BaseEmailService, EmailServiceError, EmailServiceType
from ..config.constants import OTP_CODE_PATTERN

logger = logging.getLogger(__name__)

OPENAI_SENDER_HINTS = ("openai", "chatgpt", "tm.openai", "system@openai")
OPENAI_SUBJECT_HINTS = ("openai", "chatgpt", "verification", "verify", "code", "验证码")


class FreemailService(BaseEmailService):
    def __init__(self, config: Dict[str, Any] = None, name: str = None):
        super().__init__(EmailServiceType.FREEMAIL, name)
        required_keys = ["base_url", "admin_token"]
        missing_keys = [key for key in required_keys if not (config or {}).get(key)]
        if missing_keys:
            raise ValueError(f"缺少必需配置: {missing_keys}")

        default_config = {
            "timeout": 30,
            "poll_interval": 3,
            "mail_limit": 20,
            "max_retries": 3,
            "retry_delay": 1,
        }
        self.config = {**default_config, **(config or {})}
        self.config["base_url"] = str(self.config["base_url"]).rstrip("/")
        self.config["admin_token"] = str(self.config["admin_token"]).strip()

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "CPA-Codex-Manager/1.0",
            "Connection": "close",
        })
        self.cffi_session = cffi_requests.Session(
            impersonate="chrome",
            timeout=self.config["timeout"],
            verify=True,
        )
        self.cffi_session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Connection": "close",
        })
        self._created_emails: Dict[str, Dict[str, Any]] = {}
        self._seen_email_ids: Dict[str, set] = {}

    def _headers(self) -> Dict[str, str]:
        token = self.config["admin_token"]
        return {
            "Authorization": f"Bearer {token}",
            "X-Admin-Token": token,
        }

    @staticmethod
    def _parse_response_json(response: Any, method: str, path: str) -> Any:
        if not getattr(response, "text", ""):
            return {}
        try:
            return response.json()
        except ValueError as e:
            raise EmailServiceError(f"响应解析失败: {method} {path} - {e}")

    @staticmethod
    def _raise_for_status(response: Any, method: str, path: str) -> None:
        status_code = int(getattr(response, "status_code", 0))
        if status_code >= 400:
            error_text = str(getattr(response, "text", ""))[:300]
            raise EmailServiceError(f"请求失败: {status_code} {method} {path} - {error_text}")

    def _request_via_requests(
        self,
        method: str,
        url: str,
        path: str,
        request_kwargs: Dict[str, Any],
    ) -> Any:
        retries = max(0, int(self.config.get("max_retries", 3)))
        retry_delay = max(0, float(self.config.get("retry_delay", 1)))
        last_error: Optional[Exception] = None

        for attempt in range(retries + 1):
            try:
                response = self.session.request(method, url, **request_kwargs)
                status_code = int(response.status_code)
                if status_code >= 500 or status_code == 429:
                    last_error = EmailServiceError(f"请求失败: {status_code} {method} {path} - {response.text[:300]}")
                    if attempt < retries:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
                    raise last_error
                self._raise_for_status(response, method, path)
                return self._parse_response_json(response, method, path)
            except requests.RequestException as e:
                last_error = e
                if attempt < retries:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                raise EmailServiceError(f"请求失败: {method} {path} - {e}")

        raise EmailServiceError(f"请求失败: {method} {path} - {last_error}")

    def _request_via_cffi(
        self,
        method: str,
        url: str,
        path: str,
        request_kwargs: Dict[str, Any],
    ) -> Any:
        try:
            response = self.cffi_session.request(method, url, **request_kwargs)
            self._raise_for_status(response, method, path)
            return self._parse_response_json(response, method, path)
        except EmailServiceError:
            raise
        except Exception as e:
            raise EmailServiceError(f"请求失败: {method} {path} - cffi兜底失败: {e}")

    def _make_request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.config['base_url']}{path}"
        request_kwargs = dict(kwargs)
        request_kwargs.setdefault("headers", {})
        request_kwargs["headers"].update(self._headers())
        request_kwargs.setdefault("timeout", self.config["timeout"])
        try:
            return self._request_via_requests(method, url, path, request_kwargs)
        except EmailServiceError as primary_error:
            try:
                return self._request_via_cffi(method, url, path, request_kwargs)
            except EmailServiceError as fallback_error:
                raise EmailServiceError(f"{primary_error}; {fallback_error}")

    @staticmethod
    def _parse_received_ts(received_at: Optional[str]) -> Optional[float]:
        if not received_at:
            return None
        try:
            return datetime.strptime(received_at, "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            return None

    @staticmethod
    def _normalize_domains(raw_domain: Any) -> List[str]:
        if raw_domain is None:
            return []
        if isinstance(raw_domain, list):
            return [str(item).strip() for item in raw_domain if str(item).strip()]
        if isinstance(raw_domain, str):
            if "," in raw_domain:
                return [item.strip() for item in raw_domain.split(",") if item.strip()]
            value = raw_domain.strip()
            return [value] if value else []
        value = str(raw_domain).strip()
        return [value] if value else []

    def _resolve_domain_index(self, req_config: Dict[str, Any]) -> Optional[int]:
        if req_config.get("domainIndex") is not None:
            try:
                return int(req_config.get("domainIndex"))
            except Exception:
                return None

        requested_domains = self._normalize_domains(req_config.get("domain"))
        config_domains = self._normalize_domains(self.config.get("domain"))
        preferred_domains = requested_domains or config_domains
        if not preferred_domains:
            return None

        try:
            all_domains = self._make_request("GET", "/api/domains")
        except Exception:
            return None
        if not isinstance(all_domains, list) or not all_domains:
            return None

        allowed = {item.lower() for item in preferred_domains}
        candidate_indexes = [
            idx for idx, domain in enumerate(all_domains)
            if str(domain).strip().lower() in allowed
        ]
        if not candidate_indexes:
            return None
        return random.choice(candidate_indexes)

    def create_email(self, config: Dict[str, Any] = None) -> Dict[str, Any]:
        req_config = config or {}
        payload = {}
        local = (req_config.get("name") or req_config.get("local") or "").strip()
        domain_index = self._resolve_domain_index(req_config)
        if domain_index is not None:
            payload["domainIndex"] = domain_index

        if local:
            payload["local"] = local
            data = self._make_request("POST", "/api/create", json=payload)
        else:
            if req_config.get("length") is not None:
                payload["length"] = req_config.get("length")
            data = self._make_request("GET", "/api/generate", params=payload)

        email = str(data.get("email", "")).strip()
        if not email:
            self.update_status(False, EmailServiceError("Freemail 返回数据中缺少 email"))
            raise EmailServiceError("Freemail 返回数据中缺少 email")

        email_info = {
            "email": email,
            "service_id": email,
            "id": email,
            "expires": data.get("expires"),
            "created_at": time.time(),
        }
        self._created_emails[email] = email_info
        self.update_status(True)
        return email_info

    def _extract_code(self, content: str, pattern: str) -> Optional[str]:
        if not content:
            return None
        match = re.search(pattern, content)
        return match.group(1) if match else None

    def get_verification_code(
        self,
        email: str,
        email_id: str = None,
        timeout: int = 120,
        pattern: str = OTP_CODE_PATTERN,
        otp_sent_at: Optional[float] = None,
    ) -> Optional[str]:
        target_email = email_id or email
        start_time = time.time()
        if target_email not in self._seen_email_ids:
            self._seen_email_ids[target_email] = set()
        seen_ids = self._seen_email_ids[target_email]

        while time.time() - start_time < timeout:
            try:
                messages = self._make_request(
                    "GET",
                    "/api/emails",
                    params={
                        "mailbox": target_email,
                        "limit": self.config.get("mail_limit", 20),
                    },
                )
                if not isinstance(messages, list):
                    messages = []

                for item in messages:
                    message_id = item.get("id")
                    if not message_id or message_id in seen_ids:
                        continue

                    received_ts = self._parse_received_ts(item.get("received_at"))
                    if otp_sent_at and received_ts and received_ts < otp_sent_at:
                        seen_ids.add(message_id)
                        continue

                    sender = str(item.get("sender", "")).lower()
                    subject = str(item.get("subject", ""))
                    preview = str(item.get("preview", ""))
                    combined = f"{sender}\n{subject}\n{preview}"
                    subject_lower = subject.lower()

                    looks_like_openai = any(h in sender for h in OPENAI_SENDER_HINTS) or any(
                        h in subject_lower for h in OPENAI_SUBJECT_HINTS
                    )
                    if not looks_like_openai and "openai" not in combined.lower():
                        seen_ids.add(message_id)
                        continue

                    code = self._extract_code(str(item.get("verification_code") or ""), pattern)
                    if not code:
                        code = self._extract_code(combined, pattern)
                    if code:
                        seen_ids.add(message_id)
                        self.update_status(True)
                        return code

                    detail = self._make_request("GET", f"/api/email/{message_id}")
                    detail_content = "\n".join([
                        str(detail.get("subject", "")),
                        str(detail.get("content", "")),
                        str(detail.get("html_content", "")),
                        str(detail.get("verification_code", "")),
                    ])
                    code = self._extract_code(detail_content, pattern)
                    if code:
                        seen_ids.add(message_id)
                        self.update_status(True)
                        return code

                    seen_ids.add(message_id)

            except Exception as e:
                logger.debug(f"Freemail 获取验证码轮询异常: {e}")

            time.sleep(int(self.config.get("poll_interval", 3)))

        return None

    def list_emails(self, **kwargs) -> List[Dict[str, Any]]:
        return list(self._created_emails.values())

    def delete_email(self, email_id: str) -> bool:
        target_email = email_id
        try:
            result = self._make_request("DELETE", "/api/mailboxes", params={"address": target_email})
            deleted = bool(result.get("deleted", result.get("success", False)))
            if deleted and target_email in self._created_emails:
                del self._created_emails[target_email]
            self.update_status(True)
            return deleted
        except Exception as e:
            logger.warning(f"Freemail 删除邮箱失败: {target_email} - {e}")
            self.update_status(False, e)
            if target_email in self._created_emails:
                del self._created_emails[target_email]
                return True
            return False

    def check_health(self) -> bool:
        try:
            data = self._make_request("GET", "/api/session")
            healthy = bool(data.get("authenticated", True))
            self.update_status(healthy)
            return healthy
        except Exception as e:
            self.update_status(False, e)
            return False

    def get_email_messages(self, email_id: str, **kwargs) -> List[Dict[str, Any]]:
        try:
            data = self._make_request(
                "GET",
                "/api/emails",
                params={
                    "mailbox": email_id,
                    "limit": kwargs.get("limit", self.config.get("mail_limit", 20)),
                },
            )
            if isinstance(data, list):
                self.update_status(True)
                return data
            return []
        except Exception as e:
            logger.error(f"Freemail 获取邮件列表失败: {email_id} - {e}")
            self.update_status(False, e)
            return []

    def get_service_info(self) -> Dict[str, Any]:
        return {
            "service_type": self.service_type.value,
            "name": self.name,
            "base_url": self.config["base_url"],
            "domain": self.config.get("domain"),
            "has_admin_token": bool(self.config.get("admin_token")),
            "cached_emails_count": len(self._created_emails),
            "status": self.status.value,
        }
