#!/bin/bash
# 测试用例知识库 — 管理脚本
# 配置优先级: 环境变量 > config.yaml > 默认值
set -e

cd "$(dirname "$0")"

# ── 加载配置 ──

# 尝试从 config.yaml 读取
if [ -f config.yaml ]; then
  _host=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('api',{}).get('host',''))" 2>/dev/null)
  _port=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('api',{}).get('port',''))" 2>/dev/null)
fi

# 环境变量覆盖
API_HOST="${TC_API_HOST:-${_host:-0.0.0.0}}"
API_PORT="${TC_API_PORT:-${_port:-8765}}"

# ── 命令分发 ──

case "${1:-help}" in
  api)
    echo "🚀 启动 REST API (${API_HOST}:${API_PORT})..."
    echo "   Swagger: http://localhost:${API_PORT}/docs"
    exec uvicorn server.api:app --host "${API_HOST}" --port "${API_PORT}" --reload
    ;;
  api:bg)
    echo "🚀 后台启动 REST API (${API_HOST}:${API_PORT})..."
    nohup uvicorn server.api:app --host "${API_HOST}" --port "${API_PORT}" > /tmp/testcase-rag-api.log 2>&1 &
    echo "  PID: $!"
    echo "  日志: /tmp/testcase-rag-api.log"
    echo "  API: http://${API_HOST}:${API_PORT}"
    ;;
  mcp)
    echo "🧩 启动 MCP Server (stdio)..."
    exec python3 mcp/server.py
    ;;
  mcp:test)
    echo "🧪 测试 MCP Server..."
    python3 -c "
import subprocess, json
proc = subprocess.Popen(['python3', 'mcp/server.py'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
def s(m):
    raw = json.dumps(m, ensure_ascii=False)
    proc.stdin.write(f'Content-Length: {len(raw.encode(\"utf-8\"))}\\r\\n\\r\\n{raw}'.encode())
    proc.stdin.flush()
def r():
    line = b''
    while True:
        c = proc.stdout.read(1)
        if not c: return None
        if c == b'\\n' and line.endswith(b'\\r'): break
        line += c
    h = line.decode().strip()
    l = int(h.split(':')[1].strip())
    proc.stdout.read(2)
    return json.loads(proc.stdout.read(l))

s({'jsonrpc':'2.0','method':'initialize','id':1}); print('Init:', r().get('result',{}).get('serverInfo'))
s({'jsonrpc':'2.0','method':'notifications/initialized'})
s({'jsonrpc':'2.0','method':'tools/list','id':2})
tools = r().get('result',{}).get('tools',[])
print(f'工具 ({len(tools)}):')
for t in tools: print(f'  - {t[\"name\"]}: {t[\"description\"][:50]}...')
proc.stdin.close(); proc.wait()
print('✅ MCP 测试通过')
" 2>&1
    ;;
  api:test)
    echo "🧪 测试 REST API..."
    if ! curl -sf "http://${API_HOST}:${API_PORT}/api/v1/health" >/dev/null 2>&1; then
      echo "⚠️  API 未运行，请先执行 ./run.sh api:bg"
      exit 1
    fi
    echo "✅ Health: $(curl -s "http://${API_HOST}:${API_PORT}/api/v1/health")"
    echo "---"
    echo "✅ Stats: $(curl -s "http://${API_HOST}:${API_PORT}/api/v1/stats")"
    ;;
  seed)
    echo "🌱 填充示例测试用例..."
    python3 scripts/seed_data.py
    ;;
  stop)
    echo "🛑 停止 API 服务..."
    pkill -f "uvicorn server.api" 2>/dev/null && echo "已停止" || echo "未运行"
    ;;
  demo)
    echo "🔬 全链路演示..."
    echo ""
    echo "--- 1. Health Check ---"
    curl -s "http://${API_HOST}:${API_PORT}/api/v1/health" | python3 -m json.tool
    echo ""
    echo "--- 2. 搜索 ---"
    curl -s -X POST "http://${API_HOST}:${API_PORT}/api/v1/search" \
      -H "Content-Type: application/json" \
      -d '{"query":"登录失败怎么办","n_results":3}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'共 {d[\"total\"]} 条结果:'); [print(f'  [{r[\"score\"]:.2f}] {r[\"title\"]} ({r[\"module\"]})') for r in d['results']]"
    echo ""
    echo "--- 3. Stats ---"
    curl -s "http://${API_HOST}:${API_PORT}/api/v1/stats" | python3 -m json.tool
    ;;
  *)
    echo "测试用例知识库 - 管理脚本"
    echo ""
    echo "用法: ./run.sh <command>"
    echo ""
    echo "服务:"
    echo "  api        启动 REST API (前台)"
    echo "  api:bg     后台启动 REST API"
    echo "  mcp        启动 MCP Server (stdio)"
    echo "  stop       停止 API"
    echo ""
    echo "数据:"
    echo "  seed       填充示例数据"
    echo ""
    echo "测试:"
    echo "  api:test   测试 API"
    echo "  mcp:test   测试 MCP"
    echo "  demo       全链路演示"
    echo ""
    echo "配置:"
    echo "  环境变量: TC_API_HOST, TC_API_PORT, TC_EMBED_MODEL, TC_CHROMA_DIR"
    echo "  配置文件: config.yaml (参考 config.example.yaml)"
    ;;
esac
