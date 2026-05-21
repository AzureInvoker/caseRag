#!/bin/bash
cd "$(dirname "$0")"

case "${1:-help}" in
  start)
    echo "🚀 启动 API..."
    nohup uv run uvicorn server.api:app --host 0.0.0.0 --port 8765 > /tmp/testcase-rag.log 2>&1 &
    PID=$!
    echo "$PID" > /tmp/testcase-rag.pid
    echo "PID: $PID"
    ;;
  stop)
    echo "🛑 停止 API..."
    if [ -f /tmp/testcase-rag.pid ]; then
      PID=$(cat /tmp/testcase-rag.pid)
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" && echo "已停止 PID: $PID" || echo "停止失败"
      else
        echo "PID $PID 不存在，可能已手动停止"
      fi
      rm -f /tmp/testcase-rag.pid
    else
      echo "未找到 PID 文件（/tmp/testcase-rag.pid）"
    fi
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

  modelswitch)
    if [ -z "$2" ]; then
      echo "❌ 请指定目标模型名"
      echo "   用法: ./run.sh modelswitch <model_name>"
      echo "   示例: ./run.sh modelswitch paraphrase-multilingual-MiniLM-L12-v2"
      exit 1
    fi
    echo "🔄 切换嵌入模型为: $2"
    uv run python3 scripts/model_switch.py "$2"
    ;;

  *)
    echo "用法: ./run.sh start|stop|update|modelswitch <model_name>"
    ;;
esac
