"""
性能对比可视化
生成整定前后的对比图表
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from typing import Dict, Optional
import os


class ComparisonVisualizer:
    """性能对比可视化器"""
    
    def __init__(self):
        self.fig = None
        self.axes = None
    
    def plot_comparison(self,
                       comparison_data: Dict,
                       pv_original: Optional[np.ndarray] = None,
                       pv_tuned: Optional[np.ndarray] = None,
                       sv: Optional[np.ndarray] = None,
                       mv_original: Optional[np.ndarray] = None,
                       mv_tuned: Optional[np.ndarray] = None,
                       time: Optional[np.ndarray] = None,
                       save_path: Optional[str] = None,
                       show: bool = False) -> str:
        """
        绘制对比图表
        
        Args:
            comparison_data: 对比数据字典
            pv_original: 原始过程值
            pv_tuned: 整定后过程值
            sv: 设定值
            mv_original: 原始控制输出
            mv_tuned: 整定后控制输出
            time: 时间数组
            save_path: 保存路径
            show: 是否显示图表
            
        Returns:
            保存的文件路径
        """
        # 创建图形
        self.fig = plt.figure(figsize=(16, 10))
        gs = GridSpec(3, 2, figure=self.fig, hspace=0.3, wspace=0.3)
        
        # 1. PID参数对比（左上）
        ax1 = self.fig.add_subplot(gs[0, 0])
        self._plot_pid_comparison(ax1, comparison_data.get('pid_comparison', {}))
        
        # 2. 性能指标对比（右上）
        ax2 = self.fig.add_subplot(gs[0, 1])
        self._plot_performance_comparison(ax2, comparison_data.get('performance_comparison', {}))
        
        # 3. 过程值对比（中间）
        if pv_original is not None and pv_tuned is not None and sv is not None:
            ax3 = self.fig.add_subplot(gs[1, :])
            self._plot_pv_comparison(ax3, pv_original, pv_tuned, sv, time)
        
        # 4. 控制输出对比（左下）
        if mv_original is not None and mv_tuned is not None:
            ax4 = self.fig.add_subplot(gs[2, 0])
            self._plot_mv_comparison(ax4, mv_original, mv_tuned, time)
        
        # 5. 误差分析（右下）
        if pv_original is not None and pv_tuned is not None and sv is not None:
            ax5 = self.fig.add_subplot(gs[2, 1])
            self._plot_error_analysis(ax5, pv_original, pv_tuned, sv, time)
        
        # 添加总标题
        summary = comparison_data.get('improvement_summary', {})
        overall = summary.get('overall_assessment', '对比分析')
        self.fig.suptitle(f'PID整定性能对比 - {overall}', 
                         fontsize=16, fontweight='bold', y=0.98)
        
        # 保存图形
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"✅ 对比图表已保存: {save_path}")
        
        if show:
            plt.show()
        else:
            plt.close()
        
        return save_path if save_path else ""
    
    def _plot_pid_comparison(self, ax, pid_data: Dict):
        """绘制PID参数对比柱状图"""
        if not pid_data:
            ax.text(0.5, 0.5, '无PID参数数据', ha='center', va='center', transform=ax.transAxes)
            ax.set_title('PID参数对比')
            ax.axis('off')
            return
        
        original = pid_data.get('original', {})
        tuned = pid_data.get('tuned', {})
        
        params = ['Kp', 'Ki', 'Kd']
        x = np.arange(len(params))
        width = 0.35
        
        original_values = [original.get(p, 0) for p in params]
        tuned_values = [tuned.get(p, 0) for p in params]
        
        # 检查是否所有值都为0或很小
        max_val = max(max(original_values), max(tuned_values))
        if max_val < 1e-6:
            # 使用表格形式显示参数（即使为0也能看到）
            ax.axis('off')
            ax.set_title('PID Parameters Comparison', fontsize=12, fontweight='bold', pad=20)
            
            # 创建表格数据
            table_data = [
                ['Param', 'Before', 'After', 'Change'],
                ['Kp', f'{original.get("Kp", 0):.4f}', f'{tuned.get("Kp", 0):.4f}', 
                 f'{tuned.get("Kp", 0) - original.get("Kp", 0):+.4f}'],
                ['Ki', f'{original.get("Ki", 0):.4f}', f'{tuned.get("Ki", 0):.4f}', 
                 f'{tuned.get("Ki", 0) - original.get("Ki", 0):+.4f}'],
                ['Kd', f'{original.get("Kd", 0):.4f}', f'{tuned.get("Kd", 0):.4f}', 
                 f'{tuned.get("Kd", 0) - original.get("Kd", 0):+.4f}']
            ]
            
            # 绘制表格
            table = ax.table(cellText=table_data, cellLoc='center', loc='center',
                           colWidths=[0.2, 0.25, 0.25, 0.3])
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 2)
            
            # 设置表头样式
            for i in range(4):
                table[(0, i)].set_facecolor('#4ECDC4')
                table[(0, i)].set_text_props(weight='bold', color='white')
            
            # 设置行颜色
            for i in range(1, 4):
                for j in range(4):
                    if i % 2 == 0:
                        table[(i, j)].set_facecolor('#F0F0F0')
            
            return
        
        bars1 = ax.bar(x - width/2, original_values, width, label='Before', alpha=0.8, color='#FF6B6B')
        bars2 = ax.bar(x + width/2, tuned_values, width, label='After', alpha=0.8, color='#4ECDC4')
        
        ax.set_xlabel('Parameter', fontsize=10)
        ax.set_ylabel('Value', fontsize=10)
        ax.set_title('PID Parameters Comparison', fontsize=12, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(params)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        # 设置合适的y轴范围
        if max_val > 0:
            ax.set_ylim(0, max_val * 1.2)
        
        # 添加数值标签
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                if height > 1e-6:
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{height:.3f}',
                           ha='center', va='bottom', fontsize=8)
    
    def _plot_performance_comparison(self, ax, perf_data: Dict):
        """绘制性能指标对比"""
        if not perf_data or 'improvements' not in perf_data:
            ax.text(0.5, 0.5, 'No Performance Data', ha='center', va='center', 
                   transform=ax.transAxes, fontsize=11)
            ax.set_title('Performance Comparison', fontsize=12, fontweight='bold')
            ax.axis('off')
            return
        
        improvements = perf_data['improvements']
        
        # 提取评分数据
        if 'score' in improvements:
            score_data = improvements['score']
            orig_score = score_data.get('original', 0)
            tuned_score = score_data.get('tuned', 0)
            
            # 检查评分是否有效
            if orig_score <= 0 and tuned_score <= 0:
                ax.text(0.5, 0.5, 'Invalid Score Data', ha='center', va='center', 
                       transform=ax.transAxes, fontsize=11)
                ax.set_title('Performance Score', fontsize=12, fontweight='bold')
                ax.axis('off')
                return
            
            # 绘制评分对比
            scores = [orig_score, tuned_score]
            labels = ['Before', 'After']
            colors = ['#FF6B6B', '#4ECDC4']
            
            bars = ax.barh(labels, scores, color=colors, alpha=0.8, height=0.5)
            
            ax.set_xlabel('Score', fontsize=10)
            ax.set_title('Performance Score Comparison', fontsize=12, fontweight='bold')
            ax.set_xlim(0, 100)
            ax.grid(True, alpha=0.3, axis='x')
            
            # 添加数值标签
            for i, (bar, score) in enumerate(zip(bars, scores)):
                if score > 0:
                    ax.text(score + 2, i, f'{score:.1f}', 
                           va='center', fontsize=10, fontweight='bold')
            
            # 添加等级标签
            orig_grade = score_data.get('original_grade', self._get_grade(orig_score))
            tuned_grade = score_data.get('tuned_grade', self._get_grade(tuned_score))
            ax.text(-5, 0, f'[{orig_grade}]', va='center', ha='right', fontsize=9, color='gray')
            ax.text(-5, 1, f'[{tuned_grade}]', va='center', ha='right', fontsize=9, color='gray')
            
            # 添加改进信息
            improvement = tuned_score - orig_score
            if abs(improvement) > 0.1:
                color = 'green' if improvement > 0 else 'red'
                symbol = '+' if improvement > 0 else '-'
                ax.text(0.98, 0.02, f'{symbol}{abs(improvement):.1f}', 
                       transform=ax.transAxes, ha='right', va='bottom',
                       fontsize=11, fontweight='bold', color=color,
                       bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=color))
        else:
            ax.text(0.5, 0.5, 'No Score Data', ha='center', va='center', 
                   transform=ax.transAxes, fontsize=11)
            ax.set_title('Performance Score', fontsize=12, fontweight='bold')
            ax.axis('off')
    
    def _get_grade(self, score):
        """根据评分获取等级"""
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'
    
    def _plot_pv_comparison(self, ax, pv_original, pv_tuned, sv, time):
        """绘制过程值对比"""
        if time is None:
            time = np.arange(len(pv_original))
        
        ax.plot(time, sv, 'k--', label='设定值 (SV)', linewidth=2, alpha=0.7)
        ax.plot(time, pv_original, label='整定前 (PV)', color='#FF6B6B', linewidth=1.5, alpha=0.8)
        ax.plot(time, pv_tuned, label='整定后 (PV)', color='#4ECDC4', linewidth=1.5, alpha=0.8)
        
        ax.set_xlabel('时间 (s)', fontsize=10)
        ax.set_ylabel('过程值', fontsize=10)
        ax.set_title('过程值对比', fontsize=12, fontweight='bold')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
    
    def _plot_mv_comparison(self, ax, mv_original, mv_tuned, time):
        """绘制控制输出对比"""
        if time is None:
            time = np.arange(len(mv_original))
        
        ax.plot(time, mv_original, label='整定前 (MV)', color='#FF6B6B', linewidth=1.5, alpha=0.8)
        ax.plot(time, mv_tuned, label='整定后 (MV)', color='#4ECDC4', linewidth=1.5, alpha=0.8)
        
        ax.set_xlabel('时间 (s)', fontsize=10)
        ax.set_ylabel('控制输出', fontsize=10)
        ax.set_title('控制输出对比', fontsize=12, fontweight='bold')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        # 计算并显示控制量变化
        tv_original = np.sum(np.abs(np.diff(mv_original)))
        tv_tuned = np.sum(np.abs(np.diff(mv_tuned)))
        tv_change = ((tv_tuned - tv_original) / tv_original * 100) if tv_original > 0 else 0
        
        info_text = f'控制量变化: {tv_change:+.1f}%'
        ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
               va='top', ha='left', fontsize=9,
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    def _plot_error_analysis(self, ax, pv_original, pv_tuned, sv, time):
        """绘制误差分析"""
        error_original = np.abs(pv_original - sv)
        error_tuned = np.abs(pv_tuned - sv)
        
        if time is None:
            time = np.arange(len(error_original))
        
        ax.plot(time, error_original, label='整定前误差', color='#FF6B6B', linewidth=1.5, alpha=0.8)
        ax.plot(time, error_tuned, label='整定后误差', color='#4ECDC4', linewidth=1.5, alpha=0.8)
        
        # 添加平均误差线
        mae_original = np.mean(error_original)
        mae_tuned = np.mean(error_tuned)
        ax.axhline(mae_original, color='#FF6B6B', linestyle=':', alpha=0.5, linewidth=1)
        ax.axhline(mae_tuned, color='#4ECDC4', linestyle=':', alpha=0.5, linewidth=1)
        
        ax.set_xlabel('时间 (s)', fontsize=10)
        ax.set_ylabel('绝对误差', fontsize=10)
        ax.set_title('误差分析', fontsize=12, fontweight='bold')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        # 显示误差改进
        error_improvement = ((mae_original - mae_tuned) / mae_original * 100) if mae_original > 0 else 0
        color = 'green' if error_improvement > 0 else 'red'
        symbol = '↓' if error_improvement > 0 else '↑'
        
        info_text = f'平均误差{symbol} {abs(error_improvement):.1f}%\n'
        info_text += f'整定前: {mae_original:.3f}\n'
        info_text += f'整定后: {mae_tuned:.3f}'
        
        ax.text(0.98, 0.98, info_text, transform=ax.transAxes, 
               va='top', ha='right', fontsize=9,
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    def plot_metrics_comparison_table(self, comparison_data: Dict, save_path: Optional[str] = None):
        """绘制性能指标对比表格"""
        perf_data = comparison_data.get('performance_comparison', {})
        if not perf_data or 'improvements' not in perf_data:
            print("⚠️ 无性能数据可绘制")
            return
        
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.axis('tight')
        ax.axis('off')
        
        # 准备表格数据
        improvements = perf_data['improvements']
        table_data = [['指标', '整定前', '整定后', '改进幅度', '状态']]
        
        for metric, data in improvements.items():
            if metric == 'score':
                name = '综合评分'
                orig = f"{data['original']:.1f}"
                tuned = f"{data['tuned']:.1f}"
                improvement = f"{data['absolute_change']:+.1f}"
            else:
                name = metric
                orig = f"{data['original']:.4f}"
                tuned = f"{data['tuned']:.4f}"
                improvement = f"{data['improvement_percentage']:+.1f}%"
            
            status = '✓ 改进' if data.get('improved', False) else '✗ 变差'
            table_data.append([name, orig, tuned, improvement, status])
        
        # 创建表格
        table = ax.table(cellText=table_data, cellLoc='center', loc='center',
                        colWidths=[0.25, 0.15, 0.15, 0.15, 0.15])
        
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 2)
        
        # 设置表头样式
        for i in range(5):
            table[(0, i)].set_facecolor('#4ECDC4')
            table[(0, i)].set_text_props(weight='bold', color='white')
        
        # 设置行颜色
        for i in range(1, len(table_data)):
            for j in range(5):
                if i % 2 == 0:
                    table[(i, j)].set_facecolor('#F0F0F0')
        
        plt.title('性能指标详细对比', fontsize=14, fontweight='bold', pad=20)
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"✅ 对比表格已保存: {save_path}")
        
        plt.close()
