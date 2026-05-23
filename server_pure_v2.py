"""
qwen2api — 纯 Python 版本 v2（支持多轮对话）

改进点：
  1. 支持多轮对话上下文传递
  2. 自动管理 session_id / topic_id，保持对话连续
  3. 正确映射 OpenAI messages → Qwen messages 格式
  4. sacsft 池自动刷新

用法：
  1. 把你的 Cookie 填入 config.py 的 QWEN_COOKIES
  2. python server_pure_v2.py
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
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

import config

app = FastAPI(title="qwen2api", version="0.4.0")


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
# 会话管理器
# ============================================================

class ConversationManager:
    """
    管理多轮对话的 session_id / topic_id 映射。
    
    客户端通过 OpenAI 的 messages 数组传入完整对话历史，
    我们根据 messages 内容生成稳定的 session_key，
    同一个对话复用相同的 session_id / topic_id。
    """
    
    def __init__(self):
        # session_key -> {"session_id": ..., "topic_id": ..., "last_used": ...}
        self._sessions: dict[str, dict] = {}
        self._max_sessions = 1000  # 最多缓存多少个会话
        self._ttl = 3600 * 2  # 会话过期时间（秒）
    
    def _make_session_key(self, messages: list, model: str) -> str:
        """
        根据对话内容生成稳定的 session key。
        策略：用 system prompt + 前几条消息的 hash 作为 key，
        这样同一个连续对话会映射到同一个 session。
        """
        # 提取关键内容用于生成 key
        key_parts = []
        for msg in messages[:4]:  # 取前 4 条消息
            content = msg.get("content", "")
            role = msg.get("role", "")
            key_parts.append(f"{role}:{content[:200]}")
        
        key_str = f"{model}|{'||'.join(key_parts)}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get_session(self, messages: list, model: str) -> dict:
        """获取或创建会话的 session_id / topic_id"""
        self._cleanup_expired()
        
        session_key = self._make_session_key(messages, model)
        
        if session_key in self._sessions:
            session = self._sessions[session_key]
            session["last_used"] = time.time()
            print(f"[session] 复用会话: {session_key[:12]}... "
                  f"session_id={session['session_id'][:16]}...")
            return session
        
        # 创建新会话
        session = {
            "session_id": str(uuid.uuid4()).replace("-", ""),
            "topic_id": str(uuid.uuid4()).replace("-", "")[:32],
            "last_used": time.time(),
        }
        
        # 缓存管理
        if len(self._sessions) >= self._max_sessions:
            self._evict_oldest()
        
        self._sessions[session_key] = session
        print(f"[session] 新建会话: {session_key[:12]}... "
              f"session_id={session['session_id'][:16]}...")
        return session
    
    def _cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            k for k, v in self._sessions.items()
            if now - v["last_used"] > self._ttl
        ]
        for k in expired:
            del self._sessions[k]
    
    def _evict_oldest(self):
        """淘汰最久未使用的会话"""
        if not self._sessions:
            return
        oldest_key = min(self._sessions, key=lambda k: self._sessions[k]["last_used"])
        del self._sessions[oldest_key]


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

        self.kp = "tytk_hash:46c239e0849295b9128670c3a659ff1a"
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
conversations = ConversationManager()


# ============================================================
# 消息格式转换
# ============================================================

def estimate_tokens(text: str) -> int:
    """粗略估算 token 数"""
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)


# 上下文压缩阈值（实测有效极限约 27K，留余量）
MAX_CONTEXT_TOKENS = 22000
# 保留最近 N 轮对话（user+assistant 各算一轮）
KEEP_RECENT_TURNS = 4


def compress_messages(messages: list) -> list:
    """
    当 messages 总 token 超过阈值时，自动压缩中间的旧消息为摘要。
    
    策略：
      1. 提取 system prompt（保留）
      2. 保留最近 KEEP_RECENT_TURNS 轮对话
      3. 中间被丢弃的部分 → 生成摘要，作为一条 system 消息插入
    """
    if not messages:
        return messages
    
    total_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
    
    if total_tokens <= MAX_CONTEXT_TOKENS:
        return messages  # 不需要压缩
    
    print(f"[compress] 总 token ≈{total_tokens} 超过 {MAX_CONTEXT_TOKENS}，执行压缩...")
    
    # 分离 system prompt
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system_msgs = [m for m in messages if m.get("role") != "system"]
    
    if len(non_system_msgs) <= KEEP_RECENT_TURNS + 1:
        return messages  # 消息太少，没法压缩
    
    # 分出旧消息和最近消息
    split_point = len(non_system_msgs) - KEEP_RECENT_TURNS
    old_msgs = non_system_msgs[:split_point]
    recent_msgs = non_system_msgs[split_point:]
    
    # 生成旧消息的摘要（更激进的压缩）
    summary_parts = []
    for msg in old_msgs:
        role = msg.get("role", "")
        content = msg.get("content", "")
        # 用户消息保留更多（通常包含关键问题），助手回复更短
        if role == "user":
            truncated = content[:200] + ("..." if len(content) > 200 else "")
            summary_parts.append(f"用户: {truncated}")
        elif role == "assistant":
            truncated = content[:100] + ("..." if len(content) > 100 else "")
            summary_parts.append(f"助手: {truncated}")
    
    summary_text = "\n---\n".join(summary_parts)
    
    # 兜底：如果摘要本身超过 15K token，只保留最后的部分
    max_summary_tokens = 15000
    if estimate_tokens(summary_text) > max_summary_tokens:
        # 从后往前保留
        lines = summary_text.split("\n---\n")
        kept = []
        tokens_so_far = 0
        for line in reversed(lines):
            t = estimate_tokens(line)
            if tokens_so_far + t > max_summary_tokens:
                break
            kept.append(line)
            tokens_so_far += t
        kept.reverse()
        summary_text = "\n---\n".join(kept)
        print(f"[compress] 摘要过长，截断至最后 ~{max_summary_tokens} tok")
    
    summary = "[以下是之前对话的摘要，请基于此上下文继续回答]\n" + summary_text
    
    # 估算压缩后的 token
    summary_tokens = estimate_tokens(summary)
    recent_tokens = sum(estimate_tokens(m.get("content", "")) for m in recent_msgs)
    system_tokens = sum(estimate_tokens(m.get("content", "")) for m in system_msgs)
    compressed_total = system_tokens + summary_tokens + recent_tokens
    
    print(f"[compress] 压缩前: {total_tokens} tok → 压缩后: ~{compressed_total} tok "
          f"(旧消息 {len(old_msgs)} 条→摘要 {summary_tokens} tok，保留最近 {len(recent_msgs)} 条)")
    
    # 组装：system + 摘要 + 最近消息
    result = system_msgs + [{"role": "system", "content": summary}] + recent_msgs
    return result


def openai_messages_to_qwen(messages: list) -> list:
    """
    将 OpenAI 格式的 messages 转换为通义千问的 messages 格式。
    
    OpenAI 格式:
      [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, 
       {"role": "assistant", "content": "..."}, {"role": "user", "content": "..."}]
    
    通义千问格式:
      [{"mime_type": "text/plain", "content": "...", "meta_data": {...}, "status": "complete"}]
    """
    # 先做上下文压缩
    messages = compress_messages(messages)
    
    qwen_messages = []
    
    system_content = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        
        if not content:
            continue
        
        if role == "system":
            # system 消息合并到最前面
            if system_content:
                system_content += "\n\n" + content
            else:
                system_content = content
        elif role == "user":
            final_content = content
            if system_content and not qwen_messages:
                # 第一条 user 消息前加上 system 指令
                final_content = f"[系统指令]: {system_content}\n\n{content}"
                system_content = ""  # 只加一次
            
            qwen_messages.append({
                "mime_type": "text/plain",
                "content": final_content,
                "meta_data": {"ori_query": final_content},
                "status": "complete",
            })
        elif role == "assistant":
            qwen_messages.append({
                "mime_type": "text/plain",
                "content": content,
                "meta_data": {},
                "status": "complete",
            })
    
    return qwen_messages


# ============================================================
# 核心：发送聊天请求
# ============================================================

async def send_chat(messages: list, model: str, stream: bool):
    if not baxia.initialized:
        success = await baxia.init()
        if not success:
            return {"error": "Baxia 初始化失败，请检查 Cookie"}

    # 获取会话信息（复用 session_id / topic_id）
    session_info = conversations.get_session(messages, model)
    session_id = session_info["session_id"]
    topic_id = session_info["topic_id"]

    # 转换消息格式
    qwen_messages = openai_messages_to_qwen(messages)
    if not qwen_messages:
        return {"error": "没有有效的消息内容"}

    req_id = str(uuid.uuid4()).replace("-", "")[:32]

    body = {
        "req_id": req_id,
        "parent_req_id": "0",
        "relate_req_id": str(uuid.uuid4()).replace("-", ""),
        "messages": qwen_messages,
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
        "version": "0.4.0 (pure python, multi-turn)",
        "baxia_ready": baxia.initialized,
        "sacsft_pool": len(baxia.sacsft_pool),
        "active_sessions": len(conversations._sessions),
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "Qwen3.7-Max", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
            {"id": "Qwen3.5-Flash", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
            {"id": "Qwen3-Max", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
            {"id": "Qwen3-Max-Thinking-Preview", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
            {"id": "Qwen3-Coder", "object": "model", "created": 1700000000, "owned_by": "alibaba"},
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
                    full_content = content
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


@app.get("/debug/sessions")
async def debug_sessions():
    """查看当前活跃会话"""
    sessions = []
    for key, val in conversations._sessions.items():
        sessions.append({
            "key": key[:16] + "...",
            "session_id": val["session_id"][:16] + "...",
            "last_used": time.time() - val["last_used"],
        })
    return {"count": len(sessions), "sessions": sessions[:20]}


if __name__ == "__main__":
    import uvicorn
    print(f"🚀 qwen2api v0.4.0 (Pure Python, Multi-turn) 启动中...")
    print(f"   服务地址: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT)
