"""
简易整定模块 (Simple Tuning Module)
===================================

基于模型参数 {K, T1, T2, L} 计算 PID 参数，提供多种经典整定公式。
配合 ModelRating.evaluate() 使用可自动评分和选优。

用法:
    from core.algorithm.model_type.simple_tuning import SimpleTuning
    from core.algorithm.model_type.rating import ModelRating

    model = {'K': 1.5, 'T1': 30, 'T2': 0, 'L': 5}

    # 1. 获取所有整定方案
    all_results = SimpleTuning.tune_all(model)
    # → {'zn': {'Kp': .., 'Ki': .., 'Kd': ..}, 'lambda': {...}, ...}

    # 2. 自动选最优
    best = SimpleTuning.auto_tune(model)
    # → {'method': 'imc', 'pid': {...}, 'rating': 8.2, ...}
"""

from typing import Dict, List, Tuple, Optional


class SimpleTuning:
    """
    简易 PID 整定器
    
    所有方法为 @staticmethod，输入模型参数 → 输出 PID 参数。
    """
    
    @staticmethod
    def ziegler_nichols(model_params: Dict) -> Dict:
        """
        Ziegler-Nichols 开环法 (经典 ZN)
        
        适用: 一般过程，偏激进
        特点: 响应快，超调大 (约 25%)
        
        入参: {'K': float, 'T1': float, 'L': float}
        出参: {'Kp': float, 'Ki': float, 'Kd': float, 'method': str}
        """
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        L = max(model_params.get('L', 1.0), 0.1)
        
        r = T1 / L  # 可控比
        
        Kp = 1.2 * T1 / (K * L)
        Ti = 2.0 * L
        Td = 0.5 * L
        
        Ki = Kp / Ti if Ti > 0 else 0
        Kd = Kp * Td
        
        return {'Kp': round(Kp, 6), 'Ki': round(Ki, 6), 'Kd': round(Kd, 6), 'method': 'ziegler_nichols'}
    
    @staticmethod
    def cohen_coon(model_params: Dict) -> Dict:
        """
        Cohen-Coon 法
        
        适用: 滞后较大的过程 (L/T1 > 0.3)
        特点: 比 ZN 保守，对大滞后更鲁棒
        
        入参: {'K': float, 'T1': float, 'L': float}
        出参: {'Kp': float, 'Ki': float, 'Kd': float, 'method': str}
        """
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        L = max(model_params.get('L', 1.0), 0.1)
        
        r = L / T1
        
        Kp = (1.0 / (K * r)) * (1.33 + r / 4.0)
        Ti = L * (32.0 + 6.0 * r) / (13.0 + 8.0 * r)
        Td = L * 4.0 / (11.0 + 2.0 * r)
        
        Ki = Kp / Ti if Ti > 0 else 0
        Kd = Kp * Td
        
        return {'Kp': round(Kp, 6), 'Ki': round(Ki, 6), 'Kd': round(Kd, 6), 'method': 'cohen_coon'}
    
    @staticmethod
    def lambda_tuning(model_params: Dict, lambda_factor: float = 3.0) -> Dict:
        """
        Lambda 整定法
        
        适用: 需要无超调或极低超调的过程
        特点: 保守、平滑、无超调，响应偏慢
        
        入参:
            model_params: {'K': float, 'T1': float, 'L': float}
            lambda_factor: λ/L 比值 (默认 3.0，越大越保守)
        出参: {'Kp': float, 'Ki': float, 'Kd': float, 'method': str}
        """
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        L = max(model_params.get('L', 1.0), 0.1)
        
        lam = L * lambda_factor  # 期望闭环时间常数
        
        Kp = T1 / (K * (lam + L))
        Ti = T1
        Td = 0  # Lambda 法通常不用微分
        
        Ki = Kp / Ti if Ti > 0 else 0
        Kd = 0
        
        return {'Kp': round(Kp, 6), 'Ki': round(Ki, 6), 'Kd': round(Kd, 6), 'method': 'lambda'}
    
    @staticmethod
    def imc(model_params: Dict, aggressiveness: float = 0.5) -> Dict:
        """
        IMC 内模控制法
        
        适用: 大多数过程，工业最常用
        特点: 平衡快速性和鲁棒性，可调激进度
        
        入参:
            model_params: {'K': float, 'T1': float, 'T2': float, 'L': float}
            aggressiveness: 0-1，0=保守 1=激进 (默认 0.5)
        出参: {'Kp': float, 'Ki': float, 'Kd': float, 'method': str}
        """
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        T2 = model_params.get('T2', 0.0)
        L = max(model_params.get('L', 1.0), 0.1)
        
        # 期望闭环时间常数: 在 3*L (保守) 到 0.5*L (激进) 之间
        tau_c = L * (3.0 - 2.5 * aggressiveness)
        tau_c = max(tau_c, 0.2 * T1)  # 最少 0.2*T1 保底
        
        if T2 > 0.1:
            # 二阶 SOPDT
            Kp = (T1 + T2) / (K * (tau_c + L))
            Ti = T1 + T2
            Td = T1 * T2 / (T1 + T2)
        else:
            # 一阶 FOPDT
            Kp = T1 / (K * (tau_c + L))
            Ti = T1
            Td = 0
        
        Ki = Kp / Ti if Ti > 0 else 0
        Kd = Kp * Td
        
        return {'Kp': round(Kp, 6), 'Ki': round(Ki, 6), 'Kd': round(Kd, 6), 'method': 'imc'}
    
    @staticmethod
    def tyreus_luyben(model_params: Dict) -> Dict:
        """
        Tyreus-Luyben 法
        
        适用: 需要比 ZN 更稳健的场合
        特点: 超调更小 (<10%)，收敛更平稳
        
        入参: {'K': float, 'T1': float, 'L': float}
        出参: {'Kp': float, 'Ki': float, 'Kd': float, 'method': str}
        """
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        L = max(model_params.get('L', 1.0), 0.1)
        
        # 先用 ZN 估算临界增益和临界周期
        Ku = 1.2 * T1 / (K * L)  # 近似临界增益
        Pu = 4.0 * L              # 近似临界周期
        
        Kp = Ku / 3.2
        Ti = 2.2 * Pu
        Td = Pu / 6.3
        
        Ki = Kp / Ti if Ti > 0 else 0
        Kd = Kp * Td
        
        return {'Kp': round(Kp, 6), 'Ki': round(Ki, 6), 'Kd': round(Kd, 6), 'method': 'tyreus_luyben'}
    
    # ==================================================================
    # 便捷接口
    # ==================================================================
    
    @staticmethod
    def tune_all(model_params: Dict) -> Dict[str, Dict]:
        """
        用所有方法整定，返回全部结果
        
        入参: model_params: {'K': float, 'T1': float, 'T2': float, 'L': float}
        出参: {'zn': {pid}, 'cohen_coon': {pid}, 'lambda': {pid}, 'imc': {pid}, 'tyreus_luyben': {pid}}
        """
        return {
            'zn': SimpleTuning.ziegler_nichols(model_params),
            'cohen_coon': SimpleTuning.cohen_coon(model_params),
            'lambda': SimpleTuning.lambda_tuning(model_params),
            'imc': SimpleTuning.imc(model_params),
            'tyreus_luyben': SimpleTuning.tyreus_luyben(model_params),
        }
    
    @staticmethod
    def auto_tune(model_params: Dict, loop_type: str = 'flow') -> Dict:
        """
        自动选优：用所有方法整定，逐一仿真评分，选最优结果
        
        入参:
            model_params: {'K': float, 'T1': float, 'T2': float, 'L': float}
            loop_type: 回路类型
        出参:
            {
                'method': str,            # 最优方法名
                'pid': dict,              # 最优 PID 参数
                'rating': float,          # Layer 1 评分 (0-10)
                'all_results': [          # 所有方法结果 (按评分排序)
                    {'method': str, 'pid': dict, 'rating': float, 'simulation': dict},
                    ...
                ]
            }
        """
        from .rating import ModelRating
        
        all_pids = SimpleTuning.tune_all(model_params)
        results = []
        
        for name, pid in all_pids.items():
            try:
                eval_result = ModelRating.evaluate(
                    model_params, pid, method=name, loop_type=loop_type
                )
                results.append({
                    'method': name,
                    'pid': {k: v for k, v in pid.items() if k != 'method'},
                    'rating': eval_result['performance_score'],
                    'details': eval_result['performance_details'],
                    'simulation': {
                        'is_stable': eval_result['simulation']['is_stable'],
                        'overshoot': eval_result['simulation']['overshoot'],
                        'settling_time': eval_result['simulation']['settling_time'],
                        'steady_state_error': eval_result['simulation']['steady_state_error'],
                    },
                })
            except Exception:
                continue
        
        # 按评分排序
        results.sort(key=lambda x: x['rating'], reverse=True)
        
        best = results[0] if results else {'method': 'none', 'pid': {}, 'rating': 0}
        
        return {
            'method': best['method'],
            'pid': best.get('pid', {}),
            'rating': best['rating'],
            'all_results': results,
        }
