"""
核心引擎 — ChromaDB 向量库 + sentence-transformers 嵌入 + BM25 混合搜索
"""

import os
import hashlib
import re
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
    project: str = ""                  # 项目类型 (如: slot游戏、后台、活动)
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

    def get_bm25_text(self) -> str:
        """生成用于 BM25 关键词搜索的文本（聚焦高信号字段）"""
        parts = [self.title, self.module]
        if self.tags:
            parts.append(", ".join(self.tags))
        if self.preconditions:
            # 前置条件取前 200 字，太多会稀释 BM25 信号
            parts.append(self.preconditions[:200])
        return " ".join(p for p in parts if p)

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
        # BM25 缓存
        self._bm25 = None
        self._bm25_metadata = None
        self._bm25_all_ids = None
        self._bm25_size = 0

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
        # 使 BM25 缓存失效
        self._bm25 = None
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
        self._bm25 = None
        return len(cases)

    def delete(self, case_id: str) -> bool:
        """删除指定 case"""
        try:
            self.collection.delete(ids=[case_id])
            self._bm25 = None
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
                self._bm25 = None
            return len(existing["ids"])
        except Exception:
            return 0

    # ── 检索 ──

    def search(self, query: str, n_results: int = 10,
               module: str = None, priority: str = None,
               category: str = None) -> list[dict]:
        """
        混合搜索测试用例（向量 0.6 + BM25 关键词 0.4）

        搜索流程：
        1. 向量搜索：用 ChromaDB 做语义匹配（generous top-K）
        2. BM25 搜索：用 jieba 分词 + rank_bm25 做关键词精确匹配
        3. 融合排序：min-max 归一化后加权合并

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
        where_clause = where if where else None

        # ── 1. 向量搜索 ──
        vec_results = self.collection.query(
            query_embeddings=query_emb,
            n_results=n_results * 3,  # generous top-K，给融合留空间
            where=where_clause,
        )

        # 构建 ID → 结果映射
        hit_map = {}
        if vec_results["ids"] and vec_results["ids"][0]:
            for i, id_ in enumerate(vec_results["ids"][0]):
                meta = vec_results["metadatas"][0][i]
                dist = vec_results["distances"][0][i]
                doc = vec_results["documents"][0][i] if vec_results["documents"] else ""
                hit_map[id_] = {
                    "meta": meta,
                    "doc": doc,
                    "vec_score": 1.0 - dist,  # cosine distance → similarity
                    "bm25_score": 0.0,
                }

        # ── 2. BM25 关键词搜索 ──
        bm25_pairs = self._bm25_search(query, where_clause=where_clause)
        for id_, bm25_score in bm25_pairs:
            if id_ in hit_map:
                hit_map[id_]["bm25_score"] = bm25_score
            else:
                # 向量没命中但 BM25 命中了（比如精确术语匹配）
                try:
                    doc_data = self.collection.get(ids=[id_])
                    if doc_data["ids"]:
                        meta = doc_data["metadatas"][0]
                        doc = doc_data["documents"][0] if doc_data["documents"] else ""
                        hit_map[id_] = {
                            "meta": meta,
                            "doc": doc,
                            "vec_score": 0.0,
                            "bm25_score": bm25_score,
                        }
                except Exception:
                    pass

        if not hit_map:
            return []

        # ── 3. 分数归一化 + 融合 ──
        bm25_all_zero = all(h["bm25_score"] == 0.0 for h in hit_map.values())
        vec_scores = [h["vec_score"] for h in hit_map.values()]
        bm25_scores = [h["bm25_score"] for h in hit_map.values()]

        if bm25_scores and not bm25_all_zero:
            vec_min, vec_max = min(vec_scores), max(vec_scores)
            bm25_min, bm25_max = min(bm25_scores), max(bm25_scores)
        else:
            vec_min, vec_max = min(vec_scores), max(vec_scores)
            bm25_min, bm25_max = 0, 1

        vec_range = vec_max - vec_min if vec_max > vec_min else 1.0
        bm25_range = bm25_max - bm25_min if bm25_max > bm25_min else 1.0

        results = []
        for id_, data in hit_map.items():
            norm_vec = (data["vec_score"] - vec_min) / vec_range
            norm_bm25 = (data["bm25_score"] - bm25_min) / bm25_range if not bm25_all_zero else 0.0

            # 融合: 向量的语义泛化能力 + BM25 的精确匹配能力
            if bm25_all_zero:
                final_score = norm_vec
            else:
                final_score = 0.6 * norm_vec + 0.4 * norm_bm25

            meta = data["meta"]
            doc_text = data["doc"]
            results.append({
                "id": id_,
                "title": meta.get("title", ""),
                "module": meta.get("module", ""),
                "priority": meta.get("priority", ""),
                "category": meta.get("category", ""),
                "tags": meta.get("tags", "").split(",") if meta.get("tags") else [],
                "project": meta.get("project", ""),
                "creator": meta.get("creator", ""),
                "created_at": meta.get("created_at", ""),
                "score": round(final_score, 4),
                "summary": doc_text[:200] + "..." if len(doc_text) > 200 else doc_text,
            })

        results.sort(key=lambda x: -x["score"])
        return results[:n_results]

    def _bm25_search(self, query: str, where_clause: dict = None) -> list[tuple[str, float]]:
        """
        BM25 关键词搜索（内部方法）

        使用 jieba 分词 + rank_bm25 对 title/tags/module 做关键词匹配。
        特别擅长捕获专有名词、模块名、按钮文本等精确匹配场景。

        返回: [(id, score), ...] 按 score 降序
        """
        import jieba

        all_docs = self.collection.get()
        if not all_docs["ids"]:
            return []

        # 检查 BM25 缓存是否有效
        current_size = len(all_docs["ids"])
        if (self._bm25 is not None and self._bm25_size == current_size
                and self._bm25_all_ids == all_docs["ids"]):
            bm25 = self._bm25
            metadata = self._bm25_metadata
            all_ids = self._bm25_all_ids
        else:
            # 重建 BM25 索引
            from rank_bm25 import BM25Okapi
            corpus = []
            for i, meta in enumerate(all_docs["metadatas"]):
                title = meta.get("title", "")
                tags = meta.get("tags", "")
                module = meta.get("module", "")
                precond = meta.get("preconditions", "")
                text = f"{title} {module} {tags}"
                tokens = jieba.lcut(text)[:200]  # 限制 token 数量防过长的文档
                corpus.append(tokens)
            bm25 = BM25Okapi(corpus)
            self._bm25 = bm25
            self._bm25_metadata = all_docs["metadatas"]
            self._bm25_all_ids = all_docs["ids"]
            self._bm25_size = current_size
            metadata = all_docs["metadatas"]
            all_ids = all_docs["ids"]

        query_tokens = jieba.lcut(query)
        if not query_tokens:
            return []

        scores = bm25.get_scores(query_tokens)

        # 应用 where 过滤 + 组装结果
        results = []
        for i in range(len(all_ids)):
            if scores[i] <= 0:
                continue
            # 应用 metadata 过滤
            if where_clause:
                skip = False
                for key, val in where_clause.items():
                    if metadata[i].get(key) != val:
                        skip = True
                        break
                if skip:
                    continue
            results.append((all_ids[i], scores[i]))

        results.sort(key=lambda x: -x[1])
        return results[:50]  # 最多返回 50 条 BM25 结果

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
