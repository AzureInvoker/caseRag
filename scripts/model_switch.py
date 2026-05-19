"""模型切换脚本：备份旧库 → 导出全部用例 → 切换模型 → 重建索引

用法:
   sh run.sh modelswitch intfloat/multilingual-e5-small
   sh run.sh modelswitch paraphrase-multilingual-MiniLM-L12-v2

流程:
  1. 备份当前 chroma_db 目录到 .chroma_db_backup/
  2. 从旧库中导出全部用例（含 steps/preconditions/expected）为 JSON
  3. 更新 config.yaml 中的 embed_model
  4. 删除旧 .chroma_db/
  5. 重新初始化引擎，用新模型重新嵌入所有用例
  6. 搜索验证
"""

import sys
import os
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime

# 读取目标模型名
if len(sys.argv) < 2:
    print("❌ 请指定目标模型名")
    print("   用法: python3 scripts/model_switch.py <model_name>")
    print("   示例: python3 scripts/model_switch.py paraphrase-multilingual-MiniLM-L12-v2")
    sys.exit(1)

TARGET_MODEL = sys.argv[1].strip()

# ── 模型校验 ──
print("=" * 60)
print(f"🔍 校验模型: {TARGET_MODEL}")
print("=" * 60)

VALIDATED = False
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# 候选查询名（自动补全 sentence-transformers/ 前缀）
check_names = [TARGET_MODEL]
if "/" not in TARGET_MODEL:
    check_names.insert(0, f"sentence-transformers/{TARGET_MODEL}")

for name in check_names:
    try:
        url = f"https://huggingface.co/api/models/{name}"
        headers = {"User-Agent": "Mozilla/5.0"}
        if HF_TOKEN:
            headers["Authorization"] = f"Bearer {HF_TOKEN}"
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        lib = data.get("library_name", "")
        tags = data.get("cardData", {}).get("tags", [])
        is_st = lib == "sentence-transformers" or "sentence-transformers" in tags
        dl = data.get("downloads", 0)

        print(f"   ✅ 模型存在: {data.get('modelId')}")
        print(f"   下载量: {dl:,}")
        if is_st:
            print(f"   ✅ sentence-transformers 原生兼容")
        else:
            print(f"   ⚠️  library={lib}，非原生 sentence-transformers 模型")
            print(f"      但仍可尝试加载，若失败请换用原生 ST 模型")

        if name != TARGET_MODEL:
            print(f"   ℹ️  自动补全为: {name}")
            TARGET_MODEL = name

        VALIDATED = True
        break
    except urllib.error.HTTPError as e:
        if e.code == 404:
            continue  # 继续试下一个候选名
        elif e.code in (401, 403):
            # HF 新版 API 需要登录，无法验证
            print(f"   ⚠️  HF API 返回 {e.code}（未登录或需 Token）")
            print(f"      跳过在线校验，模型名直接传递")
            # 尝试自动补全
            if "/" not in TARGET_MODEL:
                guessed = f"sentence-transformers/{TARGET_MODEL}"
                print(f"   ℹ️  已自动补全为: {guessed}")
                TARGET_MODEL = guessed
            VALIDATED = True
            break
        else:
            print(f"   ⚠️  查询失败 (HTTP {e.code})，跳过在线校验")
            VALIDATED = True
            break
    except Exception as e:
        print(f"   ⚠️  查询异常: {e}，跳过在线校验")
        VALIDATED = True
        break

if not VALIDATED:
    print(f"   ❌ 模型 '{TARGET_MODEL}' 在 HuggingFace 上未找到")
    print()
    print("   💡 常见中文/多语言 embedding 模型:")
    print()
    print(f"     模型名                                                             维数   大小   说明")
    print(f"   ─────────────────────────────────────────────────────────────────────────────────────")
    print(f"   sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2         384    180MB  多语言，主人其他服务器在用")
    print(f"   intfloat/multilingual-e5-small                                      384    118MB  多语言，轻量⭐ 当前最佳选择")
    print(f"   BAAI/bge-small-zh-v1.5                                              512    33MB   中文原生，极轻量")
    print(f"   BAAI/bge-base-zh-v1.5                                               768    ~400MB 中文原生，中等")
    print(f"   shibing624/text2vec-base-chinese                                    768    ~500MB 中文原生")
    print(f"   jinaai/jina-embeddings-v2-base-zh                                   768    ~600MB 中英双语")
    print()
    print("   用法示例:")
    print(f"     sh run.sh modelswitch intfloat/multilingual-e5-small")
    print(f"     sh run.sh modelswitch paraphrase-multilingual-MiniLM-L12-v2")
    sys.exit(1)

print()

PROJECT_ROOT = Path(__file__).parent.parent
BACKUP_DIR = PROJECT_ROOT / ".chroma_db_backup"

os.chdir(str(PROJECT_ROOT))

print("=" * 60)
print(f"🔄 模型切换: all-MiniLM-L6-v2 → {TARGET_MODEL}")
print("=" * 60)

# ── 0. 停 API ──
print("\n🛑 步骤 0: 停 API...")
subprocess.run(["bash", "run.sh", "stop"], capture_output=True)
print("   ✅ 已停止")

# ── 1. 读取当前 DB ──
print("\n🔍 步骤 1/6: 读取当前 ChromaDB...")
sys.path.insert(0, str(PROJECT_ROOT / "server"))
try:
    from engine import TestCase, get_engine, VectorEngine, CHROMA_DIR, get_config
except ImportError:
    # 兼容导入路径
    sys.path.insert(0, str(PROJECT_ROOT))
    import importlib
    engine_mod = importlib.import_module("engine")
    TestCase = engine_mod.TestCase
    VectorEngine = engine_mod.VectorEngine
    CHROMA_DIR = engine_mod.CHROMA_DIR
    get_engine = engine_mod.get_engine

engine = get_engine()
all_docs = engine.collection.get()
total = len(all_docs["ids"])
print(f"   📊 当前库: {total} 条用例")

if total == 0:
    print("   ⚠️  数据库为空，跳过导出")
    CASES = []
else:
    # ── 2. 从 document 中解析完整字段 ──
    print("\n📦 步骤 2/6: 解析全部用例（恢复 steps/preconditions/expected）...")

    def parse_case_from_doc(doc_text: str, meta: dict) -> dict:
        """从 embedding_text + metadata 反向解析完整用例"""
        case = {
            "title": meta.get("title", ""),
            "module": meta.get("module", ""),
            "sub_module": meta.get("sub_module", ""),
            "priority": meta.get("priority", "P3"),
            "category": meta.get("category", "功能测试"),
            "project": meta.get("project", ""),
            "creator": meta.get("creator", "admin"),
            "created_at": meta.get("created_at", ""),
            "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
            "steps": [],
            "preconditions": "",
            "expected": "",
        }

        if not doc_text:
            return case

        lines = doc_text.split("\n")
        current_field = None
        pre_parts = []
        steps_parts = []
        expt_parts = []

        for line in lines:
            if line.startswith("前置条件: "):
                pre_parts.append(line[len("前置条件: "):])
                current_field = "pre"
            elif line.startswith("步骤: "):
                steps_parts.append(line[len("步骤: "):])
                current_field = "steps"
            elif line.startswith("预期: "):
                expt_parts.append(line[len("预期: "):])
                current_field = "expt"
            elif line.startswith("标题: ") or line.startswith("模块: ") or \
                 line.startswith("优先级: ") or line.startswith("类别: ") or \
                 line.startswith("标签: ") or line.startswith("项目: ") or \
                 line.startswith("子模块: ") or line.startswith("子模块:"):
                current_field = None
            else:
                if current_field == "pre" and line.strip():
                    pre_parts.append(line)
                elif current_field == "steps" and line.strip():
                    steps_parts.append(line)
                elif current_field == "expt" and line.strip():
                    expt_parts.append(line)

        case["preconditions"] = " ".join(p for p in pre_parts if p).strip()
        steps_raw = "".join(steps_parts).strip()
        if steps_raw:
            case["steps"] = [s.strip() for s in re.split(r"[;；]", steps_raw) if s.strip()]
        case["expected"] = " ".join(p for p in expt_parts if p).strip()

        return case

    CASES = []
    for i, id_ in enumerate(all_docs["ids"]):
        meta = all_docs["metadatas"][i]
        doc = all_docs["documents"][i] if all_docs["documents"] else ""
        case = parse_case_from_doc(doc, meta)
        CASES.append(case)
        if (i + 1) % 100 == 0:
            print(f"   已解析 {i + 1}/{total}...")

    print(f"   ✅ 全部 {len(CASES)} 条用例解析完成")

    # ── 3. 备份 chroma_db 目录 + JSON ──
    print("\n💾 步骤 3/6: 备份数据...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_subdir = BACKUP_DIR / f"model_backup_{timestamp}"
    backup_subdir.mkdir(parents=True, exist_ok=True)

    # 3a. 备份 chroma_db 目录
    chroma_path = str(CHROMA_DIR)
    if Path(chroma_path).exists():
        zip_path = backup_subdir / "chroma_db.zip"
        shutil.make_archive(str(backup_subdir / "chroma_db"), "zip", Path(chroma_path).parent, Path(chroma_path).name)
        print(f"   ✅ chroma_db 目录已打包备份: {zip_path}")

    # 3b. 导出 JSON
    json_path = backup_subdir / "testcases_backup.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(CASES, f, ensure_ascii=False, indent=2)
    print(f"   ✅ 用例数据已导出: {json_path} ({len(CASES)} 条)")

# ── 4. 更新 config.yaml ──
print(f"\n⚙️  步骤 4/6: 更新 config.yaml → embed_model: {TARGET_MODEL}")
config_path = PROJECT_ROOT / "config.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    config_text = f.read()

config_text = re.sub(
    r'embed_model:\s*".*?"',
    f'embed_model: "{TARGET_MODEL}"',
    config_text
)

with open(config_path, "w", encoding="utf-8") as f:
    f.write(config_text)

# 验证
new_config = open(config_path).read()
model_line = [l for l in new_config.split("\n") if "embed_model" in l]
print(f"   ✅ config.yaml 已更新: {model_line[0].strip() if model_line else '❌ 未找到'}")

# ── 5. 删除旧 chroma_db ──
print(f"\n🗑️  步骤 5/6: 删除旧 chroma_db...")
if str(CHROMA_DIR).startswith(str(PROJECT_ROOT)):
    shutil.rmtree(str(CHROMA_DIR), ignore_errors=True)
    print(f"   ✅ 已删除 {CHROMA_DIR}")
else:
    print(f"   ⚠️  chroma_db 不在项目目录内，请手动删除: {CHROMA_DIR}")
    print(f"   跳过自动删除")

if total == 0:
    print("\n⚠️  旧库为空，迁移完成（新库也会是空的）")
    sys.exit(0)

# ── 6. 重新加载引擎 + 重建索引 ──
print(f"\n🔄 步骤 6/6: 用新模型「{TARGET_MODEL}」重建索引...")

# 重置模块缓存让引擎重新加载
for mod_name in list(sys.modules.keys()):
    if "engine" in mod_name or "config" in mod_name:
        del sys.modules[mod_name]

sys.path.insert(0, str(PROJECT_ROOT / "server"))
import importlib
try:
    from engine import TestCase as TC_new, get_engine as get_engine_new, CHROMA_DIR as NEW_CHROMA_DIR
except ImportError:
    sys.path.insert(0, str(PROJECT_ROOT))
    engine_mod_new = importlib.import_module("engine")
    TC_new = engine_mod_new.TestCase
    get_engine_new = engine_mod_new.get_engine
    NEW_CHROMA_DIR = engine_mod_new.CHROMA_DIR

print(f"   📍 新模型: {TARGET_MODEL}")
print(f"   📍 新 chroma_db: {NEW_CHROMA_DIR}")

# 重建 TestCase 对象
test_cases = []
for c in CASES:
    tc = TC_new(
        title=c.get("title", ""),
        module=c.get("module", ""),
        sub_module=c.get("sub_module", ""),
        priority=c.get("priority", "P3"),
        category=c.get("category", "功能测试"),
        preconditions=c.get("preconditions", ""),
        steps=c.get("steps", []),
        expected=c.get("expected", ""),
        tags=c.get("tags", []),
        project=c.get("project", ""),
        creator=c.get("creator", "admin"),
        created_at=c.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    test_cases.append(tc)

# 批量导入
engine_new = get_engine_new()
count = engine_new.add_many(test_cases)
print(f"   ✅ 成功重新导入 {count} 条用例")

# ── 验证 ──
print(f"\n🧪 验证搜索结果:")
test_queries = ["登录失败", "支付超时", "密码锁定", "退款"]
for q in test_queries:
    try:
        results = engine_new.search(q, n_results=3)
        if results:
            titles = [f"[{r['score']:.3f}] {r['title'][:30]}" for r in results]
            print(f"   🔍 「{q}」→ {', '.join(titles)}")
        else:
            print(f"   🔍 「{q}」→ (无结果)")
    except Exception as e:
        print(f"   🔍 「{q}」→ 出错: {e}")

print("\n" + "=" * 60)
print("✅ 模型切换完成！")
print("=" * 60)
print(f"\n   新模型: {TARGET_MODEL}")
print(f"   导入数: {count} 条")
print(f"   备份位置: {backup_subdir}")
print(f"   备份文件: chroma_db.zip + testcases_backup.json")
print(f"\n   💡 启动 API: sh run.sh start")
