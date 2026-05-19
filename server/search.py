"""
SearchRouter — 统一检索入口

三种模式：
  chroma: 只走 ChromaDB + BM25（现有方式）
  graph:  只走 LightRAG 知识图谱
  auto:   先走向量，再用图谱增强（如果两者都可用）
"""

import logging
from typing import Optional

logger = logging.getLogger("search_router")


class SearchRouter:
    """融合 ChromaDB 和 LightRAG 的检索路由"""

    def __init__(self, vector_engine, lightrag_engine):
        """
        vector_engine:   VectorEngine 实例
        lightrag_engine: LightRAGEngine 实例
        """
        self.vec = vector_engine
        self.lr = lightrag_engine

    def search(self, query: str, n_results: int = 5,
               module: str = None, priority: str = None,
               category: str = None, sub_module: str = None,
               mode: str = "auto") -> dict:
        """
        统一检索入口。

        返回: {
          mode: str,             # 实际使用的模式
          results: [list[dict]], # 命中的用例列表（同现有格式）
          graph_hits: {...},     # LightRAG 图谱命中（graph/auto 模式）
          total: int,
        }
        """
        if mode == "chroma":
            return self._chroma_only(query, n_results, module, priority, category, sub_module)

        if mode == "graph":
            return self._graph_only(query, n_results)

        # auto: 两路并行
        chroma_results = self.vec.search(query, n_results, module, priority, category, sub_module)
        graph_result = self.lr.search(query, n_results) if self.lr.is_available() else {"ok": False}

        if not graph_result.get("ok"):
            return {
                "mode": "chroma",
                "results": chroma_results,
                "graph_hits": None,
                "total": len(chroma_results),
            }

        # 如果有图谱结果，附加到输出
        return {
            "mode": "auto",
            "results": chroma_results,
            "graph_hits": {
                "entities": graph_result.get("entities", []),
                "relationships": graph_result.get("relationships", []),
                "chunks": graph_result.get("chunks", []),
            },
            "total": len(chroma_results),
        }

    def _chroma_only(self, query, n_results, module, priority, category, sub_module):
        results = self.vec.search(query, n_results, module, priority, category, sub_module)
        return {
            "mode": "chroma",
            "results": results,
            "graph_hits": None,
            "total": len(results),
        }

    def _graph_only(self, query, n_results):
        graph_result = self.lr.search(query, n_results)
        if not graph_result.get("ok"):
            return {
                "mode": "graph",
                "results": [],
                "graph_hits": None,
                "total": 0,
                "error": graph_result.get("message", "图谱检索失败"),
            }
        return {
            "mode": "graph",
            "results": [],
            "graph_hits": {
                "entities": graph_result.get("entities", []),
                "relationships": graph_result.get("relationships", []),
                "chunks": graph_result.get("chunks", []),
            },
            "total": 0,
        }
