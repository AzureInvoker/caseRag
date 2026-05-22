#!/usr/bin/env python3
"""从 lostcase.txt 读取 case ID，补录到 LightRAG 知识图谱。

用法:
  cd /home/admin/testcase-rag
  python scripts/repair_lightrag.py lostcase.txt

格式: lostcase.txt 每行一个 case ID（空行和 # 注释会被忽略）
"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("repair_lightrag")

# 确保能找到 server 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.api import engine, lightrag_engine


def read_ids(path: str) -> list[str]:
    """读取 lostcase.txt，返回非空、非注释的 ID 列表"""
    ids = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line)
    return ids


async def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/repair_lightrag.py <lostcase.txt>")
        sys.exit(1)

    ids = read_ids(sys.argv[1])
    if not ids:
        logger.warning("没有找到任何 case ID")
        return

    logger.info(f"共读取 {len(ids)} 个 case ID")

    # 确保 LightRAG 已初始化
    if not lightrag_engine.is_available():
        logger.error("LightRAG 不可用，请检查配置")
        sys.exit(1)

    success = 0
    failed = 0
    not_found = 0

    for i, cid in enumerate(ids):
        case = engine.get_by_id(cid)
        if not case:
            logger.warning(f"[{i+1}/{len(ids)}] ❌ 未找到: {cid}")
            not_found += 1
            continue

        text = case.get("content", "")
        if not text:
            logger.warning(f"[{i+1}/{len(ids)}] ⚠️ 内容为空: {cid}")
            not_found += 1
            continue

        result = await lightrag_engine.async_insert([text], ids=[cid])
        if result.get("ok"):
            success += 1
            if success % 10 == 0 or i == len(ids) - 1:
                logger.info(f"[{i+1}/{len(ids)}] ✅ 已补录 {success} 条...")
        else:
            logger.error(f"[{i+1}/{len(ids)}] ❌ 补录失败 {cid}: {result.get('message')}")
            failed += 1

        # 加个小间隔，避免把 DeepSeek API 打爆
        if (i + 1) % 5 == 0:
            await asyncio.sleep(0.5)

    logger.info(f"\n🎉 完成！成功 {success}，失败 {failed}，未找到 {not_found}")


if __name__ == "__main__":
    asyncio.run(main())
