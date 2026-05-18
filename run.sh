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
  update)
    echo "🔄 拉取最新代码..."
    OLD_HASH=$(git rev-parse HEAD)
    if ! git pull; then
      echo "❌ git pull 失败，请检查本地是否有未提交的修改"
      exit 1
    fi
    NEW_HASH=$(git rev-parse HEAD)
    if [ "$OLD_HASH" != "$NEW_HASH" ] && git diff "$OLD_HASH".."$NEW_HASH" -- requirements.txt | grep -q .; then
      echo "📦 检测到依赖变更，更新中..."
      uv pip install -r requirements.txt && echo "✅ 依赖更新完成" || echo "⚠️ 依赖更新失败"
    else
      echo "✅ 已是最新，无需更新依赖"
    fi
    ;;

  *)
    echo "用法: ./run.sh start|stop|update"
    ;;
esac
