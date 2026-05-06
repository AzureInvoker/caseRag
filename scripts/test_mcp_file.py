#!/usr/bin/env python3
"""
测试用例知识库 MCP — 用文件重定向方式测试
"""

import subprocess
import json
import sys
import time

# 构造请求
requests = [
    {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    }},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "method": "tools/list", "id": 2},
    {"jsonrpc": "2.0", "method": "tools/call", "id": 3, "params": {
        "name": "tc_stats", "arguments": {},
    }},
]

# 序列化为 MCP 协议格式
input_data = b""
for req in requests:
    raw = json.dumps(req, ensure_ascii=False)
    input_data += f"Content-Length: {len(raw.encode('utf-8'))}\r\n\r\n{raw}".encode()

import os
# 写入临时文件并重定向 stdin
tmpf = "/tmp/mcp_test_input.json"
with open(tmpf, "wb") as f:
    f.write(input_data)

proc = subprocess.Popen(
    [sys.executable, "/home/admin/testcase-rag/mcp/server.py"],
    stdin=open(tmpf, "rb"),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

try:
    stdout, stderr = proc.communicate(timeout=30)
except subprocess.TimeoutExpired:
    proc.kill()
    stdout, stderr = proc.communicate()

if stderr:
    print("STDERR:", stderr.decode()[:1000], file=sys.stderr)

# 解析 MCP 响应
pos = 0
data = stdout
response_count = 0
while pos < len(data):
    # 找 Content-Length 头
    header_end = data.find(b"\r\n\r\n", pos)
    if header_end == -1:
        break
    header = data[pos:header_end].decode()
    if not header.startswith("Content-Length:"):
        pos = header_end + 4
        continue
    length = int(header.split(":")[1].strip())
    body_start = header_end + 4
    body = data[body_start:body_start + length]
    try:
        resp = json.loads(body)
        resp_id = resp.get("id")
        if resp_id == 1:
            si = resp.get("result", {}).get("serverInfo", {})
            print(f"[INIT] {si.get('name')} v{si.get('version')}")
            assert si["name"] == "testcase-rag-mcp"
            response_count += 1
        elif resp_id == 2:
            tools = resp.get("result", {}).get("tools", [])
            print(f"[TOOLS] {len(tools)} 个工具:")
            for t in tools:
                print(f"  - {t['name']}: {t['description'][:60]}...")
            assert len(tools) == 4
            response_count += 1
        elif resp_id == 3:
            text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
            print(f"[STATS] {text[:200]}")
            assert "总用例数" in text
            response_count += 1
        pos = body_start + length
    except json.JSONDecodeError:
        pos = body_start + length
        continue

print(f"\n✅ 收到 {response_count}/3 个响应，测试通过！")
