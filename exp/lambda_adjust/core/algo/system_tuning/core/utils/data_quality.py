"""
数据质量检查模块
用于在整定前评估数据质量，避免低质量数据导致整定失败
"""
import numpy as np
from typing import Tuple, Dict, List
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config, DataQualityError, InsufficientDataError


class DataQualityChecker:
    """数据质量检查器"""
    
    def __init__(self, requirements: Dict = None):
        """
        初始化数据质量检查器
        
        Args:
            requirements: 数据质量要求字典，如果为None则使用默认配置
        """
        self.requirements = requirements or Config.DATA_QUALITY_REQUIREMENTS
    
    def assess_data_quality(self, 
                           t: np.ndarray, 
                           pv: np.ndarray, 
                           mv: np.ndarray = None, 
                           sv: np.ndarray = None) -> Tuple[bool, str, Dict]:
        """
        评估数据质量
        
        Args:
            t: 时间数组
            pv: 过程变量数组
            mv: 操作变量数组（可选）
            sv: 设定值数组（可选）
            
        Returns:
            (is_valid, message, details): 
                - is_valid: 数据质量是否合格
                - message: 评估结果消息
                - details: 详细的检查结果
        """
        checks = {}
        issues = []
        warnings = []
        
        # 1. 数据长度检查
        data_length = len(pv)
        min_length = self.requirements['min_length']
        checks['sufficient_length'] = data_length >= min_length
        if not checks['sufficient_length']:
            issues.append(f"数据长度不足: {data_length} < {min_length}")
        
        # 2. PV变化检查
        pv_std = np.std(pv)
        min_pv_std = self.requirements['min_pv_std']
        checks['sufficient_pv_variation'] = pv_std > min_pv_std
        if not checks['sufficient_pv_variation']:
            issues.append(f"PV变化不足: std={pv_std:.4f} < {min_pv_std}")
        
        # 3. MV变化检查（如果提供）
        if mv is not None and len(mv) == len(pv):
            mv_std = np.std(mv)
            min_mv_std = self.requirements['min_mv_std']
            checks['sufficient_mv_variation'] = mv_std > min_mv_std
            if not checks['sufficient_mv_variation']:
                warnings.append(f"MV变化不足: std={mv_std:.4f} < {min_mv_std}")
        else:
            checks['sufficient_mv_variation'] = None
            warnings.append("未提供MV数据或长度不匹配")
        
        # 4. 信噪比检查
        snr = self._calculate_snr(pv)
        min_snr = self.requirements['min_snr']
        checks['sufficient_snr'] = snr > min_snr
        if not checks['sufficient_snr']:
            warnings.append(f"信噪比偏低: SNR={snr:.2f} < {min_snr}")
        
        # 5. 缺失数据检查
        missing_ratio = self._check_missing_data(t, pv)
        max_missing_ratio = self.requirements['max_missing_ratio']
        checks['no_excessive_missing'] = missing_ratio < max_missing_ratio
        if not checks['no_excessive_missing']:
            issues.append(f"缺失数据过多: {missing_ratio*100:.1f}% > {max_missing_ratio*100:.1f}%")
        
        # 6. 采样一致性检查
        sampling_jitter = self._check_sampling_consistency(t)
        max_jitter = self.requirements['max_sampling_jitter']
        checks['consistent_sampling'] = sampling_jitter < max_jitter
        if not checks['consistent_sampling']:
            warnings.append(f"采样间隔不均匀: 抖动率={sampling_jitter*100:.1f}% > {max_jitter*100:.1f}%")
        
        # 7. 数据范围检查
        pv_range = np.max(pv) - np.min(pv)
        checks['reasonable_range'] = pv_range > Config.EPSILON
        if not checks['reasonable_range']:
            issues.append(f"PV数据无变化: range={pv_range:.6f}")
        
        # 8. NaN/Inf检查
        has_nan_inf = np.any(np.isnan(pv)) or np.any(np.isinf(pv))
        checks['no_nan_inf'] = not has_nan_inf
        if has_nan_inf:
            issues.append("数据包含NaN或Inf值")
        
        # 综合判断
        critical_checks = ['sufficient_length', 'sufficient_pv_variation', 
                          'no_excessive_missing', 'reasonable_range', 'no_nan_inf']
        is_valid = all(checks.get(key, False) for key in critical_checks)
        
        # 生成消息
        if is_valid:
            if warnings:
                message = f"数据质量合格（有{len(warnings)}个警告）"
            else:
                message = "数据质量优秀"
        else:
            message = f"数据质量不足: {', '.join(issues)}"
        
        # 详细结果
        details = {
            'checks': checks,
            'issues': issues,
            'warnings': warnings,
            'metrics': {
                'data_length': data_length,
                'pv_std': pv_std,
                'mv_std': np.std(mv) if mv is not None else None,
                'snr': snr,
                'missing_ratio': missing_ratio,
                'sampling_jitter': sampling_jitter,
                'pv_range': pv_range
            }
        }
        
        return is_valid, message, details
    
    def _calculate_snr(self, data: np.ndarray) -> float:
        """
        计算信噪比
        
        Args:
            data: 数据数组
            
        Returns:
            信噪比（dB）
        """
        if len(data) < 2:
            return 0.0
        
        # 信号功率：数据的标准差
        signal_power = np.std(data)
        
        # 噪声功率：一阶差分的标准差
        noise_power = np.std(np.diff(data))
        
        if noise_power < Config.EPSILON:
            return 100.0  # 噪声极小，认为SNR很高
        
        snr = signal_power / noise_power
        return snr
    
    def _check_missing_data(self, t: np.ndarray, data: np.ndarray) -> float:
        """
        检查缺失数据比例
        
        Args:
            t: 时间数组
            data: 数据数组
            
        Returns:
            缺失数据比例（0-1）
        """
        if len(t) < 2:
            return 0.0
        
        # 计算期望的采样间隔
        dt_median = np.median(np.diff(t))
        
        # 检测大间隔（可能是缺失数据）
        dt_array = np.diff(t)
        large_gaps = dt_array > dt_median * 2.0
        
        # 估算缺失数据点数
        missing_points = np.sum((dt_array[large_gaps] - dt_median) / dt_median)
        total_expected_points = len(t) + missing_points
        
        missing_ratio = missing_points / total_expected_points if total_expected_points > 0 else 0.0
        return missing_ratio
    
    def _check_sampling_consistency(self, t: np.ndarray) -> float:
        """
        检查采样一致性
        
        Args:
            t: 时间数组
            
        Returns:
            采样抖动率（0-1）
        """
        if len(t) < 2:
            return 0.0
        
        dt_array = np.diff(t)
        dt_mean = np.mean(dt_array)
        
        if dt_mean < Config.EPSILON:
            return 1.0  # 采样间隔为0，认为抖动率最大
        
        # 计算相对标准差（变异系数）
        dt_std = np.std(dt_array)
        jitter = dt_std / dt_mean
        
        return jitter
    
    def raise_if_invalid(self, 
                        t: np.ndarray, 
                        pv: np.ndarray, 
                        mv: np.ndarray = None, 
                        sv: np.ndarray = None):
        """
        检查数据质量，如果不合格则抛出异常
        
        Args:
            t: 时间数组
            pv: 过程变量数组
            mv: 操作变量数组（可选）
            sv: 设定值数组（可选）
            
        Raises:
            DataQualityError: 数据质量不合格
            InsufficientDataError: 数据量不足
        """
        is_valid, message, details = self.assess_data_quality(t, pv, mv, sv)
        
        if not is_valid:
            # 检查是否是数据量不足
            if not details['checks'].get('sufficient_length', False):
                raise InsufficientDataError(message)
            else:
                raise DataQualityError(message)
    
    def print_quality_report(self, 
                            t: np.ndarray, 
                            pv: np.ndarray, 
                            mv: np.ndarray = None, 
                            sv: np.ndarray = None):
        """
        打印数据质量报告
        
        Args:
            t: 时间数组
            pv: 过程变量数组
            mv: 操作变量数组（可选）
            sv: 设定值数组（可选）
        """
        is_valid, message, details = self.assess_data_quality(t, pv, mv, sv)
        
        print("\n" + "="*60)
        print("数据质量评估报告")
        print("="*60)
        print(f"\n总体评估: {message}")
        print(f"数据质量: {'✓ 合格' if is_valid else '✗ 不合格'}")
        
        print("\n【检查项目】")
        for key, value in details['checks'].items():
            if value is None:
                status = "⚠ 跳过"
            elif value:
                status = "✓ 通过"
            else:
                status = "✗ 失败"
            print(f"  {key}: {status}")
        
        print("\n【数据指标】")
        metrics = details['metrics']
        print(f"  数据长度: {metrics['data_length']}")
        print(f"  PV标准差: {metrics['pv_std']:.4f}")
        if metrics['mv_std'] is not None:
            print(f"  MV标准差: {metrics['mv_std']:.4f}")
        print(f"  信噪比: {metrics['snr']:.2f}")
        print(f"  缺失数据比例: {metrics['missing_ratio']*100:.2f}%")
        print(f"  采样抖动率: {metrics['sampling_jitter']*100:.2f}%")
        print(f"  PV变化范围: {metrics['pv_range']:.4f}")
        
        if details['issues']:
            print("\n【问题】")
            for issue in details['issues']:
                print(f"  ✗ {issue}")
        
        if details['warnings']:
            print("\n【警告】")
            for warning in details['warnings']:
                print(f"  ⚠ {warning}")
        
        print("="*60 + "\n")
