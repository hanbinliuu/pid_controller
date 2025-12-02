"""
整定报告生成器
集成现有模块的输出，生成结构化报告
"""
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import json


def convert_to_serializable(obj):
    """将numpy类型转换为Python原生类型，以支持JSON序列化"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_to_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_to_serializable(item) for item in obj)
    return obj


class TuningReportGenerator:
    """PID整定报告生成器"""
    
    def __init__(self):
        self.report_data = {}
    
    def generate_report(self,
                       case_type: str,
                       original_pid: Dict[str, float],
                       tuned_pid: Dict[str, float],
                       model_params: Dict[str, Any],
                       evaluation_metrics: Dict[str, Any],
                       non_steady_segments: List[tuple],
                       pv_data: Optional[np.ndarray] = None,
                       sv_data: Optional[np.ndarray] = None,
                       timestamp: Optional[str] = None) -> Dict:
        """
        生成完整的整定报告
        
        Args:
            case_type: 案例类型 (CASE_1/CASE_2/CASE_3)
            original_pid: 原始PID参数
            tuned_pid: 整定后PID参数
            model_params: 模型参数
            evaluation_metrics: 评估指标
            non_steady_segments: 非稳态段列表
            pv_data: PV数据（可选）
            sv_data: SV数据（可选）
            timestamp: 时间戳（可选）
            
        Returns:
            结构化报告字典
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = {
            "metadata": {
                "timestamp": timestamp,
                "case_type": case_type,
                "data_points": len(pv_data) if pv_data is not None else 0
            },
            "diagnosis": self._generate_diagnosis(case_type, non_steady_segments),
            "pid_parameters": {
                "original": original_pid,
                "tuned": tuned_pid,
                "changes": self._calculate_pid_changes(original_pid, tuned_pid)
            },
            "model_identification": model_params,
            "performance_evaluation": evaluation_metrics,
            "recommendations": self._generate_recommendations(
                case_type, evaluation_metrics, tuned_pid
            ),
            "summary": self._generate_summary(
                case_type, original_pid, tuned_pid, evaluation_metrics
            )
        }
        
        self.report_data = report
        return report
    
    def _generate_diagnosis(self, case_type: str, non_steady_segments: List[tuple]) -> Dict:
        """生成诊断信息"""
        diagnosis_map = {
            "CASE_1": {
                "type": "冷启动非稳态",
                "description": "系统从初始状态启动，初始PID参数不合适导致非稳态",
                "severity": "高",
                "action_required": "需要立即整定"
            },
            "CASE_2": {
                "type": "设定值调整",
                "description": "设定值手动调整导致的过渡过程",
                "severity": "中",
                "action_required": "检查调整后是否稳态"
            },
            "CASE_3": {
                "type": "扰动引起非稳态",
                "description": "原本稳态的系统受到扰动后出现非稳态",
                "severity": "高",
                "action_required": "需要重新整定"
            },
            "ALREADY_STABLE": {
                "type": "全程稳态",
                "description": "系统运行稳定，无需整定",
                "severity": "低",
                "action_required": "无需操作"
            }
        }
        
        diagnosis = diagnosis_map.get(case_type, {
            "type": "未知",
            "description": "无法判断系统状态",
            "severity": "未知",
            "action_required": "需要人工检查"
        })
        
        diagnosis["non_steady_segments_count"] = len(non_steady_segments)
        diagnosis["non_steady_segments"] = [
            {"start": int(seg[0]), "end": int(seg[1]), "setpoint": float(seg[2])}
            for seg in non_steady_segments
        ]
        
        return diagnosis
    
    def _calculate_pid_changes(self, original: Dict, tuned: Dict) -> Dict:
        """计算PID参数变化"""
        changes = {}
        for key in ['Kp', 'Ki', 'Kd']:
            if key in original and key in tuned:
                orig_val = original[key]
                tuned_val = tuned[key]
                if orig_val != 0:
                    change_pct = ((tuned_val - orig_val) / orig_val) * 100
                else:
                    change_pct = 0 if tuned_val == 0 else float('inf')
                
                changes[key] = {
                    "absolute": round(tuned_val - orig_val, 4),
                    "percentage": round(change_pct, 2)
                }
        
        return changes
    
    def _generate_recommendations(self, case_type: str, 
                                  evaluation_metrics: Dict,
                                  tuned_pid: Dict) -> List[str]:
        """生成优化建议"""
        recommendations = []
        
        # 基于评估指标的建议
        if 'overall' in evaluation_metrics:
            score = evaluation_metrics['overall'].get('score', 0)
            grade = evaluation_metrics['overall'].get('grade', 'F')
            
            if score < 60:
                recommendations.append("⚠️ 整定效果不理想，建议检查模型辨识质量")
            elif score < 80:
                recommendations.append("✓ 整定效果良好，可考虑进一步微调")
            else:
                recommendations.append("✓✓ 整定效果优秀，参数可直接使用")
        
        # 基于振荡的建议
        if 'oscillation' in evaluation_metrics:
            osc_count = evaluation_metrics['oscillation'].get('oscillation_count', 0)
            if osc_count > 5:
                recommendations.append("⚠️ 检测到较多振荡，建议降低Kp或增加Kd")
        
        # 基于稳态误差的建议
        if 'steady_state' in evaluation_metrics:
            sse = evaluation_metrics['steady_state'].get('steady_state_error', 0)
            if sse > 0.5:
                recommendations.append("⚠️ 稳态误差较大，建议增加Ki")
        
        # 基于控制平滑性的建议
        if 'control_smoothness' in evaluation_metrics:
            tv = evaluation_metrics['control_smoothness'].get('total_variation', 0)
            if tv > 100:
                recommendations.append("⚠️ 控制输出变化频繁，建议增加滤波或降低Kd")
        
        # 基于案例类型的建议
        if case_type == "CASE_1":
            recommendations.append("💡 冷启动场景，建议进行多次验证")
        elif case_type == "CASE_3":
            recommendations.append("💡 扰动场景，建议监控扰动源并考虑前馈控制")
        
        return recommendations if recommendations else ["✓ 当前参数表现良好"]
    
    def _generate_summary(self, case_type: str, original_pid: Dict,
                         tuned_pid: Dict, evaluation_metrics: Dict) -> str:
        """生成摘要"""
        score = evaluation_metrics.get('overall', {}).get('score', 0)
        grade = evaluation_metrics.get('overall', {}).get('grade', 'F')
        
        summary = f"系统诊断为{case_type}，"
        summary += f"整定后性能评分{score:.1f}分（等级{grade}）。"
        
        # 参数变化摘要
        kp_change = ((tuned_pid.get('Kp', 0) - original_pid.get('Kp', 0)) / 
                     original_pid.get('Kp', 1)) * 100 if original_pid.get('Kp', 0) != 0 else 0
        
        if abs(kp_change) > 50:
            summary += f"Kp调整幅度较大（{kp_change:+.1f}%），"
        
        if score >= 80:
            summary += "整定效果优秀，建议采用。"
        elif score >= 60:
            summary += "整定效果良好，可以使用。"
        else:
            summary += "整定效果欠佳，建议重新评估。"
        
        return summary
    
    def export_to_json(self, filepath: str):
        """导出为JSON格式"""
        # 转换所有numpy类型为Python原生类型
        serializable_data = convert_to_serializable(self.report_data)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(serializable_data, f, indent=2, ensure_ascii=False)
    
    def export_to_markdown(self, filepath: str):
        """导出为Markdown格式"""
        if not self.report_data:
            raise ValueError("No report data to export")
        
        md_content = self._format_markdown()
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
    
    def _format_markdown(self) -> str:
        """格式化为Markdown"""
        report = self.report_data
        
        md = f"# PID整定报告\n\n"
        md += f"**生成时间**: {report['metadata']['timestamp']}\n\n"
        
        # 诊断信息
        md += "## 系统诊断\n\n"
        diag = report['diagnosis']
        md += f"- **类型**: {diag['type']}\n"
        md += f"- **描述**: {diag['description']}\n"
        md += f"- **严重程度**: {diag['severity']}\n"
        md += f"- **建议操作**: {diag['action_required']}\n"
        md += f"- **非稳态段数量**: {diag['non_steady_segments_count']}\n\n"
        
        # PID参数
        md += "## PID参数对比\n\n"
        md += "| 参数 | 原始值 | 整定值 | 变化量 | 变化率 |\n"
        md += "|------|--------|--------|--------|--------|\n"
        
        pid_params = report['pid_parameters']
        for key in ['Kp', 'Ki', 'Kd']:
            orig = pid_params['original'].get(key, 0)
            tuned = pid_params['tuned'].get(key, 0)
            change = pid_params['changes'].get(key, {})
            abs_change = change.get('absolute', 0)
            pct_change = change.get('percentage', 0)
            md += f"| {key} | {orig:.4f} | {tuned:.4f} | {abs_change:+.4f} | {pct_change:+.2f}% |\n"
        
        md += "\n"
        
        # 性能评估
        md += "## 性能评估\n\n"
        metrics = report['performance_evaluation']
        
        if 'overall' in metrics:
            overall = metrics['overall']
            md += f"**综合评分**: {overall.get('score', 0):.2f} / 100\n\n"
            md += f"**等级**: {overall.get('grade', 'N/A')}\n\n"
        
        if 'steady_state' in metrics:
            ss = metrics['steady_state']
            md += "### 稳态性能\n\n"
            md += f"- 稳态误差: {ss.get('steady_state_error', 0):.4f}\n"
            md += f"- IAE: {ss.get('iae', 0):.4f}\n"
            md += f"- ISE: {ss.get('ise', 0):.4f}\n\n"
        
        if 'oscillation' in metrics:
            osc = metrics['oscillation']
            md += "### 振荡分析\n\n"
            md += f"- 振荡次数: {osc.get('oscillation_count', 0)}\n"
            md += f"- 最大振幅: {osc.get('max_amplitude', 0):.4f}\n\n"
        
        # 建议
        md += "## 优化建议\n\n"
        for rec in report['recommendations']:
            md += f"- {rec}\n"
        
        md += f"\n## 总结\n\n{report['summary']}\n"
        
        return md
    
    def print_summary(self):
        """打印报告摘要"""
        if not self.report_data:
            print("No report data available")
            return
        
        print("\n" + "="*60)
        print("PID整定报告摘要")
        print("="*60)
        print(f"\n{self.report_data['summary']}\n")
        print("详细建议:")
        for rec in self.report_data['recommendations']:
            print(f"  {rec}")
        print("="*60 + "\n")
