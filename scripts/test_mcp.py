#!/usr/bin/env python3
"""
测试用例知识库 MCP Server 测试
"""

import subprocess
import json
import sys

proc = subprocess.Popen(
    [sys.executable, "mcp/server.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)


def send(msg: dict):
    raw = json.dumps(msg, ensure_ascii=False)
    data = f"Content-Length: {len(raw.encode('utf-8'))}\r\n\r\n{raw}"
    proc.stdin.write(data.encode())
    proc.stdin.flush()


def recv() -> dict | None:
    line = b""
    while True:
        c = proc.stdout.read(1)
        if not c:
            return None
        if c == b"\n" and line.endswith(b"\r"):
            break
        line += c
    header = line.decode().strip()
    if not header.startswith("Content-Length:"):
        return None
    length = int(header.split(":")[1].strip())
    proc.stdout.read(2)  # \r\n
    raw = proc.stdout.read(length)
    return json.loads(raw) if raw else None


# 1. Initialize
send({"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "1.0"},
}})
resp = recv()
print("[INIT]", json.dumps(resp, ensure_ascii=False)[:100], "...")
assert resp and resp.get("result", {}).get("serverInfo", {}).get("name") == "testcase-rag-mcp"

# 2. 初始化通知
send({"jsonrpc": "2.0", "method": "notifications/initialized"})

# 3. tools/list
send({"jsonrpc": "2.0", "method": "tools/list", "id": 2})
resp = recv()
tools = resp.get("result", {}).get("tools", [])
print(f"[TOOLS] {len(tools)} 个工具:")
for t in tools:
    print(f"  - {t['name']}: {t['description'][:60]}...")
assert len(tools) == 4

# 4. tc_stats
send({"jsonrpc": "2.0", "method": "tools/call", "id": 3, "params": {
    "name": "tc_stats", "arguments": {},
}})
resp = recv()
text = resp["result"]["content"][0]["text"]
print(f"[STATS] 前200字:\n{text[:200]}")
assert "总用例数" in text

# 5. tc_search
send({"jsonrpc": "2.0", "method": "tools/call", "id": 4, "params": {
    "name": "tc_search", "arguments": {"query": "登录失败"},
}})
resp = recv()
text = resp["result"]["content"][0]["text"]
print(f"[SEARCH] 前200字:\n{text[:200]}")
assert "登录" in text

proc.stdin.close()
proc.wait(timeout=5)
print(f"\n✅ 所有测试通过！退出码: {proc.returncode}")
