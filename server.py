"""
qwen2api — 通义千问网页转 API 服务

核心流程：
  客户端请求 → OpenAI 格式解析 → 转发到通义千问后端 → 流式/非流式响应

研究目标：
  1. 逆向通义千问网页端的 API 协议
  2. 封装为 OpenAI 兼容格式
  3. 试探上下文 token 上限
"""

import json
import time
import uuid
import asyncio
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

import config

app = FastAPI(title="qwen2api", version="0.1.0")


# ============================================================
# 工具函数
# ============================================================

def generate_chat_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:12]}"


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中英混合场景）"""
    try:
        import tiktoken
        enc = tiktoken.get_encoding(config.TOKEN_ENCODING)
        return len(enc.encode(text))
    except Exception:
        # fallback: 中文约 1.5 字/token，英文约 4 字符/token
        cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        en_chars = len(text) - cn_chars
        return int(cn_chars / 1.5 + en_chars / 4)


def build_qwen_payload(messages: list, stream: bool = True) -> dict:
    """
    把 OpenAI 格式的 messages 转成通义千问的请求体
    
    TODO: 根据抓包结果调整这个函数的映射逻辑
    """
    payload = {
        **config.QWEN_REQUEST_TEMPLATE,
        "messages": messages,
        "stream": stream,
    }
    return payload


def qwen_headers() -> dict:
    """构建请求头，可以在这里加动态逻辑（如 token 刷新）"""
    return {**config.QWEN_HEADERS}


# ============================================================
# 核心：转发到通义千问
# ============================================================

async def stream_qwen_response(messages: list):
    """
    流式请求通义千问，yield SSE 格式的数据块
    
    TODO: 根据实际抓包调整响应解析逻辑
    通义千问的 SSE 格式可能是：
      data: {"text": "你"}     ← 逐字/逐句
      data: {"text": "好"}
      data: [DONE]             ← 结束标记
    
    或者是 OpenAI 兼容格式：
      data: {"choices": [{"delta": {"content": "你"}}]}
    """
    completion_id = generate_chat_completion_id()
    created = int(time.time())
    payload = build_qwen_payload(messages, stream=True)
    headers = qwen_headers()

    total_content = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        try:
            async with client.stream(
                "POST",
                config.QWEN_API_URL,
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    yield _error_sse(
                        completion_id, created,
                        f"通义千问返回 HTTP {resp.status_code}: {error_body.decode()}"
                    )
                    return

                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                # 结束
                                yield _final_sse(completion_id, created)
                                return
                            try:
                                data = json.loads(data_str)
                                # ============================================================
                                # TODO: 根据实际响应格式提取 content
                                # 通义千问的响应格式可能是：
                                #   {"text": "..."}                          — 旧格式
                                #   {"choices": [{"delta": {"content": "..."}}]} — OpenAI 格式
                                #   {"result": {"text": "..."}}              — 嵌套格式
                                #   {"output": {"choices": [{"message": {"content": "..."}}]}}
                                # ============================================================
                                content = _extract_content(data)
                                if content:
                                    total_content += content
                                    yield _content_sse(
                                        completion_id, created, content
                                    )
                            except json.JSONDecodeError:
                                # 可能是纯文本流
                                if data_str:
                                    total_content += data_str
                                    yield _content_sse(
                                        completion_id, created, data_str
                                    )

        except httpx.ReadTimeout:
            yield _error_sse(completion_id, created, "请求超时")

    # 如果循环结束没有收到 [DONE]
    yield _final_sse(completion_id, created)


def _extract_content(data: dict) -> str:
    """
    从通义千问的响应 JSON 中提取文本内容
    
    TODO: 根据抓包结果确认实际路径，下面列出各种可能：
    """
    # 尝试多种可能的响应格式
    # 格式 1: OpenAI 兼容
    choices = data.get("choices", [])
    if choices:
        delta = choices[0].get("delta", {})
        content = delta.get("content", "")
        if content:
            return content

    # 格式 2: {"text": "..."}
    text = data.get("text", "")
    if text:
        return text

    # 格式 3: {"result": {"text": "..."}}
    result = data.get("result", {})
    if isinstance(result, dict):
        text = result.get("text", "")
        if text:
            return text

    # 格式 4: {"output": {"choices": [...]}}
    output = data.get("output", {})
    if isinstance(output, dict):
        output_choices = output.get("choices", [])
        if output_choices:
            msg = output_choices[0].get("message", {})
            content = msg.get("content", "")
            if content:
                return content

    return ""


# ============================================================
# SSE 格式化（OpenAI 兼容）
# ============================================================

def _content_sse(completion_id: str, created: int, content: str) -> dict:
    return {
        "event": "message",
        "data": json.dumps({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": config.QWEN_REQUEST_TEMPLATE.get("model", "qwen"),
            "choices": [{
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }],
        }, ensure_ascii=False),
    }


def _final_sse(completion_id: str, created: int) -> dict:
    return {
        "event": "message",
        "data": json.dumps({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": config.QWEN_REQUEST_TEMPLATE.get("model", "qwen"),
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
        }, ensure_ascii=False),
    }


def _error_sse(completion_id: str, created: int, error_msg: str) -> dict:
    return {
        "event": "message",
        "data": json.dumps({
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": config.QWEN_REQUEST_TEMPLATE.get("model", "qwen"),
            "choices": [{
                "index": 0,
                "delta": {"content": f"\n\n[ERROR] {error_msg}"},
                "finish_reason": "stop",
            }],
        }, ensure_ascii=False),
    }


# ============================================================
# API 路由
# ============================================================

@app.get("/")
async def root():
    return {
        "name": "qwen2api",
        "version": "0.1.0",
        "status": "running",
        "endpoints": ["/v1/chat/completions", "/v1/models", "/probe"],
    }


@app.get("/v1/models")
async def list_models():
    """OpenAI 兼容的模型列表"""
    return {
        "object": "list",
        "data": [
            {
                "id": "qwen-max",
                "object": "model",
                "created": 1700000000,
                "owned_by": "alibaba",
            },
            {
                "id": "qwen-plus",
                "object": "model",
                "created": 1700000000,
                "owned_by": "alibaba",
            },
            {
                "id": "qwen-turbo",
                "object": "model",
                "created": 1700000000,
                "owned_by": "alibaba",
            },
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI 兼容的 Chat Completions 接口
    """
    # API Key 鉴权（可选）
    if config.API_KEY:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != config.API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API Key")

    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    model = body.get("model", "qwen-max")

    if not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    # 估算 token 用量（用于研究）
    total_input = sum(estimate_tokens(m.get("content", "")) for m in messages)
    print(f"[probe] model={model} | input_tokens≈{total_input} | messages={len(messages)} | stream={stream}")

    if stream:
        return EventSourceResponse(stream_qwen_response(messages))
    else:
        # 非流式：收集所有内容后返回
        full_content = ""
        async for event in stream_qwen_response_non_stream(messages):
            full_content += event
        return JSONResponse({
            "id": generate_chat_completion_id(),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": total_input,
                "completion_tokens": estimate_tokens(full_content),
                "total_tokens": total_input + estimate_tokens(full_content),
            },
        })


async def stream_qwen_response_non_stream(messages: list):
    """非流式模式：收集所有片段"""
    async for event in stream_qwen_response(messages):
        data_str = event.get("data", "{}")
        try:
            data = json.loads(data_str)
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
        except json.JSONDecodeError:
            pass


# ============================================================
# 探测接口：试探上下文边界
# ============================================================

@app.post("/probe")
async def probe_context_limit(request: Request):
    """
    专门用来试探上下文 token 上限的接口
    
    发送不同长度的输入，观察返回：
    - 正常响应 → 还没到上限
    - 报错/截断 → 找到边界了
    - 返回内容变短 → 可能接近上限
    """
    body = await request.json()
    target_tokens = body.get("target_tokens", 1000)
    test_prompt = body.get("prompt", "请回复OK")

    # 生成指定长度的填充文本
    filler = "这是一段测试文本。" * (target_tokens // 5)
    actual_tokens = estimate_tokens(filler + test_prompt)

    messages = [
        {"role": "system", "content": filler},
        {"role": "user", "content": test_prompt},
    ]

    print(f"[probe] 测试 {actual_tokens} tokens 的上下文...")

    # 发送请求并记录结果
    result = {
        "target_tokens": target_tokens,
        "estimated_tokens": actual_tokens,
        "status": "pending",
        "response_length": 0,
        "error": None,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            payload = build_qwen_payload(messages, stream=False)
            # 非流式方便分析
            payload["stream"] = False
            resp = await client.post(
                config.QWEN_API_URL,
                headers=qwen_headers(),
                json=payload,
            )
            result["http_status"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                content = _extract_content(data) if isinstance(data, dict) else str(data)
                result["status"] = "ok"
                result["response_length"] = len(content)
                result["response_preview"] = content[:200]
            else:
                result["status"] = "error"
                result["error"] = resp.text[:500]
    except Exception as e:
        result["status"] = "exception"
        result["error"] = str(e)

    return JSONResponse(result)


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print(f"🚀 qwen2api 启动中...")
    print(f"   目标接口: {config.QWEN_API_URL}")
    print(f"   服务地址: http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    print(f"   OpenAI 兼容: http://{config.SERVER_HOST}:{config.SERVER_PORT}/v1/chat/completions")
    print(f"   上下文探测: POST http://{config.SERVER_HOST}:{config.SERVER_PORT}/probe")
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT)
