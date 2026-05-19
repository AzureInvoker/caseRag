"""验证数据库状态和搜索效果"""
import sys, json
sys.path.insert(0, '/home/admin/testcase-rag/server')
import importlib
engine = importlib.import_module('engine').get_engine()

# 统计
all_docs = engine.collection.get()
print(f'✅ 总用例数: {len(all_docs["ids"])}')
modules = {}
for meta in all_docs['metadatas']:
    m = meta.get('module','')
    modules[m] = modules.get(m, 0) + 1
print(f'📋 模块数: {len(modules)}')
print('模块分布:')
for m in sorted(modules, key=lambda x: -modules[x]):
    print(f'  {m}: {modules[m]}')

# 项目类型
project_types = set(meta.get('project','') for meta in all_docs['metadatas'])
print(f'📋 项目类型: {project_types}')

# 获取 types 详情
types_list = engine.get_project_types()
print(f'📋 get_project_types(): {types_list}')

# 搜索测试
print()
print('═'*60)
print('🔍 搜索效果验证')
print('═'*60)

tests = [
    ('密码输了太多次怎么办', '安全登录-锁定'),
    ('钱不够怎么支付', '余额不足'),
    ('购物车商品删除了', '购物车删除'),
    ('订单不想要了取消', '取消订单'),
    ('搜索不到东西', '无结果搜索'),
    ('支付超时了', '支付超时'),
    ('恶意代码注入', 'XSS/注入安全'),
    ('API限流频率限制', 'API限流'),
    ('多端登录同步', '多端同步'),
    ('秒杀抢购超卖', '秒杀并发'),
    ('优惠券怎么用', '优惠券'),
    ('发票怎么开', '发票'),
    ('地址怎么改', '地址管理'),
    ('注册密码太简单', '密码强度'),
    ('退款流程', '退款'),
]

for query, tag in tests:
    try:
        results = engine.search(query, n_results=5)
        if results:
            titles = [r['title'][:35] for r in results]
            print(f'\n  ✨ [{tag}]')
            print(f'    查: {query}')
            print(f'    得: {json.dumps(titles, ensure_ascii=False)}')
        else:
            print(f'\n  ❌ [{tag}] 查: {query} → 无结果')
    except Exception as e:
        print(f'\n  ❌ [{tag}] 查: {query} → 出错: {e}')
