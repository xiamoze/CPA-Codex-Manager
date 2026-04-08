#!/usr/bin/env python3
"""
Cloudflare 临时邮箱服务 - 集成测试
测试 cloudflare_temp.py 服务类的完整功能
"""

import sys
import time

# 确保能导入项目模块
sys.path.insert(0, '/root/openclaw-workspace/CPA-Codex-Manager/src')

from services import CloudflareTempService, EmailServiceType, EmailServiceFactory


def test_service_creation():
    """测试 1: 服务创建和注册"""
    print("\n=== Test 1: 服务创建和注册 ===")
    
    # 验证工厂注册
    available = EmailServiceFactory.get_available_services()
    assert EmailServiceType.CLOUDFLARE_TEMP in available, "CLOUDFLARE_TEMP 未注册"
    print(f"✅ CLOUDFLARE_TEMP 已注册，可用服务: {[s.value for s in available]}")
    
    # 验证可以通过工厂创建
    service = EmailServiceFactory.create(
        EmailServiceType.CLOUDFLARE_TEMP,
        {"base_url": "https://tml.yltkj.ggff.net", "domain": "yltkj.ggff.net"}
    )
    assert service is not None, "工厂创建失败"
    print(f"✅ EmailServiceFactory.create() 成功: {service}")
    
    return service


def test_create_email(service):
    """测试 2: 创建邮箱"""
    print("\n=== Test 2: 创建邮箱 ===")
    
    email_info = service.create_email()
    
    assert "email" in email_info, "缺少 email 字段"
    assert "jwt" in email_info, "缺少 jwt 字段"
    assert email_info["email"].endswith("@yltkj.ggff.net"), f"域名不对: {email_info['email']}"
    assert len(email_info["jwt"]) > 20, "JWT 太短"
    
    print(f"✅ 邮箱创建成功: {email_info['email']}")
    print(f"   JWT: {email_info['jwt'][:50]}...")
    
    return email_info


def test_health_check(service):
    """测试 3: 健康检查"""
    print("\n=== Test 3: 健康检查 ===")
    
    health = service.check_health()
    assert health is True, "健康检查失败"
    
    info = service.get_service_info()
    print(f"✅ 健康状态: {info['status']}")
    print(f"   服务信息: {info}")
    
    return info


def test_list_emails(service):
    """测试 4: 列出邮箱"""
    print("\n=== Test 4: 列出邮箱 ===")
    
    emails = service.list_emails()
    assert len(emails) > 0, "邮箱列表为空"
    
    print(f"✅ 缓存邮箱数: {len(emails)}")
    for e in emails:
        print(f"   - {e['email']}")


def test_delete_email(service, email_info):
    """测试 5: 删除邮箱"""
    print("\n=== Test 5: 删除邮箱 ===")
    
    result = service.delete_email(email_info["email"])
    assert result is True, "删除失败"
    
    print(f"✅ 删除成功: {email_info['email']}")


def test_random_name_generation():
    """测试 6: 随机名称生成"""
    print("\n=== Test 6: 随机名称生成 ===")
    
    service = CloudflareTempService()
    names = set()
    
    for _ in range(5):
        email_info = service.create_email()
        name = email_info["email"].split("@")[0]
        names.add(name)
    
    assert len(names) == 5, f"名称不唯一: {names}"
    print(f"✅ 生成 5 个唯一邮箱名: {names}")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Cloudflare 临时邮箱服务 - 集成测试")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    try:
        # Test 1: 服务创建
        service = test_service_creation()
        passed += 1
    except Exception as e:
        print(f"❌ Test 1 失败: {e}")
        failed += 1
        return
    
    try:
        # Test 2: 创建邮箱
        email_info = test_create_email(service)
        passed += 1
    except Exception as e:
        print(f"❌ Test 2 失败: {e}")
        failed += 1
        return
    
    try:
        # Test 3: 健康检查
        test_health_check(service)
        passed += 1
    except Exception as e:
        print(f"❌ Test 3 失败: {e}")
        failed += 1
    
    try:
        # Test 4: 列出邮箱
        test_list_emails(service)
        passed += 1
    except Exception as e:
        print(f"❌ Test 4 失败: {e}")
        failed += 1
    
    try:
        # Test 5: 删除邮箱
        test_delete_email(service, email_info)
        passed += 1
    except Exception as e:
        print(f"❌ Test 5 失败: {e}")
        failed += 1
    
    try:
        # Test 6: 随机名称
        test_random_name_generation()
        passed += 1
    except Exception as e:
        print(f"❌ Test 6 失败: {e}")
        failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} ✅ / {failed} ❌")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
