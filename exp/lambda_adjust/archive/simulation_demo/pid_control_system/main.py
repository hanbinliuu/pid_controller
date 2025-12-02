"""
PID控制系统主入口

功能：
    - 启动PID控制监控系统
    - 支持温度控制和流量控制模式
    - 支持多种PID整定方法
    - 实时可视化系统状态

使用方法：
    python main.py

依赖：
    - numpy
    - scipy
    - matplotlib
"""
import sys
import os

# 添加当前目录到路径，以便导入模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from control_monitor import ControlMonitor


if __name__ == "__main__":
    try:
        print("=" * 60)
        print("PID控制系统启动中...")
        print("=" * 60)
        
        monitor = ControlMonitor()
        monitor.run()
        
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 程序运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)




