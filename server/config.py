"""
统一配置加载模块

优先级: 环境变量 > 配置文件 (config.yaml) > 默认值

环境变量：
  TC_API_HOST       API 监听地址 (默认 0.0.0.0)
  TC_API_PORT       API 监听端口 (默认 8765)
  TC_EMBED_MODEL    嵌入模型 (默认 all-MiniLM-L6-v2)
  TC_CHROMA_DIR     ChromaDB 目录 (默认 .chroma_db)
  TC_DATA_DIR       项目数据根目录 (默认 auto)
"""

import os
import yaml
from pathlib import Path


def _find_project_root() -> Path:
    """从当前文件位置推断项目根目录（server/config.py → 项目根）"""
    return Path(__file__).parent.parent.resolve()


def _load_config_file() -> dict:
    """从 config.yaml 加载配置"""
    config_file = _find_project_root() / "config.yaml"
    if config_file.exists():
        with open(config_file, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


_config_cache = None


class Config:
    """统一配置对象"""

    def __init__(self):
        file_config = _load_config_file()
        api_cfg = file_config.get("api", {}) if file_config else {}
        engine_cfg = file_config.get("engine", {}) if file_config else {}

        api_host = api_cfg.get("host", "0.0.0.0")
        api_port = api_cfg.get("port", 8765)

        # 环境变量覆盖
        self.api_host = os.getenv("TC_API_HOST", api_host)
        api_port_env = os.getenv("TC_API_PORT")
        self.api_port = int(api_port_env) if api_port_env else api_port
        self.embed_model = os.getenv("TC_EMBED_MODEL", engine_cfg.get("embed_model", "BAAI/bge-small-zh-v1.5"))

        chroma_dir = engine_cfg.get("chroma_dir", ".chroma_db")
        chroma_env = os.getenv("TC_CHROMA_DIR")
        if chroma_env:
            self.chroma_dir = Path(chroma_env)
        else:
            data_dir_env = os.getenv("TC_DATA_DIR")
            if data_dir_env:
                data_dir = Path(data_dir_env)
            else:
                data_dir = _find_project_root()
            self.chroma_dir = data_dir / chroma_dir


def get_config() -> Config:
    global _config_cache
    if _config_cache is None:
        _config_cache = Config()
    return _config_cache
