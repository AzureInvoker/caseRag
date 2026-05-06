# TestCase RAG — 测试用例知识库

结构化存储 + 语义检索的测试用例知识库。支持 **REST API** 程序化管理和 **MCP 协议** AI 检索。

---

## 架构

```
┌──────────────────────────────────────┐
│   REST API (FastAPI :8765)           │ ← 程序化插入/检索/管理
├──────────────────────────────────────┤
│   MCP Server (stdio)                  │ ← AI 工具检索 (tc_search 等)
├──────────────────────────────────────┤
│   ChromaDB (向量库)                    │ ← 语义搜索
├──────────────────────────────────────┤
│   sentence-transformers (嵌入模型)     │ ← all-MiniLM-L6-v2
└──────────────────────────────────────┘
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
./run.sh api:bg

# 填充示例数据
./run.sh seed

# 运行 MCP 测试
./run.sh mcp:test

# 完整演示
./run.sh demo
```

## REST API

服务默认运行在 `http://localhost:8765`，Swagger 文档访问 `http://localhost:8765/docs`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/cases` | 添加单条用例 |
| `POST` | `/api/v1/cases/batch` | 批量添加 |
| `GET` | `/api/v1/cases` | 列表（支持筛选+分页） |
| `GET` | `/api/v1/cases/{id}` | 获取单条详情 |
| `DELETE` | `/api/v1/cases/{id}` | 删除单条 |
| `DELETE` | `/api/v1/cases` | 按条件批量删除 |
| `POST` | `/api/v1/search` | 语义搜索 |
| `GET` | `/api/v1/stats` | 统计信息 |
| `GET` | `/api/v1/health` | 健康检查 |

### 添加用例

```bash
curl -X POST http://localhost:8765/api/v1/cases \
  -H "Content-Type: application/json" \
  -d '{
    "title": "用户登录-正确账号密码登录",
    "module": "登录",
    "priority": "P0",
    "category": "功能测试",
    "preconditions": "已注册账号",
    "steps": ["输入用户名", "输入密码", "点击登录"],
    "expected": "登录成功，跳转到首页",
    "tags": ["登录", "冒烟测试"],
    "project": "电商平台"
  }'
```

### 批量添加

```bash
curl -X POST http://localhost:8765/api/v1/cases/batch \
  -H "Content-Type: application/json" \
  -d '{
    "cases": [
      {"title": "用例1", "module": "登录", "steps": ["step"], "expected": "ok"},
      {"title": "用例2", "module": "支付", "steps": ["step"], "expected": "ok"}
    ]
  }'
```

### 语义搜索

```bash
curl -X POST http://localhost:8765/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "登录失败怎么办", "n_results": 5}'
```

支持筛选参数：
- `module` — 按模块（登录/支付/搜索...）
- `priority` — 按优先级（P0/P1/P2/P3）
- `category` — 按类别（功能测试/安全测试/性能测试）

## MCP 协议

供 Claude Code、Cursor、Cline 等 AI 工具检索测试用例。

### 使用方式

```bash
# Claude Code
claude --mcp "python3 /home/admin/testcase-rag/mcp/server.py"

# 或配置文件 ~/.claude/settings.json
{
  "mcpServers": {
    "testcase-rag": {
      "command": "python3",
      "args": ["/home/admin/testcase-rag/mcp/server.py"]
    }
  }
}

# Cursor → Settings → MCP → Add:
#   Name: testcase-rag
#   Type: command
#   Command: python3 /home/admin/testcase-rag/mcp/server.py
```

### MCP 工具

| 工具名 | 说明 |
|--------|------|
| `tc_search` | 语义搜索测试用例（支持模块/优先级/类别筛选） |
| `tc_list` | 列出用例（支持筛选+分页） |
| `tc_get` | 按 ID 获取完整内容 |
| `tc_stats` | 知识库统计信息 |

## 数据模型

```python
TestCase:
  id: str             # 自动生成的唯一 ID
  title: str          # 用例标题
  module: str         # 模块名（如 登录/支付/搜索）
  priority: str       # P0/P1/P2/P3
  category: str       # 功能测试/性能测试/安全测试/回归测试
  preconditions: str  # 前置条件
  steps: list[str]    # 测试步骤
  expected: str       # 预期结果
  tags: list[str]     # 标签
  project: str        # 所属项目
  creator: str        # 创建人
  created_at: str     # 创建时间
```

## 管理命令

```bash
./run.sh api          # 前台启动 API
./run.sh api:bg       # 后台启动 API
./run.sh mcp          # 启动 MCP Server
./run.sh seed         # 填充示例数据
./run.sh stop         # 停止 API
./run.sh mcp:test     # 测试 MCP
./run.sh api:test     # 测试 API
./run.sh demo         # 全链路演示
```

## 项目结构

```
testcase-rag/
├── server/
│   ├── api.py            # FastAPI REST API
│   └── engine.py         # ChromaDB 引擎 + 数据模型
├── mcp/
│   └── server.py         # MCP Server
├── scripts/
│   ├── seed_data.py      # 示例数据填充
│   └── test_mcp_file.py  # MCP 测试脚本
├── .chroma_db/           # ChromaDB 向量库（自动生成）
├── requirements.txt      # Python 依赖
└── run.sh                # 管理脚本
```
