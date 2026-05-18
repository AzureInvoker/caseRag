#!/usr/bin/env python3
"""
导出测试用例知识库全部数据为 JSON
用法: uv run python3 scripts/export_cases.py
输出: /tmp/testcase-export.json
"""

import os
import sys
import json

# ── 确保能找到 server 模块 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from server.engine import get_engine
except ImportError:
    print("❌ 请在 testcase-rag 项目根目录下运行")
    sys.exit(1)

engine = get_engine()

# 直接拿底层数据（不走分页限制）
collection = engine.collection
all_data = collection.get()

if not all_data["ids"]:
    print("📭 库里没有数据")
    sys.exit(0)

cases = []
for i, id_ in enumerate(all_data["ids"]):
    meta = all_data["metadatas"][i]
    # 从 metadata 重建完整字段
    case = {
        "id": id_,
        "title": meta.get("title", ""),
        "module": meta.get("module", ""),
        "priority": meta.get("priority", "P3"),
        "category": meta.get("category", "功能测试"),
        "project": meta.get("project", ""),
        "creator": meta.get("creator", ""),
        "created_at": meta.get("created_at", ""),
        "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
    }
    # 从 document 里解析 steps/preconditions/expected（如果存了的话）
    doc = all_data["documents"][i] if all_data["documents"] else ""
    # 不反解析了，直接用 metadata 里的 + 原文做参考
    case["_doc_preview"] = doc[:300] if doc else ""
    cases.append(case)

output_path = "/tmp/testcase-export.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump({"total": len(cases), "cases": cases}, f, ensure_ascii=False, indent=2)

print(f"✅ 导出完成: {len(cases)} 条用例")
print(f"   文件: {output_path}")
print(f"   大小: {os.path.getsize(output_path) / 1024:.1f} KB")
