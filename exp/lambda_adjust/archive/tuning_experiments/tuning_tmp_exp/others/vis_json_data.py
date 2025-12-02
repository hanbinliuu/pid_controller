import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def visualize_pv_values(json_file_path):
    """
    从JSON文件中读取数据并可视化pv值的时间序列（仅显示线条）
    """
    # 读取JSON文件
    with open(json_file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)

    # 提取时间戳和pv值
    timestamps = []
    pv_values = []

    for record in data['data']:
        # 将时间戳转换为datetime对象
        dt = datetime.fromtimestamp(record['timestamp'] / 1000)  # 转换为秒
        timestamps.append(dt)
        pv_values.append(record['pv'])

    # 创建图表
    plt.figure(figsize=(12, 6))
    # 移除marker参数，只保留线条
    plt.plot(timestamps, pv_values, linestyle='-', linewidth=1)

    # 设置图表标题和标签
    plt.title(f'PV Values Over Time\n({data["start_time"]} to {data["end_time"]})', fontsize=14)
    plt.xlabel('Time', fontsize=12)
    plt.ylabel('PV Value', fontsize=12)

    # 格式化x轴日期显示
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.gca().xaxis.set_major_locator(mdates.SecondLocator(interval=30))  # 每30秒显示一个刻度
    plt.xticks(rotation=45)

    # 添加网格
    plt.grid(True, linestyle='--', alpha=0.6)

    # 调整布局以适应旋转的日期标签
    plt.tight_layout()

    # 显示统计信息
    print(f"数据概览:")
    print(f"- 总记录数: {len(pv_values)}")
    print(f"- PV值范围: {min(pv_values)} - {max(pv_values)}")
    print(f"- 平均PV值: {sum(pv_values) / len(pv_values):.2f}")

    # 显示图表
    plt.show()


def visualize_from_string(json_string):
    """
    直接从JSON字符串可视化数据（仅显示线条，适用于部分数据）
    """
    # 解析JSON字符串
    data = json.loads(json_string)

    # 提取时间戳和pv值
    timestamps = []
    pv_values = []

    for record in data['data']:
        # 将时间戳转换为datetime对象
        dt = datetime.fromtimestamp(record['timestamp'] / 1000)  # 转换为秒
        timestamps.append(dt)
        pv_values.append(record['pv'])

    # 创建图表
    plt.figure(figsize=(12, 6))
    # 移除marker参数，只保留线条
    plt.plot(timestamps, pv_values, linestyle='-', linewidth=1)

    # 设置图表标题和标签
    if 'start_time' in data and 'end_time' in data:
        plt.title(f'PV Values Over Time\n({data["start_time"]} to {data["end_time"]})', fontsize=14)
    else:
        plt.title('PV Values Over Time', fontsize=14)
    plt.xlabel('Time', fontsize=12)
    plt.ylabel('PV Value', fontsize=12)

    # 格式化x轴日期显示
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    if len(timestamps) > 1:
        # 自动调整刻度间隔，避免过密
        plt.gca().xaxis.set_major_locator(mdates.SecondLocator(interval=max(1, len(timestamps) // 10)))
    plt.xticks(rotation=45)

    # 添加网格
    plt.grid(True, linestyle='--', alpha=0.6)

    # 调整布局以适应旋转的日期标签
    plt.tight_layout()

    # 显示统计信息
    print(f"数据概览:")
    print(f"- 总记录数: {len(pv_values)}")
    print(f"- PV值范围: {min(pv_values)} - {max(pv_values)}")
    print(f"- 平均PV值: {sum(pv_values) / len(pv_values):.2f}")

    # 显示图表
    plt.show()


# 使用示例
if __name__ == "__main__":
    path = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/core/data_simulation/zhongkong/response_1761644174772.json'
    visualize_pv_values(path)