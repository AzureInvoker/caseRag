#!/bin/bash
cd "$(dirname "$0")"

case "${1:-help}" in
  start)
    echo "🚀 启动 API..."
    nohup uv run uvicorn server.api:app --host 0.0.0.0 --port 8765 > /tmp/testcase-rag.log 2>&1 &
    echo "PID: $!"
    ;;
  stop)
    echo "🛑 停止 API..."
    pkill -f "uvicorn.*server.api" 2>/dev/null && echo "已停止" || echo "未运行"
    ;;
  *)
    echo "用法: ./run.sh start|stop"
    ;;
esac
