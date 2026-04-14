from typing import List, Tuple, Dict, Any
from enum import Enum
import numpy as np

class FallbackStrategy(Enum):
    REJECT = "reject"               # 1. 废弃成果：直接不给结果，打回给人工
    SAFE_PRESET = "preset"          # 2. 强塞安全低保：无论如何套用最保守的老掉牙参数 (绝对不震荡)
    CLIP_TO_BOUNDS = "clip"         # 3. 强制边缘裁剪：算法算出PB=10，但底线是40，就强拽到40 (折中方案)


class MechanismAuditor:
    """
    统一机理审核引擎 (Unified Mechanism Auditor) - OS 边界层
    
    无论算法底层是一万层神经网络的“大模型推理引擎”还是“常规专家系统”，
    任何输出最终参数（或模型参数）的行为，都必须经过此审计器的硬性约束检查。
    """
    
    @staticmethod
    def verify(os_constraints: Dict[str, Any], 
               tuning_output: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        纯粹的数据对接校验！
        
        Args:
            os_constraints: 从知识图谱/工厂中台拿到的红线约束字典
                            必须包含: time_constant_min/max, dead_time_min/max, 
                                     pb_min/max, expected_sign
            tuning_output: OutputBuilder 吐出来的 JSON 结果字典
            
        Returns:
            is_compliant: 是否合规通过
            violation_reasons: 违规详细理由列表
        """
        reasons = []
        
        if not tuning_output.get('success', False):
            # 如果它连算都没算成功，自然没法过机理验证
            return False, ["算法在生成阶段已失败 (success=False)"]
            
        model = tuning_output.get('model_parameters', {})
        pid = tuning_output.get('pid_parameters', {})
        
        # ==========================================
        # 1. 模型物理特征验证 (拦截幻觉辨识结果)
        # ==========================================
        
        # 1A. 时间常数 T1 拦截
        t1_min = os_constraints.get('time_constant_min', 0.0)
        t1_max = os_constraints.get('time_constant_max', float('inf'))
        if model.get('T1', 0) > 0:
            if model['T1'] < t1_min or model['T1'] > t1_max:
                reasons.append(f"T1 ({model['T1']}s) 越界，机理许可范围 [{t1_min}, {t1_max}]")
                
        # 1B. 纯滞后时间 L 拦截
        l_min = os_constraints.get('dead_time_min', 0.0)
        l_max = os_constraints.get('dead_time_max', float('inf'))
        if model.get('L', 0) > 0:
            if model['L'] < l_min or model['L'] > l_max:
                reasons.append(f"L ({model['L']}s) 越界，机理许可范围 [{l_min}, {l_max}]")
                
        # 1C. 过程增益正反作用一致性拦截
        expected_sign = os_constraints.get('expected_sign', 0)
        if expected_sign != 0 and model.get('K', 0) != 0:
            k_val = model['K']
            if (k_val > 0 and expected_sign < 0) or (k_val < 0 and expected_sign > 0):
                reasons.append(f"辨识增益 K ({k_val:.2f}) 符号与设备正反作用属性(Sign={expected_sign})冲突")
                
        # ==========================================
        # 2. 控制器安全底线验证 (防止发疯参数导致炸厂)
        # ==========================================
        
        # 2A. 比例带 PB 红线拦截 (极度危险)
        pb_min = os_constraints.get('pb_min', 10.0)
        pb_max = os_constraints.get('pb_max', 300.0)
        # 如果 tuning_output 里直接给了 pb，优先用；否则从 Kp 推算
        pb = pid.get('pb', 100.0 / abs(pid.get('Kp', 1.0)) if pid.get('Kp', 1.0) != 0 else float('inf'))
        
        if pb < pb_min or pb > pb_max:
            reasons.append(f"整定 PB ({pb:.1f}%) 突破安全专家红线 [{pb_min}%, {pb_max}%]")
            
        # 2B. 积分时间 Ti 底线拦截
        ti_max = os_constraints.get('ti_max', 300.0)
        ti_min = os_constraints.get('ti_min', 0.0)
        ti = pid.get('ti', 0)
        if ti > 0 and (ti < ti_min or ti > ti_max):
             reasons.append(f"积分时间 Ti ({ti:.1f}s) 突破安全防线 [{ti_min}s, {ti_max}s]")
                
        return len(reasons) == 0, reasons
        
    @staticmethod
    def enforce_fallback(os_constraints: Dict[str, Any], 
                         strategy: FallbackStrategy = FallbackStrategy.SAFE_PRESET,
                         violating_pid: Dict[str, float] = None) -> Dict[str, float]:
        """
        统一受罚与降级处理中心。提供三种可选的处罚力度。
        
        Args:
            os_constraints: 包含物理限制字典
            strategy: 惩罚策略选择
            violating_pid: 原本违规的 PID（仅在 CLIP 策略时需要）
            
        Returns:
            兜底后的安全 PID 字典（如果采取 REJECT，则返回 None）
        """
        if strategy == FallbackStrategy.REJECT:
            return None
            
        elif strategy == FallbackStrategy.SAFE_PRESET:
            # 策略2：强塞低保 (保守求稳)
            pb_max = os_constraints.get("pb_max", 300.0)    
            ti_max = os_constraints.get("ti_max", 120.0)
            
            kp_sign = os_constraints.get('expected_sign', 1) 
            if kp_sign == 0: kp_sign = 1
            
            kp_fallback = (100.0 / pb_max) * kp_sign
            
            return {
                'Kp': kp_fallback,
                'Ki': kp_fallback / ti_max if ti_max > 0 else 0.0,
                'Kd': 0.0,
                'pb': pb_max,
                'ti': ti_max,
                'td': 0.0
            }
            
        elif strategy == FallbackStrategy.CLIP_TO_BOUNDS:
            # 策略3：违纪裁剪 (刀法)
            if not violating_pid:
                return MechanismAuditor.enforce_fallback(os_constraints, FallbackStrategy.SAFE_PRESET)
                
            pb_min = os_constraints.get('pb_min', 10.0)
            pb_max = os_constraints.get('pb_max', 300.0)
            ti_max = os_constraints.get('ti_max', 120.0)
            ti_min = os_constraints.get('ti_min', 0.0)
            
            original_kp = violating_pid.get('Kp', 1.0)
            current_pb = violating_pid.get('pb', 100.0 / abs(original_kp) if original_kp != 0 else float('inf'))
            
            # 强制收束到机理范围内
            clamped_pb = max(pb_min, min(current_pb, pb_max))
            
            kp_sign = np.sign(original_kp) if original_kp != 0 else os_constraints.get('expected_sign', 1)
            new_kp = (100.0 / clamped_pb) * kp_sign
            
            # Ti 也裁剪
            current_ti = violating_pid.get('ti', float('inf'))
            if current_ti == 0: current_ti = float('inf')
            clamped_ti = max(ti_min, min(current_ti, ti_max))
            
            new_ki = new_kp / clamped_ti if clamped_ti > 0 else 0.0
            
            return {
                'Kp': new_kp,
                'Ki': new_ki,
                'Kd': violating_pid.get('Kd', 0.0),
                'pb': clamped_pb,
                'ti': clamped_ti,
                'td': violating_pid.get('td', 0.0),
            }
        
        return None

# =====================================================================
# 💡 调用示例及演示 (Run this file directly to see the example)
# =====================================================================
if __name__ == '__main__':
    print("=" * 60)
    print(" 🏭 场景：巨型储水罐液位控制 (大模型与常规算子统一接受机理安检)")
    print("=" * 60)
    
    # 门卫（Auditor）持有的从【数据机理中台】下载的安全红线：
    os_constraints = {
        'pb_min': 100.0,            # 专家红线：这可是巨型液位管，比例带绝不能低于 100%
        'pb_max': 400.0,
        'time_constant_min': 60.0,  # 物理红线：水满得再快也不可能 60秒内满
        'time_constant_max': 300.0,
        'dead_time_min': 5.0,
        'dead_time_max': 15.0,
        'expected_sign': 1          # 预期正作用
    }
    
    # 系统吐出的标准的、黑盒的 JSON：
    output_json = {
        'success': True,
        'model_parameters': {'K': -0.5, 'T1': 10.0, 'L': 6.0}, 
        'pid_parameters': {'Kp': 5.0, 'Ki': 0.1, 'Kd': 0.0, 'pb': 20.0, 'ti': 50.0}
    }
    
    print(f"👻 输出的激进结果: PB = {output_json['pid_parameters'].get('pb')}% (底线 100%), T1 = {output_json['model_parameters'].get('T1')}s (底线 60s)")
    
    # 1. 过安检门
    is_ok, reasons_list = MechanismAuditor.verify(os_constraints, output_json)
    
    print(f"\n👮 机理安检门验证通过? -> {is_ok}")
    print("📝 拦截原因日志:")
    for r in reasons_list:
        print(f"  ❌ {r}")
        
    # 2. 如果不合法，执行统一处罚（边缘限制裁剪）
    if not is_ok:
        print("\n🛡️ 触发防线：强制执行 [边缘裁剪 CLIP_TO_BOUNDS] 法案...")
        safe_pid = MechanismAuditor.enforce_fallback(
            os_constraints=os_constraints,
            strategy=FallbackStrategy.CLIP_TO_BOUNDS,
            violating_pid=output_json['pid_parameters']
        )
        print(f"✅ 发往下一级工业控制器的最终合法参数: {safe_pid}")
    print("=" * 60)

