"""深入搜索质量评估"""
import sys
sys.path.insert(0, '/home/admin/testcase-rag/server')
import importlib, json
from collections import Counter

engine = importlib.import_module('engine').get_engine()

# 精确匹配搜索评估
print("=" * 70)
print("📊 搜索质量评估报告")
print("=" * 70)

tests = [
    # (query, 期望命中的用例标题关键词, 评分依据)
    ("密码输了太多次怎么办", "账户锁定", "语义搜索"),
    ("钱不够怎么支付", "余额不足场景", "语义搜索"),
    ("购物车商品删除了", "删除商品", "精确搜索"),
    ("订单不想要了取消", "取消未支付", "精确搜索"),
    ("搜索不到东西", "无结果提示", "语义搜索"),
    ("支付超时了", "支付超时订单", "精确搜索"),
    ("恶意代码注入", "特殊字符处理", "语义搜索"),
    ("API限流频率限制", "Rate Limiting", "精确搜索"),
    ("多端登录同步", "移动端登录态同步", "精确搜索"),
    ("秒杀抢购超卖", "秒杀", "语义搜索"),
    ("优惠券怎么用", "优惠券-领取与过期", "精确搜索"),
    ("发票怎么开", "发票信息填写", "语义搜索"),
    ("地址怎么改", "修改收货地址", "精确搜索"),
    ("注册密码太简单", "密码强度校验", "语义搜索"),
    ("退款流程", "申请退款", "语义搜索"),
    ("重新登录", "登录", "精确搜索"),
    ("验证码收不到", "验证码", "语义搜索"),
    ("下单后改地址", "修改收货地址", "语义搜索"),
    ("库存不足加购物车", "库存不足", "精确搜索"),
    ("收藏商品", "收藏", "精确搜索"),
]

hit_count = 0
partial_count = 0
miss_count = 0

for query, expected, stype in tests:
    results = engine.search(query, n_results=5)
    titles = [r['title'] for r in results]
    hit = any(expected in t for t in titles)
    partial = any(expected[:4] in t for t in titles) if not hit else False
    
    status = "✅" if hit else ("🔶" if partial else "❌")
    if hit: hit_count += 1
    elif partial: partial_count += 1
    else: miss_count += 1
    
    print(f"\n{status} [{stype}] {query}")
    print(f"   期望命中: {expected}")
    print(f"   实际: {[t[:30] for t in titles[:3]]}")

print(f"\n{'='*70}")
total = hit_count + partial_count + miss_count
print(f"📈 总评分:")
print(f"   ✅ 准确命中: {hit_count}/{total} ({hit_count/total*100:.0f}%)")
print(f"   🔶 部分相关: {partial_count}/{total} ({partial_count/total*100:.0f}%)")
print(f"   ❌ 完全丢失: {miss_count}/{total} ({miss_count/total*100:.0f}%)")
print(f"   🎯 有效命中率: {(hit_count+partial_count)/total*100:.0f}%")

print(f"\n{'='*70}")
print(f"🔧 识别到的核心问题:")
print(f"   1. 当前模型为 all-MiniLM-L6-v2（纯英文模型）")
print(f"      → 对中文语义理解本质上是噪声，靠 BM25 关键词兜底")
print(f"   2. 专用中文模型 bge-small-zh-v1.5 可将中文命中率大幅提升")
print(f"      → 详见 skills/devops/testcase-rag-knowledge-base 说明书")
print(f"   3. 数据量 58 条偏少，建议扩充到200条以上以获得更稳定的搜索结果")
