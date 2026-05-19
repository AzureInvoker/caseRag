"""从 testcase_data.json 导入测试用例到 ChromaDB"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
import importlib
engine_mod = importlib.import_module('engine')
VectorEngine = engine_mod.VectorEngine
TestCase = engine_mod.TestCase

# 读取数据
data_path = Path(__file__).parent / "testcase_data.json"
with open(data_path, 'r', encoding='utf-8') as f:
    raw_cases = json.load(f)

print(f"📖 读取到 {len(raw_cases)} 条用例")

# 清洗函数
import re

def clean_text(s):
    if not isinstance(s, str):
        return ""
    s = s.replace("\\n", " ").replace("\\r", " ")
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def clean_list(items):
    if not isinstance(items, list):
        return []
    return [clean_text(i) for i in items if isinstance(i, str) and clean_text(i)]

# 创建 engine
engine = VectorEngine()
# 确保 chroma_dir 存在
engine_mod.CHROMA_DIR = engine_mod.Path(engine_mod.DATA_DIR / ".chroma_db")
engine_mod.CHROMA_DIR.mkdir(parents=True, exist_ok=True)

test_cases = []
for i, c in enumerate(raw_cases):
    tc = TestCase(
        title=clean_text(c.get("title", "")),
        module=clean_text(c.get("module", "")),
        sub_module=clean_text(c.get("sub_module", "")),
        priority=clean_text(c.get("priority", "P3")),
        category=clean_text(c.get("category", "功能测试")),
        preconditions=clean_text(c.get("preconditions", "")),
        steps=clean_list(c.get("steps", [])),
        expected=clean_text(c.get("expected", "")),
        tags=clean_list(c.get("tags", [])),
        project=clean_text(c.get("project", "")),
        creator=clean_text(c.get("creator", "admin")),
        created_at=__import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    tc.id = tc.gen_id()
    test_cases.append(tc)

print(f"🧹 清洗完成，共 {len(test_cases)} 条待导入")
print(f"\n📋 项目类型: {sorted(set(tc.project for tc in test_cases))}")
print(f"📋 模块列表: {sorted(set(tc.module for tc in test_cases))}")

# 批量导入
print(f"\n🔄 开始导入（共 {len(test_cases)} 条）...")
engine = engine_mod.get_engine()
count = engine.add_many(test_cases)
print(f"✅ 成功导入 {count} 条用例！")

# 验证
stats = engine.stats()
print(f"\n📊 数据库统计:")
print(f"   总用例数: {stats['total_cases']}")
print(f"   模块数: {stats['modules']}")
print(f"   项目类型数: {stats['project_types']}")
print(f"   用例数最多的 TOP5 模块:")
for m in stats['top_modules'][:5]:
    print(f"     - {m['module']}: {m['count']}")

# 搜索验证
print(f"\n🔍 搜索验证:")
test_queries = [
    "密码输错了多次怎么办",
    "购物车金额不对",
    "退款流程",
    "API接口安全",
    "搜索不到商品",
]
for q in test_queries:
    results = engine.search(q, n_results=3)
    if results:
        titles = [r['title'][:30] for r in results]
        print(f"   '{q}' → {titles}")
    else:
        print(f"   '{q}' → 无结果")
