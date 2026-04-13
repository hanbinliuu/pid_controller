import argparse
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from pathlib import Path

# 配置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'Heiti TC', 'PingFang SC']
plt.rcParams['axes.unicode_minus'] = False

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR / "output"

def plot_device(device_id, start_str, end_str):
    device_name = f"2216_LIC_{device_id}"
    json_path = DATA_DIR / f"{device_name}.json"
    
    if not json_path.exists():
        print(f"❌ 找不到数据文件: {json_path}")
        return
        
    print(f"\n📂 正在处理 [{device_name}] ...")
    with open(json_path) as f:
        data = json.load(f)
        
    history_data = data.get("history_data", [])
    if not history_data:
        print("❌ 数据文件中没有历史数据！")
        return
        
    start_ts = int(datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    
    sliced = [d for d in history_data if start_ts <= d["timestamp"] <= end_ts]
    
    if not sliced:
        data_start = datetime.fromtimestamp(history_data[0]["timestamp"]/1000).strftime('%Y-%m-%d %H:%M:%S')
        data_end = datetime.fromtimestamp(history_data[-1]["timestamp"]/1000).strftime('%Y-%m-%d %H:%M:%S')
        print(f"⚠️ 在 {start_str} 到 {end_str} 之间没有找到数据！")
        print(f"💡 该文件的有效数据时间范围是: {data_start} ~ {data_end}")
        return
        
    print(f"✂️ 截取了 {len(sliced)} 个数据点进行绘图...")
    
    times = [datetime.fromtimestamp(d["timestamp"]/1000) for d in sliced]
    pvs = [d["pv"] for d in sliced]
    svs = [d["sv"] for d in sliced]
    mvs = [d["mv"] for d in sliced]
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    
    fig.suptitle(f'{device_name} 运行趋势可视化\n{start_str} ~ {end_str}', fontsize=14, fontweight='bold')
    
    ax1.plot(times, pvs, 'b-', label='PV (过程值)', linewidth=1.0)
    ax1.plot(times, svs, 'r--', label='SV (设定值)', linewidth=1.2)
    ax1.set_ylabel('PV / SV (%)', fontsize=11)
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_title("过程值 & 设定值")
    
    ax2.plot(times, mvs, 'g-', label='MV (操作输出)', linewidth=1.0)
    ax2.fill_between(times, 0, mvs, color='green', alpha=0.15)
    ax2.set_ylabel('MV (%)', fontsize=11)
    ax2.set_xlabel('时间', fontsize=11)
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.set_title("操作输出")
    
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    fig.autofmt_xdate(rotation=30)
    
    out_dir = OUTPUT_DIR
    out_dir.mkdir(exist_ok=True)
    
    safe_start = start_str.replace(" ", "_").replace(":", "")
    safe_end = end_str.replace(" ", "_").replace(":", "")
    out_name = out_dir / f"view_{device_name}_{safe_start}_to_{safe_end}.png"
    
    plt.tight_layout()
    plt.savefig(out_name, dpi=150)
    plt.close()
    print(f"✅ 图表已保存至: output/{out_name.name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按指定时间段可视化回路 PV/SV/MV 数据")
    parser.add_argument("--loop", choices=["50104", "50108", "both"], default="50104", 
                        help="指定需要可视化的回路，可选 '50104', '50108', 或是默认的 'both' (同时出两张图)")
    parser.add_argument("--start", type=str, default="2025-11-28 00:00:00", 
                        help="开始时间，格式: YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--end", type=str, default="2025-11-29 00:00:00", 
                        help="结束时间，格式: YYYY-MM-DD HH:MM:SS")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("📈 大榭现场数据局部切片可视化器")
    print(f"🔎 目标区间: {args.start} ~ {args.end}")
    print("=" * 60)
    
    loops = ["50104", "50108"] if args.loop == "both" else [args.loop]
    for loop in loops:
        plot_device(loop, args.start, args.end)
