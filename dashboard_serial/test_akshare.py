#!/usr/bin/env python3
"""测试akshare功能"""
import akshare as ak

print("=== 测试akshare功能 ===")
print(f"akshare版本: {ak.__version__}")
print()

# 测试1：简单的A股数据
print("测试1：获取A股数据")
try:
    df = ak.stock_zh_a_spot_em()
    print(f"✅ 成功获取A股数据，共 {len(df)} 只股票")
    print("前3只股票:")
    print(df.head(3))
    print()
except Exception as e:
    print(f"❌ A股数据获取失败: {e}")
    print()

# 测试2：概念板块数据
print("测试2：获取概念板块数据")
try:
    boards = ak.stock_board_concept_name_em()
    print(f"✅ 成功找到 {len(boards)} 个概念板块")
    print("前3个板块:")
    print(boards.head(3))
    print()

    if len(boards) > 0:
        # 测试获取第一个板块的成分股
        first_board = boards.iloc[0]['板块名称']
        print(f"测试3：获取 '{first_board}' 的成分股")
        stocks = ak.stock_board_concept_cons_em(symbol=first_board)
        print(f"✅ 成功找到 {len(stocks)} 个成分股")
        print("前3个成分股:")
        print(stocks.head(3))
        print()

        # 测试排序获取前2个
        top_stocks = stocks.sort_values('涨跌幅', ascending=False).head(2)
        print("涨跌幅最高的2个股:")
        print(top_stocks[['名称', '涨跌幅']])

except Exception as e:
    print(f"❌ 概念板块数据获取失败: {e}")
    print("提示: 东方财富服务器可能暂时不可用")

print()
print("=== 测试完成 ===")