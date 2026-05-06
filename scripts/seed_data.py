#!/usr/bin/env python3
"""
填充示例测试用例数据 — 通过 REST API 插入
"""

import sys
import json
import httpx

API = "http://localhost:8765/api/v1"

# 示例测试用例
CASES = [
    {
        "title": "用户登录-正确账号密码登录",
        "module": "登录",
        "priority": "P0",
        "category": "功能测试",
        "preconditions": "已注册账号，用户名 user01，密码 Abc12345",
        "steps": [
            "打开登录页面",
            "输入用户名 user01",
            "输入密码 Abc12345",
            "点击登录按钮",
        ],
        "expected": "登录成功，跳转到首页，显示用户昵称",
        "tags": ["登录", "冒烟测试", "核心功能"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "用户登录-错误密码登录",
        "module": "登录",
        "priority": "P1",
        "category": "功能测试",
        "preconditions": "已注册账号，用户名 user01",
        "steps": [
            "打开登录页面",
            "输入用户名 user01",
            "输入错误密码 wrong123",
            "点击登录按钮",
        ],
        "expected": "登录失败，显示「用户名或密码错误」提示，停留在登录页",
        "tags": ["登录", "异常场景"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "用户登录-账号锁定测试",
        "module": "登录",
        "priority": "P1",
        "category": "安全测试",
        "preconditions": "已注册账号",
        "steps": [
            "连续 5 次输入错误密码登录",
            "第 6 次输入正确密码",
        ],
        "expected": "第 5 次失败后提示「账号已锁定，请 30 分钟后重试」，第 6 次即使密码正确也登录失败",
        "tags": ["登录", "安全", "锁定策略"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "支付-余额不足时支付",
        "module": "支付",
        "priority": "P1",
        "category": "功能测试",
        "preconditions": "登录态有效，账户余额 10 元，订单金额 100 元",
        "steps": [
            "添加 100 元商品到购物车",
            "进入结算页",
            "选择余额支付",
            "点击确认支付",
        ],
        "expected": "支付失败，提示「余额不足」，引导用户选择其他支付方式",
        "tags": ["支付", "异常场景", "核心功能"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "支付-超时未支付取消订单",
        "module": "支付",
        "priority": "P2",
        "category": "功能测试",
        "preconditions": "登录态有效，已创建待支付订单",
        "steps": [
            "提交订单",
            "不进行支付，等待 30 分钟",
            "查看订单状态",
        ],
        "expected": "30 分钟后订单状态变为「已取消」，库存自动释放",
        "tags": ["支付", "超时", "订单"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "搜索-关键词联想功能",
        "module": "搜索",
        "priority": "P2",
        "category": "功能测试",
        "preconditions": "系统中有商品数据",
        "steps": [
            "打开搜索框",
            "输入 '手机'",
            "观察联想下拉框",
        ],
        "expected": "输入后 300ms 内显示联想商品列表，包含'手机壳''手机膜''手机支架'等",
        "tags": ["搜索", "体验", "联想"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "搜索-空结果搜索",
        "module": "搜索",
        "priority": "P3",
        "category": "功能测试",
        "preconditions": "系统中有商品数据",
        "steps": [
            "打开搜索框",
            "输入不存在的关键词 'zzzxxxnotfound'",
            "点击搜索",
        ],
        "expected": "显示「未找到相关商品」，推荐热门商品",
        "tags": ["搜索", "异常场景"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "秒杀-并发下单压力测试",
        "module": "秒杀",
        "priority": "P0",
        "category": "性能测试",
        "preconditions": "秒杀活动已配置，库存 100 件",
        "steps": [
            "使用 JMeter 模拟 1000 用户并发请求",
            "所有用户在秒杀开始时刻同时点击购买",
        ],
        "expected": "系统不崩溃，实际下单成功数不超过 100，响应时间 < 2s",
        "tags": ["秒杀", "并发", "性能", "P0"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "退款-退款流程测试",
        "module": "退款",
        "priority": "P1",
        "category": "功能测试",
        "preconditions": "已支付且未发货的订单",
        "steps": [
            "登录后进入订单详情页",
            "点击申请退款",
            "选择退款理由「不想要了」",
            "提交退款申请",
        ],
        "expected": "退款申请提交成功，状态变为「退款中」，资金在 1-7 个工作日原路返回",
        "tags": ["退款", "核心功能", "订单"],
        "project": "电商平台",
        "creator": "Zoey",
    },
    {
        "title": "权限-未登录访问购物车",
        "module": "权限",
        "priority": "P1",
        "category": "安全测试",
        "preconditions": "未登录状态",
        "steps": [
            "清除浏览器缓存",
            "直接访问 /cart 页面",
        ],
        "expected": "跳转到登录页，登录后自动回到购物车页",
        "tags": ["权限", "安全", "未登录"],
        "project": "电商平台",
        "creator": "Zoey",
    },
]


def main():
    try:
        resp = httpx.get(f"{API}/health", timeout=5)
        if resp.status_code != 200:
            print(f"❌ API 未运行，请先启动: ./run.sh api:bg")
            sys.exit(1)
    except Exception:
        print(f"❌ API 未运行，请先启动: ./run.sh api:bg")
        sys.exit(1)

    print(f"🌱 准备插入 {len(CASES)} 条测试用例...")

    count = 0
    for case in CASES:
        resp = httpx.post(f"{API}/cases", json=case, timeout=10)
        if resp.status_code == 201:
            count += 1
            print(f"  ✅ [{count}/{len(CASES)}] {case['title']}")
        else:
            print(f"  ❌ [{count+1}/{len(CASES)}] {case['title']}: {resp.status_code} {resp.text}")

    print(f"\n✅ 成功插入 {count}/{len(CASES)} 条用例")
    print(f"   API: {API}")


if __name__ == "__main__":
    main()
