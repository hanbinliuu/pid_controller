"""
可视化模块

用于可视化模型检测结果。
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Optional, Union
import os

from .model_types import ModelType
from .model_detector import ModelDetector, DetectionResult


class Visualizer:
    """可视化器"""
    
    def __init__(self):
        """初始化可视化器"""
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
    
    def visualize_detection(self,
                           json_data: Union[str, Dict],
                           detection_result: DetectionResult,
                           output_path: Optional[str] = None):
        """
        可视化单个检测结果
        
        Args:
            json_data: JSON数据（可以是文件路径字符串或字典）
            detection_result: 检测结果
            output_path: 输出图片路径（可选）
        """
        # 加载数据
        if isinstance(json_data, str):
            with open(json_data, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = json_data
        
        data_list = data["data"]
        timestamps = []
        pv_data = []
        mv_data = []
        
        for item in data_list:
            timestamp = item.get("timestamp", 0)
            pv = item.get("pv", 0)
            mv = item.get("mv", 0)
            timestamps.append(timestamp / 1000.0)
            pv_data.append(pv)
            mv_data.append(mv)
        
        time_data = np.array(timestamps)
        pv_data = np.array(pv_data)
        mv_data = np.array(mv_data)
        
        if len(time_data) > 0:
            time_data = time_data - time_data[0]
        
        # 创建图形
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)
        
        # 子图1：输入输出数据
        ax1 = fig.add_subplot(gs[0, :])
        ax1_twin = ax1.twinx()
        
        ax1.plot(time_data, pv_data, 'b-', linewidth=2, label='实际输出 (PV)', alpha=0.7)
        ax1_twin.plot(time_data, mv_data, 'r--', linewidth=1.5, label='控制输入 (MV)', alpha=0.7)
        
        ax1.set_xlabel('时间 (秒)', fontsize=11, fontweight='bold')
        ax1.set_ylabel('输出 (PV)', fontsize=11, fontweight='bold', color='b')
        ax1_twin.set_ylabel('输入 (MV)', fontsize=11, fontweight='bold', color='r')
        ax1.set_title('输入输出数据', fontsize=12, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper left', fontsize=9)
        ax1_twin.legend(loc='upper right', fontsize=9)
        
        # 子图2：检测结果对比（所有模型的拟合）
        ax2 = fig.add_subplot(gs[1, :])
        ax2.plot(time_data, pv_data, 'b-', linewidth=2, label='实际输出', alpha=0.7)
        
        # 绘制所有模型的预测
        detector = ModelDetector()
        colors = {
            "first_order": "green",
            "fopdt": "orange",
            "second_order": "purple"
        }
        
        # 获取初始值
        y0 = np.mean(pv_data[:max(10, int(0.1 * len(pv_data)))])
        
        for model_name, model_result in detection_result.all_results.items():
            if model_name not in ["first_order", "fopdt", "second_order"]:
                continue
            
            # 重新计算预测值用于可视化
            if model_name == "first_order":
                params = [model_result["parameters"]["K"], model_result["parameters"]["T"]]
                y_pred = detector.first_order_model(np.array(params), time_data, mv_data, y0)
            elif model_name == "fopdt":
                params = [model_result["parameters"]["K"], 
                         model_result["parameters"]["T"], 
                         model_result["parameters"]["L"]]
                y_pred = detector.fopdt_model(np.array(params), time_data, mv_data, y0)
            elif model_name == "second_order":
                params = [model_result["parameters"]["K"], 
                         model_result["parameters"]["T1"], 
                         model_result["parameters"]["T2"]]
                y_pred = detector.second_order_model(np.array(params), time_data, mv_data, y0)
            else:
                continue
            
            color = colors.get(model_name, "gray")
            linestyle = "-" if model_name == detection_result.detected_model.value else "--"
            linewidth = 2.5 if model_name == detection_result.detected_model.value else 1.5
            alpha = 0.9 if model_name == detection_result.detected_model.value else 0.6
            
            label = f"{model_name} (R²={model_result['r2']:.4f})"
            if model_name == detection_result.detected_model.value:
                label += " [检测结果]"
            
            ax2.plot(time_data, y_pred, color=color, linestyle=linestyle, 
                    linewidth=linewidth, label=label, alpha=alpha)
        
        ax2.set_xlabel('时间 (秒)', fontsize=11, fontweight='bold')
        ax2.set_ylabel('输出', fontsize=11, fontweight='bold')
        title = f'模型检测结果对比\n'
        title += f"检测模型: {detection_result.detected_model.value} | "
        title += f"置信度: {detection_result.confidence:.4f} | "
        title += f"R² = {detection_result.r2:.4f} | RMSE = {detection_result.rmse:.4f}"
        ax2.set_title(title, fontsize=11, fontweight='bold')
        ax2.legend(loc='best', fontsize=9)
        ax2.grid(True, alpha=0.3)
        
        # 子图3：R²对比
        ax3 = fig.add_subplot(gs[2, 0])
        model_names = list(detection_result.all_results.keys())
        r2_values = [detection_result.all_results[m]["r2"] for m in model_names]
        colors_bar = [colors.get(m, "gray") if m != detection_result.detected_model.value 
                     else "red" for m in model_names]
        
        bars = ax3.barh(model_names, r2_values, color=colors_bar, alpha=0.7)
        ax3.set_xlabel('R² (决定系数)', fontsize=10, fontweight='bold')
        ax3.set_title('模型拟合度对比 (R²)', fontsize=11, fontweight='bold')
        ax3.grid(True, alpha=0.3, axis='x')
        
        # 添加数值标签
        for i, (bar, val) in enumerate(zip(bars, r2_values)):
            ax3.text(val, i, f' {val:.4f}', va='center', fontsize=8)
        
        # 子图4：参数对比
        ax4 = fig.add_subplot(gs[2, 1])
        param_text = "检测到的模型参数:\n\n"
        for param_name, param_value in detection_result.parameters.items():
            param_text += f"{param_name}: {param_value:.4f}\n"
        
        param_text += f"\n置信度: {detection_result.confidence:.4f}\n"
        param_text += f"R²: {detection_result.r2:.4f}\n"
        param_text += f"RMSE: {detection_result.rmse:.4f}"
        
        ax4.text(0.1, 0.5, param_text, fontsize=10, verticalalignment='center',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        ax4.set_xlim(0, 1)
        ax4.set_ylim(0, 1)
        ax4.axis('off')
        ax4.set_title('检测结果详情', fontsize=11, fontweight='bold')
        
        plt.suptitle('模型检测可视化结果', fontsize=14, fontweight='bold', y=0.995)
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
            print(f"可视化结果已保存到: {output_path}")
        else:
            plt.show()
        
        plt.close()
    
    def visualize_batch_detections(self,
                                  test_data_dir: str,
                                  output_dir: str,
                                  max_samples: int = 20):
        """
        批量可视化检测结果
        
        Args:
            test_data_dir: 测试数据目录
            output_dir: 输出目录
            max_samples: 最大可视化样本数
        """
        os.makedirs(output_dir, exist_ok=True)
        
        detector = ModelDetector()
        
        # 加载测试文件
        test_files = []
        for filename in os.listdir(test_data_dir):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(test_data_dir, filename)
            test_files.append((filepath, filename))
        
        # 限制数量
        test_files = test_files[:max_samples]
        
        print(f"开始可视化 {len(test_files)} 个检测结果...")
        
        for filepath, filename in test_files:
            try:
                detection_result = detector.detect_from_json(filepath)
                output_path = os.path.join(output_dir, filename.replace('.json', '_detection.png'))
                self.visualize_detection(filepath, detection_result, output_path)
            except Exception as e:
                print(f"可视化失败 {filename}: {e}")

