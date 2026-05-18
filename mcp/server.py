#!/usr/bin/env python3
"""
测试用例知识库 MCP Server — 供 Claude Code / Cursor / Hermes 检索

使用方式:
  # Hermes config.yaml 中配置:
  mcp_servers:
    testcase-rag:
      command: "python3"
      args: ["/home/admin/testcase-rag/mcp/server.py"]

  # 独立测试:
  echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | python3 mcp/server.py
"""

import json
import sys
import os
import re
from pathlib import Path
from datetime import datetime
from collections import Counter

# 将项目根目录添加到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

# 直接从目录 import（避免包名冲突）
import importlib.util
spec = importlib.util.spec_from_file_location(
    "engine",
    str(Path(__file__).parent.parent / "server" / "engine.py"),
)
engine_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine_mod)

TestCase = engine_mod.TestCase
get_engine = engine_mod.get_engine

# ── 输入清洗 ──


def _clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\\n", " ").replace("\\r", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _clean_list(items: list) -> list:
    if not isinstance(items, list):
        return []
    return [_clean_text(i) for i in items if isinstance(i, str) and _clean_text(i)]


def _make_tc(args: dict) -> "TestCase":
    from datetime import datetime
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


engine = get_engine()

# ── MCP 工具定义 ──

TOOLS = [
    {
        "name": "tc_search",
        "description": "语义搜索测试用例，返回最匹配的结果",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或自然语言描述（如'登录失败怎么测'、'支付超时用例'）",
                },
                "n_results": {
                    "type": "number",
                    "description": "返回结果数量（默认5，最多20）",
                    "default": 5,
                },
                "module": {
                    "type": "string",
                    "description": "按模块筛选（如：登录/支付/搜索/权限）",
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
            "required": [],
        },
    },
    {
        "name": "tc_get",
        "description": "按 ID 获取测试用例的完整内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "用例 ID"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "tc_stats",
        "description": "获取知识库统计信息（总数、模块分布、优先级分布）",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
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
        "description": "【重要】添加前先调用 tc_project_types 查询已有项目类型，统一使用已有的类型名。添加单条测试用例。自动清洗规则：标题/模块必填且非空；project 为项目类型（如 slot游戏/后台/活动），空则留空；优先级默认为 P3；类别默认为 功能测试；创建人默认 MCP；steps/tags 中空元素自动过滤；所有文本 trim 首尾并合并多余空白/换行；非字符串字段降级为空串",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "用例标题（必填，非空校验）"},
                "module": {"type": "string", "description": "模块名，如 登录/支付/搜索/音效/转盘/UI/榜单/主页（必填，非空校验）"},
                "priority": {"type": "string", "description": "优先级 P0/P1/P2/P3（空则默认 P3）"},
                "category": {"type": "string", "description": "类别（空则默认 功能测试）"},
                "preconditions": {"type": "string", "description": "前置条件（自动 trim 去换行）"},
                "steps": {"type": "array", "items": {"type": "string"}, "description": "测试步骤列表（自动过滤空行）"},
                "expected": {"type": "string", "description": "预期结果（自动 trim 去换行）"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表（自动过滤空元素）"},
                "project": {"type": "string", "description": "项目类型，如 slot游戏/后台/活动/大厅/新手引导（可空）"},
                "creator": {"type": "string", "description": "创建人（空则默认 MCP）"},
            },
            "required": ["title", "module"],
        },
    },
    {
        "name": "tc_add_batch",
        "description": "【重要】添加前先调用 tc_project_types 查询已有项目类型，统一使用已有的类型名。批量添加测试用例（逐条清洗，单条失败不阻塞整体）。清洗规则同 tc_add：标题/模块必填非空；project 为项目类型（如 slot游戏/后台/活动），空则留空；priority→P3；category→功能测试；creator→MCP；steps/tags 空元素自动过滤；所有文本 trim+合并空白。返回成功/失败统计和模块分布",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cases": {
                    "type": "array",
                    "description": "用例数组（每条清洗规则同 tc_add），每条必填 title, module",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "用例标题（必填，非空校验）"},
                            "module": {"type": "string", "description": "模块名（必填，非空校验）"},
                            "priority": {"type": "string", "description": "优先级（空则默认 P3）"},
                            "category": {"type": "string", "description": "类别（空则默认 功能测试）"},
                            "preconditions": {"type": "string", "description": "前置条件"},
                            "steps": {"type": "array", "items": {"type": "string"}, "description": "测试步骤列表（空元素过滤）"},
                            "expected": {"type": "string", "description": "预期结果"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表（空元素过滤）"},
                            "project": {"type": "string", "description": "项目类型（如 slot游戏/后台/活动），空则留空"},
                            "creator": {"type": "string", "description": "创建人（空则 MCP）"},
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
        "description": "删除测试用例。支持两种模式：按 ID 删除单条，或按 module/project 批量删除。注意批量删除不可撤销",
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
]


# ── MCP 协议 ──


def send_json(obj: dict):
    """发送 JSON-RPC 消息（用 buffer.write 绕过编码问题，确保中文不变成 ????）"""
    msg = json.dumps(obj, ensure_ascii=False)
    raw = f"Content-Length: {len(msg.encode('utf-8'))}\\r\\n\\r\\n{msg}".encode("utf-8")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def read_json() -> dict | None:
    """
    读取并解析 MCP JSON-RPC 消息。
    用 buffer 按字节读取，避免 text-mode 下 read(n) 读的是字符而非字节的问题。
    """
    # 读原始字节，自行解析 Content-Length 头
    buf = sys.stdin.buffer

    # 读取头部直到空行
    headers = b""
    while True:
        chunk = buf.readline()
        if not chunk:
            return None  # EOF
        headers += chunk
        if chunk in (b"\r\n", b"\n", b"\r"):
            break

    # 解析 Content-Length
    length = 0
    for header_line in headers.split(b"\r\n"):
        header_line = header_line.strip()
        if header_line.lower().startswith(b"content-length:"):
            length = int(header_line.split(b":")[1].strip())
            break

    if length <= 0:
        return None

    # 按字节精确读取 body
    raw_bytes = buf.read(length)
    if not raw_bytes:
        return None

    raw = raw_bytes.decode("utf-8")
    return json.loads(raw) if raw else None


# ── 处理函数 ──


def handle_tool(name: str, args: dict) -> dict:
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
                f"| 项目 | {r.get('project', '')} |\n"
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
        text = f"## 📊 知识库统计\n\n"
        text += f"**总用例数**: {stats_data['total']}\n\n"
        if stats_data.get("modules"):
            text += "### 📁 按模块\n\n"
            for mod, count in sorted(stats_data["modules"].items(), key=lambda x: -x[1]):
                text += f"- {mod}: {count} 条\n"
        if stats_data.get("priorities"):
            text += "\n### 🔴 按优先级\n\n"
            for p, count in sorted(stats_data["priorities"].items()):
                text += f"- {p}: {count} 条\n"
        if stats_data.get("categories"):
            text += "\n### 📂 按类别\n\n"
            for c, count in sorted(stats_data["categories"].items(), key=lambda x: -x[1]):
                text += f"- {c}: {count} 条\n"
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

    elif name == "tc_add":
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
                    + f"\n可用 tc_get 传入 ID `{tc.id}` 查看详情"
                ),
            }]
        }

    elif name == "tc_add_batch":
        raw_cases = args.get("cases", [])
        if not isinstance(raw_cases, list) or not raw_cases:
            return {"content": [{"type": "text", "text": "❌ cases 必须是数组，且至少包含一条用例"}]}
        added = []
        errors = []
        for i, c in enumerate(raw_cases):
            try:
                if not isinstance(c, dict):
                    errors.append(f"第 {i+1} 条：参数格式错误")
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
        if added:
            mods = Counter(tc.module for tc in added)
            summary += "\n\n**按模块分布:**\n"
            for mod, count in mods.most_common():
                summary += f"- {mod}: {count} 条\n"
            summary += "\n**新增用例 ID:**\n"
            for tc in added[:10]:
                summary += f"- `{tc.id}` — {tc.title}\n"
            if len(added) > 10:
                summary += f"  ... 还有 {len(added) - 10} 条\n"
        return {"content": [{"type": "text", "text": summary}]}

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

    else:
        return {"content": [{"type": "text", "text": f"未知工具: {name}"}]}


# ── 主循环 ──


def main():
    while True:
        try:
            msg = read_json()
        except Exception:
            continue
        if msg is None:
            break

        msg_id = msg.get("id")
        method = msg.get("method")

        if method == "initialize":
            send_json({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "testcase-rag-mcp", "version": "2.0.0"},
                },
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send_json({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = msg.get("params", {}).get("name", "")
            args = msg.get("params", {}).get("arguments", {})
            result = handle_tool(name, args)
            send_json({"jsonrpc": "2.0", "id": msg_id, "result": result})
        elif method == "ping":
            send_json({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        else:
            send_json({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"不支持的方法: {method}"},
            })


if __name__ == "__main__":
    main()
