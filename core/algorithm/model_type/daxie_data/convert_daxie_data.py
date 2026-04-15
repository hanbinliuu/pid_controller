"""
大榭现场数据转换脚本
=================

功能：
1. 读取 数据1.csv 和 数据2.csv
2. 拼接两份数据（去除时间重叠部分）
3. 按设备拆分（2216_LIC_50104 / 2216_LIC_50108）
4. 转换为整定算法可用的 JSON 格式

输出文件：
- 2216_LIC_50104.json  (废水自S-503 液位控制)
- 2216_LIC_50108.json  (废液至D-506 液位控制)

用法：
    python convert_daxie_data.py
"""

import pandas as pd
import numpy as np
import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"


def load_and_merge_csv():
    """读取并合并存在的 CSV 文件，去除重叠时间段"""
    
    file1 = DATA_DIR / "数据1.csv"
    file2 = DATA_DIR / "数据2.csv"
    
    dfs = []
    
    if file1.exists():
        print(f"📂 读取 {file1.name} ...")
        df1 = pd.read_csv(file1, skiprows=[1], index_col=False, engine='c')  # 跳过第2行
        df1 = df1.loc[:, ~df1.columns.str.startswith('Unnamed')]
        df1['datetime'] = pd.to_datetime(df1['Test'], format='%Y/%m/%d %H:%M:%S')
        print(f"   行数: {len(df1)}, 时间范围: {df1['datetime'].iloc[0]} ~ {df1['datetime'].iloc[-1]}")
        dfs.append(df1)
    
    if file2.exists():
        print(f"📂 读取 {file2.name} ...")
        df2 = pd.read_csv(file2, skiprows=[1], index_col=False, engine='c')
        df2 = df2.loc[:, ~df2.columns.str.startswith('Unnamed')]
        df2['datetime'] = pd.to_datetime(df2['Test'], format='%Y/%m/%d %H:%M:%S')
        print(f"   行数: {len(df2)}, 时间范围: {df2['datetime'].iloc[0]} ~ {df2['datetime'].iloc[-1]}")
        dfs.append(df2)
        
    if not dfs:
        raise FileNotFoundError("未在 data 目录下找到 数据1.csv 或 数据2.csv！")
        
    if len(dfs) == 1:
        merged = dfs[0]
        print(f"✅ 只找到一份数据, 行数: {len(merged)}")
    else:
        df1, df2 = dfs[0], dfs[1]
        # 去除重叠：保留 df1 中时间 < df2 起始时间 的数据，然后拼接 df2
        df2_start = df2['datetime'].iloc[0]
        df1_no_overlap = df1[df1['datetime'] < df2_start]
        
        overlap_count = len(df1) - len(df1_no_overlap)
        print(f"⚙️  去除重叠数据 {overlap_count} 行 (df1 中 >= {df2_start})")
        
        # 拼接
        print("⚙️  拼接数据...")
        merged = pd.concat([df1_no_overlap, df2], ignore_index=True)
        merged.sort_values('datetime', inplace=True)
        merged.drop_duplicates(subset='datetime', keep='first', inplace=True)
        merged.reset_index(drop=True, inplace=True)
        print(f"✅ 合并完成: {len(merged)} 行")
        
    # 转换为毫秒时间戳 (epoch ms)
    merged['timestamp_ms'] = (merged['datetime'].astype(np.int64) // 10**6).astype(np.int64)
    
    return merged


def extract_and_save(merged_df, device_prefix, description):
    """提取单个设备的数据并直接以流式方式写入 JSON"""
    
    pv_col = f"{device_prefix}.PV"
    sv_col = f"{device_prefix}.SV"
    mv_col = f"{device_prefix}.MV"
    
    # 向量化提取
    timestamps = merged_df['timestamp_ms'].values
    pvs = merged_df[pv_col].fillna(0.0).values.astype(np.float64)
    svs = merged_df[sv_col].fillna(0.0).values.astype(np.float64)
    mvs = merged_df[mv_col].fillna(0.0).values.astype(np.float64)
    
    n = len(timestamps)
    
    print(f"\n📊 {device_prefix} ({description}):")
    print(f"   数据点数: {n}")
    print(f"   时间范围: {merged_df['datetime'].iloc[0]} ~ {merged_df['datetime'].iloc[-1]}")
    print(f"   PV 范围: [{pvs.min():.2f}, {pvs.max():.2f}], 均值: {pvs.mean():.2f}")
    print(f"   SV 范围: [{svs.min():.2f}, {svs.max():.2f}], 均值: {svs.mean():.2f}")
    print(f"   MV 范围: [{mvs.min():.2f}, {mvs.max():.2f}], 均值: {mvs.mean():.2f}")
    
    # 构建 history_data 列表（使用向量化构建，避免 iterrows）
    print(f"⚙️  构建 history_data ({n} 点)...")
    history_data = [
        {
            "timestamp": int(timestamps[i]),
            "pv": round(float(pvs[i]), 6),
            "sv": round(float(svs[i]), 6),
            "mv": round(float(mvs[i]), 6),
        }
        for i in range(n)
    ]
    
    # 构建完整结构
    output = {
        "metadata": {
            "device": device_prefix,
            "description": description,
            "loop_type": "level",
            "data_source": "大榭现场数据",
            "time_range": {
                "start": str(merged_df['datetime'].iloc[0]),
                "end": str(merged_df['datetime'].iloc[-1])
            },
            "sampling_interval_sec": 5,
            "total_points": n,
        },
        "data_points": n,
        "columns": ["timestamp", "pv", "sv", "mv"],
        "history_data": history_data
    }
    
    # 保存
    output_path = DATA_DIR / f"{device_prefix}.json"
    print(f"💾 保存 {output_path.name} ...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, separators=(',', ':'))
    
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"   文件大小: {size_mb:.1f} MB")


def get_devices_from_columns(columns):
    """自动从表头扫描提取出所有设备位号前缀"""
    devices = set()
    for col in columns:
        if col.endswith('.PV'):
            devices.add(col.replace('.PV', ''))
    return sorted(list(devices))


def main():
    print("=" * 60)
    print("🔧 大榭现场数据转换工具")
    print("=" * 60)
    
    # 1. 读取并合并 CSV
    merged = load_and_merge_csv()
    
    # 2. 自动识别数据里所有的设备通道
    device_prefixes = get_devices_from_columns(merged.columns)
    
    print(f"\n🔍 自动探测到 {len(device_prefixes)} 个设备:")
    for device in device_prefixes:
        print(f"   - {device}")
        
    if not device_prefixes:
        print("❌ 未在 CSV 中找到任何以 .PV 结尾的数据列！")
        return
    
    # 3. 按设备拆分、转换并保存
    for device_prefix in device_prefixes:
        # 这里把 description 默认设置为和 device_prefix 一样，
        # 因为我们不再硬编码，不知道设备中文名
        extract_and_save(merged, device_prefix, device_prefix)
    
    print("\n" + "=" * 60)
    print("✅ 转换完成！生成文件：")
    for device_prefix in device_prefixes:
        print(f"   → {device_prefix}.json")
    print("\n📌 使用方式：")
    print("   import json")
    print(f"   with open('{device_prefixes[0]}.json') as f:")
    print("       input_data = json.load(f)")
    print("   # input_data 可直接传入 TuningOrchestrator.run()")
    print("=" * 60)


if __name__ == "__main__":
    main()
