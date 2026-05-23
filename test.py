#!/usr/bin/env python3
"""
测试脚本 — 验证 qwen2api 是否正常工作

用法：
  1. 先启动服务: python server_pw.py
  2. 再运行测试: python test.py
"""

import json
import sys
import httpx

BASE = "http://127.0.0.1:8000"


def test_root():
    """测试根路径"""
    r = httpx.get(f"{BASE}/")
    data = r.json()
    print(f"✅ 根路径: {data['name']} v{data['version']}")
    print(f"   ready: {data.get('ready', 'unknown')}")
    return True


def test_models():
    """测试模型列表"""
    r = httpx.get(f"{BASE}/v1/models")
    data = r.json()
    models = [m["id"] for m in data["data"]]
    print(f"✅ 模型列表: {models}")
    return True


def test_status():
    """测试状态"""
    r = httpx.get(f"{BASE}/status")
    data = r.json()
    print(f"✅ 状态: {json.dumps(data, ensure_ascii=False)}")
    return data.get("ready", False)


def test_chat():
    """测试聊天"""
    print("\n📤 发送消息: 你好，请用一句话介绍自己")
    r = httpx.post(
        f"{BASE}/v1/chat/completions",
        json={
            "model": "Qwen3.7-Max",
            "messages": [{"role": "user", "content": "你好，请用一句话介绍自己"}],
            "stream": False,
        },
        timeout=120.0,
    )

    if r.status_code != 200:
        print(f"❌ 请求失败: {r.status_code}")
        print(f"   {r.text[:500]}")
        return False

    data = r.json()
    content = data["choices"][0]["message"]["content"]
    print(f"\n📥 回复:\n{content[:500]}")
    print(f"\n📊 usage: {data.get('usage', {})}")
    return True


def test_chat_stream():
    """测试流式聊天"""
    print("\n📤 流式消息: 写一首关于AI的五言绝句")
    with httpx.stream(
        "POST",
        f"{BASE}/v1/chat/completions",
        json={
            "model": "Qwen3.7-Max",
            "messages": [{"role": "user", "content": "写一首关于AI的五言绝句"}],
            "stream": True,
        },
        timeout=120.0,
    ) as r:
        if r.status_code != 200:
            print(f"❌ 请求失败: {r.status_code}")
            return False

        print("📥 流式回复: ", end="", flush=True)
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                content = data["choices"][0]["delta"].get("content", "")
                print(content, end="", flush=True)
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        print()
    return True


def main():
    print("=" * 50)
    print("qwen2api 测试")
    print("=" * 50)

    # 1. 基础测试
    try:
        test_root()
        test_models()
    except httpx.ConnectError:
        print("❌ 无法连接服务，请先启动: python server_pw.py")
        sys.exit(1)

    # 2. 检查浏览器状态
    ready = test_status()
    if not ready:
        print("⏳ 浏览器未就绪，等待初始化...")
        import time
        for i in range(30):
            time.sleep(2)
            ready = test_status()
            if ready:
                break
        if not ready:
            print("❌ 浏览器初始化超时")
            sys.exit(1)

    # 3. 聊天测试
    print("\n" + "=" * 50)
    print("聊天测试")
    print("=" * 50)
    test_chat()

    # 4. 流式测试
    print("\n" + "=" * 50)
    print("流式测试")
    print("=" * 50)
    test_chat_stream()

    print("\n✅ 所有测试完成!")


if __name__ == "__main__":
    main()
