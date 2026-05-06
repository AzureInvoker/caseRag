"""
REST API — 测试用例知识库

启动:
  cd /home/admin/testcase-rag
  uvicorn server.api:app --host $TC_API_HOST --port $TC_API_PORT

配置优先级: 环境变量 > config.yaml > 默认值
  TC_API_HOST=0.0.0.0
  TC_API_PORT=8765

端点:
  POST   /api/v1/cases          — 添加单条用例
  POST   /api/v1/cases/batch    — 批量添加
  GET    /api/v1/cases          — 列表/筛选/分页
  GET    /api/v1/cases/{id}     — 获取单条
  DELETE /api/v1/cases/{id}     — 删除单条
  DELETE /api/v1/cases          — 按条件批量删除
  POST   /api/v1/search         — 语义搜索
  GET    /api/v1/stats          — 统计信息
  GET    /api/v1/health         — 健康检查
"""

from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import TestCase, get_engine

# ── FastAPI 应用 ──

app = FastAPI(
    title="测试用例知识库 API",
    description="Test Case RAG — 结构化存储 + 语义检索",
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


# ── Pydantic 模型 ──


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


# ── API 端点 ──


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
