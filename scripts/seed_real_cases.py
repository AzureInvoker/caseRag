"""
录入真实测试用例集（来源：博客园/测试窝/softtest）
覆盖登录、支付、搜索、购物车、文件上传五大模块
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine import TestCase, get_engine, EMBED_MODEL

engine = get_engine()
print(f'嵌入模型: {EMBED_MODEL}')

def tc(**kw):
    return TestCase(**kw)

cases = []

# 登录模块
cases += [
    tc(title='登录成功-正确用户名密码', module='登录', priority='P0',
       category='功能测试', preconditions='用户已注册且账号状态正常',
       steps=['打开登录页面', '输入正确的用户名', '输入正确的密码', '点击登录按钮'],
       expected='登录成功，跳转到首页，显示用户昵称',
       tags=['登录', '正向', '核心流程']),

    tc(title='登录失败-密码错误', module='登录', priority='P1',
       category='功能测试', preconditions='用户已注册',
       steps=['打开登录页面', '输入正确的用户名', '输入错误的密码', '点击登录按钮'],
       expected='提示「用户名或密码错误」，登录失败，不跳转',
       tags=['登录', '异常', '密码']),

    tc(title='登录失败-用户名不存在', module='登录', priority='P1',
       category='功能测试', preconditions='无',
       steps=['打开登录页面', '输入不存在的用户名', '输入任意密码', '点击登录按钮'],
       expected='提示「用户名或密码错误」，不暴露用户是否存在',
       tags=['登录', '异常', '安全']),

    tc(title='登录-密码连续错误5次锁定', module='登录', priority='P2',
       category='安全测试', preconditions='用户已注册',
       steps=['连续5次输入错误密码', '第6次输入正确密码', '点击登录按钮'],
       expected='提示「账户已被锁定，请15分钟后重试」或通过验证码解锁',
       tags=['登录', '安全', '锁定', '暴力破解']),

    tc(title='登录-空用户名或密码提交', module='登录', priority='P2',
       category='功能测试', preconditions='无',
       steps=['打开登录页面', '用户名或密码留空', '点击登录按钮'],
       expected='按钮置灰或提示「请输入用户名/密码」，不允许提交',
       tags=['登录', '边界', '输入校验']),

    tc(title='登录-SQL注入尝试', module='登录', priority='P1',
       category='安全测试', preconditions='无',
       steps=["在用户名输入框输入 ' OR 1=1 --", '密码输入任意值', '点击登录按钮'],
       expected='登录失败，系统未将SQL注入当作有效凭证',
       tags=['登录', '安全', 'SQL注入']),

    tc(title='登录-XSS脚本注入', module='登录', priority='P2',
       category='安全测试', preconditions='无',
       steps=["用户名输入 <script>alert('xss')</script>", '点击登录'],
       expected='输入被转义或过滤，不执行脚本，不弹窗',
       tags=['登录', '安全', 'XSS']),

    tc(title='登录-跨浏览器兼容', module='登录', priority='P3',
       category='兼容性测试', preconditions='各浏览器已安装',
       steps=['分别在Chrome/Firefox/Edge/Safari中打开登录页', '执行完整登录流程'],
       expected='各浏览器下登录功能正常，UI布局无错乱',
       tags=['登录', '兼容性', '跨浏览器']),

    tc(title='登录-Token过期自动跳转', module='登录', priority='P1',
       category='功能测试', preconditions='用户已登录且有有效Token',
       steps=['等待Token过期', '发起需要认证的API请求'],
       expected='自动跳转到登录页面，原操作需要重新登录后继续',
       tags=['登录', 'Token', '会话']),
]

# 支付模块
cases += [
    tc(title='支付成功-余额充足', module='支付', priority='P0',
       category='功能测试', preconditions='用户已登录，账户余额充足，有可支付订单',
       steps=['进入支付页面', '选择余额支付', '确认支付', '输入支付密码'],
       expected='支付成功，余额扣除正确，订单状态变为已支付',
       tags=['支付', '正向', '核心流程']),

    tc(title='支付失败-余额不足', module='支付', priority='P1',
       category='功能测试', preconditions='用户已登录，账户余额不足',
       steps=['进入支付页面', '选择余额支付', '确认支付'],
       expected='提示「余额不足，请选择其他支付方式」，不扣款',
       tags=['支付', '异常', '余额']),

    tc(title='支付-金额边界值测试', module='支付', priority='P1',
       category='功能测试', preconditions='用户已登录',
       steps=['输入支付金额为0.01', '输入支付金额为999999.99',
              '输入支付金额为0', '输入支付金额为负数'],
       expected='0.01和999999.99可正常支付；0和负数提示金额不合法',
       tags=['支付', '边界', '金额']),

    tc(title='支付-第三方支付取消', module='支付', priority='P2',
       category='功能测试', preconditions='用户已登录，已安装微信/支付宝',
       steps=['在支付页面选择微信支付', '跳转到微信后点击取消支付'],
       expected='返回订单页面，订单状态为未支付，不扣款',
       tags=['支付', '第三方', '取消']),

    tc(title='支付-重复提交防重', module='支付', priority='P1',
       category='功能测试', preconditions='用户已登录，余额充足',
       steps=['点击支付按钮后快速连续点击多次', '观察支付结果'],
       expected='只发起一次支付请求，不会重复扣款',
       tags=['支付', '防重复', '幂等']),

    tc(title='支付-订单已取消后支付', module='支付', priority='P2',
       category='异常测试', preconditions='订单已被取消',
       steps=['对已取消的订单发起支付'],
       expected='提示「订单已取消，无法支付」，不扣款',
       tags=['支付', '异常', '订单状态']),

    tc(title='支付-弱网环境支付超时', module='支付', priority='P2',
       category='性能测试', preconditions='用户已登录，网络设置为弱网模式（3G模拟）',
       steps=['在弱网下发起支付', '等待支付结果回调超时'],
       expected='显示「支付处理中」状态，避免重复支付；网络恢复后最终结果同步',
       tags=['支付', '弱网', '超时']),

    tc(title='支付-修改支付金额安全校验', module='支付', priority='P1',
       category='安全测试', preconditions='使用抓包工具（如Charles）',
       steps=['正常发起支付请求', '用抓包工具拦截请求修改支付金额', '放行修改后的请求'],
       expected='服务端校验签名失败或金额不一致，拒绝支付',
       tags=['支付', '安全', '金额篡改']),

    tc(title='支付-支付密码错误', module='支付', priority='P1',
       category='功能测试', preconditions='用户已登录，余额充足',
       steps=['选择支付方式', '确认支付', '输入错误的支付密码'],
       expected='提示「支付密码错误」，允许重新输入，不超过3次',
       tags=['支付', '异常', '密码']),
]

# 搜索模块
cases += [
    tc(title='搜索-模糊匹配查询', module='搜索', priority='P0',
       category='功能测试', preconditions='数据库中有包含关键词的商品数据',
       steps=['在搜索框输入部分关键词', '点击搜索或按回车'],
       expected='返回包含该关键词的所有相关结果，支持模糊匹配',
       tags=['搜索', '功能', '模糊搜索']),

    tc(title='搜索-精确匹配查询', module='搜索', priority='P1',
       category='功能测试', preconditions='数据库中有精确匹配的商品',
       steps=['在搜索框输入完整商品名称', '点击搜索'],
       expected='精确匹配的结果排在最前面',
       tags=['搜索', '功能', '精确匹配']),

    tc(title='搜索-空关键词查询', module='搜索', priority='P2',
       category='功能测试', preconditions='无',
       steps=['搜索框留空', '点击搜索按钮'],
       expected='提示「请输入搜索关键词」或返回默认推荐列表',
       tags=['搜索', '边界', '空值']),

    tc(title='搜索-超长关键词', module='搜索', priority='P2',
       category='功能测试', preconditions='无',
       steps=['输入超过允许长度（如500字）的文本', '点击搜索'],
       expected='系统截取合法长度进行搜索或提示关键词过长',
       tags=['搜索', '边界', '超长']),

    tc(title='搜索-特殊字符处理', module='搜索', priority='P2',
       category='安全测试', preconditions='无',
       steps=['输入 % _ \\\\ \\\' " < > 等特殊字符', '点击搜索'],
       expected='特殊字符被正确转义或过滤，不报错不崩溃',
       tags=['搜索', '安全', '特殊字符']),

    tc(title='搜索-中英文混合查询', module='搜索', priority='P2',
       category='功能测试', preconditions='数据库中有中英文混合的商品名',
       steps=['输入中英文混合关键词如 iPhone 手机壳', '点击搜索'],
       expected='返回包含中英文的准确结果',
       tags=['搜索', '功能', '中英文']),

    tc(title='搜索-无结果场景', module='搜索', priority='P2',
       category='功能测试', preconditions='数据库中没有匹配数据',
       steps=['输入不可能存在的数据如 asdfghjkl123', '点击搜索'],
       expected='显示「未找到相关结果」及推荐/热门词条',
       tags=['搜索', '功能', '无结果']),

    tc(title='搜索-搜索结果分页', module='搜索', priority='P2',
       category='功能测试', preconditions='数据库中有大量匹配数据（超过一页）',
       steps=['搜索关键词获得多页结果', '点击第2页/下一页'],
       expected='分页正常，翻页后数据不重复不遗漏',
       tags=['搜索', '分页', '功能']),

    tc(title='搜索-空格分隔多关键词', module='搜索', priority='P2',
       category='功能测试', preconditions='数据库中有多个关键词匹配的商品',
       steps=['输入多个关键词以空格分隔', '点击搜索'],
       expected='返回同时包含多个关键词的结果，默认AND逻辑',
       tags=['搜索', '功能', '多关键词']),
]

# 购物车模块
cases += [
    tc(title='购物车-添加商品成功', module='购物车', priority='P0',
       category='功能测试', preconditions='用户已登录，商品状态为在售',
       steps=['打开商品详情页', '点击加入购物车'],
       expected='购物车数量+1，弹出「已加入购物车」提示',
       tags=['购物车', '正向', '添加']),

    tc(title='购物车-未登录加入购物车', module='购物车', priority='P1',
       category='功能测试', preconditions='用户未登录',
       steps=['未登录状态下点击加入购物车'],
       expected='跳转到登录页面，登录成功后购物车保持该商品',
       tags=['购物车', '登录', '跳转']),

    tc(title='购物车-商品数量修改', module='购物车', priority='P1',
       category='功能测试', preconditions='购物车中已有商品',
       steps=['在购物车页面修改商品数量为2', '点击更新'],
       expected='小计金额正确更新为单价x数量',
       tags=['购物车', '功能', '数量']),

    tc(title='购物车-商品库存不足', module='购物车', priority='P1',
       category='功能测试', preconditions='商品库存仅剩1件',
       steps=['将商品数量修改为5', '点击更新'],
       expected='提示「库存不足，最多可购买1件」，数量自动调整为库存上限',
       tags=['购物车', '异常', '库存']),

    tc(title='购物车-删除商品', module='购物车', priority='P1',
       category='功能测试', preconditions='购物车中至少有一件商品',
       steps=['点击商品后的删除按钮'],
       expected='商品从购物车中移除，购物车总数和金额重新计算',
       tags=['购物车', '功能', '删除']),

    tc(title='购物车-全选计算总价', module='购物车', priority='P1',
       category='功能测试', preconditions='购物车中有多件商品',
       steps=['勾选/取消全选复选框'],
       expected='全选时所有商品选中，总价=全部选中商品之和；取消全选时总价归零',
       tags=['购物车', '功能', '全选']),

    tc(title='购物车-商品下架后状态', module='购物车', priority='P2',
       category='功能测试', preconditions='购物车中某商品已被下架',
       steps=['打开购物车页面'],
       expected='下架商品显示「已下架」或「失效」，不可选中且不参与结算',
       tags=['购物车', '异常', '下架']),

    tc(title='购物车-清空购物车', module='购物车', priority='P2',
       category='功能测试', preconditions='购物车中有商品',
       steps=['点击清空购物车按钮', '在确认弹窗中点击确认'],
       expected='购物车中所有商品被清空，显示「购物车是空的」',
       tags=['购物车', '功能', '清空']),
]

# 文件上传模块
cases += [
    tc(title='上传-图片格式校验', module='文件上传', priority='P1',
       category='功能测试', preconditions='准备JPG/PNG/GIF/BMP/WEBP格式图片各一张',
       steps=['分别上传各格式图片'],
       expected='JPG/PNG/GIF/WEBP上传成功，BMP提示格式不支持',
       tags=['上传', '格式', '图片']),

    tc(title='上传-文件大小限制', module='文件上传', priority='P1',
       category='功能测试', preconditions='准备小于1MB和大于10MB的文件各一个',
       steps=['先上传小于1MB的文件', '再上传大于10MB的文件'],
       expected='小文件上传成功，大文件提示「文件大小超过限制」',
       tags=['上传', '边界', '大小']),

    tc(title='上传-文件名特殊字符', module='文件上传', priority='P2',
       category='安全测试', preconditions='准备文件名含特殊字符的文件',
       steps=["上传文件名为 test's#1&2@3!.jpg 的文件"],
       expected='上传成功，文件名被正确转义或重命名，无报错',
       tags=['上传', '安全', '文件名']),

    tc(title='上传-同时上传多个文件', module='文件上传', priority='P2',
       category='功能测试', preconditions='准备多张图片',
       steps=['一次选择5个文件同时上传'],
       expected='所有文件依次上传成功，上传进度条正确显示',
       tags=['上传', '功能', '批量']),

    tc(title='上传-上传过程中断网', module='文件上传', priority='P2',
       category='异常测试', preconditions='上传进行中',
       steps=['文件上传到50%时断开网络'],
       expected='显示上传失败提示，已上传部分不保存，支持断点续传或重试',
       tags=['上传', '异常', '网络']),

    tc(title='上传-病毒文件扫描', module='文件上传', priority='P1',
       category='安全测试', preconditions='准备含病毒的测试文件（EICAR测试文件）',
       steps=['上传含病毒标记的文件'],
       expected='文件被拦截，提示「文件含安全风险，上传被拒绝」',
       tags=['上传', '安全', '病毒扫描']),

    tc(title='上传-文件重名覆盖', module='文件上传', priority='P2',
       category='功能测试', preconditions='已上传过同名文件',
       steps=['再次上传同名的文件'],
       expected='不会覆盖原文件，自动重命名或提示是否覆盖',
       tags=['上传', '功能', '重名']),

    tc(title='上传-非图片文件上传到图片区域', module='文件上传', priority='P2',
       category='功能测试', preconditions='准备一个.txt文件',
       steps=['在仅支持图片的上传区域选择.txt文件'],
       expected='文件被过滤或提示「仅支持图片格式」，不上传',
       tags=['上传', '格式', '校验']),
]

print(f'共 {len(cases)} 条用例，开始录入...')

count = engine.add_many(cases)
print(f' 成功录入 {count} 条用例')

# 验证统计
stats = engine.get_stats()
print(f'\n按模块分布:')
for mod, cnt in sorted(stats['modules'].items(), key=lambda x: -x[1]):
    print(f'   {mod}: {cnt} 条')
print(f'   总计: {stats["total"]} 条')
