"""
抓包分析结果
=============

来源：通义千问移动端 H5（www.qianwen.com）
时间：2026-05-23
"""

# ============================================================
# 1. 接口地址
# ============================================================
# POST https://chat2.qianwen.com/api/v2/chat
#
# Query 参数（部分是动态的）：
#   biz_id=ai_qwen
#   fe_version=1.0.0
#   chat_client=h5
#   device=pc
#   fr=h5
#   pr=qwen
#   ut=<device_id>           ← 动态，设备标识
#   la=zh-CN
#   tz=Asia/Shanghai
#   wv=2.9.3
#   ve=2.9.3
#   nonce=<random>           ← 动态，随机字符串
#   timestamp=<ms>           ← 动态，毫秒时间戳

# ============================================================
# 2. 请求体（已确认结构）
# ============================================================
# {
#   "req_id": "<chatId><random>",        ← 请求唯一标识
#   "parent_req_id": "0",                ← 父请求ID（首轮为0）
#   "relate_req_id": "<uuid>",           ← 关联请求ID
#   "messages": [{
#     "mime_type": "text/plain",
#     "content": "用户消息内容",
#     "meta_data": {"ori_query": "用户消息内容"},
#     "status": "complete"
#   }],
#   "scene": "chat",
#   "sub_scene": "",
#   "scene_param": "retry",              ← 首次聊天可能是 ""
#   "operation_type": "regenerate",      ← 首次可能是 "send"
#   "session_id": "<uuid>",              ← 会话ID
#   "biz_id": "ai_qwen",
#   "topic_id": "<uuid>",                ← 话题ID
#   "model": "Qwen3.7-Max",             ← 模型标识
#   "from": "default",
#   "protocol_version": "v2",
#   "messages_merge": false,
#   "chat_client": "h5",
#   "deep_search": "0",
#   "ai_tool_scene": ""
# }

# ============================================================
# 3. 关键 Headers 分析
# ============================================================
#
# 【认证类】
#   cookie: tongyi_sso_ticket=...        ← SSO 登录凭证（最重要）
#   cookie: tongyi_sso_ticket_hash=...   ← ticket 的 hash
#   cookie: cna=...                      ← 阿里系设备ID
#   cookie: isg=...                      ← 阿里系会签名
#   cookie: tfstk=...                    ← 阿里系安全token
#
# 【反爬签名类】（这是难点！）
#   eo-clt-actkn: KXhBzvaR...           ← 加密的访问token
#   eo-clt-sacsft: PRAiGhcS...          ← 签名
#   eo-clt-snver: lv                     ← 签名版本
#   eo-clt-dvidn: eCy#AAN5...           ← 加密设备标识
#   eo-clt-acs-kp: tytk_hash:46c239...  ← ticket hash
#   eo-clt-acs-kp: tytk_hash:46c239...  ← ticket hash
#   clt-acs-sign: bEinbSUc...           ← 请求签名
#   clt-acs-bfg: tqqhUH+j...           ← 指纹
#   clt-acs-reqt: 1779502075863         ← 请求时间戳
#   clt-acs-request-params: biz_id,...  ← 参与签名的参数列表
#   clt-acs-caer: vrad                   ← 算法标识
#
# 【业务类】
#   x-device-id: <uuid>                  ← 设备ID
#   x-chat-id: <req_id>                  ← 当前聊天ID
#   x-chat-biz: {"chatId":...,"agentId":""}  ← 聊天业务参数
#   x-platform: pc_tongyi                ← 平台标识
#   x-csrf-token: (空)                   ← CSRF token
#   x-wpk-reqid: <req_id>               ← 请求ID
#   x-wpk-traceid: <trace_id>           ← 链路追踪
#   x-wpk-bid: 66ur41cs-cntu1744        ← 业务ID

# ============================================================
# 4. 响应格式
# ============================================================
# HTTP/2 200
# content-type: text/event-stream;charset=UTF-8
# 
# SSE 流式响应（需要拿到实际的 data 内容才能确认格式）

# ============================================================
# 5. 关键发现
# ============================================================
# ✅ 接口地址确认：chat2.qianwen.com/api/v2/chat
# ✅ 请求体格式确认：v2 协议，messages 数组
# ✅ 模型标识确认：Qwen3.7-Max
# ✅ 认证方式确认：Cookie（tongyi_sso_ticket 为核心）
# ⚠️ 存在反爬签名：eo-clt-* 和 clt-acs-* 系列 header
# ⚠️ 签名算法未知：需要逆向 JS 分析
# ❓ SSE 响应格式：需要额外抓包看 data 内容
