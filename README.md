# TestCase RAG — 测试用例知识库

结构化存储 + 语义检索的测试用例知识库。支持 **REST API** 程序化管理和 **HTTP MCP** 远程 AI 检索。

---

## 架构

```
┌──────────────────────────────────────┐
│   REST API (FastAPI :8765)           │ ← 程序化插入/检索/管理
│     /api/v1/cases ...                │
├──────────────────────────────────────┤
│   MCP over HTTP/SSE (:8765/mcp)      │ ← AI 工具远程检索
│     /mcp/sse  /mcp  /mcp/info        │
├──────────────────────────────────────┤
│   ChromaDB (向量库)                    │ ← 语义搜索
├──────────────────────────────────────┤
│   sentence-transformers (嵌入模型)     │ ← all-MiniLM-L6-v2
└──────────────────────────────────────┘
```

## 快速开始

```bash
# 1. 安装依赖
uv pip install -r requirements.txt

# 2. 启动服务（API + MCP 都在一个端口）
uv run uvicorn server.api:app --host 0.0.0.0 --port 8765 --reload

# 3. 另开终端，填充示例数据
uv run python3 scripts/seed_data.py

# 4. 打开浏览器
# http://localhost:8765/docs  — Swagger 文档
# http://localhost:8765/mcp/info  — MCP 信息
```

## 配置

支持三种配置方式（优先级从高到低）：

### 1. 环境变量

```bash
TC_API_HOST=0.0.0.0    # 监听地址
TC_API_PORT=8765        # 监听端口（API + MCP 共用）
TC_EMBED_MODEL=all-MiniLM-L6-v2  # 嵌入模型
TC_CHROMA_DIR=/path/to/chroma    # ChromaDB 目录
```

### 2. 配置文件

复制 `config.example.yaml` 为 `config.yaml` 并修改（已 `.gitignore`）：

```yaml
api:
  host: "0.0.0.0"
  port: 8765
engine:
  embed_model: "all-MiniLM-L6-v2"
  chroma_dir: ".chroma_db"
```

### 3. 默认值

不配也能直接用：`0.0.0.0:8765`

## REST API

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

## MCP（HTTP/SSE 模式）

MCP 内置在 API 服务中，**启动 API 后即可通过 HTTP 协议远程使用**，无需额外配置。

### MCP 端点

| 端点 | 说明 |
|------|------|
| `GET /mcp/info` | 服务信息 |
| `GET /mcp/sse` | SSE 流端点（MCP 标准协议） |
| `POST /mcp` | 消息端点（需带 `session_id` 参数） |

### 配置到 AI 工具

#### Cursor

Settings → MCP → Add:

| 字段 | 值 |
|------|-----|
| Name | `testcase-rag` |
| Type | `url` |
| URL | `http://your-server-ip:8765/mcp` |

#### Claude Code（开发版支持 HTTP MCP）

```bash
claude --mcp-url "http://your-server-ip:8765/mcp"
```

#### 其他 MCP 客户端

将 MCP 端点指向 `http://your-server-ip:8765/mcp` 即可。

> `your-server-ip` 替换为运行该服务的服务器 IP 地址。

### MCP 工具

| 工具名 | 说明 |
|--------|------|
| `tc_search` | 语义搜索测试用例 |
| `tc_list` | 列出用例（支持筛选+分页） |
| `tc_get` | 按 ID 获取完整内容 |
| `tc_stats` | 知识库统计信息 |

### 手工测试 MCP

```bash
# 查看 MCP 服务信息
curl http://localhost:8765/mcp/info

# 查看可用工具
curl -X POST http://localhost:8765/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# 搜索测试用例
curl -X POST http://localhost:8765/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":2,"params":{"name":"tc_search","arguments":{"query":"登录失败"}}}'
```

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

## 项目结构

```
testcase-rag/
├── server/
│   ├── api.py            # FastAPI REST API + HTTP MCP
│   ├── engine.py         # ChromaDB 引擎 + 数据模型
│   └── config.py         # 统一配置加载
├── mcp/
│   └── server.py         # stdio 模式 MCP（备用）
├── scripts/
│   ├── seed_data.py      # 示例数据填充
│   └── test_mcp_file.py  # MCP 测试脚本
├── config.example.yaml   # 配置示例
├── config.yaml           # 本地配置（不提交）
├── requirements.txt      # Python 依赖
├── .gitignore
└── README.md
```

> `mcp/server.py` 是 stdio 模式的 MCP 备用实现，供本地 AI 工具直接调用。**推荐使用 HTTP 模式的 `/mcp` 端点**，支持远程访问。
