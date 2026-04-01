"""
邮箱服务模块
"""

from .base import (
    BaseEmailService,
    EmailServiceError,
    EmailServiceStatus,
    EmailServiceFactory,
    create_email_service,
    EmailServiceType
)
from .tempmail import TempmailService
from .cloud_mail import CloudMailService
from .freemail import FreemailService

# 注册核心服务
EmailServiceFactory.register(EmailServiceType.TEMPMAIL, TempmailService)
EmailServiceFactory.register(EmailServiceType.CLOUD_MAIL, CloudMailService)
EmailServiceFactory.register(EmailServiceType.FREEMAIL, FreemailService)

__all__ = [
    # 基类
    'BaseEmailService',
    'EmailServiceError',
    'EmailServiceStatus',
    'EmailServiceFactory',
    'create_email_service',
    'EmailServiceType',
    # 服务类
    'TempmailService',
    'CloudMailService',
    'FreemailService',
]
