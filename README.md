# qwen2api

通义千问网页端逆向 API 封装，纯 Python 实现，**不需要浏览器**。

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

关键字段：`tongyi_sso_ticket`, `cna`, `isg`

### 3. 启动服务

```bash
python server_pure.py
```

### 4. 调用

```bash
# OpenAI 兼容格式
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.7-Max",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

```python
# Python OpenAI SDK
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="any")
resp = client.chat.completions.create(
    model="Qwen3.7-Max",
    messages=[{"role": "user", "content": "你好"}],
    stream=True,
)
for chunk in resp:
    print(chunk.choices[0].delta.content or "", end="")
```

## 项目结构

```
qwen2api/
├── server_pure.py     # 主服务（纯 Python，已验证可用）
├── server.py          # 通用骨架（参考用）
├── config.py          # 配置文件（Cookie、端口等）
├── analyze.py         # 抓包分析辅助工具
├── probe.py           # 上下文 Token 边界探测器
├── test.py            # 测试脚本
├── README.md          # 本文件
├── .gitignore         # Git 忽略规则
└── js/                # 逆向分析用的 JS 文件（参考）
    ├── main.js
    ├── pre.js
    ├── core-libs.js
    ├── vendor.js
    └── tongyi-checker.js
```

## 可用模型

| 模型 | Model Code | 上下文窗口 |
|------|-----------|-----------|
| Qwen3.7-Max | `Qwen3.7-Max` | ~128K |
| Qwen3.5-Flash | `Qwen3.5-Flash` | ~128K |
| Qwen3-Max | `Qwen3-Max` | ~128K |
| Qwen3-Max-Thinking | `Qwen3-Max-Thinking-Preview` | ~128K |
| Qwen3-Coder | `Qwen3-Coder` | ~128K |

## 上下文探测

运行探测脚本，自动测试每个模型的最大上下文长度：

```bash
python probe.py
```

结果保存到 `probe_results.json`。

## 接口

| 路径 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务状态 |
| `/v1/models` | GET | 模型列表 |
| `/v1/chat/completions` | POST | OpenAI 兼容聊天接口 |
| `/debug/register` | POST | 手动触发 Baxia 注册 |

## 注意事项

- Cookie 有有效期，过期后需要重新获取
- Baxia 的 sacsft token 池有 100 个，用完需刷新
- 本项目仅供技术研究，请遵守通义千问的使用条款
- 上下文窗口实测约 128K tokens（可能因账号/模型版本不同）

## 技术细节

### 反爬体系分析

通义千问使用阿里系 **Baxia** 反爬系统，核心组件：

- `sec.qianwen.com` — 注册/刷新 token
- `chat2.qianwen.com` — 聊天 API
- `eo-clt-*` 系列 header — 签名/设备标识
- `AWSC` SDK — 浏览器指纹/umid 生成

### 逆向过程

1. 浏览器抓包分析请求格式
2. 下载页面 JS 文件（`pre.js`、`main.js`）
3. 定位签名函数 `calculateSignature`
4. 提取 HMAC-SHA256 签名算法
5. 用 Python 复现签名流程
6. 通过 register 接口获取 token 池
7. 实现 OpenAI 兼容 API

## License

MIT
