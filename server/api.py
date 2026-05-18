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
import re
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .engine import TestCase, get_engine

# ── FastAPI 应用 ──

app = FastAPI(
    title="测试用例知识库 API",
    description="Test Case RAG — 结构化存储 + 语义检索 + HTTP MCP",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = get_engine()

# ── 输入清洗 ──

def _clean_text(s: str) -> str:
    """清洗单行文本：去换行、去首尾空白、合并连续空白"""
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
            text += f"{i+1}. **{item['title']}**\n"
            text += f"   `{item['id']}` | {item['module']} | {item['priority']} | {item['category']}{tags_str}\n"
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
        types = engine.get_project_types()
        if not types:
            return {"content": [{"type": "text", "text": "📋 当前没有已录入的项目类型，project 字段可留空"}]}
        text = "## 📋 已录入的项目类型\n\n"
        for i, t in enumerate(types, 1):
            text += f"{i}. **{t}**\n"
        text += "\n💡 添加新用例时请从以上类型中选择，保持数据一致性。如需新增类型，请确认不存在近似名称后直接填写新值"
        return {"content": [{"type": "text", "text": text}]}

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
        "description": "语义搜索测试用例，返回最匹配的结果",
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
        "description": "列出测试用例（支持按模块/优先级/类别筛选和分页）",
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
        "description": "按 ID 获取测试用例的完整内容",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "用例 ID"}},
            "required": ["id"],
        },
    },
    {
        "name": "tc_stats",
        "description": "获取知识库统计信息（总数、模块分布、优先级分布）",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "tc_project_types",
        "description": "获取已录入的所有项目类型列表（去重排序）。在调用 tc_add / tc_add_batch 前应先查询本接口，了解已有的项目类型后再填写 project 字段，确保数据一致性",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "tc_add",
        "description": "【重要】添加前先调用 tc_project_types 查询已有项目类型，统一使用已有的类型名。添加一条新的测试用例到知识库（自动清洗输入：去换行、trim、过滤空元素）。注意：project 为项目类型（如 slot游戏/后台/活动），空则留空，不再默认取 module",
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
        "description": "【重要】添加前先调用 tc_project_types 查询已有项目类型，统一使用已有的类型名。批量添加测试用例（自动清洗每条）。传入 cases 数组，每条结构和 tc_add 一致",
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
]


# ── MCP HTTP/SSE 端点 ──


@app.get("/mcp/info")
def mcp_info():
    """MCP 服务信息"""
    return {
        "name": "testcase-rag-mcp",
        "version": "2.0.0",
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

        # tc_add / tc_add_batch 走专用处理函数
        if tool_name == "tc_add":
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
    module: str = Field("", description="按模块筛选")
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
    module: str = Query("", description="按模块筛选"),
    priority: str = Query("", description="按优先级筛选"),
    category: str = Query("", description="按类别筛选"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    items = engine.get_all(
        module=module or None,
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
        priority=req.priority or None,
        category=req.category or None,
    )
    return {"query": req.query, "total": len(results), "results": results}


@app.get("/api/v1/stats")
def stats():
    return engine.get_stats()


@app.get("/api/v1/project-types")
def project_types():
    """获取所有已录入的项目类型列表"""
    return {"project_types": engine.get_project_types()}
