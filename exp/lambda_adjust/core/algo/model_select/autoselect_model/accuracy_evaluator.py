"""
准确率评估器

用于评估模型检测的准确率，生成混淆矩阵和详细报告。
"""

import json
import os
import sys
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

# 处理导入路径，使其既可以作为模块导入，也可以直接运行
if __name__ == '__main__':
    # 直接运行时，需要设置路径使相对导入能工作
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    # 设置包名
    __package__ = 'autoselect_model'
    from .model_types import ModelType
    from .model_detector import ModelDetector, DetectionResult
else:
    # 作为模块导入时，使用相对导入
    from .model_types import ModelType
    from .model_detector import ModelDetector, DetectionResult


@dataclass
class EvaluationResult:
    """评估结果"""
    total_samples: int
    correct_predictions: int
    accuracy: float
    per_model_accuracy: Dict[str, float]
    confusion_matrix: Dict[str, Dict[str, int]]
    detailed_results: List[Dict]


class AccuracyEvaluator:
    """准确率评估器"""
    
    def __init__(self):
        """初始化评估器"""
        self.detector = ModelDetector()
    
    def evaluate(self, test_data_dir: str) -> EvaluationResult:
        """
        评估检测准确率
        
        Args:
            test_data_dir: 测试数据目录
        
        Returns:
            评估结果
        """
        # 加载测试数据
        test_files = self._load_test_files(test_data_dir)
        
        if not test_files:
            raise ValueError(f"测试数据目录为空: {test_data_dir}")
        
        # 进行检测
        results = []
        for file_info in test_files:
            try:
                detection_result = self.detector.detect_from_json(file_info["filepath"])
                
                results.append({
                    "filename": file_info["filename"],
                    "true_model": file_info["model_type"],
                    "detected_model": detection_result.detected_model.value,
                    "confidence": detection_result.confidence,
                    "r2": detection_result.r2,
                    "parameters": detection_result.parameters,
                    "correct": file_info["model_type"] == detection_result.detected_model.value
                })
            except Exception as e:
                print(f"检测失败 {file_info['filename']}: {e}")
                results.append({
                    "filename": file_info["filename"],
                    "true_model": file_info["model_type"],
                    "detected_model": "error",
                    "error": str(e),
                    "correct": False
                })
        
        # 计算统计信息
        total_samples = len(results)
        correct_predictions = sum(1 for r in results if r.get("correct", False))
        accuracy = correct_predictions / total_samples if total_samples > 0 else 0.0
        
        # 计算各模型类型的准确率
        model_types = ["first_order", "fopdt", "second_order"]
        per_model_accuracy = {}
        for model_type in model_types:
            model_results = [r for r in results if r["true_model"] == model_type]
            if model_results:
                model_correct = sum(1 for r in model_results if r.get("correct", False))
                per_model_accuracy[model_type] = model_correct / len(model_results)
            else:
                per_model_accuracy[model_type] = 0.0
        
        # 构建混淆矩阵
        confusion_matrix = {}
        for true_model in model_types:
            confusion_matrix[true_model] = {}
            for detected_model in model_types:
                count = sum(1 for r in results 
                           if r["true_model"] == true_model 
                           and r.get("detected_model") == detected_model)
                confusion_matrix[true_model][detected_model] = count
        
        return EvaluationResult(
            total_samples=total_samples,
            correct_predictions=correct_predictions,
            accuracy=accuracy,
            per_model_accuracy=per_model_accuracy,
            confusion_matrix=confusion_matrix,
            detailed_results=results
        )
    
    def _load_test_files(self, test_data_dir: str) -> List[Dict]:
        """
        加载测试文件
        
        Args:
            test_data_dir: 测试数据目录
        
        Returns:
            测试文件信息列表
        """
        test_files = []
        
        if not os.path.exists(test_data_dir):
            return test_files
        
        for filename in os.listdir(test_data_dir):
            if not filename.endswith('.json'):
                continue
            
            filepath = os.path.join(test_data_dir, filename)
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 从文件名或数据中获取模型类型
                model_type = data.get("model_type")
                if not model_type:
                    # 从文件名推断
                    if "first_order" in filename:
                        model_type = "first_order"
                    elif "fopdt" in filename:
                        model_type = "fopdt"
                    elif "second_order" in filename:
                        model_type = "second_order"
                    else:
                        continue
                
                test_files.append({
                    "filepath": filepath,
                    "filename": filename,
                    "model_type": model_type
                })
            except Exception as e:
                print(f"加载文件失败 {filename}: {e}")
        
        return test_files
    
    def print_evaluation_report(self, result: EvaluationResult):
        """
        打印评估报告
        
        Args:
            result: 评估结果
        """
        print("=" * 80)
        print("模型检测准确率评估报告")
        print("=" * 80)
        
        print(f"\n总样本数: {result.total_samples}")
        print(f"正确预测数: {result.correct_predictions}")
        print(f"总体准确率: {result.accuracy * 100:.2f}%")
        
        print(f"\n各模型类型准确率:")
        for model_type, acc in result.per_model_accuracy.items():
            print(f"  {model_type}: {acc * 100:.2f}%")
        
        print(f"\n混淆矩阵:")
        print("真实模型 \\ 检测模型 | ", end="")
        model_types = ["first_order", "fopdt", "second_order"]
        for model_type in model_types:
            print(f"{model_type:15s} | ", end="")
        print()
        print("-" * 80)
        
        for true_model in model_types:
            print(f"{true_model:15s} | ", end="")
            for detected_model in model_types:
                count = result.confusion_matrix[true_model].get(detected_model, 0)
                print(f"{count:15d} | ", end="")
            print()
        
        # 显示错误案例
        error_cases = [r for r in result.detailed_results if not r.get("correct", False)]
        if error_cases:
            print(f"\n错误案例（前10个）:")
            for i, case in enumerate(error_cases[:10], 1):
                print(f"  {i}. {case['filename']}")
                print(f"     真实模型: {case['true_model']}, 检测模型: {case.get('detected_model', 'error')}")
                if 'confidence' in case:
                    print(f"     置信度: {case['confidence']:.4f}, R²: {case['r2']:.4f}")
    
    def save_evaluation_report(self, result: EvaluationResult, output_path: str):
        """
        保存评估报告
        
        Args:
            result: 评估结果
            output_path: 输出文件路径
        """
        report = {
            "total_samples": result.total_samples,
            "correct_predictions": result.correct_predictions,
            "accuracy": result.accuracy,
            "per_model_accuracy": result.per_model_accuracy,
            "confusion_matrix": result.confusion_matrix,
            "detailed_results": result.detailed_results
        }
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"\n评估报告已保存到: {output_path}")


if __name__ == "__main__":
    # 直接运行时的测试代码
    evaluator = AccuracyEvaluator()
    
    # 默认测试数据目录
    test_data_dir = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/core/algo/model_select/autoselect_model/data_generation'
    
    if not os.path.exists(test_data_dir):
        print(f"错误: 测试数据目录不存在: {test_data_dir}")
        print("请先运行 data_generator.py 生成测试数据")
        sys.exit(1)
    
    print("=" * 60)
    print("开始评估模型检测准确率")
    print("=" * 60)
    print(f"测试数据目录: {test_data_dir}\n")
    
    # 执行评估
    result = evaluator.evaluate(test_data_dir)
    
    # 打印报告
    evaluator.print_evaluation_report(result)
    
    # 保存报告
    output_dir = "exp/lambda_adjust/core/algo/model_select/autoselect_model/output"
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "evaluation_report.json")
    evaluator.save_evaluation_report(result, report_path)