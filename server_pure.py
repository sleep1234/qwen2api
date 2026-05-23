"""
qwen2api — 纯 Python 版本（已验证可用）

完全基于逆向分析实现，不需要浏览器。

用法：
  1. 把你的 Cookie 填入 config.py 的 QWEN_COOKIES
  2. python server_pure.py
  3. curl http://localhost:8000/v1/chat/completions ...
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid
import random
import base64
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

import config

app = FastAPI(title="qwen2api", version="0.3.0")


# ============================================================
# 工具函数
# ============================================================

def random_string(length=11) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(random.choice(chars) for _ in range(length))


def hmac_sha256_b64(key: str, message: str) -> str:
    sig = hmac.new(key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()


# ============================================================
# Baxia 签名客户端
# ============================================================

class BaxiaClient:
    def __init__(self):
        self.device_id = ""
        self.actkn = ""
        self.snver = ""
        self.sacsft_pool = []
        self.kp = ""
        self.version = "2.9.3"
        self.initialized = False
        self._state_file = Path(__file__).parent / "baxia_state.json"
        self._load_state()

    def _load_state(self):
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                self.device_id = data.get("device_id", "")
                self.actkn = data.get("actkn", "")
                self.snver = data.get("snver", "")
                self.sacsft_pool = data.get("sacsft_pool", [])
                self.kp = data.get("kp", "")
                if self.actkn and self.sacsft_pool:
                    self.initialized = True
                    print(f"[baxia] 从缓存恢复，sacsft 池: {len(self.sacsft_pool)} 个")
            except Exception:
                pass

    def _save_state(self):
        self._state_file.write_text(json.dumps({
            "device_id": self.device_id,
            "actkn": self.actkn,
            "snver": self.snver,
            "sacsft_pool": self.sacsft_pool,
            "kp": self.kp,
        }, indent=2))

    async def init(self) -> bool:
        if self.initialized:
            return True

        cookies = config.QWEN_COOKIES
        if not cookies:
            print("[baxia] ❌ 未配置 Cookie，请在 config.py 中设置 QWEN_COOKIES")
            return False

        self.kp = "tytk_hash:46c239e0849295b9128670c3a659ff1a"  # TODO: 从 cookie 中提取
        fingerprint = hashlib.md5(f"{random.random()}{time.time()}".encode()).hexdigest()
        chid = random_string(11)

        body = {
            "screenResolution": "1920x1080",
            "cookieEnabled": True,
            "localStorageEnabled": True,
            "timezoneOffset": -480,
            "fontList": [],
            "pluginList": [],
            "language": ["zh-CN"],
            "unifyRelateGenerate": [],
            "fingerprint": fingerprint,
            "businessScene": "qwen_web",
            "chid": chid,
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://www.qianwen.com",
            "Referer": "https://www.qianwen.com/",
            "Cookie": cookies,
            "bx-umidtoken": "",
            "eo-clt-sftcnt": "100",
            "clt-acs-caer": "vrad",
            "eo-clt-acs-bx-intss": "2",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://sec.qianwen.com/security/external/access/register?chid={chid}",
                headers=headers,
                json=body,
            )
            data = resp.json()

            if data.get("status") != 0:
                print(f"[baxia] 注册失败: {data}")
                return False

            result = data["data"]
            self.device_id = result.get("eo-clt-dvidn", "")
            self.actkn = result.get("eo-clt-actkn", "")
            self.snver = result.get("eo-clt-snver", "")
            self.sacsft_pool = result.get("eo-clt-bacsft", [])

            self.initialized = True
            self._save_state()
            print(f"[baxia] ✅ 注册成功，sacsft 池: {len(self.sacsft_pool)} 个")
            return True

    def sign(self, query_params: str, body: str = "") -> dict:
        if not self.sacsft_pool:
            return {}

        timestamp = str(int(time.time() * 1000))
        sacsft = self.sacsft_pool.pop(0)
        body_key = f"{sacsft}:{timestamp}"

        body_hmac = hmac_sha256_b64(body_key, body) if body else ""
        sign_text = f"{self.device_id}{self.version}{self.kp}{query_params}{body_hmac}"
        sign = hmac_sha256_b64(body_key, sign_text)

        # 池不足时自动刷新
        if len(self.sacsft_pool) < 5:
            asyncio.create_task(self._refresh())

        return {
            "clt-acs-sign": sign,
            "clt-acs-reqt": timestamp,
            "clt-acs-request-params": query_params,
            "eo-clt-dvidn": self.device_id,
            "eo-clt-sacsft": sacsft,
            "eo-clt-snver": self.snver,
            "eo-clt-actkn": self.actkn,
            "eo-clt-acs-ve": self.version,
            "clt-acs-caer": "vrad",
            "eo-clt-acs-kp": self.kp,
        }

    async def _refresh(self):
        """刷新 sacsft 池"""
        if not self.actkn:
            return await self.init()

        cookies = config.QWEN_COOKIES
        chid = random_string(11)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.qianwen.com",
            "Referer": "https://www.qianwen.com/",
            "Cookie": cookies,
            "eo-clt-dvidn": self.device_id,
            "eo-clt-actkn": self.actkn,
            "bx-umidtoken": "",
            "eo-clt-sftcnt": "100",
            "clt-acs-caer": "vrad",
            "eo-clt-acs-bx-intss": "2",
        }

        params = {
            "businessScene": "qwen_web",
            "unifyRelateGenerate": "",
            "chid": chid,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    "https://sec.qianwen.com/security/external/access/refresh",
                    headers=headers,
                    params=params,
                )
                data = resp.json()
                if data.get("status") == 0:
                    result = data["data"]
                    self.actkn = result.get("eo-clt-actkn", self.actkn)
                    self.snver = result.get("eo-clt-snver", self.snver)
                    new_pool = result.get("eo-clt-bacsft", [])
                    if new_pool:
                        self.sacsft_pool.extend(new_pool)
                    self._save_state()
                    print(f"[baxia] 刷新成功，sacsft 池: {len(self.sacsft_pool)} 个")
            except Exception as e:
                print(f"[baxia] 刷新失败: {e}")


# ============================================================
# 全局状态
# ============================================================
baxia = BaxiaClient()


# ============================================================
# 核心：发送聊天请求
# ============================================================

async def send_chat(messages: list, model: str, stream: bool):
    if not baxia.initialized:
        success = await baxia.init()
        if not success:
            return {"error": "Baxia 初始化失败，请检查 Cookie"}

    # 提取消息
    user_content = ""
    for msg in messages:
        if msg["role"] == "user":
            user_content = msg["content"]
        elif msg["role"] == "system":
            user_content = f"[系统指令]: {msg['content']}\n\n{user_content}"

    session_id = str(uuid.uuid4()).replace("-", "")
    req_id = str(uuid.uuid4()).replace("-", "")[:32]
    topic_id = str(uuid.uuid4()).replace("-", "")[:32]

    body = {
        "req_id": req_id,
        "parent_req_id": "0",
        "relate_req_id": str(uuid.uuid4()).replace("-", ""),
        "messages": [{
            "mime_type": "text/plain",
            "content": user_content,
            "meta_data": {"ori_query": user_content},
            "status": "complete",
        }],
        "scene": "chat",
        "sub_scene": "",
        "scene_param": "",
        "operation_type": "send",
        "session_id": session_id,
        "biz_id": "ai_qwen",
        "topic_id": topic_id,
        "model": model,
        "from": "default",
        "protocol_version": "v2",
        "messages_merge": False,
        "chat_client": "h5",
        "deep_search": "0",
        "ai_tool_scene": "",
    }
    body_str = json.dumps(body, ensure_ascii=False)

    # 签名
    query_params_str = "biz_id,chat_client,device,fe_version,fr,la,nonce,pr,timestamp,tz,ut,ve,wv"
    nonce = random_string(11)
    timestamp = str(int(time.time() * 1000))

    sign_headers = baxia.sign(query_params_str, body_str)
    if not sign_headers:
        return {"error": "签名失败"}

    url_params = f"biz_id=ai_qwen&chat_client=h5&device=pc&fe_version=1.0.0&fr=h5&la=zh-CN&nonce={nonce}&pr=qwen&timestamp={timestamp}&tz=Asia%2FShanghai&ut={baxia.device_id}&ve={baxia.version}&wv={baxia.version}"
    url = f"https://chat2.qianwen.com/api/v2/chat?{url_params}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://www.qianwen.com",
        "Referer": f"https://www.qianwen.com/chat/{session_id}",
        "Cookie": config.QWEN_COOKIES,
        "x-device-id": baxia.device_id,
        "x-chat-id": req_id,
        "x-platform": "pc_tongyi",
        "x-csrf-token": "",
        **sign_headers,
    }

    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    try:
        resp = await client.send(
            client.build_request("POST", url, headers=headers, content=body_str.encode()),
            stream=True,
        )
        if resp.status_code != 200:
            error = await resp.aread()
            await resp.aclose()
            return {"error": f"HTTP {resp.status_code}: {error.decode()[:500]}"}

        return {"response": resp, "stream": stream, "client": client}
    except Exception as e:
        await client.aclose()
        return {"error": str(e)}


def extract_content_from_sse_line(line: str) -> str:
    """从单行 SSE 数据中提取文本内容"""
    if not line.startswith("data:"):
        return ""
    data_str = line[5:].strip()
    if data_str in ("true", "[DONE]"):
        return ""
    try:
        data = json.loads(data_str)
        msgs = data.get("data", {}).get("messages", [])
        if msgs:
            return msgs[-1].get("content", "")
    except json.JSONDecodeError:
        pass
    return ""


def is_sse_complete(line: str) -> bool:
    """检查 SSE 是否完成"""
    if not line.startswith("data:"):
        return False
    data_str = line[5:].strip()
    if data_str == "true":
        return True
    try:
        data = json.loads(data_str)
        msgs = data.get("data", {}).get("messages", [])
        if msgs:
            return msgs[-1].get("status") == "complete"
    except json.JSONDecodeError:
        pass
    return False


# ============================================================
# API 路由
# ============================================================

def gen_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


@app.get("/")
async def root():
    return {
        "name": "qwen2api",
        "version": "0.3.0 (pure python)",
        "baxia_ready": baxia.initialized,
        "sacsft_pool": len(baxia.sacsft_pool),
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "Qwen3.7-Max", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
            {"id": "qwen-max", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    model = body.get("model", "Qwen3.7-Max")

    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    completion_id = gen_id()
    created = int(time.time())

    result = await send_chat(messages, model, stream)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])

    resp = result["response"]
    http_client = result["client"]

    if stream:
        async def stream_events():
            prev_content = ""
            try:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue

                    content = extract_content_from_sse_line(line)
                    if content and content != prev_content:
                        # 只发送新增的部分
                        delta = content[len(prev_content):]
                        if delta:
                            yield {
                                "event": "message",
                                "data": json.dumps({
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": created,
                                    "model": model,
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": delta},
                                        "finish_reason": None,
                                    }],
                                }, ensure_ascii=False),
                            }
                        prev_content = content

                    if is_sse_complete(line):
                        break
            finally:
                await resp.aclose()
                await http_client.aclose()

            # 结束标记
            yield {
                "event": "message",
                "data": json.dumps({
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }),
            }

        return EventSourceResponse(stream_events())

    else:
        full_content = ""
        try:
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                content = extract_content_from_sse_line(line)
                if content:
                    full_content = content  # 最后一个 complete 事件包含完整内容
                if is_sse_complete(line):
                    break
        finally:
            await resp.aclose()
            await http_client.aclose()

        return JSONResponse({
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": sum(len(m.get("content", "")) // 2 for m in messages),
                "completion_tokens": len(full_content) // 2,
                "total_tokens": sum(len(m.get("content", "")) // 2 for m in messages) + len(full_content) // 2,
            },
        })


@app.post("/debug/register")
async def debug_register():
    success = await baxia.init()
    return {
        "success": success,
        "sacsft_count": len(baxia.sacsft_pool),
        "device_id": baxia.device_id[:30] + "..." if baxia.device_id else "",
    }


if __name__ == "__main__":
    import uvicorn
    print(f"🚀 qwen2api (Pure Python) 启动中...")
    print(f"   服务地址: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT)
