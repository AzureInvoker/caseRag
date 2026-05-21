"""
测试用例知识库 — MCP + REST API

启动:
  cd /home/admin/testcase-rag
  uvicorn server.api:app --host $TC_API_HOST --port $TC_API_PORT

配置优先级: 环境变量 > config.yaml > 默认值
  TC_API_HOST=0.0.0.0
  TC_API_PORT=8765

MCP 写入工具使用说明:
  tc_add / tc_add_batch — 添加测试用例
  所有字符串字段会自动清洗（去换行、去首尾空白、过滤空值）
  project 字段为可选项，若留空则默认取 module 值
  steps 和 tags 中空字符串会被自动过滤
"""

import json
import asyncio
import logging
import re
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field

from .engine import TestCase, get_engine
from .config import get_config
from .lightrag_engine import LightRAGEngine
from .search import SearchRouter

logger = logging.getLogger("api")

# ── 初始化（模块加载时同步初始化，启动时一次完成） ──

engine = get_engine()
cfg = get_config()
lightrag_engine = LightRAGEngine(cfg)
search_router = SearchRouter(engine, lightrag_engine)

# ── FastAPI 应用 ──

app = FastAPI(
    title="测试用例知识库 API",
    description="Test Case RAG — 结构化存储 + 语义检索 + 知识图谱 + Agentic MCP",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 异步工具处理器（图谱搜索等需要 await 的操作） ──


async def _async_graph_search(args: dict) -> dict:
    """异步知识图谱搜索"""
    if not lightrag_engine.is_available():
        return {"content": [{"type": "text", "text": "❌ LightRAG 图谱未启用或初始化失败。可调 tc_graph_status 查看详情"}]}
    query = args.get("query", "").strip()
    if not query:
        return {"content": [{"type": "text", "text": "请提供搜索关键词"}]}
    result = await lightrag_engine.async_search(query, n_results=min(int(args.get("n_results", 5)), 20))
    if not result.get("ok"):
        return {"content": [{"type": "text", "text": f"❌ 图谱检索失败: {result.get('message', '')}"}]}
    entities, relationships, chunks = result.get("entities", []), result.get("relationships", []), result.get("chunks", [])
    text = f"## 🕸️ 知识图谱检索「{query}」\n\n共找到 {len(entities)} 个实体, {len(relationships)} 条关系, {len(chunks)} 个片段\n\n"
    if entities:
        text += "### 📍 实体\n\n"
        for e in entities:
            text += f"- **{e['name']}**（{e.get('type', '-')}）\n  {e.get('description', '')[:150]}\n"
    if relationships:
        text += "\n### 🔗 关系\n\n"
        for r in relationships[:10]:
            text += f"- {r['source']} → {r['target']}: {r.get('description', '')[:100]}\n"
    if chunks:
        text += "\n### 📄 相关片段\n\n"
        for c in chunks[:5]:
            text += f"- {c.get('content', '')[:200]}...\n"
    return {"content": [{"type": "text", "text": text.strip()}]}


async def _async_agentic_search(args: dict) -> dict:
    """异步自适应检索"""
    query = args.get("query", "").strip()
    if not query:
        return {"content": [{"type": "text", "text": "请提供搜索关键词"}]}
    n_results = min(int(args.get("n_results", 5)), 20)
    result = await search_router.async_search(query=query, n_results=n_results, module=args.get("module"), priority=args.get("priority"), category=args.get("category"), mode="auto")
    text = f"## 🔍 自适应检索「{query}」\n\n模式: {result['mode']}\n\n"
    cr = result.get("results", [])
    if cr:
        text += f"### 📋 向量匹配结果（{len(cr)} 条）\n\n"
        for r in cr:
            text += f"**{r['title']}** [{'█' * int(r['score'] * 20)}{'░' * (20 - int(r['score'] * 20))}] {r['score']:.2f}\n`{r['id']}` | {r['module']} | {r['priority']}\n\n"
    else:
        text += "无可用的向量搜索结果\n\n"
    gh = result.get("graph_hits")
    if gh:
        ents = gh.get("entities", [])
        rels = gh.get("relationships", [])
        if ents:
            text += f"### 🕸️ 图谱增强（{len(ents)} 实体）\n\n"
            for e in ents[:5]:
                text += f"- **{e['name']}**\n"
        if rels:
            text += "\n"
            for r in rels[:5]:
                text += f"- {r['source']} → {r['target']}\n"
    return {"content": [{"type": "text", "text": text.strip()}]}


async def _async_graph_status() -> dict:
    """异步图谱状态"""
    if not cfg.lightrag_enabled:
        return {"content": [{"type": "text", "text": "📋 LightRAG 状态: 未启用"}]}
    status = lightrag_engine.get_status()
    text = "## 📊 LightRAG 状态\n\n| 字段 | 值 |\n|------|-----|\n"
    text += f"| 启用 | {'✅ 是' if status.get('enabled') else '❌ 否'} |\n"
    text += f"| 就绪 | {'✅ 是' if status.get('ready') else '❌ 否'} |\n"
    text += f"| LLM 提供商 | {status.get('provider', '-')} |\n"
    text += f"| LLM 模型 | {status.get('model', '-')} |\n"
    if status.get("node_count") is not None:
        text += f"| 实体数量 | {status['node_count']} |\n"
    if status.get("processing_status"):
        text += f"| 处理状态 | {status['processing_status']} |\n"
    if status.get("message"):
        text += f"| 消息 | {status['message']} |\n"
    return {"content": [{"type": "text", "text": text.strip()}]}


# ── 输入清洗 ──


def _clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\\n", " ").replace("\\r", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _clean_list(items: list) -> list:
    """清洗列表：过滤空、去换行、trim"""
    if not isinstance(items, list):
        return []
    cleaned = []
    for i in items:
        if isinstance(i, str):
            c = _clean_text(i)
            if c:
                cleaned.append(c)
    return cleaned


def _make_tc(args: dict) -> "TestCase":
    """从参数字典构造 TestCase，自动清洗所有字段"""
    title = _clean_text(args.get("title", ""))
    module = _clean_text(args.get("module", ""))
    if not title:
        raise ValueError("标题不能为空")
    if not module:
        raise ValueError("模块名不能为空")

    project = _clean_text(args.get("project", ""))

    return TestCase(
        title=title,
        module=module,
        sub_module=_clean_text(args.get("sub_module", "")),
        project=project,
        priority=_clean_text(args.get("priority", "P3")) or "P3",
        category=_clean_text(args.get("category", "功能测试")) or "功能测试",
        preconditions=_clean_text(args.get("preconditions", "")),
        steps=_clean_list(args.get("steps", [])),
        expected=_clean_text(args.get("expected", "")),
        tags=_clean_list(args.get("tags", [])),
        creator=_clean_text(args.get("creator", "MCP")) or "MCP",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

# ── MCP 会话管理 ──

# 每个 SSE 连接对应一个消息队列
_mcp_sessions: dict[str, asyncio.Queue] = {}
_next_session_id = 0


def _mcp_handle(name: str, args: dict) -> dict:
    """MCP 工具处理函数（复用 stdio 版的逻辑）"""
    if name == "tc_search":
        query = args.get("query", "").strip()
        if not query:
            return {"content": [{"type": "text", "text": "请提供搜索关键词"}]}
        results = engine.search(
            query=query,
            n_results=min(int(args.get("n_results", 5)), 20),
            module=args.get("module"),
            sub_module=args.get("sub_module"),
            priority=args.get("priority"),
            category=args.get("category"),
        )
        if not results:
            return {"content": [{"type": "text", "text": f"未找到与「{query}」相关的测试用例"}]}
        text = f"## 🔍 搜索「{query}」共找到 {len(results)} 条用例\n\n"
        for r in results:
            score_bar = "█" * int(r["score"] * 20) + "░" * (20 - int(r["score"] * 20))
            text += (
                f"### {r['title']}  [{score_bar}] {r['score']:.2f}\n\n"
                f"| 字段 | 值 |\n"
                f"|------|-----|\n"
                f"| ID | `{r['id']}` |\n"
                f"| 模块 | {r['module']} |\n"
                f"| 子模块 | {r.get('sub_module', '') or '-'} |\n"
                f"| 优先级 | {r['priority']} |\n"
                f"| 类别 | {r['category']} |\n"
            )
            if r.get("tags"):
                text += f"| 标签 | {', '.join(r['tags'])} |\n"
            text += f"\n摘要: {r.get('summary', '')}\n\n---\n\n"
        return {"content": [{"type": "text", "text": text.strip()}]}

    elif name == "tc_list":
        items = engine.get_all(
            module=args.get("module"),
            sub_module=args.get("sub_module"),
            priority=args.get("priority"),
            category=args.get("category"),
            offset=int(args.get("offset", 0)),
            limit=min(int(args.get("limit", 50)), 200),
        )
        if not items:
            return {"content": [{"type": "text", "text": "暂无用例（或筛选条件无匹配）"}]}
        text = f"## 📋 用例列表（共 {len(items)} 条）\n\n"
        for i, item in enumerate(items):
            tags_str = f" [{', '.join(item['tags'])}]" if item.get("tags") else ""
            sub = f" | 子模块:{item.get('sub_module', '')}" if item.get('sub_module') else ""
            text += f"{i+1}. **{item['title']}**\n"
            text += f"   `{item['id']}` | {item['module']}{sub} | {item['priority']} | {item['category']}{tags_str}\n"
        return {"content": [{"type": "text", "text": text.strip()}]}

    elif name == "tc_get":
        case = engine.get_by_id(args.get("id", ""))
        if not case:
            return {"content": [{"type": "text", "text": f"❌ 用例 {args.get('id')} 不存在"}]}
        text = (
            f"# {case['title']}\n\n"
            f"| 字段 | 值 |\n"
            f"|------|-----|\n"
            f"| ID | `{case['id']}` |\n"
            f"| 模块 | {case['module']} |\n"
            f"| 优先级 | {case['priority']} |\n"
            f"| 类别 | {case['category']} |\n"
            f"| 项目 | {case.get('project', '')} |\n"
            f"| 创建人 | {case.get('creator', '')} |\n"
            f"| 创建时间 | {case.get('created_at', '')} |\n"
        )
        tags = case.get("tags", [])
        if tags:
            text += f"| 标签 | {', '.join(tags)} |\n"
        text += f"\n{case.get('content', '')}"
        return {"content": [{"type": "text", "text": text}]}

    elif name == "tc_stats":
        stats_data = engine.get_stats()
        text = f"## 📊 知识库统计\n\n总用例数: {stats_data['total']}\n\n"
        if stats_data.get("modules"):
            text += "### 按模块\n\n"
            for mod, count in sorted(stats_data["modules"].items(), key=lambda x: -x[1]):
                text += f"- {mod}: {count} 条\n"
        if stats_data.get("priorities"):
            text += "\n### 按优先级\n\n"
            for p, count in sorted(stats_data["priorities"].items()):
                text += f"- {p}: {count} 条\n"
        return {"content": [{"type": "text", "text": text.strip()}]}

    elif name == "tc_project_types":
        details = engine.get_project_types_detail()
        if not details:
            return {"content": [{"type": "text", "text": "📋 当前没有已录入的项目类型，project 字段可留空"}]}
        text = "## 📋 已录入的项目类型\n\n"
        for d in details:
            text += f"### {d['project']}（{d['module_count']} 个模块）\n"
            for m in d['modules']:
                text += f"  - {m}\n"
            text += "\n"
        text += "💡 添加新用例时请从以上项目类型中选择。如需新增类型，请确认不存在近似名称后直接填写新值"
        return {"content": [{"type": "text", "text": text}]}

    elif name == "tc_delete":
        case_id = args.get("id", "").strip()
        module = args.get("module", "").strip()
        project = args.get("project", "").strip()

        if case_id:
            ok = engine.delete(case_id)
            if ok:
                return {"content": [{"type": "text", "text": f"✅ 用例 `{case_id}` 已删除"}]}
            else:
                return {"content": [{"type": "text", "text": f"❌ 用例 `{case_id}` 不存在"}]}
        elif module or project:
            count = engine.delete_many(module=module or None, project=project or None)
            parts = []
            if module: parts.append(f"模块={module}")
            if project: parts.append(f"项目={project}")
            return {"content": [{"type": "text", "text": f"✅ 已删除 {count} 条用例（{'，'.join(parts)}）"}]}
        else:
            return {"content": [{"type": "text", "text": "❌ 请提供 id（删单条），或 module/project（批量删除）"}]}

    elif name == "tc_graph_search":
        if not lightrag_engine.is_available():
            return {"content": [{"type": "text", "text": "❌ LightRAG 图谱未启用或初始化失败。可调 tc_graph_status 查看详情，或检查配置 lightrag.enabled"}]}
        query = args.get("query", "").strip()
        if not query:
            return {"content": [{"type": "text", "text": "请提供搜索关键词"}]}
        result = lightrag_engine.search(query, n_results=min(int(args.get("n_results", 5)), 20))
        if not result.get("ok"):
            return {"content": [{"type": "text", "text": f"❌ 图谱检索失败: {result.get('message', '未知错误')}"}]}
        entities = result.get("entities", [])
        relationships = result.get("relationships", [])
        chunks = result.get("chunks", [])
        text = f"## 🕸️ 知识图谱检索「{query}」\n\n"
        text += f"共找到 {len(entities)} 个实体, {len(relationships)} 条关系, {len(chunks)} 个片段\n\n"
        if entities:
            text += "### 📍 实体\n\n"
            for e in entities:
                text += f"- **{e['name']}**（{e.get('type', '-')}）\n  {e.get('description', '')[:150]}\n"
        if relationships:
            text += "\n### 🔗 关系\n\n"
            for r in relationships[:10]:
                text += f"- {r['source']} → {r['target']}: {r.get('description', '')[:100]}\n"
        if chunks:
            text += "\n### 📄 相关片段\n\n"
            for c in chunks[:5]:
                text += f"- {c.get('content', '')[:200]}...\n"
        return {"content": [{"type": "text", "text": text.strip()}]}

    elif name == "tc_agentic_search":
        query = args.get("query", "").strip()
        if not query:
            return {"content": [{"type": "text", "text": "请提供搜索关键词"}]}
        n_results = min(int(args.get("n_results", 5)), 20)
        result = await search_router.async_search(
            query=query,
            n_results=n_results,
            module=args.get("module"),
            priority=args.get("priority"),
            category=args.get("category"),
            mode="auto",
        )
        text = f"## 🔍 自适应检索「{query}」\n\n模式: {result['mode']}\n\n"
        chroma_results = result.get("results", [])
        if chroma_results:
            text += f"### 📋 向量匹配结果（{len(chroma_results)} 条）\n\n"
            for r in chroma_results:
                score_bar = "█" * int(r["score"] * 20) + "░" * (20 - int(r["score"] * 20))
                text += f"**{r['title']}** [{score_bar}] {r['score']:.2f}\n"
                text += f"`{r['id']}` | {r['module']} | {r['priority']}\n\n"
        else:
            text += "无可用的向量搜索结果\n\n"

        graph_hits = result.get("graph_hits")
        if graph_hits:
            entities = graph_hits.get("entities", [])
            relationships = graph_hits.get("relationships", [])
            if entities:
                text += f"### 🕸️ 图谱增强（{len(entities)} 实体）\n\n"
                for e in entities[:5]:
                    text += f"- **{e['name']}**\n"
            if relationships:
                text += "\n"
                for r in relationships[:5]:
                    text += f"- {r['source']} → {r['target']}\n"

        return {"content": [{"type": "text", "text": text.strip()}]}

    elif name == "tc_graph_status":
        if not cfg.lightrag_enabled:
            return {"content": [{"type": "text", "text": "📋 LightRAG 状态: 未启用（config.lightrag.enabled = false）\n如需启用，设置 enabled: true 并重启服务"}]}
        status = lightrag_engine.get_status()
        text = "## 📊 LightRAG 状态\n\n"
        text += f"| 字段 | 值 |\n|------|-----|\n"
        text += f"| 启用 | {'✅ 是' if status.get('enabled') else '❌ 否'} |\n"
        text += f"| 就绪 | {'✅ 是' if status.get('ready') else '❌ 否'} |\n"
        text += f"| LLM 提供商 | {status.get('provider', '-')} |\n"
        text += f"| LLM 模型 | {status.get('model', '-')} |\n"
        if status.get("node_count") is not None:
            text += f"| 实体数量 | {status['node_count']} |\n"
        if status.get("processing_status"):
            text += f"| 处理状态 | {status['processing_status']} |\n"
        if status.get("message"):
            text += f"| 消息 | {status['message']} |\n"
        return {"content": [{"type": "text", "text": text.strip()}]}

    else:
        return {"content": [{"type": "text", "text": f"未知工具: {name}"}]}


def _normalize_args(raw) -> dict:
    """归一化 MCP arguments 参数，兼容部分客户端误传 list"""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], dict):
        return raw[0]
    # 打印日志便于定位问题
    import logging
    logging.getLogger("mcp").warning(f"invalid arguments type: {type(raw).__name__}, value: {raw}")
    return {}


def _mcp_handle_tc_add(args: dict) -> dict:
    """处理 tc_add：添加单条测试用例（自动清洗）"""
    try:
        tc = _make_tc(args)
    except ValueError as e:
        return {"content": [{"type": "text", "text": f"❌ {e}"}]}
    tc.id = tc.gen_id()
    engine.add(tc)
    # 同步到 LightRAG 图谱
    if lightrag_engine.is_available():
        lightrag_engine.insert([tc.get_embedding_text()], ids=[tc.id])
    return {
        "content": [{
            "type": "text",
            "text": (
                f"✅ 测试用例已添加\n\n"
                f"| 字段 | 值 |\n"
                f"|------|-----|\n"
                f"| ID | `{tc.id}` |\n"
                f"| 标题 | {tc.title} |\n"
                f"| 模块 | {tc.module} |\n"
                f"| 子模块 | {tc.sub_module or '-'} |\n"
                f"| 项目 | {tc.project} |\n"
                f"| 优先级 | {tc.priority} |\n"
                f"| 类别 | {tc.category} |\n"
                + (f"| 步骤 | {len(tc.steps)} 条 |\n" if tc.steps else "")
                + (f"| 标签 | {', '.join(tc.tags)} |\n" if tc.tags else "")
                + f"\n可用 `tc_get` 传入 ID `{tc.id}` 查看详情"
            ),
        }]
    }


def _mcp_handle_tc_add_batch(args: dict) -> dict:
    """处理 tc_add_batch：批量添加测试用例（自动清洗每条）"""
    raw_cases = args.get("cases", [])
    if not isinstance(raw_cases, list) or not raw_cases:
        return {"content": [{"type": "text", "text": "❌ cases 必须是数组，且至少包含一条用例"}]}

    added = []
    errors = []
    for i, c in enumerate(raw_cases):
        try:
            if not isinstance(c, dict):
                errors.append(f"第 {i+1} 条：参数格式错误（非对象）")
                continue
            tc = _make_tc(c)
            tc.id = tc.gen_id()
            engine.add(tc)
            added.append(tc)
        except ValueError as e:
            errors.append(f"第 {i+1} 条：{e}")

    # 同步到 LightRAG 图谱（批量）
    if added and lightrag_engine.is_available():
        texts = [tc.get_embedding_text() for tc in added]
        ids = [tc.id for tc in added]
        lightrag_engine.insert(texts, ids=ids)

    summary = f"✅ 成功添加 {len(added)} 条"
    if errors:
        summary += f"，{len(errors)} 条失败:\n" + "\n".join(errors)

    # 按 module 分组展示
    if added:
        from collections import Counter
        mods = Counter(tc.module for tc in added)
        summary += "\n\n**按模块分布:**\n"
        for mod, count in mods.most_common():
            summary += f"- {mod}: {count} 条\n"

    # 列出前几条 ID
    summary += "\n**新增用例 ID:**\n"
    for tc in added[:10]:
        summary += f"- `{tc.id}` — {tc.title}\n"
    if len(added) > 10:
        summary += f"  ... 还有 {len(added) - 10} 条\n"

    return {"content": [{"type": "text", "text": summary}]}


# ── MCP 工具 Schema ──

MCP_TOOLS = [
    {
        "name": "tc_search",
        "description": "基础语义搜索（ChromaDB + BM25 向量引擎），快速返回最匹配的测试用例。支持按 module/sub_module/priority/category 精确筛选。"
            "【使用流程】① 先调 tc_project_types 了解项目分布 → ② 用本工具做关键词搜索 → ③ 得分低或结果不够时，换关键词精化，或改调 tc_agentic_search 自动融合图谱增强。"
            "需要跨模块关联推理时，请用 tc_graph_search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或自然语言描述"},
                "n_results": {"type": "number", "description": "返回结果数量（默认5，最多20）", "default": 5},
                "module": {"type": "string", "description": "按模块筛选"},
                "priority": {"type": "string", "description": "按优先级筛选（P0/P1/P2/P3）"},
                "category": {"type": "string", "description": "按类别筛选"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "tc_list",
        "description": "浏览测试用例列表（支持按 module/sub_module/priority/category 筛选和分页）。想查具体某条详情请用 tc_get；想做语义搜索请用 tc_search 或 tc_agentic_search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module": {"type": "string", "description": "按模块筛选"},
                "priority": {"type": "string", "description": "按优先级筛选"},
                "category": {"type": "string", "description": "按类别筛选"},
                "offset": {"type": "number", "description": "分页偏移"},
                "limit": {"type": "number", "description": "每页数量（默认50）"},
            },
        },
    },
    {
        "name": "tc_get",
        "description": "按 ID 获取测试用例的完整内容（包含 steps/expected/tags 等全部字段）。如果不知道 ID，先调 tc_search / tc_list 找到目标用例",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "用例 ID"}},
            "required": ["id"],
        },
    },
    {
        "name": "tc_stats",
        "description": "获取知识库统计信息（总数、模块分布、优先级分布、类别分布）。先调此工具了解整体规模和数据覆盖情况，再决定后续搜索策略",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tc_project_types",
        "description": "获取已录入的所有项目类型列表（去重排序，含各类型下的模块分布）。"
            "【使用场景】① 添加用例前：先查已有类型再填 project 字段，保持数据一致性。"
            "② 检索用例前：了解模块和项目分布，帮助构建更精准的搜索关键词。"
            "③ 需要查看特定项目下的子模块（sub_module）结构时，可结合 tc_list 进一步浏览",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "tc_add",
        "description": "【重要】添加前先调用 tc_project_types 查询已有项目类型。添加单条测试用例。"
            "自动清洗规则：标题/模块必填非空；project 为项目类型（如 slot游戏/后台/活动），空则留空；priority→P3；category→功能测试；creator→MCP；steps/tags 空元素自动过滤；所有文本 trim+合并换行空白。"
            "⚠️ 添加后自动同步写入 LightRAG 知识图谱（如已启用），后续可用 tc_graph_search 检索新用例的实体关系",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "用例标题（必填）"},
                "module": {"type": "string", "description": "模块名，如：登录/支付/搜索/音效/转盘/UI（必填）"},
                "priority": {"type": "string", "description": "优先级 P0/P1/P2/P3（默认 P3）"},
                "category": {"type": "string", "description": "类别：功能测试/性能测试/安全测试/回归测试（默认 功能测试）"},
                "preconditions": {"type": "string", "description": "前置条件"},
                "steps": {"type": "array", "items": {"type": "string"}, "description": "测试步骤列表（自动过滤空行和换行符）"},
                "expected": {"type": "string", "description": "预期结果"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表（自动过滤空元素）"},
                "project": {"type": "string", "description": "项目类型，如 slot游戏/后台/活动（可空，建议先查 tc_project_types）"},
                "creator": {"type": "string", "description": "创建人（默认 MCP）"},
            },
            "required": ["title", "module"],
        },
    },
    {
        "name": "tc_add_batch",
        "description": "【重要】添加前先调用 tc_project_types 查询已有项目类型。批量添加测试用例（逐条清洗，单条失败不阻塞整体）。清洗规则同 tc_add。"
            "返回成功/失败统计和模块分布。"
            "⚠️ 添加后自动同步写入 LightRAG 知识图谱（如已启用），后续可用 tc_graph_search 检索新用例的实体关系",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cases": {
                    "type": "array",
                    "description": "用例数组，每条包含 title, module（必填）及可选字段",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "用例标题（必填）"},
                            "module": {"type": "string", "description": "模块名（必填）"},
                            "priority": {"type": "string", "description": "优先级 P0-P3"},
                            "category": {"type": "string", "description": "类别"},
                            "preconditions": {"type": "string", "description": "前置条件"},
                            "steps": {"type": "array", "items": {"type": "string"}, "description": "测试步骤"},
                            "expected": {"type": "string", "description": "预期结果"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                            "project": {"type": "string", "description": "项目类型（可空，建议先查 tc_project_types）"},
                            "creator": {"type": "string", "description": "创建人"},
                        },
                        "required": ["title", "module"],
                    },
                }
            },
            "required": ["cases"],
        },
    },
    {
        "name": "tc_delete",
        "description": "删除测试用例。支持两种模式：按 ID 删除单条，或按 module/project 批量删除。注意批量删除不可撤销。"
            "⚠️ 删除不同步清除 LightRAG 知识图谱中的对应实体关系；如需完整重建图谱，请调 tc_graph_status 确认图谱存在后再手动重建",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "用例 ID（按 ID 删单条时填写）"},
                "module": {"type": "string", "description": "模块名，删除该模块下所有用例（批量模式）"},
                "project": {"type": "string", "description": "项目类型，删除该项目下所有用例（批量模式）"},
            },
            "required": [],
        },
    },
    {
        "name": "tc_graph_search",
        "description": "【需 LightRAG 启用】知识图谱检索——通过实体-关系图做跨模块关联推理。"
            "适用场景：① 跨模块关联查询（如'扣费模块关联哪些模块'）② 多跳推理（'某条用例和哪些项目相关'）③ 概念关系发现。"
            "返回：实体列表、关系列表、关联文本片段。"
            "【使用提示】调 tc_graph_status 确认图谱就绪后再使用。如果结果为空洞，尝试简化查询词。"
            "需要完整用例内容时，用找到的实体名配合 tc_search 或 tc_agentic_search 做向量检索",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或自然语言描述",
                },
                "n_results": {
                    "type": "number",
                    "description": "返回结果数量（默认5，最多20）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "tc_agentic_search",
        "description": "【推荐】自适应检索——自动融合向量搜索 + 知识图谱增强。先走 ChromaDB 做语义匹配，再调用 LightRAG 图谱补充实体关系。"
            "如果图谱不可用，自动降级为纯向量搜索。"
            "适用场景：① 复杂问题不确定怎么精确表达关键词 ② 需要同时看语义匹配结果和相关实体关系 ③ tc_search 首轮结果不够理想时的深入检索。"
            "如果只想要纯向量快速匹配，用 tc_search。需要纯图谱推理，用 tc_graph_search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或自然语言描述",
                },
                "n_results": {
                    "type": "number",
                    "description": "返回结果数量（默认5，最多20）",
                    "default": 5,
                },
                "module": {
                    "type": "string",
                    "description": "按父模块筛选（如：spin/bonus玩法/Jackpot玩法/UI）",
                },
                "priority": {
                    "type": "string",
                    "description": "按优先级筛选（P0/P1/P2/P3）",
                },
                "category": {
                    "type": "string",
                    "description": "按类别筛选（功能测试/性能测试/安全测试/回归测试）",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "tc_graph_status",
        "description": "诊断 LightRAG 知识图谱状态：是否启用、是否已建图、实体数量、LLM 提供商、处理状态等。"
            "使用场景：① tc_graph_search 无结果时先调此工具诊断 ② 确认图谱就绪后再做图谱检索 ③ 建图过程中查看处理进度",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ── MCP HTTP/SSE 端点 ──


@app.get("/mcp/info")
def mcp_info():
    """MCP 服务信息"""
    return {
        "name": "testcase-rag-mcp",
        "version": "3.0.0",
        "protocol": "MCP 2024-11-05",
        "transport": "HTTP + SSE",
        "endpoints": {
            "sse": "/mcp/sse",
            "message": "POST /mcp",
        },
        "tools": [t["name"] for t in MCP_TOOLS],
    }


@app.get("/mcp/sse")
async def mcp_sse(request: Request):
    """MCP SSE 端点 — 客户端通过 EventSource 连接"""
    global _next_session_id
    session_id = f"sess-{_next_session_id}"
    _next_session_id += 1
    queue: asyncio.Queue = asyncio.Queue()
    _mcp_sessions[session_id] = queue

    async def event_generator():
        try:
            # 先发 endpoint 事件
            endpoint_url = str(request.base_url) + f"mcp?session_id={session_id}"
            yield f"event: endpoint\ndata: {endpoint_url}\n\n"

            # 发 initialized 事件
            init_msg = json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })
            yield f"event: message\ndata: {init_msg}\n\n"

            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: message\ndata: {msg}\n\n"
                except asyncio.TimeoutError:
                    # 保活 ping
                    yield f": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _mcp_sessions.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class MCPMessage(BaseModel):
    jsonrpc: str = "2.0"
    id: int | None = None
    method: str | None = None
    params: dict = {}


@app.post("/mcp")
async def mcp_message(msg: MCPMessage, request: Request, session_id: str = Query("")):
    """MCP 消息端点 — 客户端发送 JSON-RPC 请求"""
    msg_id = msg.id
    method = msg.method

    # 如果是 tools/list
    if method == "tools/list":
        resp = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": MCP_TOOLS},
        }
        return resp

    # 如果是 initialize
    if method == "initialize":
        resp = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "testcase-rag-mcp", "version": "2.0.0"},
            },
        }
        return resp

    # 如果是 notifications/initialized
    if method == "notifications/initialized":
        return {"jsonrpc": "2.0"}

    # 如果是 ping
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    # 如果是 tools/call
    if method == "tools/call":
        tool_name = msg.params.get("name", "")
        tool_args = _normalize_args(msg.params.get("arguments", {}))

        if tool_name == "tc_graph_search":
            result = await _async_graph_search(tool_args)
        elif tool_name == "tc_agentic_search":
            result = await _async_agentic_search(tool_args)
        elif tool_name == "tc_graph_status":
            result = await _async_graph_status()
        elif tool_name == "tc_add":
            result = _mcp_handle_tc_add(tool_args)
        elif tool_name == "tc_add_batch":
            result = _mcp_handle_tc_add_batch(tool_args)
        else:
            result = _mcp_handle(tool_name, tool_args)

        resp = {"jsonrpc": "2.0", "id": msg_id, "result": result}

        # 如果有 SSE session，通过 SSE 推回
        if session_id and session_id in _mcp_sessions:
            await _mcp_sessions[session_id].put(json.dumps(resp))
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"_delivered": "sse"}}

        return resp

    # 未知方法
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"不支持的方法: {method}"},
    }


# ── REST API Pydantic 模型 ──


class CaseCreate(BaseModel):
    title: str = Field(..., description="用例标题")
    module: str = Field(..., description="模块名，如 登录/支付/搜索")
    sub_module: str = Field("", description="子模块/测试点，如：扣费/玩法触发/派奖")
    priority: str = Field("P3", description="P0/P1/P2/P3")
    category: str = Field("功能测试", description="功能测试/性能测试/安全测试/回归测试")
    preconditions: str = Field("", description="前置条件")
    steps: list[str] = Field(default_factory=list, description="测试步骤列表")
    expected: str = Field("", description="预期结果")
    tags: list[str] = Field(default_factory=list, description="标签")
    project: str = Field("", description="所属项目")
    creator: str = Field("", description="创建人")


class CaseBatchCreate(BaseModel):
    cases: list[CaseCreate]


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索关键词或自然语言问句")
    n_results: int = Field(10, description="返回数量", ge=1, le=50)
    module: str = Field("", description="按父模块筛选")
    sub_module: str = Field("", description="按子模块/测试点精确筛选")
    priority: str = Field("", description="按优先级筛选")
    category: str = Field("", description="按类别筛选")


# ── REST API 端点 ──


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/api/v1/cases", status_code=201)
def create_case(case: CaseCreate):
    tc = TestCase(
        title=case.title,
        module=case.module,
        sub_module=case.sub_module,
        priority=case.priority,
        category=case.category,
        preconditions=case.preconditions,
        steps=case.steps,
        expected=case.expected,
        tags=case.tags,
        project=case.project,
        creator=case.creator,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    tc.id = tc.gen_id()
    engine.add(tc)
    return {"id": tc.id, "message": f"用例「{tc.title}」已添加"}


@app.post("/api/v1/cases/batch", status_code=201)
def create_cases_batch(batch: CaseBatchCreate):
    cases = []
    for c in batch.cases:
        tc = TestCase(
            title=c.title,
            module=c.module,
            sub_module=c.sub_module,
            priority=c.priority,
            category=c.category,
            preconditions=c.preconditions,
            steps=c.steps,
            expected=c.expected,
            tags=c.tags,
            project=c.project,
            creator=c.creator,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        tc.id = tc.gen_id()
        cases.append(tc)
    count = engine.add_many(cases)
    return {"count": count, "message": f"成功添加 {count} 条用例"}


@app.get("/api/v1/cases")
def list_cases(
    module: str = Query("", description="按父模块筛选"),
    sub_module: str = Query("", description="按子模块/测试点精确筛选"),
    priority: str = Query("", description="按优先级筛选"),
    category: str = Query("", description="按类别筛选"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    items = engine.get_all(
        module=module or None,
        sub_module=sub_module or None,
        priority=priority or None,
        category=category or None,
        offset=offset,
        limit=limit,
    )
    return {"total": len(items), "items": items}


@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: str):
    case = engine.get_by_id(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
    return case


@app.delete("/api/v1/cases/{case_id}")
def delete_case(case_id: str):
    ok = engine.delete(case_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"用例 {case_id} 不存在")
    return {"message": f"用例 {case_id} 已删除"}


@app.delete("/api/v1/cases")
def delete_cases_batch(module: str = Query(""), project: str = Query("")):
    count = engine.delete_many(module=module or None, project=project or None)
    return {"deleted": count, "message": f"已删除 {count} 条用例"}


@app.post("/api/v1/search")
def search_cases(req: SearchRequest):
    results = engine.search(
        query=req.query,
        n_results=req.n_results,
        module=req.module or None,
        sub_module=req.sub_module or None,
        priority=req.priority or None,
        category=req.category or None,
    )
    return {"query": req.query, "total": len(results), "results": results}


@app.get("/api/v1/stats")
def stats():
    return engine.get_stats()


@app.get("/api/v1/project-types")
def project_types():
    """获取所有已录入的项目类型列表（含各项目下的模块）"""
    return {"project_types": engine.get_project_types_detail()}


class GraphSearchRequest(BaseModel):
    query: str = Field(..., description="搜索关键词")
    n_results: int = Field(5, description="返回数量", ge=1, le=50)
    mode: str = Field("auto", description="检索模式: auto(向量+图谱)/graph(仅图谱)/chroma(仅向量)")


@app.post("/api/v1/search/graph")
async def search_graph(req: GraphSearchRequest):
    """LightRAG 知识图谱检索"""
    if not lightrag_engine.is_available():
        raise HTTPException(status_code=503, detail="LightRAG 图谱未启用或初始化失败")
    result = await lightrag_engine.async_search(req.query, n_results=req.n_results)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("message", "图谱检索失败"))
    return {
        "query": req.query,
        "entities": result.get("entities", []),
        "relationships": result.get("relationships", []),
        "chunks": result.get("chunks", []),
    }


@app.post("/api/v1/search/agentic")
async def search_agentic(req: GraphSearchRequest):
    """自适应检索 — 向量搜索 + 图谱增强"""
    result = await search_router.async_search(
        query=req.query, n_results=req.n_results, mode=req.mode,
    )
    return {
        "query": req.query,
        "mode": result["mode"],
        "results": result.get("results", []),
        "graph_hits": result.get("graph_hits"),
    }


@app.get("/api/v1/graph/status")
async def graph_status():
    """LightRAG 知识图谱状态"""
    return lightrag_engine.get_status()


# ── 文件上传（临时，用于接收 ChromaDB 导出） ──

import os as _os

UPLOAD_DIR = "/tmp/testcase-uploads"
_os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/upload")
def upload_form():
    """文件上传页面"""
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="zh">
    <head><meta charset="utf-8"><title>文件上传</title>
    <style>
        body {{ font-family: sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
        .drop {{ border: 2px dashed #ccc; border-radius: 8px; padding: 40px; text-align: center; }}
        .drop.dragover {{ border-color: #4A90D9; background: #f0f6ff; }}
        #file {{ display: none; }}
        .btn {{ background: #4A90D9; color: #fff; border: none; padding: 10px 24px; border-radius: 6px; cursor: pointer; }}
        #status {{ margin-top: 16px; font-size: 14px; }}
    </style>
    </head>
    <body>
    <h2>📤 上传文件</h2>
    <div class="drop" id="drop">
        <p>拖拽文件到此处，或点击选择</p>
        <input type="file" id="file">
        <button class="btn" onclick="document.getElementById('file').click()">选择文件</button>
    </div>
    <div id="status"></div>
    <script>
        const drop = document.getElementById('drop');
        const fileInput = document.getElementById('file');
        const status = document.getElementById('status');

        drop.addEventListener('dragover', e => {{ e.preventDefault(); drop.classList.add('dragover') }});
        drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
        drop.addEventListener('drop', e => {{ e.preventDefault(); drop.classList.remove('dragover'); upload(e.dataTransfer.files[0]) }});
        fileInput.addEventListener('change', () => upload(fileInput.files[0]));

        async function upload(file) {{
            if (!file) return;
            status.innerHTML = '⏳ 上传中...';
            const form = new FormData();
            form.append('file', file);
            try {{
                const r = await fetch('/upload', {{ method: 'POST', body: form }});
                const d = await r.json();
                status.innerHTML = d.error ? `❌ ${{d.error}}` : `✅ ${{d.message}}<br>📁 ${{d.path}}`;
            }} catch(e) {{
                status.innerHTML = '❌ 上传失败: ' + e.message;
            }}
        }}
    </script>
    </body>
    </html>
    """)


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """接收上传文件"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    # 安全处理文件名
    safe_name = _os.path.basename(file.filename)
    save_path = _os.path.join(UPLOAD_DIR, safe_name)

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    size_mb = len(content) / 1024 / 1024
    return {
        "message": f"文件已保存: {safe_name} ({size_mb:.1f} MB)",
        "path": save_path,
        "size": len(content),
    }
