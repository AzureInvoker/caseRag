#!/usr/bin/env python3
"""
ChromaDB → LightRAG 数据迁移脚本

读取 ChromaDB 中已有的用例数据，批量插入 LightRAG 建图。

用法:
  cd /home/admin/testcase-rag
  uv run python3 scripts/migrate_to_lightrag.py

配置:
  从 config.yaml 读取 lightrag 相关配置（provider, api_key, model 等）
  环境变量 TC_LIGHTRAG_ENABLED=1 必须设置或 config 中启用

注意:
  如果 lightrag 已建过图，重复运行会跳过已存在的数据（基于 doc_id 去重）。
  如需完全重建，先删除 .lightrag_storage 目录再运行。
"""

import sys
import os

# 把项目根加进 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from config import get_config
from engine import get_engine


def main():
    cfg = get_config()

    # 确保 LightRAG 启用
    if not cfg.lightrag_enabled:
        print("❌ LightRAG 未启用（config.lightrag.enabled = false）")
        print("   请先在 config.yaml 中设置 lightrag.enabled: true")
        print("   或设置环境变量 TC_LIGHTRAG_ENABLED=1")
        sys.exit(1)

    print(f"🔧 LightRAG 配置:")
    print(f"   提供商: {cfg.llm_provider}")
    print(f"   模型: {cfg.llm_model}")
    print(f"   工作目录: {cfg.lightrag_working_dir}")
    if cfg.llm_provider == "deepseek":
        key_preview = cfg.deepseek_api_key[:8] + "..." if len(cfg.deepseek_api_key) > 8 else "(未设置)"
        print(f"   API Key: {key_preview}")
        if not cfg.deepseek_api_key or cfg.deepseek_api_key.startswith("${"):
            print("⚠️  警告: API Key 可能未正确配置")

    print()
    print("📦 从 ChromaDB 读取数据...")

    engine = get_engine()
    all_texts = engine.get_all_texts()

    if not all_texts:
        print("❌ ChromaDB 中无数据，请先导入测试用例")
        sys.exit(1)

    print(f"   共读取 {len(all_texts)} 条用例")

    # 初始化 LightRAG
    print()
    print("🔄 初始化 LightRAG...")

    from lightrag_engine import LightRAGEngine
    lr_engine = LightRAGEngine(cfg)

    if not lr_engine.is_available():
        print(f"❌ LightRAG 初始化失败: {lr_engine.error}")
        sys.exit(1)

    print("   LightRAG 就绪")

    # 逐条插入
    print()
    print("📝 开始建图...")
    print("   正在调用 LLM 提取实体和关系，这可能需要几分钟...")
    print("   (每条用例需要一次 LLM 调用)")

    texts = []
    doc_ids = []
    for item in all_texts:
        # 拼接嵌入文本（复用 get_embedding_text 的逻辑）
        text = item["text"] or item["title"]
        texts.append(text)
        doc_ids.append(item["id"])

    batch_size = 20
    total = len(texts)
    ok_count = 0

    for i in range(0, total, batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_ids = doc_ids[i:i + batch_size]
        result = lr_engine.insert(batch_texts, ids=batch_ids)
        if result.get("ok"):
            ok_count += len(batch_texts)
            print(f"   ✅ [{i + 1}-{min(i + batch_size, total)}/{total}] 成功")
        else:
            print(f"   ❌ [{i + 1}-{min(i + batch_size, total)}/{total}] 失败: {result.get('message')}")

    print()
    if ok_count == total:
        print(f"✅ 迁移完成！{ok_count}/{total} 条用例已成功建图")
    else:
        print(f"⚠️ 迁移完成，{ok_count}/{total} 条成功，{total - ok_count} 条失败")

    # 打印状态
    status = lr_engine.get_status()
    if status.get("ready"):
        print(f"   图谱实体数: {status.get('node_count', 'N/A')}")
    print()
    print("💡 现在可以用 tc_graph_search 和 tc_agentic_search 检索了")


if __name__ == "__main__":
    main()
