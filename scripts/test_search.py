"""
搜索引擎效果验证
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from engine import get_engine

engine = get_engine()

queries = [
    # 语义搜索: 自然语言描述
    ("密码输了太多次", "→ 期望命中: 登录-密码连续错误5次锁定"),
    ("钱不够怎么支付", "→ 期望命中: 支付失败-余额不足"),
    ("网络不好时支付会怎样", "→ 期望命中: 支付-弱网环境支付超时"),
    ("搜东西搜不到", "→ 期望命中: 搜索-无结果场景"),

    # 精确术语: 专有名词
    ("SQL注入", "→ 期望命中: 登录-SQL注入尝试"),
    ("XSS", "→ 期望命中: 登录-XSS脚本注入"),
    ("Token过期", "→ 期望命中: 登录-Token过期自动跳转"),
    ("跨浏览器", "→ 期望命中: 登录-跨浏览器兼容"),

    # 场景描述
    ("上传病毒文件", "→ 期望命中: 上传-病毒文件扫描"),
    ("购物车是空的", "→ 期望命中: 购物车-清空购物车"),
    ("文件太大超过限制", "→ 期望命中: 上传-文件大小限制"),
    ("库存不够买不了", "→ 期望命中: 购物车-商品库存不足"),

    # 边界/异常
    ("空格搜索", "→ 期望命中: 搜索-空关键词查询"),
    ("特殊字符搜索", "→ 期望命中: 搜索-特殊字符处理"),
    ("支付金额为0", "→ 期望命中: 支付-金额边界值测试"),
]

print('=' * 70)
print(f' 混合搜索效果验证 (bge-small-zh-v1.5 + BM25)')
print(f' 向量权重: 0.6 | BM25权重: 0.4')
print('=' * 70)

for query, hint in queries:
    results = engine.search(query, n_results=3)
    print(f'\n🔍 "{query}"')
    print(f'   {hint}')
    if results:
        for r in results:
            bar = '█' * int(r['score'] * 20) + '░' * (20 - int(r['score'] * 20))
            print(f'   [{bar}] {r["score"]:.3f}  {r["title"]}  ({r["module"]})')
    else:
        print('   (无结果)')

# 再试一个跨模块区分的场景 - 验证不同模块的区分度
print('\n\n' + '=' * 70)
print(' 区分度测试: 搜「支付」时不应混入大量搜索/登录结果')
print('=' * 70)
results = engine.search('支付', n_results=8)
for r in results:
    print(f'   [{r["score"]:.3f}] {r["title"]}  ({r["module"]})')
