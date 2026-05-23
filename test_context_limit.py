#!/usr/bin/env python3
"""
快速探测上下文极限
通过逐步增大 messages 数组的总长度，找到通义千问的实际上下文边界。
"""

import httpx
import json
import time
import sys

BASE = "http://127.0.0.1:8000"

def estimate_tokens(text: str) -> int:
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)

def build_messages(target_tokens: int) -> list:
    """构建指定 token 数的多轮对话"""
    # 每个中文字符约 0.67 token
    chars_per_round = 500  # 每轮约 330 tokens
    rounds = max(1, target_tokens // 330)
    
    messages = [{"role": "system", "content": "你是一个有帮助的助手。请认真回答用户的问题。"}]
    
    filler = "这是一段用于测试上下文长度的模拟对话内容，包含中英文混合场景。"
    
    for i in range(rounds):
        user_text = f"第{i+1}轮对话：{filler * (chars_per_round // len(filler))}"
        user_text = user_text[:chars_per_round]
        messages.append({"role": "user", "content": user_text})
        
        # 模拟 assistant 回复（让对话更真实）
        assistant_text = f"好的，我收到了第{i+1}轮的消息。{filler * 2}"
        assistant_text = assistant_text[:300]
        messages.append({"role": "assistant", "content": assistant_text})
    
    # 最后加上真正的问题
    messages.append({"role": "user", "content": "请用一句话总结：我们之前的对话一共有几轮？每轮说了什么关键词？"})
    
    return messages

def test_context(target_tokens: int) -> dict:
    messages = build_messages(target_tokens)
    actual_input = sum(estimate_tokens(m["content"]) for m in messages)
    
    print(f"\n{'='*60}")
    print(f"📤 目标: ~{target_tokens} tokens | 实际输入: ~{actual_input} tokens | 消息数: {len(messages)}")
    
    start = time.time()
    try:
        r = httpx.post(
            f"{BASE}/v1/chat/completions",
            json={
                "model": "Qwen3.7-Max",
                "messages": messages,
                "stream": False,
            },
            timeout=120.0,
        )
        elapsed = time.time() - start
        
        if r.status_code == 200:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            print(f"✅ 成功 | {elapsed:.1f}s | 回复长度={len(content)} | {usage}")
            print(f"   回复预览: {content[:150]}")
            return {"tokens": actual_input, "status": "ok", "time": elapsed, "reply_len": len(content)}
        else:
            print(f"❌ HTTP {r.status_code} | {elapsed:.1f}s | {r.text[:200]}")
            return {"tokens": actual_input, "status": "error", "code": r.status_code, "error": r.text[:200]}
    
    except httpx.ReadTimeout:
        elapsed = time.time() - start
        print(f"❌ 超时 | {elapsed:.1f}s")
        return {"tokens": actual_input, "status": "timeout", "time": elapsed}
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ 异常: {e}")
        return {"tokens": actual_input, "status": "exception", "error": str(e)}

def main():
    print("=" * 60)
    print("🔬 通义千问上下文极限探测")
    print("=" * 60)
    
    # 测试梯度：从 1K 到 130K
    targets = [
        1000,
        5000,
        10000,
        20000,
        40000,
        60000,
        80000,
        100000,
        120000,
        130000,
    ]
    
    results = []
    last_ok = 0
    first_fail = None
    
    for target in targets:
        result = test_context(target)
        results.append(result)
        
        if result["status"] == "ok":
            last_ok = result["tokens"]
        elif first_fail is None:
            first_fail = result["tokens"]
            print(f"\n⚠️  首次失败在 ~{first_fail} tokens，后续测试跳过")
            break
        
        time.sleep(1)  # 避免请求过快
    
    # 汇总
    print(f"\n{'='*60}")
    print(f"📊 汇总结果")
    print(f"{'='*60}")
    print(f"{'目标 tokens':>12} | {'状态':>6} | {'耗时':>6} | {'回复长度':>8}")
    print("-" * 50)
    for r in results:
        status = "✅" if r["status"] == "ok" else "❌"
        t = f"{r.get('time', 0):.1f}s" if "time" in r else "N/A"
        reply = str(r.get("reply_len", "-"))
        print(f"{r['tokens']:>10} tok | {status:>6} | {t:>6} | {reply:>8}")
    
    print(f"\n🎯 结论：上下文极限约在 {last_ok} ~ {(first_fail or '?')} tokens 之间")

if __name__ == "__main__":
    main()
