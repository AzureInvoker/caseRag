#!/usr/bin/env python3
"""
从标题前缀回填已有 chromadb 记录的 sub_module 字段。

规则：
- 标题含全角冒号「：」时，取冒号前内容作为 sub_module
- 冒号前内容不超过 8 个字才提取（避免把整句当子模块）
- 已有 sub_module 的不覆盖
"""
import sys
import re
sys.path.insert(0, '.')
sys.path.insert(0, 'server')

from engine import get_engine

engine = get_engine()

# 获取全部记录
data = engine.collection.get()
if not data["ids"]:
    print("数据库为空")
    sys.exit(0)

updated = 0
skipped_submodule_exists = 0
skipped_no_colon = 0

for i, (id_, meta) in enumerate(zip(data["ids"], data["metadatas"])):
    existing_sub = meta.get("sub_module", "") or ""
    if existing_sub:
        skipped_submodule_exists += 1
        continue

    title = meta.get("title", "")
    # full-width colon: 中文冒号
    m = re.match(r'^(.{1,8})[:：]\s*(.*)', title)
    if m:
        sub = m.group(1).strip()
        if sub:
            engine.collection.update(
                ids=[id_],
                metadatas=[{"sub_module": sub}]
            )
            updated += 1
            if updated <= 5:
                print(f"  {sub} ← {title[:60]}")
    else:
        skipped_no_colon += 1

print(f"\n✅ 更新: {updated} 条")
print(f"  跳过（已有 sub_module）: {skipped_submodule_exists} 条")
print(f"  跳过（无冒号前缀）: {skipped_no_colon} 条")
