"""
qwen2api 配置文件

TODO: 抓包后把实际值填进来
"""

# ============================================================
# 1. 通义千问后端接口地址（从抓包中获取）
# ============================================================
# 打开 tongyi.aliyun.com，发一条消息，在 Network 里找到实际的请求地址
# 通常是 POST 请求，URL 类似：
#   https://qianwen.aliyun.com/api/chat/completions
#   https://qianwen.aliyun.com/v2/api/chat/completions
#   https://chat.qwenlm.ai/api/chat/completions
QWEN_API_URL = "https://qianwen.aliyun.com/api/chat/completions"  # TODO: 替换为实际地址

# ============================================================
# 2. 请求头（从抓包中获取）
# ============================================================
# 把浏览器请求的 Headers 完整复制过来
# 关键字段通常包括：
#   Cookie          — 登录态
#   Authorization   — Bearer token 或其他格式
#   X-CSRF-Token    — CSRF 防护
#   User-Agent      — 浏览器标识
#   Referer         — 来源页面
QWEN_HEADERS = {
    "Content-Type": "application/json",
    "Cookie": "TODO_REPLACE_ME",           # TODO: 从浏览器复制
    "Authorization": "Bearer TODO",        # TODO: 如果有的话
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://tongyi.aliyun.com/qianwen",
    "Origin": "https://tongyi.aliyun.com",
    # "X-CSRF-Token": "TODO",             # TODO: 如果有的话
}

# ============================================================
# 3. 请求体模板（从抓包中分析）
# ============================================================
# 观察浏览器发送的 JSON 结构，下面是一个常见模板
# 实际字段名和嵌套结构需要根据抓包调整
QWEN_REQUEST_TEMPLATE = {
    "model": "qwen-max",                   # TODO: 确认实际的模型标识
    "messages": [],                        # 由代码动态填充
    "stream": True,                        # 启用流式输出
    # ============================================================
    # 4. 上下文长度探索（你的核心目标之一）
    # ============================================================
    # "max_tokens": 8192,                  # TODO: 试探最大值
    # "max_input_tokens": 30000,           # TODO: 如果支持的话
    # "context_length": 32768,             # TODO: 如果支持的话
}

# ============================================================
# 5. 对外暴露的 API 配置
# ============================================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000

# API Key 访问控制（可选，保护你的 API 不被滥用）
# 留空则不启用鉴权
API_KEY = ""

# ============================================================
# 6. Token 计数配置
# ============================================================
# 用于估算上下文长度，帮助试探边界
TOKEN_ENCODING = "cl100k_base"  # 通用编码，Qwen 可能不同，但可估算

# ============================================================
# 7. Cookie（必须配置）
# ============================================================
# 从浏览器抓包中提取的 Cookie 字符串
# 关键字段：tongyi_sso_ticket, cna, isg
# 登录 tongyi.aliyun.com 后，从 DevTools → Network → 任意请求 → Headers → Cookie 复制
QWEN_COOKIES = ""  # TODO: 填入你的 Cookie
