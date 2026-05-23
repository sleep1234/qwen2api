"""
抓包分析辅助工具

用法：
  1. 把浏览器抓到的 cURL 命令粘贴到 capture.txt
  2. 运行 python parse_curl.py
  3. 自动生成 config 中需要填的内容
"""

import json
import re
import sys
from pathlib import Path


def parse_curl(curl_cmd: str) -> dict:
    """解析 cURL 命令，提取 URL、Headers、Body"""
    result = {"url": "", "method": "GET", "headers": {}, "body": None}

    # 提取 URL
    url_match = re.search(r"curl\s+(?:-[^\s]*\s+)*['\"]?(https?://[^\s'\"]+)", curl_cmd)
    if url_match:
        result["url"] = url_match.group(1).strip("'\"")

    # 提取 -X POST
    method_match = re.search(r"-X\s+(GET|POST|PUT|DELETE|PATCH)", curl_cmd, re.I)
    if method_match:
        result["method"] = method_match.group(1).upper()

    # 提取 Headers (-H)
    for match in re.finditer(r"-H\s+['\"](.+?)['\"]", curl_cmd):
        header = match.group(1)
        if ":" in header:
            key, value = header.split(":", 1)
            result["headers"][key.strip()] = value.strip()

    # 提取 Body (-d / --data-raw / --data)
    body_match = re.search(r"(?:--data-raw|--data|-d)\s+['\"](.+?)['\"]", curl_cmd, re.S)
    if body_match:
        raw = body_match.group(1)
        # 处理转义的单引号
        raw = raw.replace("\\'", "'")
        try:
            result["body"] = json.loads(raw)
        except json.JSONDecodeError:
            result["body"] = raw

    return result


def generate_config(parsed: dict) -> str:
    """根据解析结果生成 config.py 的相关配置"""
    lines = ["# === 从抓包自动生成 ===\n"]

    if parsed["url"]:
        lines.append(f'QWEN_API_URL = "{parsed["url"]}"\n')

    if parsed["headers"]:
        lines.append("\nQWEN_HEADERS = {")
        lines.append('    "Content-Type": "application/json",')
        for k, v in parsed["headers"].items():
            # 跳过一些自动生成的 header
            if k.lower() in ("content-length", "content-type"):
                continue
            escaped = v.replace('"', '\\"')
            lines.append(f'    "{k}": "{escaped}",')
        lines.append("}\n")

    if parsed["body"]:
        lines.append("\n# 请求体结构分析：")
        lines.append(f"# {json.dumps(parsed['body'], ensure_ascii=False, indent=2)}")
        lines.append("\n# 关键字段：")
        if isinstance(parsed["body"], dict):
            for key in parsed["body"]:
                lines.append(f"#   {key}: {type(parsed['body'][key]).__name__}")

    return "\n".join(lines)


def analyze_response(response_file: str):
    """分析保存的响应样本"""
    with open(response_file, "r") as f:
        content = f.read()

    print("=== 响应分析 ===\n")

    # 尝试按 SSE 格式解析
    events = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                print(f"✅ 找到结束标记 [DONE]")
                continue
            try:
                data = json.loads(data_str)
                events.append(data)
            except json.JSONDecodeError:
                events.append({"raw": data_str})

    if events:
        print(f"共 {len(events)} 个 SSE 事件\n")
        print("第一个事件的结构：")
        print(json.dumps(events[0], ensure_ascii=False, indent=2))
        print(f"\n最后一个事件的结构：")
        print(json.dumps(events[-1], ensure_ascii=False, indent=2))

        # 分析字段路径
        print("\n=== 提取内容的字段路径 ===")
        _find_content_paths(events[0], "")
    else:
        # 尝试当作普通 JSON
        try:
            data = json.loads(content)
            print("普通 JSON 响应：")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        except json.JSONDecodeError:
            print("原始内容（前 1000 字符）：")
            print(content[:1000])


def _find_content_paths(obj, prefix: str):
    """递归查找可能包含文本内容的字段"""
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(val, str) and len(val) > 0 and key not in ("id", "model", "object"):
                print(f"  {path} = \"{val[:50]}...\"" if len(val) > 50 else f"  {path} = \"{val}\"")
            elif isinstance(val, (dict, list)):
                _find_content_paths(val, path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _find_content_paths(item, f"{prefix}[{i}]")


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python analyze.py curl    解析 cURL 命令（从 stdin 或 capture.txt）")
        print("  python analyze.py response <file>  分析响应样本")
        print()
        print("快速流程:")
        print("  1. 浏览器 DevTools → Network → 右键请求 → Copy as cURL")
        print("  2. 粘贴到 capture.txt")
        print("  3. python analyze.py curl < capture.txt")
        return

    action = sys.argv[1]

    if action == "curl":
        if len(sys.argv) > 2:
            with open(sys.argv[2]) as f:
                curl_cmd = f.read()
        else:
            print("请粘贴 cURL 命令（Ctrl+D 结束）：")
            curl_cmd = sys.stdin.read()

        parsed = parse_curl(curl_cmd)
        print("\n=== 解析结果 ===")
        print(f"URL: {parsed['url']}")
        print(f"Method: {parsed['method']}")
        print(f"Headers: {len(parsed['headers'])} 个")
        if parsed["body"]:
            print(f"Body: {json.dumps(parsed['body'], ensure_ascii=False)[:200]}")

        print("\n=== 生成的配置 ===")
        print(generate_config(parsed))

    elif action == "response":
        if len(sys.argv) < 3:
            print("请指定响应文件路径")
            return
        analyze_response(sys.argv[2])


if __name__ == "__main__":
    main()
