"""
大榭现场数据可视化脚本
===================
对每个回路 (2216_LIC_50104 / 2216_LIC_50108) 绘制 PV、SV、MV 半年趋势图。
数据量大 (~3M 点)，自动降采样以加速绘图。

用法：
    python visualize_daxie_data.py
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 非交互后端，避免弹窗
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'Heiti TC', 'PingFang SC']
plt.rcParams['axes.unicode_minus'] = False

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR / "output"
DOWNSAMPLE_TARGET = 5000  # 绘图用的目标点数


def load_merged_data():
    """从 CSV 加载并合并数据（比读 JSON 快很多）"""
    file1 = DATA_DIR / "数据1.csv"
    file2 = DATA_DIR / "数据2.csv"

    print("📂 读取 CSV ...")
    df1 = pd.read_csv(file1, skiprows=[1], index_col=False, engine='c')
    df2 = pd.read_csv(file2, skiprows=[1], index_col=False, engine='c')
    df1 = df1.loc[:, ~df1.columns.str.startswith('Unnamed')]
    df2 = df2.loc[:, ~df2.columns.str.startswith('Unnamed')]

    df1['datetime'] = pd.to_datetime(df1['Test'], format='%Y/%m/%d %H:%M:%S')
    df2['datetime'] = pd.to_datetime(df2['Test'], format='%Y/%m/%d %H:%M:%S')

    # 去重叠拼接
    df1_cut = df1[df1['datetime'] < df2['datetime'].iloc[0]]
    merged = pd.concat([df1_cut, df2], ignore_index=True)
    merged['datetime'] = pd.to_datetime(merged['Test'], format='%Y/%m/%d %H:%M:%S')
    merged.sort_values('datetime', inplace=True)
    merged.drop_duplicates(subset='datetime', keep='first', inplace=True)
    merged.reset_index(drop=True, inplace=True)

    print(f"✅ 合并完成: {len(merged)} 行, {merged['datetime'].iloc[0]} ~ {merged['datetime'].iloc[-1]}")
    return merged


def downsample(df, target=DOWNSAMPLE_TARGET):
    """均匀降采样"""
    n = len(df)
    if n <= target:
        return df
    step = n // target
    return df.iloc[::step].copy()


def plot_loop(df, device, description, output_path):
    """绘制单个回路的 PV / SV / MV 趋势图"""
    pv_col = f"{device}.PV"
    sv_col = f"{device}.SV"
    mv_col = f"{device}.MV"

    ds = downsample(df)
    t = ds['datetime']
    pv = ds[pv_col].astype(float)
    sv = ds[sv_col].astype(float)
    mv = ds[mv_col].astype(float)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10), sharex=True,
                                    gridspec_kw={'height_ratios': [2, 1]})
    fig.suptitle(f'{device}  ({description})\n'
                 f'{df["datetime"].iloc[0].strftime("%Y-%m-%d")} ~ '
                 f'{df["datetime"].iloc[-1].strftime("%Y-%m-%d")}',
                 fontsize=16, fontweight='bold')

    # ---- 上图：PV & SV ----
    ax1.plot(t, pv, color='#2196F3', linewidth=0.6, alpha=0.85, label='PV (过程值)')
    ax1.plot(t, sv, color='#FF5722', linewidth=0.8, linestyle='--', alpha=0.9, label='SV (设定值)')
    ax1.set_ylabel('PV / SV (%)', fontsize=12)
    ax1.legend(loc='upper right', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.set_title('过程值 & 设定值', fontsize=13)

    # ---- 下图：MV ----
    ax2.fill_between(t, 0, mv, color='#4CAF50', alpha=0.35)
    ax2.plot(t, mv, color='#388E3C', linewidth=0.6, alpha=0.85, label='MV (操作输出)')
    ax2.set_ylabel('MV (%)', fontsize=12)
    ax2.set_xlabel('时间', fontsize=12)
    ax2.legend(loc='upper right', fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.set_title('操作输出', fontsize=13)

    # X 轴月份格式
    ax2.xaxis.set_major_locator(mdates.MonthLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))
    fig.autofmt_xdate(rotation=30)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"💾 已保存: {output_path.name}")


def main():
    print("=" * 60)
    print("📊 大榭现场数据可视化")
    print("=" * 60)

    merged = load_merged_data()

    devices = [
        ("2216_LIC_50104", "废水自S-503 液位控制"),
        ("2216_LIC_50108", "废液至D-506 液位控制"),
    ]

    for device, desc in devices:
        out = OUTPUT_DIR / f"{device}_trend.png"
        plot_loop(merged, device, desc, out)

    print("\n✅ 全部可视化完成！")


if __name__ == "__main__":
    main()
