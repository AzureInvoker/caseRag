"""
迁移脚本：读取旧 ChromaDB（all-MiniLM-L6-v2），导出全部用例，
删除旧库，用新模型（bge-small-zh-v1.5）重建索引。
"""

import sys
import os
import json
import re
import shutil
from pathlib import Path

# 将项目根目录加入 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "server"))

os.chdir(str(PROJECT_ROOT))

print("=" * 60)
print("🔍 步骤 1/5: 读取旧 ChromaDB 数据...")
print("=" * 60)

from engine import TestCase, get_engine, VectorEngine, CHROMA_DIR

engine = get_engine()
all_docs = engine.collection.get()

print(f"   共 {len(all_docs['ids'])} 条用例")

if not all_docs["ids"]:
    print("   数据库为空，跳过迁移。")
    sys.exit(0)

# 解析 document 中的字段
def parse_document(doc_text: str, meta: dict) -> TestCase:
    """从 get_embedding_text() 的输出中反向解析字段"""
    tc = TestCase()
    tc.id = meta.get("id", "")
    tc.title = meta.get("title", "")
    tc.module = meta.get("module", "")
    tc.priority = meta.get("priority", "P3")
    tc.category = meta.get("category", "")
    tc.project = meta.get("project", "")
    tc.creator = meta.get("creator", "MCP")
    tc.created_at = meta.get("created_at", "")
    tc.tags = meta.get("tags", "").split(",") if meta.get("tags") else []

    # 从 document 中解析预置条件、步骤、预期结果
    if doc_text:
        # 找 前置条件: ... 步骤: ... 预期: ... 三个块
        lines = doc_text.split("\n")
        current_field = None
        buffer = []
        preconditions_parts = []
        steps_parts = []
        expected_parts = []

        for line in lines:
            if line.startswith("前置条件: "):
                preconditions_parts.append(line[len("前置条件: "):])
                current_field = "preconditions"
            elif line.startswith("步骤: "):
                steps_parts.append(line[len("步骤: "):])
                current_field = "steps"
            elif line.startswith("预期: "):
                expected_parts.append(line[len("预期: "):])
                current_field = "expected"
            elif line.startswith("标题: ") or line.startswith("模块: ") or \
                 line.startswith("优先级: ") or line.startswith("类别: ") or \
                 line.startswith("标签: ") or line.startswith("项目: "):
                current_field = None
            else:
                # 多行续接
                if current_field == "preconditions" and line.strip():
                    preconditions_parts.append(line)
                elif current_field == "steps" and line.strip():
                    steps_parts.append(line)
                elif current_field == "expected" and line.strip():
                    expected_parts.append(line)

        tc.preconditions = " ".join(p for p in preconditions_parts if p).strip()
        # 步骤可能用 ; 分隔
        steps_raw = "".join(steps_parts).strip()
        if steps_raw:
            tc.steps = [s.strip() for s in re.split(r"[;；]", steps_raw) if s.strip()]
        tc.expected = " ".join(p for p in expected_parts if p).strip()

    return tc


print("=" * 60)
print("📦 步骤 2/5: 解析并保存全部用例到备份文件...")
print("=" * 60)

cases = []
for i, id_ in enumerate(all_docs["ids"]):
    meta = all_docs["metadatas"][i]
    doc = all_docs["documents"][i] if all_docs["documents"] else ""
    tc = parse_document(doc, meta)
    cases.append(tc.to_dict())
    if (i + 1) % 50 == 0:
        print(f"   已解析 {i + 1}/{len(all_docs['ids'])} 条...")

# 保存备份
backup_path = PROJECT_ROOT / ".chroma_db_backup"
backup_path.mkdir(parents=True, exist_ok=True)
backup_file = backup_path / "testcases_backup.json"
with open(backup_file, "w", encoding="utf-8") as f:
    json.dump(cases, f, ensure_ascii=False, indent=2)

print(f"   ✅ 备份已保存到 {backup_file} ({len(cases)} 条)")


print("=" * 60)
print("🗑️  步骤 3/5: 删除旧 ChromaDB...")
print("=" * 60)

if str(CHROMA_DIR).startswith(str(PROJECT_ROOT)):
    shutil.rmtree(str(CHROMA_DIR), ignore_errors=True)
    print(f"   ✅ 已删除 {CHROMA_DIR}")
else:
    print(f"   ⚠️  ChromaDB 不在项目目录内，跳过自动删除")
    print(f"     路径: {CHROMA_DIR}")
    print(f"     请手动删除后重新运行")
    sys.exit(1)


print("=" * 60)
print("🔄 步骤 4/5: 用新模型重建索引...")
print("=" * 60)

# 重置 engine 实例（会重新创建 chroma client 和 embedder）
import importlib
import engine as engine_mod
importlib.reload(engine_mod)

from engine import TestCase as TC_new, get_engine as get_engine_new

engine_new = get_engine_new()
print(f"   嵌入模型: {engine_mod.EMBED_MODEL}")

# 重建 TestCase 对象并批量导入
test_cases = []
for c_dict in cases:
    tc = TC_new(
        id=c_dict.get("id", ""),
        title=c_dict.get("title", ""),
        module=c_dict.get("module", ""),
        priority=c_dict.get("priority", "P3"),
        category=c_dict.get("category", ""),
        preconditions=c_dict.get("preconditions", ""),
        steps=c_dict.get("steps", []),
        expected=c_dict.get("expected", ""),
        tags=c_dict.get("tags", []),
        project=c_dict.get("project", ""),
        creator=c_dict.get("creator", "MCP"),
        created_at=c_dict.get("created_at", ""),
    )
    test_cases.append(tc)

count = engine_new.add_many(test_cases)
print(f"   ✅ 成功重新导入 {count} 条用例")


print("=" * 60)
print("🧪 步骤 5/5: 验证搜索结果...")
print("=" * 60)

# 试搜一条
test_queries = [
    "登录失败",
    "支付超时",
    "搜索",
]
for q in test_queries:
    results = engine_new.search(q, n_results=3)
    print(f"\n   🔍 搜索「{q}」:")
    if results:
        for r in results:
            print(f"      [{r['score']:.3f}] {r['title']} ({r['module']})")
    else:
        print(f"      (无结果)")


print("\n" + "=" * 60)
print("✅ 迁移完成！")
print("=" * 60)
print(f"\n备份文件: {backup_file}")
print(f"可随时用以下命令恢复:\n  python3 scripts/restore_backup.py")
