"""
LightRAG 知识图谱引擎 — DeepSeek/Ollama 双模式封装

支持两种 LLM 后端：
  deepseek: 通过 API 调用（推荐，建图成本极低）
  ollama:   调用本地 Ollama 实例（内网部署用）

嵌入统一使用 sentence-transformers（CPU 即可）。
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("lightrag_engine")


def _build_llm_func(provider: str, api_key: str, base_url: str, model: str):
    """
    根据 provider 返回一个兼容 LightRAG 的 llm_model_func。

    函数签名：async def llm_func(model: str, messages: list[dict], **kwargs) -> str
    """
    import httpx

    if provider == "deepseek":
        api_base = "https://api.deepseek.com/v1"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async def deepseek_llm(model: str, messages: list, **kwargs) -> str:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                **{k: v for k, v in kwargs.items() if k in ("temperature", "max_tokens")},
            }
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(f"{api_base}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]

        return deepseek_llm

    elif provider == "ollama":
        async def ollama_llm(model: str, messages: list, **kwargs) -> str:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {k: v for k, v in kwargs.items() if k in ("temperature", "num_predict")},
            }
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(f"{base_url}/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]

        return ollama_llm

    else:
        raise ValueError(f"不支持的 LLM provider: {provider}，仅支持 deepseek/ollama")


def _build_embed_func(model_name: str):
    """返回一个兼容 LightRAG 的 embedding_func

    函数签名：async def embed_func(texts: list[str]) -> list[list[float]]
    """
    from sentence_transformers import SentenceTransformer

    # 全局缓存，避免重复加载
    if not hasattr(_build_embed_func, "_model"):
        logger.info(f"加载嵌入模型: {model_name}")
        _build_embed_func._model = SentenceTransformer(model_name, device="cpu")

    model = _build_embed_func._model

    async def embed_func(texts: list[str]) -> list[list[float]]:
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    return embed_func


class LightRAGEngine:
    """LightRAG 知识图谱引擎封装"""

    def __init__(self, config):
        """
        config 需要包含：
          lightrag_enabled, lightrag_working_dir, lightrag_embed_model
          llm_provider, deepseek_api_key, ollama_base_url, llm_model
          lightrag_top_k, lightrag_mode
        """
        self.cfg = config
        self._rag = None
        self._ready = False
        self._error = None

    # ── 初始化 ──

    def _lazy_init(self):
        if self._rag is not None:
            return
        if not self.cfg.lightrag_enabled:
            self._ready = False
            self._error = "LightRAG 未启用（config.lightrag.enabled = false）"
            return

        try:
            from lightrag import LightRAG, QueryParam

            working_dir = self.cfg.lightrag_working_dir
            if not os.path.isabs(working_dir):
                # 相对路径以项目根为准
                working_dir = str(Path(__file__).parent.parent / working_dir)
            os.makedirs(working_dir, exist_ok=True)

            # LLM 函数
            llm_func = _build_llm_func(
                provider=self.cfg.llm_provider,
                api_key=self._resolve_api_key(),
                base_url=self.cfg.ollama_base_url,
                model=self.cfg.llm_model,
            )

            # 嵌入函数
            embed_func = _build_embed_func(self.cfg.lightrag_embed_model)

            self._rag = LightRAG(
                working_dir=working_dir,
                llm_model_func=llm_func,
                llm_model_name=self.cfg.llm_model,
                embedding_func=embed_func,
                chunk_token_size=1200,
                chunk_overlap_token_size=100,
                top_k=self.cfg.lightrag_top_k,
                max_parallel_insert=2,
            )

            self._QueryParam = QueryParam
            self._ready = True
            logger.info(f"LightRAG 初始化成功 (provider={self.cfg.llm_provider}, model={self.cfg.llm_model})")

        except Exception as e:
            self._ready = False
            self._error = str(e)
            logger.error(f"LightRAG 初始化失败: {e}")

    def _resolve_api_key(self) -> str:
        """解析 API Key（支持 ${ENV_VAR} 或直接明文）"""
        key = self.cfg.deepseek_api_key
        if key.startswith("${") and key.endswith("}"):
            env_name = key[2:-1]
            key = os.getenv(env_name, "")
        return key

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> Optional[str]:
        return self._error

    def is_available(self) -> bool:
        """检查 LightRAG 是否可用（配置启用 + 初始化成功）"""
        if not self.cfg.lightrag_enabled:
            return False
        self._lazy_init()
        return self._ready

    # ── 数据写入 ──

    def insert(self, texts: list[str], ids: list[str] = None) -> dict:
        """
        插入文档并建图。

        参数：
          texts: 文档文本列表
          ids:   可选的文档 ID 列表
        返回: {ok: bool, message: str, track_id: str or None}
        """
        if not self.is_available():
            return {"ok": False, "message": self._error or "LightRAG 不可用"}
        try:
            track_id = self._rag.insert(texts, ids=ids)
            return {"ok": True, "message": f"成功插入 {len(texts)} 条", "track_id": track_id}
        except Exception as e:
            logger.error(f"LightRAG insert 失败: {e}")
            return {"ok": False, "message": str(e)}

    # ── 检索 ──

    def search(self, query: str, n_results: int = 5) -> dict:
        """
        知识图谱检索（返回结构化数据，不调 LLM 生成回答）。

        返回: {
          ok: bool,
          entities: [...],      # 命中的实体
          relationships: [...], # 实体间关系
          chunks: [...],        # 相关文本片段
          message: str,
        }
        """
        if not self.is_available():
            return {"ok": False, "message": self._error or "LightRAG 不可用", "entities": [], "relationships": [], "chunks": []}

        try:
            param = self._QueryParam(
                mode=self.cfg.lightrag_mode,
                top_k=n_results * 2,
                chunk_top_k=n_results,
                only_need_context=True,
            )
            result = self._rag.query_data(query, param=param)

            if result.get("status") != "success":
                return {"ok": False, "message": result.get("message", "未知错误"), "entities": [], "relationships": [], "chunks": []}

            data = result.get("data", {})

            # 精简实体
            entities = []
            for e in data.get("entities", []):
                entities.append({
                    "name": e.get("entity_name", ""),
                    "type": e.get("entity_type", ""),
                    "description": e.get("description", ""),
                })

            # 精简关系
            relationships = []
            for r in data.get("relationships", []):
                relationships.append({
                    "source": r.get("src_id", ""),
                    "target": r.get("tgt_id", ""),
                    "description": r.get("description", ""),
                    "weight": r.get("weight", 0),
                })

            # 精简文本片段
            chunks = []
            for c in data.get("chunks", []):
                chunks.append({
                    "content": c.get("content", "")[:500],
                    "doc_id": c.get("doc_id", ""),
                })

            return {
                "ok": True,
                "message": f"找到 {len(entities)} 个实体, {len(relationships)} 条关系, {len(chunks)} 个片段",
                "entities": entities[:n_results * 2],
                "relationships": relationships[:n_results],
                "chunks": chunks[:n_results],
            }

        except Exception as e:
            logger.error(f"LightRAG search 失败: {e}")
            return {"ok": False, "message": str(e), "entities": [], "relationships": [], "chunks": []}

    def get_status(self) -> dict:
        """获取 LightRAG 状态"""
        if not self.cfg.lightrag_enabled:
            return {"enabled": False, "ready": False, "message": "未启用"}
        self._lazy_init()
        if not self._ready:
            return {"enabled": True, "ready": False, "message": self._error or "初始化失败"}
        try:
            status = self._rag.get_processing_status()
            # count entities
            graph = self._rag.get_knowledge_graph("")
            node_count = 0
            if graph:
                try:
                    node_count = len(graph.get("nodes", []))
                except Exception:
                    pass
            return {
                "enabled": True,
                "ready": True,
                "provider": self.cfg.llm_provider,
                "model": self.cfg.llm_model,
                "node_count": node_count,
                "processing_status": status,
            }
        except Exception as e:
            return {"enabled": True, "ready": True, "message": str(e)}
