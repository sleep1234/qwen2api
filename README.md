# qwen2api

通义千问网页端逆向 API 封装，纯 Python 实现，**不需要浏览器**。

## ✨ 特性

- 🔄 **多轮对话** — 完整传递 OpenAI 格式的 messages 数组，支持上下文连续
- 📦 **自动上下文压缩** — 当对话超过有效 token 极限时，自动压缩旧消息为摘要，保证不丢失关键上下文
- 🌊 **流式输出** — 支持 SSE 流式和非流式两种模式
- 🔐 **Baxia 签名** — 纯 Python 复现阿里系反爬签名，无需浏览器
- 🔌 **OpenAI 兼容** — 标准 `/v1/chat/completions` 接口，可直接用 OpenAI SDK 调用
- 💾 **状态持久化** — Baxia 注册状态缓存到本地，重启无需重新注册
- 🔄 **自动刷新** — sacsft token 池不足时自动刷新

## 原理

通过逆向通义千问网页端的 Baxia 反爬签名系统，用纯 Python 实现：

```
客户端请求 → HMAC-SHA256 签名 → chat2.qianwen.com/api/v2/chat → SSE 流式响应 → OpenAI 格式
```

### 签名流程（逆向自 `pre.js`）

```
1. register → 获取 actkn, sacsft 池（100个）
2. 每次请求消耗一个 sacsft
3. bodyKey = sacsft + ":" + timestamp
4. bodyHmac = HMAC-SHA256(body, bodyKey)
5. signText = deviceId + version + kp + queryParams + bodyHmac
6. sign = HMAC-SHA256(signText, bodyKey)
```

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn httpx sse-starlette
```

### 2. 配置 Cookie

在浏览器中登录 [tongyi.aliyun.com](https://tongyi.aliyun.com/qianwen)，打开 DevTools → Network → 任意请求 → 复制 Cookie 字符串，填入 `config.py`：

```python
QWEN_COOKIES = "你的cookie字符串"
```

关键字段：`tongyi_sso_ticket`, `tongyi_sso_ticket_hash`, `cna`, `isg`

> 💡 **获取 Cookie 的方法：**
> 1. 用浏览器打开 [tongyi.aliyun.com](https://tongyi.aliyun.com/qianwen) 并登录
> 2. 按 F12 打开 DevTools → Network 标签
> 3. 在千问里发一条消息，在 Network 里找到任意请求
> 4. 右键请求 → Copy → Copy as cURL
> 5. 从 cURL 命令中提取 `cookie:` 后面的完整字符串
>
> 也可以用项目里的 `analyze.py` 工具自动解析 cURL 命令。

### 3. 启动服务

```bash
# 推荐版本（支持多轮对话 + 自动上下文压缩）
python server_pure_v2.py

# 旧版本（仅单轮，参考用）
python server_pure.py
```

### 4. 调用

```bash
# 单轮对话
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.7-Max",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

```bash
# 多轮对话（带上下文）
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.7-Max",
    "messages": [
      {"role": "system", "content": "你是一个记账助手"},
      {"role": "user", "content": "我午饭花了35元"},
      {"role": "assistant", "content": "好的，已记录：午餐 35元。总计 35元。"},
      {"role": "user", "content": "我一共花了多少钱？"}
    ],
    "stream": false
  }'
```

```python
# Python OpenAI SDK
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="any")
resp = client.chat.completions.create(
    model="Qwen3.7-Max",
    messages=[
        {"role": "system", "content": "你是一个有帮助的助手"},
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "你好小明！"},
        {"role": "user", "content": "我叫什么？"},
    ],
    stream=True,
)
for chunk in resp:
    print(chunk.choices[0].delta.content or "", end="")
```

## 🧠 多轮对话与上下文压缩

### 核心问题

通义千问网页端 API 的**有效上下文极限约为 27K tokens**（实测值，远低于官方宣称的 128K）。

超过这个范围，API 不会报错，但模型会**静默丢失上下文**——回复变成通用问候语，之前的对话全部"失忆"。

### 解决方案：自动上下文压缩

`server_pure_v2.py` 内置了自动压缩机制：

```
输入 tokens > 22000（阈值）
    ↓
提取 system prompt（保留）
    ↓
保留最近 4 轮对话（完整保留）
    ↓
中间旧消息 → 压缩为摘要（用户消息保留 200 字，助手回复保留 100 字）
    ↓
摘要超过 15K tokens → 截断，只保留最近的部分
    ↓
拼接：system prompt + 摘要 + 最近对话 → 发送给 API
```

### 压缩效果实测

| 原始 tokens | 压缩后 | 压缩率 | 上下文保持 |
|---|---|---|---|
| ~27K | 不压缩 | 0% | ✅ |
| ~44K | ~15.7K | -64% | ✅ |
| ~66K | ~15.7K | -76% | ✅ |
| ~88K | ~15.7K | -82% | ✅ |
| ~111K | ~15.7K | -86% | ✅ |
| ~133K | ~15.7K | -88% | ✅ |

> 压缩后模型仍能正确回答关于对话历史的问题，因为它通过摘要保留了关键信息。

### 压缩参数

在 `server_pure_v2.py` 顶部可以调整：

```python
MAX_CONTEXT_TOKENS = 22000   # 触发压缩的阈值
KEEP_RECENT_TURNS = 4        # 保留最近几轮完整对话
```

## 可用模型

| 模型 | Model Code | 上下文窗口 |
|------|-----------|-----------|
| Qwen3.7-Max | `Qwen3.7-Max` | ~128K (有效 ~27K) |
| Qwen3.5-Flash | `Qwen3.5-Flash` | ~128K (有效 ~27K) |
| Qwen3-Max | `Qwen3-Max` | ~128K (有效 ~27K) |
| Qwen3-Max-Thinking | `Qwen3-Max-Thinking-Preview` | ~128K (有效 ~27K) |
| Qwen3-Coder | `Qwen3-Coder` | ~128K (有效 ~27K) |

> ⚠️ "有效 ~27K" 是网页端 API 的实测值。开启自动压缩后，可处理任意长度的对话。

## 上下文探测

运行探测脚本，自动测试上下文边界：

```bash
# 完整探测（每个模型逐个测试，耗时较长）
python probe.py

# 快速探测（单模型多档位测试）
python test_context_limit.py
```

探测结果会打印到终端，`probe.py` 还会保存到 `probe_results.json`。

## 接口

| 路径 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务状态（含 Baxia 初始化状态、sacsft 池余量、活跃会话数） |
| `/v1/models` | GET | 模型列表 |
| `/v1/chat/completions` | POST | OpenAI 兼容聊天接口（支持流式/非流式、多轮对话） |
| `/debug/register` | POST | 手动触发 Baxia 注册 |
| `/debug/sessions` | GET | 查看当前活跃会话列表 |

## 项目结构

```
qwen2api/
├── server_pure_v2.py      # ⭐ 主服务（多轮对话 + 自动上下文压缩）
├── server_pure.py          # 旧版主服务（单轮，参考用）
├── server.py               # 通用骨架（参考用）
├── config.py               # 配置文件（Cookie、端口等）
├── test_context_limit.py   # 上下文极限探测工具
├── analyze.py              # 抓包分析辅助工具（解析 cURL 命令）
├── packet_analysis.py      # 抓包分析笔记（请求/响应格式记录）
├── probe.py                # 上下文 Token 边界探测器（二分法）
├── test.py                 # 测试脚本
├── README.md               # 本文件
├── .gitignore              # Git 忽略规则
└── js/                     # 逆向分析用的 JS 文件（参考）
    ├── main.js             # 前端主逻辑（打包后）
    ├── pre.js              # Baxia 签名逻辑（逆向重点）
    ├── core-libs.js        # 核心库
    ├── vendor.js           # 第三方库
    └── tongyi-checker.js   # 浏览器兼容性检测
```

## 接入 OpenClaw

本项目暴露标准 OpenAI 兼容接口，可以接入 [OpenClaw](https://github.com/openclaw/openclaw) 等支持自定义模型的平台。

```
qwen2api (localhost:8000) ← OpenClaw 配置 base_url 指向这里
```

## 技术细节

### 反爬体系分析

通义千问使用阿里系 **Baxia** 反爬系统，核心组件：

| 组件 | 地址 | 作用 |
|------|------|------|
| 注册/刷新 | `sec.qianwen.com` | 获取和刷新 sacsft token 池 |
| 聊天 API | `chat2.qianwen.com` | 实际的对话请求 |
| `eo-clt-*` headers | — | 签名/设备标识 |
| `clt-acs-*` headers | — | 请求签名/时间戳 |
| AWSC SDK | — | 浏览器指纹/umid 生成 |

### 关键 Headers

```
【认证类】
  cookie: tongyi_sso_ticket=...        ← SSO 登录凭证（核心）
  cookie: tongyi_sso_ticket_hash=...   ← 即 kp 值，用于签名
  cookie: cna=...                      ← 阿里系设备 ID
  cookie: isg=...                      ← 阿里系会话签名

【反爬签名类】（Baxia 系统）
  eo-clt-actkn: ...                    ← 加密的访问 token
  eo-clt-sacsft: ...                   ← 签名 token（每次消耗一个）
  eo-clt-snver: ...                    ← 签名版本
  eo-clt-dvidn: ...                    ← 加密设备标识
  eo-clt-acs-kp: ...                   ← ticket hash
  clt-acs-sign: ...                    ← HMAC-SHA256 签名结果
  clt-acs-reqt: ...                    ← 请求时间戳（毫秒）

【业务类】
  x-device-id: ...                     ← 设备 ID
  x-chat-id: ...                       ← 当前聊天 ID
  x-platform: pc_tongyi                ← 平台标识
```

### 请求体格式

```json
{
  "req_id": "唯一请求ID",
  "parent_req_id": "0",
  "relate_req_id": "关联请求ID",
  "messages": [
    {
      "mime_type": "text/plain",
      "content": "消息内容",
      "meta_data": {"ori_query": "原始内容"},
      "status": "complete"
    }
  ],
  "scene": "chat",
  "session_id": "会话ID",
  "biz_id": "ai_qwen",
  "topic_id": "话题ID",
  "model": "Qwen3.7-Max",
  "protocol_version": "v2",
  "chat_client": "h5"
}
```

### 响应格式（SSE 流式）

```
data: {"data":{"messages":[{"content":"你好","status":"streaming"}]}}

data: {"data":{"messages":[{"content":"你好！有什么","status":"streaming"}]}}

data: {"data":{"messages":[{"content":"你好！有什么可以帮助你的吗？","status":"complete"}]}}

data: true
```

> 注意：通义千问的 SSE 格式不是 OpenAI 格式，`server_pure_v2.py` 会自动转换。

### 逆向过程

1. 浏览器抓包分析请求格式
2. 下载页面 JS 文件（`pre.js`、`main.js`）
3. 定位签名函数 `calculateSignature`
4. 提取 HMAC-SHA256 签名算法
5. 用 Python 复现签名流程
6. 通过 register 接口获取 token 池
7. 实现 OpenAI 兼容 API
8. 实测上下文边界，实现自动压缩

## 注意事项

- Cookie 有有效期，过期后需要重新获取
- Baxia 的 sacsft token 池有 100 个，用完自动刷新
- 网页端 API 的有效上下文约 27K tokens（已通过自动压缩解决）
- 本项目仅供技术研究，请遵守通义千问的使用条款

## License

MIT
