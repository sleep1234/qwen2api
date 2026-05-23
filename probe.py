#!/usr/bin/env python3
"""
上下文 Token 边界探测器

对通义千问的每个模型进行二分搜索，找出最大上下文长度。
"""

import json
import httpx
import hashlib
import hmac
import base64
import uuid
import random
import time
import re
import sys

# ============================================================
# 工具函数
# ============================================================

def random_string(length=11):
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(random.choice(chars) for _ in range(length))

def hmac_sha256_b64(key, msg):
    return base64.b64encode(hmac.new(key.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def estimate_tokens(text):
    """粗略估算 token 数（中文约 1.5 字/token，英文约 4 字符/token）"""
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)

def generate_filler(target_tokens):
    """生成指定 token 数的填充文本"""
    # 每个中文字符约 0.67 token，所以 target_tokens * 1.5 个字符
    chars_needed = int(target_tokens * 1.5)
    base = "这是一段用于测试上下文长度的填充文本。"
    repeats = chars_needed // len(base) + 1
    return (base * repeats)[:chars_needed]


# ============================================================
# Baxia 客户端（简化版）
# ============================================================

class BaxiaProbe:
    def __init__(self):
        self.device_id = ""
        self.actkn = ""
        self.snver = ""
        self.sacsft_pool = []
        self.kp = "tytk_hash:46c239e0849295b9128670c3a659ff1a"
        self.version = "2.9.3"
        self.cookies = ""

    def load_cookies(self):
        with open("config.py") as f:
            content = f.read()
        m = re.search(r'QWEN_COOKIES\s*=\s*"(.+?)"', content)
        self.cookies = m.group(1) if m else ""
        return bool(self.cookies)

    async def register(self):
        fingerprint = hashlib.md5(f"{random.random()}{time.time()}".encode()).hexdigest()
        chid = random_string(11)

        body = {
            "screenResolution": "1920x1080", "cookieEnabled": True,
            "localStorageEnabled": True, "timezoneOffset": -480,
            "fontList": [], "pluginList": [], "language": ["zh-CN"],
            "unifyRelateGenerate": [], "fingerprint": fingerprint,
            "businessScene": "qwen_web", "chid": chid,
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.qianwen.com", "Referer": "https://www.qianwen.com/",
            "Cookie": self.cookies,
            "bx-umidtoken": "", "eo-clt-sftcnt": "100",
            "clt-acs-caer": "vrad", "eo-clt-acs-bx-intss": "2",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"https://sec.qianwen.com/security/external/access/register?chid={chid}",
                headers=headers, json=body,
            )
            data = r.json()
            if data.get("status") != 0:
                return False
            result = data["data"]
            self.device_id = result.get("eo-clt-dvidn", "")
            self.actkn = result.get("eo-clt-actkn", "")
            self.snver = result.get("eo-clt-snver", "")
            self.sacsft_pool = result.get("eo-clt-bacsft", [])
            return True

    def sign(self, query_params, body_str=""):
        if not self.sacsft_pool:
            return {}
        timestamp = str(int(time.time() * 1000))
        sacsft = self.sacsft_pool.pop(0)
        body_key = f"{sacsft}:{timestamp}"
        body_hmac = hmac_sha256_b64(body_key, body_str) if body_str else ""
        sign_text = f"{self.device_id}{self.version}{self.kp}{query_params}{body_hmac}"
        sign = hmac_sha256_b64(body_key, sign_text)
        return {
            "clt-acs-sign": sign, "clt-acs-reqt": timestamp,
            "clt-acs-request-params": query_params,
            "eo-clt-dvidn": self.device_id, "eo-clt-sacsft": sacsft,
            "eo-clt-snver": self.snver, "eo-clt-actkn": self.actkn,
            "eo-clt-acs-ve": self.version, "clt-acs-caer": "vrad",
            "eo-clt-acs-kp": self.kp,
        }

    async def send_chat(self, model, user_content, timeout=60):
        """发送一条消息，返回 (success, response_text_or_error)"""
        session_id = str(uuid.uuid4()).replace("-", "")
        req_id = str(uuid.uuid4()).replace("-", "")[:32]
        topic_id = str(uuid.uuid4()).replace("-", "")[:32]

        body = {
            "req_id": req_id, "parent_req_id": "0",
            "relate_req_id": str(uuid.uuid4()).replace("-", ""),
            "messages": [{
                "mime_type": "text/plain", "content": user_content,
                "meta_data": {"ori_query": user_content}, "status": "complete",
            }],
            "scene": "chat", "sub_scene": "", "scene_param": "",
            "operation_type": "send", "session_id": session_id,
            "biz_id": "ai_qwen", "topic_id": topic_id, "model": model,
            "from": "default", "protocol_version": "v2",
            "messages_merge": False, "chat_client": "h5",
            "deep_search": "0", "ai_tool_scene": "",
        }
        body_str = json.dumps(body, ensure_ascii=False)

        qp = "biz_id,chat_client,device,fe_version,fr,la,nonce,pr,timestamp,tz,ut,ve,wv"
        nonce = random_string(11)
        ts = str(int(time.time() * 1000))
        sign_headers = self.sign(qp, body_str)
        if not sign_headers:
            return False, "签名失败"

        url_p = f"biz_id=ai_qwen&chat_client=h5&device=pc&fe_version=1.0.0&fr=h5&la=zh-CN&nonce={nonce}&pr=qwen&timestamp={ts}&tz=Asia%2FShanghai&ut={self.device_id}&ve={self.version}&wv={self.version}"
        url = f"https://chat2.qianwen.com/api/v2/chat?{url_p}"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream, text/plain, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.qianwen.com",
            "Referer": f"https://www.qianwen.com/chat/{session_id}",
            "Cookie": self.cookies,
            "x-device-id": self.device_id, "x-chat-id": req_id,
            "x-platform": "pc_tongyi", "x-csrf-token": "",
            **sign_headers,
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                async with client.stream("POST", url, headers=headers, content=body_str.encode()) as resp:
                    if resp.status_code != 200:
                        error = (await resp.aread()).decode(errors="replace")[:300]
                        return False, f"HTTP {resp.status_code}: {error}"

                    # 读取 SSE 响应
                    content = ""
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "true":
                            break
                        try:
                            data = json.loads(data_str)
                            msgs = data.get("data", {}).get("messages", [])
                            if msgs:
                                content = msgs[-1].get("content", "")
                                if msgs[-1].get("status") == "complete":
                                    break
                        except json.JSONDecodeError:
                            pass

                    return True, content

        except httpx.ReadTimeout:
            return False, "超时"
        except Exception as e:
            return False, str(e)[:200]


# ============================================================
# 探测逻辑
# ============================================================

async def probe_model(baxia, model, min_tokens=500, max_tokens=130000, step=4000):
    """二分法探测模型的上下文边界"""
    print(f"\n{'='*60}")
    print(f"🔍 探测模型: {model}")
    print(f"{'='*60}")

    results = []
    low, high = min_tokens, max_tokens
    best_ok = 0
    worst_fail = high + 1

    # 先用大步长粗探
    test_tokens = min_tokens
    while test_tokens <= max_tokens:
        filler = generate_filler(test_tokens)
        prompt = f"以下是测试文本，请回复OK\n\n{filler}"
        actual_est = estimate_tokens(prompt)

        print(f"  📤 测试 {actual_est} tokens (填充 {test_tokens})...", end=" ", flush=True)

        ok, result = await baxia.send_chat(model, prompt, timeout=90)

        if ok and result:
            print(f"✅ 长度={len(result)}")
            results.append({"tokens": actual_est, "status": "ok", "length": len(result)})
            best_ok = max(best_ok, actual_est)
            test_tokens += step
        else:
            print(f"❌ {result[:80]}")
            results.append({"tokens": actual_est, "status": "fail", "error": result[:100]})
            worst_fail = min(worst_fail, actual_est)
            break

        # 检查 sacsft 池
        if len(baxia.sacsft_pool) < 3:
            print("  ⏳ sacsft 池不足，等待刷新...")
            time.sleep(2)

    # 如果找到了边界，用小步长精确探
    if worst_fail < high + 1:
        low = best_ok
        high = worst_fail
        step2 = max(500, (high - low) // 5)

        test_tokens = low + step2
        while test_tokens < high:
            filler = generate_filler(test_tokens)
            prompt = f"以下是测试文本，请回复OK\n\n{filler}"
            actual_est = estimate_tokens(prompt)

            print(f"  📤 精确测试 {actual_est} tokens...", end=" ", flush=True)
            ok, result = await baxia.send_chat(model, prompt, timeout=90)

            if ok and result:
                print(f"✅")
                best_ok = max(best_ok, actual_est)
                test_tokens += step2
            else:
                print(f"❌ {result[:60]}")
                worst_fail = min(worst_fail, actual_est)
                break

    print(f"\n  📊 结果: 最大成功 ≈ {best_ok} tokens | 最小失败 ≈ {worst_fail} tokens")
    return {
        "model": model,
        "max_context_tokens": best_ok,
        "fail_at": worst_fail,
        "details": results,
    }


async def main():
    print("=" * 60)
    print("🔬 通义千问上下文 Token 边界探测器")
    print("=" * 60)

    baxia = BaxiaProbe()
    if not baxia.load_cookies():
        print("❌ 未找到 Cookie，请在 config.py 中设置 QWEN_COOKIES")
        return

    print("📡 注册中...")
    if not await baxia.register():
        print("❌ 注册失败")
        return
    print(f"✅ 注册成功，sacsft 池: {len(baxia.sacsft_pool)} 个")

    # 要测试的模型（show=True 的）
    models_to_test = [
        "Qwen3.7-Max",
        "Qwen",           # Qwen3.6-千问
        "Qwen3.5-Flash",
        "Qwen3-Max",
        "Qwen3-Max-Thinking-Preview",
        "Qwen3-Coder",
    ]

    all_results = []

    for model in models_to_test:
        if len(baxia.sacsft_pool) < 20:
            print("\n⏳ sacsft 池不足，刷新中...")
            # 简单等待后重新注册
            time.sleep(1)
            await baxia.register()

        result = await probe_model(baxia, model)
        all_results.append(result)

    # 汇总
    print("\n" + "=" * 60)
    print("📊 汇总结果")
    print("=" * 60)
    print(f"{'模型':<35} {'最大上下文':>10} {'失败边界':>10}")
    print("-" * 60)
    for r in all_results:
        print(f"{r['model']:<35} {r['max_context_tokens']:>8} tok {r['fail_at']:>8} tok")

    # 保存详细结果
    with open("probe_results.json", "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n详细结果已保存到 probe_results.json")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
