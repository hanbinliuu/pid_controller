from typing import List, Tuple, Dict, Any
from enum import Enum
import numpy as np

from ...pipeline.context import TuningContext

class FallbackStrategy(Enum):
    REJECT = "reject"               # 1. 废弃成果：直接不给结果，打回给人工
    SAFE_PRESET = "preset"          # 2. 强塞安全低保：无论如何套用最保守的老掉牙参数 (绝对不震荡)
    CLIP_TO_BOUNDS = "clip"         # 3. 强制边缘裁剪：算法算出PB=10，但底线是40，就强拽到40 (折中方案)


class MechanismAuditor:
    """
    统一机理审核引擎 (Unified Mechanism Auditor)
    
    无论算法底层是“常规阶跃辨识引擎”还是“大模型推理引擎”，
    任何输出最终参数（或模型参数）的行为，都必须经过此审计器的硬性约束检查。
    """
    
    @staticmethod
    def verify(context: TuningContext, 
               optimized_pid: Dict[str, float] = None) -> Tuple[bool, List[str]]:
        """
        验证给定上下文和参数是否符合预先设定的语义模型安检门。
        
        Args:
            context: 携带 MechanismModel, KnowledgeModel 的 TuningContext 上下文包裹
            optimized_pid: 算法提议的最终 PID 字典 (需包含 'Kp')
            
        Returns:
            is_compliant: 是否合规通过
            violation_reasons: 违规详细理由列表
        """
        reasons = []
        fusion = context.fusion_result
        
        # ==========================================
        # 1. 模型物理特征验证 (审核辨识模块/大模型算得的稳态模型)
        # ==========================================
        
        # 1A. 时间常数 T1 拦截
        t1_min, t1_max = context.get_time_constant_range()
        if fusion and hasattr(fusion, 'T1') and fusion.T1 > 0:
            if fusion.T1 < t1_min or fusion.T1 > t1_max:
                reasons.append(f"T1 ({fusion.T1:.1f}s) 越界，机理许可范围 [{t1_min}, {t1_max}]")
                
        # 1B. 纯滞后时间 L 拦截
        l_min, l_max = context.get_dead_time_range()
        if fusion and hasattr(fusion, 'L') and fusion.L > 0:
            if fusion.L < l_min or fusion.L > l_max:
                reasons.append(f"L ({fusion.L:.1f}s) 越界，机理许可范围 [{l_min}, {l_max}]")
                
        # 1C. 过程增益正反作用一致性拦截
        if fusion and hasattr(fusion, 'K') and fusion.K != 0:
            expected_sign = context.current_kp_sign
            if (fusion.K > 0 and expected_sign < 0) or (fusion.K < 0 and expected_sign > 0):
                reasons.append(f"辨识增益 K ({fusion.K:.2f}) 符号与设备正反作用属性(Sign={expected_sign})冲突")
                
        # ==========================================
        # 2. 控制器安全底线验证 (审核最终下发的控制参数)
        # ==========================================
        
        # 2A. 比例带 PB 红线拦截 (针对过激的AI参数)
        pb_min, pb_max = context.get_pb_range()
        if optimized_pid and 'Kp' in optimized_pid and optimized_pid['Kp'] != 0:
            pb = 100.0 / abs(optimized_pid['Kp'])
            if pb < pb_min or pb > pb_max:
                reasons.append(f"整定 PB ({pb:.1f}%) 突破安全专家红线 [{pb_min}%, {pb_max}%]")
                
        return len(reasons) == 0, reasons
        
    @staticmethod
    def enforce_fallback(context: TuningContext, 
                         strategy: FallbackStrategy = FallbackStrategy.SAFE_PRESET,
                         violating_pid: Dict[str, float] = None) -> Dict[str, float]:
        """
        统一受罚与降级处理中心。提供三种可选的处罚力度。
        
        Args:
            context: 整定上下文
            strategy: 惩罚策略选择
            violating_pid: 原本违规的 PID（仅在 CLIP 策略时需要）
            
        Returns:
            兜底后的安全 PID 字典（如果采取 REJECT，则返回 None）
        """
        if strategy == FallbackStrategy.REJECT:
            # 策略1：彻底废弃，打回不发参数
            return None
            
        elif strategy == FallbackStrategy.SAFE_PRESET:
            # 策略2：强塞低保 (保守求稳)
            preset = context._get_preset()
            pb_fallback = preset.get("pb_max", 300.0)    # 取最高阈值，保稳
            ti_fallback = preset.get("ti_max", 120.0)
            
            kp_sign = context.current_kp_sign if context.current_kp_sign != 0 else 1
            kp_fallback = (100.0 / pb_fallback) * kp_sign
            
            return {
                'Kp': kp_fallback,
                'Ki': kp_fallback / ti_fallback if ti_fallback > 0 else 0.0,
                'Kd': 0.0
            }
            
        elif strategy == FallbackStrategy.CLIP_TO_BOUNDS:
            # 策略3：违纪裁剪 (刀法)
            if not violating_pid:
                # 没源参数可裁，降级到保守策略
                return MechanismAuditor.enforce_fallback(context, FallbackStrategy.SAFE_PRESET)
                
            pb_min, pb_max = context.get_pb_range()
            ti_max = context.get_ti_max()
            
            original_kp = violating_pid.get('Kp', 1.0)
            current_pb = 100.0 / abs(original_kp) if original_kp != 0 else float('inf')
            
            # 强制收束到机理范围内
            clamped_pb = max(pb_min, min(current_pb, pb_max))
            
            kp_sign = np.sign(original_kp) if original_kp != 0 else context.current_kp_sign
            new_kp = (100.0 / clamped_pb) * kp_sign
            
            # Ti 也裁剪
            current_ki = violating_pid.get('Ki', 0.0)
            current_ti = abs(original_kp / current_ki) if current_ki != 0 else float('inf')
            clamped_ti = min(current_ti, ti_max)
            
            new_ki = new_kp / clamped_ti if clamped_ti > 0 else 0.0
            
            return {
                'Kp': new_kp,
                'Ki': new_ki,
                'Kd': violating_pid.get('Kd', 0.0)
            }
        
        return None

# =====================================================================
# 💡 调用示例及演示 (Run this file directly to see the example)
# =====================================================================
if __name__ == '__main__':
    # 临时模拟构建结构，仅供展示运行过程
    class MockFusion:
        def __init__(self, K, T1, L):
            self.K = K
            self.T1 = T1
            self.L = L

    class MockContext:
        def __init__(self, pb_range, t1_range, l_range, kp_sign):
            self.fusion_result = MockFusion(K=-0.5, T1=12.0, L=1.0)
            self.current_kp_sign = kp_sign
            self._pb_range = pb_range
            self._t1_range = t1_range
            self._l_range = l_range
            self._ti_max = 120.0
            
        def get_pb_range(self): return self._pb_range
        def get_time_constant_range(self): return self._t1_range
        def get_dead_time_range(self): return self._l_range
        def get_ti_max(self): return self._ti_max
        def _get_preset(self): return {"pb_max": 300.0, "ti_max": 120.0}

    print("=" * 60)
    print(" 🏭 场景：巨型储水罐液位控制 (极度依赖机理安全)")
    print("=" * 60)
    
    # 门卫（Auditor）持有的从【数据机理中台】下载的安全红线：
    mock_context = MockContext(
        pb_range=(100.0, 400.0),    # 专家红线：这可是巨型液位管，比例带绝不能低于 100%
        t1_range=(60.0, 300.0),     # 物理红线：水满得再快也不可能 60秒内满
        l_range=(5.0, 15.0),
        kp_sign=1                   # 预期正作用
    )
    
    # 大模型 Agent 擅作主张产生了幻觉，给出了暴力激进的解：
    llm_pid = {'Kp': 5.0, 'Ki': 0.1, 'Kd': 0.0}   # 算出 PB=20%，这是作死参数
    print(f"👻 大模型/AI 推理出的激进结果: PB = {100/5.0}% (远低于底线约束 100%)")
    
    # 1. 过安检门
    is_ok, reasons_list = MechanismAuditor.verify(mock_context, optimized_pid=llm_pid)
    
    print(f"\n👮 机理安检门验证通过? -> {is_ok}")
    print("📝 拦截原因日志:")
    for r in reasons_list:
        print(f"  ❌ {r}")
        
    # 2. 如果不合法，执行统一处罚（边缘限制裁剪）
    if not is_ok:
        print("\n🛡️ 触发防线：强制执行 [边缘裁剪 CLIP_TO_BOUNDS] 法案...")
        safe_pid = MechanismAuditor.enforce_fallback(
            context=mock_context,
            strategy=FallbackStrategy.CLIP_TO_BOUNDS,
            violating_pid=llm_pid
        )
        print(f"✅ 发往下一级工业控制器的最终合法参数: {safe_pid}")
        print(f"   (此时 PB 已被强制拉伸至红线边缘: {100/safe_pid['Kp']}%)")
    print("=" * 60)

