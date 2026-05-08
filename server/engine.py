"""
核心引擎 — ChromaDB 向量库 + sentence-transformers 嵌入
"""

import os
import hashlib
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    from .config import get_config
except ImportError:
    from config import get_config

cfg = get_config()

DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHROMA_DIR = cfg.chroma_dir
EMBED_MODEL = cfg.embed_model

# ── 数据模型 ──


@dataclass
class TestCase:
    """测试用例数据模型"""
    id: str = ""
    title: str = ""                    # 用例标题
    module: str = ""                   # 模块名 (如: 登录、支付、搜索)
    priority: str = "P3"               # P0/P1/P2/P3
    category: str = ""                 # 功能测试/性能测试/安全测试/回归测试
    preconditions: str = ""            # 前置条件
    steps: list = field(default_factory=list)   # 测试步骤
    expected: str = ""                 # 预期结果
    tags: list = field(default_factory=list)    # 标签
    project: str = ""                  # 所属项目
    creator: str = ""                  # 创建人
    created_at: str = ""               # 创建时间

    def get_embedding_text(self) -> str:
        """生成用于向量化的文本"""
        parts = [
            f"标题: {self.title}",
            f"模块: {self.module}",
            f"优先级: {self.priority}",
            f"类别: {self.category}",
            f"前置条件: {self.preconditions}",
            f"步骤: {'; '.join(self.steps)}" if self.steps else "",
            f"预期: {self.expected}",
            f"标签: {', '.join(self.tags)}" if self.tags else "",
            f"项目: {self.project}",
        ]
        return "\n".join(p for p in parts if p)

    def gen_id(self) -> str:
        """基于内容生成唯一 ID"""
        raw = f"{self.module}:{self.title}:{self.project}:{self.created_at}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "module": self.module,
            "priority": self.priority,
            "category": self.category,
            "preconditions": self.preconditions,
            "steps": self.steps,
            "expected": self.expected,
            "tags": self.tags,
            "project": self.project,
            "creator": self.creator,
            "created_at": self.created_at,
        }


# ── 向量库引擎 ──


class VectorEngine:
    """ChromaDB 引擎，管理测试用例的向量化存储和检索"""

    def __init__(self):
        self._collection = None
        self._embedder = None

    def _lazy_init(self):
        if self._collection is not None:
            return
        import chromadb
        from sentence_transformers import SentenceTransformer

        self._embedder = SentenceTransformer(EMBED_MODEL, device="cpu")

        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._collection = client.get_or_create_collection(
            name="testcases",
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def collection(self):
        self._lazy_init()
        return self._collection

    @property
    def embedder(self):
        self._lazy_init()
        return self._embedder

    # ── 增删改 ──

    def add(self, tc: TestCase) -> str:
        """添加单条测试用例，返回 ID"""
        if not tc.id:
            tc.id = tc.gen_id()
        text = tc.get_embedding_text()
        emb = self.embedder.encode([text]).tolist()
        self.collection.add(
            ids=[tc.id],
            embeddings=emb,
            metadatas=[{
                "id": tc.id,
                "title": tc.title,
                "module": tc.module,
                "priority": tc.priority,
                "category": tc.category,
                "tags": ",".join(tc.tags),
                "project": tc.project,
                "creator": tc.creator,
                "created_at": tc.created_at,
            }],
            documents=[text],
        )
        return tc.id

    def add_many(self, cases: list[TestCase]) -> int:
        """批量添加，返回添加数量"""
        if not cases:
            return 0
        documents = []
        ids = []
        metadatas = []
        for tc in cases:
            if not tc.id:
                tc.id = tc.gen_id()
            documents.append(tc.get_embedding_text())
            ids.append(tc.id)
            metadatas.append({
                "id": tc.id,
                "title": tc.title,
                "module": tc.module,
                "priority": tc.priority,
                "category": tc.category,
                "tags": ",".join(tc.tags),
                "project": tc.project,
                "creator": tc.creator,
                "created_at": tc.created_at,
            })
        batch_size = 32
        for i in range(0, len(documents), batch_size):
            batch_texts = documents[i:i + batch_size]
            batch_emb = self.embedder.encode(batch_texts).tolist()
            self.collection.add(
                ids=ids[i:i + batch_size],
                embeddings=batch_emb,
                metadatas=metadatas[i:i + batch_size],
                documents=batch_texts,
            )
        return len(cases)

    def delete(self, case_id: str) -> bool:
        """删除指定 case"""
        try:
            self.collection.delete(ids=[case_id])
            return True
        except Exception:
            return False

    def delete_many(self, module: str = None, project: str = None) -> int:
        """按条件批量删除"""
        where = {}
        if module:
            where["module"] = module
        if project:
            where["project"] = project
        try:
            existing = self.collection.get(where=where if where else None)
            if existing["ids"]:
                self.collection.delete(ids=existing["ids"])
            return len(existing["ids"])
        except Exception:
            return 0

    # ── 检索 ──

    def search(self, query: str, n_results: int = 10,
               module: str = None, priority: str = None,
               category: str = None) -> list[dict]:
        """
        语义搜索测试用例（向量 + 关键词混合）
        返回: [{id, title, module, priority, category, tags, score, ...}]
        """
        query_emb = self.embedder.encode([query]).tolist()
        where = {}
        if module:
            where["module"] = module
        if priority:
            where["priority"] = priority
        if category:
            where["category"] = category

        results = self.collection.query(
            query_embeddings=query_emb,
            n_results=n_results * 2,
            where=where if where else None,
        )

        hits = []
        if results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                meta = results["metadatas"][0][i]
                dist = results["distances"][0][i] if results["distances"] else 0
                score = 1.0 - dist
                # 读完整内容
                doc_text = results["documents"][0][i] if results["documents"] else ""
                hits.append({
                    "id": id_,
                    "title": meta.get("title", ""),
                    "module": meta.get("module", ""),
                    "priority": meta.get("priority", ""),
                    "category": meta.get("category", ""),
                    "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                    "project": meta.get("project", ""),
                    "creator": meta.get("creator", ""),
                    "created_at": meta.get("created_at", ""),
                    "score": round(score, 4),
                    "summary": doc_text[:200] + "..." if len(doc_text) > 200 else doc_text,
                })

        # 补关键词搜索
        query_lower = query.lower()
        keyword_hits = []
        all_docs = self.collection.get()
        if all_docs["ids"]:
            for i, id_ in enumerate(all_docs["ids"]):
                meta = all_docs["metadatas"][i]
                title = meta.get("title", "").lower()
                tags = meta.get("tags", "").lower()
                module_ = meta.get("module", "").lower()
                relevance = 0
                if query_lower in title:
                    relevance += 3
                if query_lower in tags:
                    relevance += 2
                if module and query_lower in module_:
                    relevance += 2
                if relevance > 0 and id_ not in [h["id"] for h in hits]:
                    keyword_hits.append({
                        "id": id_,
                        "title": meta.get("title", ""),
                        "module": meta.get("module", ""),
                        "priority": meta.get("priority", ""),
                        "category": meta.get("category", ""),
                        "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                        "project": meta.get("project", ""),
                        "creator": meta.get("creator", ""),
                        "created_at": meta.get("created_at", ""),
                        "score": round(relevance * 0.15, 4),
                        "summary": "",
                    })

        # 合并且排序
        combined = hits + keyword_hits
        combined.sort(key=lambda x: -x["score"])
        return combined[:n_results]

    def get_by_id(self, case_id: str) -> Optional[dict]:
        """按 ID 获取单条用例"""
        results = self.collection.get(ids=[case_id])
        if not results["ids"]:
            return None
        i = 0
        meta = results["metadatas"][i] if results["metadatas"] else {}
        doc = results["documents"][i] if results["documents"] else ""
        return {
            "id": case_id,
            "title": meta.get("title", ""),
            "module": meta.get("module", ""),
            "priority": meta.get("priority", ""),
            "category": meta.get("category", ""),
            "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
            "project": meta.get("project", ""),
            "creator": meta.get("creator", ""),
            "created_at": meta.get("created_at", ""),
            "content": doc,
        }

    def get_stats(self) -> dict:
        """获取统计信息"""
        all_docs = self.collection.get()
        if not all_docs["ids"]:
            return {"total": 0, "modules": {}, "priorities": {}, "categories": {}}

        modules = {}
        priorities = {}
        categories = {}
        for meta in all_docs["metadatas"]:
            m = meta.get("module", "unknown")
            modules[m] = modules.get(m, 0) + 1
            p = meta.get("priority", "unknown")
            priorities[p] = priorities.get(p, 0) + 1
            c = meta.get("category", "unknown")
            categories[c] = categories.get(c, 0) + 1

        return {
            "total": len(all_docs["ids"]),
            "modules": modules,
            "priorities": priorities,
            "categories": categories,
        }

    def get_all(self, module: str = None, priority: str = None,
                category: str = None, offset: int = 0, limit: int = 50) -> list[dict]:
        """分页列出用例"""
        where = {}
        if module:
            where["module"] = module
        if priority:
            where["priority"] = priority
        if category:
            where["category"] = category

        results = self.collection.get(
            where=where if where else None,
            offset=offset,
            limit=limit,
        )
        items = []
        if results["ids"]:
            for i, id_ in enumerate(results["ids"]):
                meta = results["metadatas"][i]
                items.append({
                    "id": id_,
                    "title": meta.get("title", ""),
                    "module": meta.get("module", ""),
                    "priority": meta.get("priority", ""),
                    "category": meta.get("category", ""),
                    "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                    "project": meta.get("project", ""),
                })
        return items


# ── 全局单例 ──

_engine = None


def get_engine() -> VectorEngine:
    global _engine
    if _engine is None:
        _engine = VectorEngine()
    return _engine
