"""LLM 保守策略决策模块（临界法整定专用）

当使用临界法（Ziegler-Nichols）整定时，用大模型决策保守策略参数。

设计理念：
- LLM 决策的是**策略参数**（配置层面的调整因子）
- 规则引擎用这些参数**计算 PID**（执行层面）
- 这样既利用了 LLM 的推理能力，又保持了计算的可解释性

适用场景：
1. 数据质量差，常规模型拟合失败
2. 高振荡数据，需要使用临界法整定
3. 阀门问题（死区、粘滞）导致的振荡

不适用场景：
- 正常数据质量好的整定（使用规则引擎即可）
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from ..config import Config


# ============================================================
# 预定义整定策略库
# LLM 只需选择策略代码，参数由工程师预先调优
# ============================================================
TUNING_STRATEGIES = {
    'A': {
        'name': '标准整定',
        'description': '适用于一般场景，数据质量好，过程稳定',
        'safety_factor': 1.0,
        'pb_extra_factor': 1.0,
        'ti_multiplier': 1.0,
        'enable_derivative': False,
        'td_factor': 0.0,
    },
    'B': {
        'name': '保守整定',
        'description': '适用于不确定场景，数据质量中等或置信度低',
        'safety_factor': 1.5,
        'pb_extra_factor': 1.2,
        'ti_multiplier': 1.3,
        'enable_derivative': False,
        'td_factor': 0.0,
    },
    'C': {
        'name': '快速整定',
        'description': '适用于响应速度优先，数据质量好，系统稳定裕度大',
        'safety_factor': 0.9,
        'pb_extra_factor': 1.0,
        'ti_multiplier': 0.9,
        'enable_derivative': True,
        'td_factor': 0.3,
    },
    'D': {
        'name': '抗扰动整定',
        'description': '适用于存在外部扰动，需要更稳健的控制',
        'safety_factor': 1.3,
        'pb_extra_factor': 1.1,
        'ti_multiplier': 1.1,
        'enable_derivative': True,
        'td_factor': 0.4,
    },
    'E': {
        'name': '阀门问题整定',
        'description': '适用于阀门死区或粘滞问题',
        'safety_factor': 1.4,
        'pb_extra_factor': 1.15,
        'ti_multiplier': 1.2,
        'enable_derivative': False,
        'td_factor': 0.0,
    },
}



@dataclass
class ConservativeStrategyParams:
    """LLM 决策的保守策略参数（用于调整规则引擎的配置）"""
    
    # ========== 核心保守因子 ==========
    safety_factor: float           # 安全系数 (1.0 ~ 2.5)，影响 pb 计算
    pb_extra_factor: float         # pb 额外乘数 (1.0 ~ 1.5)
    
    # ========== Ti/Td 调整 ==========
    ti_multiplier: float           # Ti 乘数 (0.8 ~ 1.5)，>1 更保守
    enable_derivative: bool        # 是否启用微分
    td_factor: float               # Td 因子 (0 ~ 1.0)，用于计算 Td = Pu * td_factor / 8
    
    # ========== 决策元信息 ==========
    confidence: float              # 决策置信度 (0~1)
    reasoning: str                 # 决策理由（人类可读）
    risk_factors: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class LLMOscillationTuningAdvisor:
    """
    基于大模型的临界法整定顾问
    
    LLM 决策保守策略参数，然后由规则引擎计算最终 PID。
    """
    
    def __init__(self, llm_client=None, verbose: bool = False):
        """
        Args:
            llm_client: LLM 客户端，需实现 chat(prompt) -> str 方法
            verbose: 是否输出详细日志
        """
        self._client = llm_client
        self._verbose = verbose
        self._osc_config = Config.OSCILLATION_TUNING
    
    def decide_conservative_strategy(
        self,
        Pu: float,
        Ku: float,
        K_approx: float,
        oscillation_ratio: float,
        data_quality: float,
        nonlinearity: float = 0.0,
        valve_issues: Dict = None,
        confidence: float = 0.5,
        loop_type: str = "",
        loop_name: str = ""
    ) -> Optional[ConservativeStrategyParams]:
        """
        使用 LLM 决策保守策略参数
        
        Args:
            Pu: 临界周期 (秒)
            Ku: 临界增益
            K_approx: 估计的过程增益
            oscillation_ratio: 振荡比 (0~1)
            data_quality: 数据质量评分 (0~1)
            nonlinearity: 非线性程度 (0~1)
            valve_issues: 阀门问题检测结果
            confidence: Ku/Pu 估计的置信度 (0~1)
            loop_type: 回路类型 (flow/temperature/pressure/level)
            loop_name: 回路名称
        
        Returns:
            ConservativeStrategyParams 或 None（LLM 不可用时）
        """
        if self._client is None:
            return None
        
        if valve_issues is None:
            valve_issues = {}
        
        # 最多重试 3 次
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                prompt = self._build_prompt(
                    Pu, Ku, K_approx, oscillation_ratio, data_quality,
                    nonlinearity, valve_issues, confidence, loop_type, loop_name
                )
                
                response = self._client.chat(prompt)
                strategy = self._parse_response(response)
                
                # 检查是否是完整解析（不是部分解析或默认值）
                is_complete = (
                    "部分解析" not in strategy.reasoning and 
                    "解析失败" not in strategy.reasoning and
                    "默认" not in strategy.reasoning
                )
                
                if is_complete:
                    if self._verbose:
                        print(f"🤖 LLM 保守策略决策 (尝试 {attempt + 1}/{max_retries}):")
                        print(f"   safety_factor: {strategy.safety_factor:.2f}")
                        print(f"   pb_extra_factor: {strategy.pb_extra_factor:.2f}")
                        print(f"   ti_multiplier: {strategy.ti_multiplier:.2f}")
                        print(f"   enable_derivative: {strategy.enable_derivative}")
                        print(f"   td_factor: {strategy.td_factor:.2f}")
                        print(f"   理由: {strategy.reasoning}")
                    return strategy
                elif attempt < max_retries - 1:
                    if self._verbose:
                        print(f"   ⚠️ 尝试 {attempt + 1}: 部分解析，重试...")
                    continue
                else:
                    # 最后一次尝试，返回部分解析结果
                    if self._verbose:
                        print(f"🤖 LLM 保守策略决策 (部分解析):")
                        print(f"   safety_factor: {strategy.safety_factor:.2f}")
                        print(f"   理由: {strategy.reasoning}")
                    return strategy
                    
            except Exception as e:
                last_error = e
                if self._verbose:
                    print(f"   ⚠️ 尝试 {attempt + 1} 失败: {e}")
                if attempt < max_retries - 1:
                    continue
        
        if self._verbose:
            print(f"⚠️ LLM 决策失败 (重试 {max_retries} 次): {last_error}")
        return None
    
    def _build_prompt(
        self,
        Pu: float, Ku: float, K_approx: float,
        oscillation_ratio: float, data_quality: float,
        nonlinearity: float, valve_issues: Dict,
        confidence: float, loop_type: str, loop_name: str
    ) -> str:
        """构建策略选择 Prompt（注入人类专家启发式思维）"""
        
        # 阀门问题
        has_deadband = valve_issues.get('has_deadband', False) if valve_issues else False
        has_stiction = valve_issues.get('has_stiction', False) if valve_issues else False
        valve_problem = "死区" if has_deadband else ("粘滞" if has_stiction else "无")
        
        # 回路类型中文映射
        loop_type_map = {
            'temperature': '温度', 'pressure': '压力',
            'flow': '流量', 'level': '液位'
        }
        loop_type_cn = loop_type_map.get(loop_type, '流量')
        
        # --- 1. 人类视角：看图说话 (Qualitative Analysis) ---
        # 估算滞后 L (基于 Ziegler-Nichols 经验: Pu ≈ 4L)
        estimated_L = Pu / 4.0
        T1_approx = Pu  # 粗略假设
        
        # 振荡速度判断 (Human heuristic: Fast vs Slow)
        # 如果 Pu 相对滞后很小，说明是高频P振荡；如果很大，说明是低频I振荡
        if estimated_L > 0:
            period_ratio = Pu / estimated_L
        else:
            period_ratio = 4.0
            
        osc_speed_desc = "中速振荡"
        if period_ratio < 3.0:
            osc_speed_desc = "极快振荡 (可能是微分噪音或P过强)"
        elif period_ratio > 10.0:
            osc_speed_desc = "慢速浪涌 (典型积分I过强)"
        
        # 稳定裕度判断
        ku_k_ratio = Ku / K_approx if K_approx > 0.01 else 10.0
        margin_desc = "高裕度"
        if ku_k_ratio < 2.0:
            margin_desc = "极低裕度 (系统濒临失稳)"
        elif ku_k_ratio < 4.0:
            margin_desc = "中等裕度"
            
        # --- 2. 人类视角：懂对象 (Context Awareness) ---
        loop_hint = ""
        if loop_type == 'temperature':
            loop_hint = "提示：温度对象滞后大，严禁使用过小的Ti（积分太强），否则会引发大幅度低频振荡。优先选择保守策略。"
        elif loop_type == 'flow':
            loop_hint = "提示：流量对象响应快，噪声大。通常不需要微分D。如果振荡，多半是增益K太大了。"
        elif loop_type == 'level':
            loop_hint = "提示：液位对象是积分过程。允许一定的波动，不要过度调节。Ti可以适当加大。"
        elif loop_type == 'pressure':
            loop_hint = "提示：压力对象反应灵敏，类似于流量，注意噪音影响。"

        # --- 3. 构建 Prompt ---
        prompt = f"""你是工业PID整定专家。请像一位经验丰富的工程师那样思考，根据过程特征选择最合适的整定策略。

## 1. 现场观察 (Observation)
- **对象类型**: {loop_type_cn} ({loop_type})
- **振荡特征**: {osc_speed_desc} (Pu={Pu:.1f}s)
- **振荡强度**: 衰减比 {oscillation_ratio:.2f} ({"发散/等幅" if oscillation_ratio >= 0.9 else "收敛"})
- **模型参数**: 增益 K≈{K_approx:.2f}
- **稳定裕度**: {margin_desc} (Ku/K={ku_k_ratio:.1f})
- **数据质量**: {data_quality:.1f}/1.0 ({confidence*100:.0f}% 置信度)
- **阀门状态**: {valve_problem}

## 2. 专家经验法则 (Heuristics)
1. **慢速振荡 (Pu很大)**: 通常是 **积分作用(I)过强** 导致的。必须显著增大 Ti (减弱积分)。
2. **快速振荡 (Pu很小)**: 通常是 **比例作用(P)过强** 导致的。必须减小 Kp (增大 PB)。
3. **高增益系统 (K大)**: 如果开环增益 K > 5，系统极度敏感。务必使用超保守的 PB。
4. **低数据质量**: 如果置信度低，不要尝试激进策略，安全第一。

## 3. 你的任务
{loop_hint}
请分析以上信息，从下方策略库中选择一个最合适的策略代码（A-F）。

### 策略库 (Strategy Library)
*   **A**: **标准保守** (Standard Conservative)
    *   适用：常规场景，稍微求稳。
    *   参数：Safety=1.5
*   **B**: **高抑制** (High Damping)
    *   适用：振荡较强，或者需要强力压制超调。
    *   参数：Safety=2.0 + 额外PB增加
*   **C**: **去积分** (De-Integration)
    *   适用：**慢速浪涌/长周期振荡**。确认是积分过强导致。
    *   参数：**Ti 大幅增加 (2.5倍)**
*   **D**: **噪声/微分抑制** (Noise Suppression)
    *   适用：**极快振荡**，且怀疑有噪音。
    *   参数：禁用微分 D，适度增加保守度。
*   **E**: **容忍模式** (Loose Control)
    *   适用：液位(Level)控制，或者阀门有问题的场景。
    *   参数：极度保守，允许波动。
*   **F**: **极端防御** (Extreme Defense)
    *   适用：**系统极不稳定 (发散)**，或者模型完全不可信。
    *   参数：Safety=3.0+，Ti=3.0倍。救火专用。

## 4. 输出格式
请仅输出 JSON 格式，包含 `reasoning` (思考过程) 和 `selection` (策略代码 A/B/C/D/E/F)。

示例:
{{
  "reasoning": "观察到 Pu=120s 且是温度回路，属于典型的慢速积分振荡。根据经验法则 1，如果是温度回路且振荡慢，必须大幅削弱积分。普通保守策略可能不够，需要选择去积分策略。",
  "selection": "C"
}}
"""
        return prompt
    
    def _parse_response(self, response: str) -> ConservativeStrategyParams:
        """解析 LLM 响应（解析策略代码 A-E，映射到预定义参数）"""
        
        try:
            response = response.strip().upper()
            
            if self._verbose:
                print(f"   📝 LLM 响应: {response[:100]}")
            
            import re
            
            # 提取策略代码（A-E）
            strategy_match = re.search(r'[A-E]', response)
            
            if strategy_match:
                strategy_code = strategy_match.group(0)
                strategy = TUNING_STRATEGIES.get(strategy_code)
                
                if strategy:
                    if self._verbose:
                        print(f"   ✅ 选择策略 {strategy_code}: {strategy['name']}")
                    
                    return ConservativeStrategyParams(
                        safety_factor=strategy['safety_factor'],
                        pb_extra_factor=strategy['pb_extra_factor'],
                        ti_multiplier=strategy['ti_multiplier'],
                        enable_derivative=strategy['enable_derivative'],
                        td_factor=strategy['td_factor'],
                        confidence=0.9,  # 策略选择模式置信度高
                        reasoning=f"LLM选择策略{strategy_code}: {strategy['name']}",
                        risk_factors=[],
                        recommendations=[]
                    )
            
            # 如果无法识别策略代码，尝试从响应内容推断
            if '保守' in response or 'conservative' in response.lower():
                selected = 'B'
            elif '快速' in response or 'fast' in response.lower():
                selected = 'C'
            elif '阀门' in response or 'valve' in response.lower():
                selected = 'E'
            elif '扰动' in response or 'disturbance' in response.lower():
                selected = 'D'
            else:
                selected = 'A'  # 默认标准策略
            
            strategy = TUNING_STRATEGIES[selected]
            if self._verbose:
                print(f"   ⚠️ 推断策略 {selected}: {strategy['name']}")
            
            return ConservativeStrategyParams(
                safety_factor=strategy['safety_factor'],
                pb_extra_factor=strategy['pb_extra_factor'],
                ti_multiplier=strategy['ti_multiplier'],
                enable_derivative=strategy['enable_derivative'],
                td_factor=strategy['td_factor'],
                confidence=0.7,  # 推断模式置信度较低
                reasoning=f"LLM推断策略{selected}: {strategy['name']}",
                risk_factors=["策略代码未直接匹配"],
                recommendations=[]
            )
                
        except Exception as e:
            if self._verbose:
                print(f"   ⚠️ 解析失败: {e}")
        
        # 降级：返回标准策略
        strategy = TUNING_STRATEGIES['A']
        return ConservativeStrategyParams(
            safety_factor=strategy['safety_factor'],
            pb_extra_factor=strategy['pb_extra_factor'],
            ti_multiplier=strategy['ti_multiplier'],
            enable_derivative=strategy['enable_derivative'],
            td_factor=strategy['td_factor'],
            confidence=0.5,
            reasoning="LLM响应解析失败，使用标准策略",
            risk_factors=["LLM响应格式异常"],
            recommendations=[]
        )
