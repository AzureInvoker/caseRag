"""
REST API + HTTP MCP — 测试用例知识库

启动:
  cd /home/admin/testcase-rag
  uvicorn server.api:app --host $TC_API_HOST --port $TC_API_PORT

配置优先级: 环境变量 > config.yaml > 默认值
  TC_API_HOST=0.0.0.0
  TC_API_PORT=8765

端点:
  REST API:
    POST   /api/v1/cases            — 添加单条用例
    POST   /api/v1/cases/batch      — 批量添加
    GET    /api/v1/cases            — 列表/筛选/分页
    POST   /api/v1/search           — 语义搜索
    GET    /api/v1/stats            — 统计信息
    ...

  MCP (HTTP/SSE):
    GET    /mcp                     — SSE 端点（MCP 客户端连接用）
    POST   /mcp                     — 消息端点（MCP 客户端发送请求）

  MCP 发现端点:
    GET    /mcp/info                — MCP 服务信息
    GET    /mcp/sse                 — SSE 流端点（MCP 标准协议）
"""

import json
import asyncio
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

    else:
        return {"content": [{"type": "text", "text": f"未知工具: {name}"}]}


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
        tool_args = msg.params.get("arguments", {})
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
