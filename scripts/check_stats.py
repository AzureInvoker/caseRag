"""检查当前数据库统计"""
import sys
sys.path.insert(0, '/home/admin/testcase-rag/server')
import importlib

engine_mod = importlib.import_module('engine')
engine = engine_mod.get_engine()

all_docs = engine.collection.get()
print(f"总用例数: {len(all_docs['ids'])}")

if all_docs['ids']:
    types = engine.get_project_types()
    print(f"项目类型: {types}")
    for i in range(min(5, len(all_docs['ids']))):
        meta = all_docs['metadatas'][i]
        print(f"  [{i}] id={all_docs['ids'][i]}, title={meta.get('title','')[:50]}, module={meta.get('module','')}, project={meta.get('project','')}")
else:
    print("数据库为空")
