"""
JSON数据整定评估示例
演示如何在实际的JSON数据整定流程中集成PID参数评估器
"""
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 添加路径
project_root = "/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp"
sys.path.insert(0, project_root)

# 导入项目根目录的模块
from api.routes.analysis_router import _query_tsdb_data_zhongkong
from api.routes.util import parse_time_to_milliseconds
from core.algorithm.tmp_algo.detector import StabilityDetector

# 使用importlib导入system_tuning的evaluator模块（避免core模块冲突）
import importlib.util
current_dir = os.path.dirname(os.path.abspath(__file__))
tests_dir = os.path.dirname(current_dir)  # tests目录
system_tuning_dir = os.path.dirname(tests_dir)  # system_tuning目录
evaluator_path = os.path.join(system_tuning_dir, 'core', 'pid', 'evaluator.py')

spec = importlib.util.spec_from_file_location("pid_evaluator", evaluator_path)
pid_evaluator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pid_evaluator_module)

PIDEvaluator = pid_evaluator_module.PIDEvaluator
EvaluationMetrics = pid_evaluator_module.EvaluationMetrics


class TuningEvaluationWorkflow:
    """
    整定评估工作流
    集成了非稳态检测、PID整定和性能评估
    """
    
    def __init__(self):
        self.detector = StabilityDetector()
        self.evaluator = PIDEvaluator(
            settling_band=0.02,
            settling_duration=50
        )
        self.tuning_history = []
    
    def load_json_data(self, data_list: List[Dict]):
        """
        从JSON数据加载PID控制数据
        
        Args:
            data_list: JSON数据列表
            
        Returns:
            dict: 包含时间、PV、MV、SV等数据
        """
        timestamps, pv_list, mv_list, sv_list = [], [], [], []
        pb_list, ti_list, td_list = [], [], []
        
        for item in data_list:
            if 'timestamp' in item:
                timestamps.append(item['timestamp'])
            if 'pv' in item:
                pv_list.append(item['pv'])
            if 'mv' in item:
                mv_list.append(item['mv'])
            if 'sv' in item:
                sv_list.append(item['sv'])
            if 'pb' in item:
                pb_list.append(item['pb'])
            if 'ti' in item:
                ti_list.append(item['ti'])
            if 'td' in item:
                td_list.append(item['td'])
        
        # 确保数据长度一致
        min_len = min(len(timestamps), len(pv_list))
        
        return {
            'timestamps': np.array(timestamps[:min_len]),
            'pv': np.array(pv_list[:min_len]),
            'mv': np.array(mv_list[:min_len]) if mv_list else None,
            'sv': np.array(sv_list[:min_len]) if sv_list else None,
            'pb': np.array(pb_list[:min_len]) if pb_list else None,
            'ti': np.array(ti_list[:min_len]) if ti_list else None,
            'td': np.array(td_list[:min_len]) if td_list else None,
        }
    
    def detect_disturbances(self, data: Dict):
        """
        检测非稳态段（扰动段）
        
        Args:
            data: 数据字典
            
        Returns:
            dict: 检测结果
        """
        pv = data['pv']
        sv = data['sv']
        mv = data['mv']
        timestamps = data['timestamps']
        
        # 使用StabilityDetector检测非稳态段
        non_steady_segments_raw = self.detector.detect_non_steady_segments(pv, sv, min_segment_len=20)
        disturbance_starts = self.detector.detect_all_disturbances(pv, sv, non_steady_segments=non_steady_segments_raw)
        
        # 添加时间戳信息到segments
        non_steady_segments = []
        for start_idx, end_idx, setpoint in non_steady_segments_raw:
            start_ts = timestamps[start_idx] if start_idx < len(timestamps) else timestamps[0]
            end_ts = timestamps[end_idx] if end_idx < len(timestamps) else timestamps[-1]
            non_steady_segments.append((start_idx, end_idx, start_ts, end_ts, setpoint))
        
        # 提取扰动结束点（从非稳态段中提取）
        disturbance_ends = [(end_idx, setpoint) for start_idx, end_idx, setpoint in non_steady_segments_raw]
        
        return {
            'segments': non_steady_segments,
            'starts': disturbance_starts,
            'ends': disturbance_ends
        }
    
    def evaluate_segment(self, data: Dict, segment_start: int, segment_end: int, 
                        segment_name: str = "") -> EvaluationMetrics:
        """
        评估某个扰动段的PID性能
        
        Args:
            data: 数据字典
            segment_start: 段起始索引
            segment_end: 段结束索引
            segment_name: 段名称
            
        Returns:
            评估指标
        """
        pv = data['pv']
        sv = data['sv']
        mv = data['mv']
        
        # 评估该段的性能
        metrics = self.evaluator.evaluate(
            pv, sv, mv,
            segment_start=segment_start,
            segment_end=segment_end
        )
        
        # 记录历史
        record = {
            'segment_name': segment_name,
            'segment_range': (segment_start, segment_end),
            'metrics': metrics,
            'timestamp': pd.Timestamp.now(),
            'pid_params': self._extract_pid_params(data, segment_start)
        }
        self.tuning_history.append(record)
        
        return metrics
    
    def _extract_pid_params(self, data: Dict, index: int) -> Dict:
        """提取PID参数（如果有）"""
        params = {}
        if data.get('pb') is not None and index < len(data['pb']):
            params['pb'] = float(data['pb'][index])
        if data.get('ti') is not None and index < len(data['ti']):
            params['ti'] = float(data['ti'][index])
        if data.get('td') is not None and index < len(data['td']):
            params['td'] = float(data['td'][index])
        return params
    
    def evaluate_all_segments(self, data: Dict, detection_result: Dict):
        """
        评估所有检测到的扰动段
        
        Args:
            data: 数据字典
            detection_result: 检测结果
            
        Returns:
            评估结果列表
        """
        segments = detection_result['segments']
        evaluation_results = []
        
        print("\n" + "=" * 70)
        print("开始评估所有扰动段")
        print("=" * 70)
        
        for i, (start_idx, end_idx, start_ts, end_ts, setpoint) in enumerate(segments, 1):
            segment_name = f"扰动段{i}"
            print(f"\n【{segment_name}】")
            print(f"  索引范围: [{start_idx}, {end_idx}]")
            print(f"  时间范围: {start_ts} - {end_ts}")
            print(f"  设定值: {setpoint}")
            
            # 评估该段
            metrics = self.evaluate_segment(
                data, start_idx, end_idx, segment_name
            )
            
            # 打印评估结果
            print(f"\n  【性能评估】")
            print(f"    综合评分: {metrics.overall_score:.2f} ({metrics.grade})")
            print(f"    超调量:   {metrics.overshoot:.2f}%")
            print(f"    调节时间: {metrics.settling_time:.1f} 点")
            print(f"    稳态误差: {metrics.steady_state_error:.4f}")
            print(f"    IAE:      {metrics.iae:.2f}")
            
            # 给出建议
            if metrics.overall_score < 60:
                print(f"    ⚠️  评分较低，建议重新整定")
            elif metrics.overall_score < 70:
                print(f"    ⚡ 评分一般，可以优化")
            else:
                print(f"    ✓  评分良好")
            
            evaluation_results.append({
                'segment_name': segment_name,
                'segment_range': (start_idx, end_idx),
                'metrics': metrics,
                'pid_params': self._extract_pid_params(data, start_idx)
            })
        
        return evaluation_results
    
    def generate_evaluation_report(self):
        """生成评估报告"""
        if not self.tuning_history:
            return "暂无评估历史"
        
        report = """
╔══════════════════════════════════════════════════════════════╗
║                  PID整定评估报告                              ║
╚══════════════════════════════════════════════════════════════╝

"""
        for i, record in enumerate(self.tuning_history, 1):
            metrics = record['metrics']
            params = record['pid_params']
            
            report += f"""
【评估记录 {i}】
  段名称: {record['segment_name']}
  索引范围: {record['segment_range']}
  PID参数: PB={params.get('pb', 'N/A')}, TI={params.get('ti', 'N/A')}, TD={params.get('td', 'N/A')}
  
  性能评估:
    综合评分: {metrics.overall_score:.2f} ({metrics.grade})
    超调量:   {metrics.overshoot:.2f}%
    调节时间: {metrics.settling_time:.1f} 点
    稳态误差: {metrics.steady_state_error:.4f}
    IAE:      {metrics.iae:.4f}
    
  时间: {record['timestamp']}
{'─' * 62}
"""
        
        # 添加统计信息
        scores = [r['metrics'].overall_score for r in self.tuning_history]
        report += f"""
【统计信息】
  评估段数: {len(self.tuning_history)}
  平均评分: {np.mean(scores):.2f}
  最高评分: {max(scores):.2f}
  最低评分: {min(scores):.2f}
"""
        
        return report
    
    def visualize_with_evaluation(self, data: Dict, detection_result: Dict, 
                                  evaluation_results: List[Dict],
                                  output_path: str = None):
        """
        可视化数据、检测结果和评估结果
        
        Args:
            data: 数据字典
            detection_result: 检测结果
            evaluation_results: 评估结果列表
            output_path: 输出路径
        """
        pv = data['pv']
        sv = data['sv']
        mv = data['mv']
        timestamps = data['timestamps']
        
        # 计算相对时间（秒）
        t = (timestamps - timestamps[0]) / 1000.0
        
        segments = detection_result['segments']
        
        # 创建图形
        fig, axes = plt.subplots(3, 1, figsize=(16, 12))
        
        # 子图1: PV和SV
        ax1 = axes[0]
        ax1.plot(t, pv, 'b-', linewidth=2, label='过程值PV', alpha=0.8)
        if sv is not None:
            ax1.plot(t, sv, 'r--', linewidth=2, label='设定值SV', alpha=0.8)
        
        # 标注非稳态段和评分
        for i, (start_idx, end_idx, _, _, _) in enumerate(segments):
            # 背景色
            ax1.axvspan(t[start_idx], t[min(end_idx, len(t) - 1)],
                       alpha=0.15, color='red', zorder=0)
            
            # 标注评分
            if i < len(evaluation_results):
                metrics = evaluation_results[i]['metrics']
                mid_idx = (start_idx + end_idx) // 2
                if mid_idx < len(t):
                    # 根据评分选择颜色
                    if metrics.overall_score >= 80:
                        color = 'green'
                    elif metrics.overall_score >= 60:
                        color = 'orange'
                    else:
                        color = 'red'
                    
                    ax1.text(t[mid_idx], np.max(pv) * 0.95,
                            f"段{i+1}\n{metrics.overall_score:.1f}分\n({metrics.grade})",
                            ha='center', va='top', fontsize=10,
                            bbox=dict(boxstyle='round', facecolor=color, alpha=0.3))
        
        ax1.set_ylabel('过程值 (PV/SV)', fontsize=12)
        ax1.set_title('PID控制过程 - 带性能评分', fontsize=14, fontweight='bold')
        ax1.legend(loc='best', fontsize=10)
        ax1.grid(True, alpha=0.3)
        
        # 子图2: 控制输出MV
        ax2 = axes[1]
        if mv is not None:
            ax2.plot(t, mv, 'g-', linewidth=2, label='控制输出MV', alpha=0.7)
            for start_idx, end_idx, _, _, _ in segments:
                ax2.axvspan(t[start_idx], t[min(end_idx, len(t) - 1)],
                           alpha=0.15, color='red', zorder=0)
        ax2.set_ylabel('控制输出 (MV)', fontsize=12)
        ax2.set_title('控制输出', fontsize=13, fontweight='bold')
        ax2.legend(loc='best', fontsize=10)
        ax2.grid(True, alpha=0.3)
        
        # 子图3: 评分对比
        ax3 = axes[2]
        if evaluation_results:
            segment_names = [r['segment_name'] for r in evaluation_results]
            scores = [r['metrics'].overall_score for r in evaluation_results]
            grades = [r['metrics'].grade for r in evaluation_results]
            
            # 根据评分设置颜色
            colors = []
            for score in scores:
                if score >= 80:
                    colors.append('green')
                elif score >= 60:
                    colors.append('orange')
                else:
                    colors.append('red')
            
            bars = ax3.bar(range(len(scores)), scores, color=colors, alpha=0.7)
            ax3.set_xticks(range(len(segment_names)))
            ax3.set_xticklabels(segment_names, rotation=0)
            ax3.set_ylabel('评分', fontsize=12)
            ax3.set_ylim(0, 100)
            ax3.axhline(y=60, color='orange', linestyle='--', alpha=0.5, label='及格线(60)')
            ax3.axhline(y=80, color='green', linestyle='--', alpha=0.5, label='优秀线(80)')
            ax3.set_title('各段性能评分对比', fontsize=13, fontweight='bold')
            ax3.legend(loc='best', fontsize=10)
            ax3.grid(True, alpha=0.3, axis='y')
            
            # 在柱状图上标注分数和等级
            for i, (bar, score, grade) in enumerate(zip(bars, scores, grades)):
                height = bar.get_height()
                ax3.text(bar.get_x() + bar.get_width()/2., height,
                        f'{score:.1f}\n({grade})',
                        ha='center', va='bottom', fontsize=10, fontweight='bold')
        
        ax3.set_xlabel('扰动段', fontsize=12)
        
        plt.tight_layout()
        
        # 保存图片
        if output_path is None:
            output_dir = os.path.join(current_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = os.path.join(output_dir, f"tuning_evaluation_{timestamp}.png")
        
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close(fig)
        print(f"\n✅ 评估可视化图已保存: {output_path}")


def run_tuning_evaluation(
    start_time: Union[int, str],
    end_time: Union[int, str],
    scenario_name: str = None
):
    """
    运行整定评估流程
    
    Args:
        start_time: 开始时间
        end_time: 结束时间
        scenario_name: 场景名称
    """
    try:
        # 时间转换
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        
        # 固定设备与字段
        table = "PID_FEP_Gateway_Device_001default"
        required_fields = [
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]
        
        # 查询历史数据
        print(f"\n正在查询数据: {start_time} 到 {end_time}")
        history_data = _query_tsdb_data_zhongkong(
            db='platform',
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=False,
            window=1
        )
        
        if not history_data or len(history_data) < 10:
            raise ValueError("数据不足")
        
        print(f"✓ 获取到 {len(history_data)} 条数据")
        
        # 创建工作流
        workflow = TuningEvaluationWorkflow()
        
        # 1. 加载数据
        data = workflow.load_json_data(history_data)
        print(f"✓ 数据加载完成")
        
        # 2. 检测扰动段
        detection_result = workflow.detect_disturbances(data)
        print(f"✓ 检测到 {len(detection_result['segments'])} 个扰动段")
        
        # 3. 评估所有扰动段
        evaluation_results = workflow.evaluate_all_segments(data, detection_result)
        
        # 4. 生成报告
        report = workflow.generate_evaluation_report()
        print("\n" + report)
        
        # 5. 可视化
        output_path = None
        if scenario_name:
            output_dir = os.path.join(current_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"{scenario_name}_evaluation.png")
        
        workflow.visualize_with_evaluation(
            data, detection_result, evaluation_results, output_path
        )
        
        return {
            'data': data,
            'detection': detection_result,
            'evaluation': evaluation_results,
            'report': report
        }
        
    except Exception as e:
        print(f"❌ 评估失败: {str(e)}")
        raise


if __name__ == "__main__":

    print("=" * 70)
    print("=" * 70)
    
    result = run_tuning_evaluation(
        start_time="2025-11-11 18:50:58",
        end_time="2025-11-11 20:08:58",
        scenario_name="20251111_tuning_eval"
    )
    
    print("\n" + "=" * 70)
    print("评估完成！")
    print("=" * 70)
