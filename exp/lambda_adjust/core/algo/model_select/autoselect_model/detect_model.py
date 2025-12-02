#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
简单的模型检测脚本

用法:
    python detect_model.py <json_file_path>

功能:
    检测JSON数据文件的模型类型（first_order, fopdt, second_order）
"""

import os
import sys
import json

# 添加父目录到路径，使相对导入能工作
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 设置包名
__package__ = 'autoselect_model'

from .model_detector import ModelDetector
from .visualizer import Visualizer




if __name__ == '__main__':
    # 直接在这里修改测试文件路径即可
    path = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/data_simulation/zhongkong/'
    test_json_file = os.path.join(path, 'response_1762741206598.json')
    
    # 检测模型（使用全部数据）
    try:
        detector = ModelDetector()
        visualizer = Visualizer()
        
        # 检测模型
        detection_result = detector.detect_from_json(test_json_file)
        
        # 输出结果
        print("=" * 60)
        print("模型检测结果")
        print("=" * 60)
        print(f"文件: {os.path.basename(test_json_file)}")
        print(f"检测模型: {detection_result.detected_model.value}")
        print(f"置信度: {detection_result.confidence:.4f}")
        print(f"R²值: {detection_result.r2:.4f}")
        print(f"RMSE: {detection_result.rmse:.4f}")
        print(f"\n模型参数:")
        for key, value in detection_result.parameters.items():
            print(f"  {key}: {value:.4f}")
        print("=" * 60)
        
        # 保存可视化结果
        output_dir = "exp/lambda_adjust/core/algo/model_select/autoselect_model/output/visualizations"
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成输出文件名
        base_name = os.path.splitext(os.path.basename(test_json_file))[0]
        vis_path = os.path.join(output_dir, f"{base_name}_detection.png")
        
        # 加载JSON数据用于可视化
        with open(test_json_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # 生成可视化
        visualizer.visualize_detection(json_data, detection_result, vis_path)
        print(f"\n可视化结果已保存到: {vis_path}")
        
    except Exception as e:
        print(f"错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)