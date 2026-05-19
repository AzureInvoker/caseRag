"""查询当前数据库所有用例的分模块统计"""
import sys
sys.path.insert(0, '/home/admin/testcase-rag/server')
import importlib
from collections import Counter

engine_mod = importlib.import_module('engine')
engine = engine_mod.get_engine()

all_docs = engine.collection.get()
print(f"总用例数: {len(all_docs['ids'])}")

# 模块分布
modules = Counter()
projects = Counter()
for meta in all_docs['metadatas']:
    modules[meta.get('module','')] += 1
    projects[meta.get('project','')] += 1

print("\n## 项目类型分布")
for p, c in projects.most_common():
    print(f"  {p}: {c}")

print("\n## 模块分布（TOP 20）")
for m, c in modules.most_common(20):
    print(f"  {m}: {c}")
