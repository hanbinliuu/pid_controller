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
        """构建增强版 LLM Prompt（更多上下文和示例）"""
        
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
        
        # 系统速度分类
        if Pu > 30:
            speed_class = "慢系统"
        elif Pu > 10:
            speed_class = "中速系统"
        else:
            speed_class = "快系统"
        
        # Ku/K 比值（稳定裕度）
        ku_k_ratio = Ku / K_approx if K_approx > 0.01 else 10.0
        if ku_k_ratio < 2:
            margin = "小（容易不稳定）"
        elif ku_k_ratio < 4:
            margin = "中等"
        else:
            margin = "大（容易稳定）"
        
        # 综合难度评估
        difficulty_score = 0
        if data_quality < 0.5: difficulty_score += 2
        if confidence < 0.5: difficulty_score += 2
        if oscillation_ratio > 0.7: difficulty_score += 1
        if ku_k_ratio < 2: difficulty_score += 2
        if has_deadband or has_stiction: difficulty_score += 1
        
        if difficulty_score >= 5:
            difficulty = "困难（需要保守）"
        elif difficulty_score >= 2:
            difficulty = "中等"
        else:
            difficulty = "简单（可以激进）"
        
        prompt = f"""你是工业PID整定专家。根据振荡数据给出整定策略参数。

## 目标
让控制系统快速达到稳态（<100秒），同时避免过大超调（<30%）。

## 当前过程特征
- 回路类型: {loop_type_cn}
- 系统速度: {speed_class}（临界周期Pu={Pu:.0f}秒）
- 过程增益: K={K_approx:.2f}，临界增益Ku={Ku:.2f}
- 稳定裕度: Ku/K={ku_k_ratio:.1f}（{margin}）
- 数据质量: {data_quality:.1%}
- 估计置信度: {confidence:.1%}
- 振荡程度: {oscillation_ratio:.1%}
- 阀门问题: {valve_problem}
- 综合难度: {difficulty}

## 策略参数说明
1. safety: 安全系数，影响比例带。0.8=激进，1.0=标准，1.5=保守，2.0=很保守
2. pb_extra: 比例带额外乘数，通常1.0-1.3
3. ti_mult: 积分时间乘数，0.8=快积分，1.0=标准，1.3=慢积分
4. use_d: 是否启用微分（0或1）。流量回路用0，温度/压力可用1
5. td: 微分时间因子，通常0-0.5

## 成功案例参考
| 场景 | safety | pb_extra | ti_mult | use_d | td | 结果 |
|------|--------|----------|---------|-------|----|------|
| 快流量-质量好 | 0.9 | 1.0 | 0.9 | 0 | 0 | 28秒稳态 |
| 中温度-阀门粘滞 | 1.3 | 1.1 | 1.1 | 1 | 0.3 | 65秒稳态 |
| 慢液位-低置信 | 1.5 | 1.2 | 1.4 | 0 | 0 | 120秒稳态 |
| 快压力-高振荡 | 1.2 | 1.0 | 1.0 | 1 | 0.4 | 42秒稳态 |

## 失败案例（避免）
| 场景 | 参数 | 问题 |
|------|------|------|
| 过于保守 | safety=2.5 | 调节太慢（>200秒）|
| 过于激进 | safety=0.6 | 系统不稳定振荡 |

## 输出格式
只输出5个数字（逗号分隔）：safety,pb_extra,ti_mult,use_d,td

示例输出: 1.1,1.0,1.0,0,0

你的输出:"""
        
        return prompt
    
    def _parse_response(self, response: str) -> ConservativeStrategyParams:
        """解析 LLM 响应（不限制参数范围，让LLM自由决策）"""
        
        try:
            response = response.strip()
            
            if self._verbose:
                print(f"   📝 LLM 响应: {response[:100]}")
            
            import re
            
            # 提取所有数字
            numbers = re.findall(r'(\d+\.?\d*)', response)
            
            if len(numbers) >= 5:
                # 完整解析 - 只做基本的合理性检查，不强制限制范围
                safety_factor = float(numbers[0])
                pb_extra_factor = float(numbers[1])
                ti_multiplier = float(numbers[2])
                use_derivative = float(numbers[3]) >= 0.5
                td_factor = float(numbers[4])
                
                # 基本合理性检查（防止明显错误，但范围很宽）
                safety_factor = max(0.5, min(5.0, safety_factor))  # 0.5-5.0
                pb_extra_factor = max(0.8, min(3.0, pb_extra_factor))  # 0.8-3.0
                ti_multiplier = max(0.5, min(3.0, ti_multiplier))  # 0.5-3.0
                td_factor = max(0.0, min(1.5, td_factor))  # 0-1.5
                
                if self._verbose:
                    print(f"   ✅ 完整解析: {safety_factor},{pb_extra_factor},{ti_multiplier},{int(use_derivative)},{td_factor}")
                
                return ConservativeStrategyParams(
                    safety_factor=safety_factor,
                    pb_extra_factor=pb_extra_factor,
                    ti_multiplier=ti_multiplier,
                    enable_derivative=use_derivative,
                    td_factor=td_factor,
                    confidence=0.85,
                    reasoning=f"LLM决策: safety={safety_factor:.1f}, pb_extra={pb_extra_factor:.1f}, ti={ti_multiplier:.1f}",
                    risk_factors=[],
                    recommendations=[]
                )
            
            elif len(numbers) >= 1:
                # 部分解析，根据第一个数字推断
                first_num = float(numbers[0])
                
                # 判断第一个数字是什么参数
                if 0.5 <= first_num <= 5.0:
                    safety_factor = first_num
                else:
                    safety_factor = 1.5  # 默认
                
                # 根据 safety_factor 推断其他参数（更灵活的推断）
                if safety_factor >= 2.5:
                    # 非常保守
                    pb_extra, ti_mult, use_d, td_f = 1.5, 1.5, True, 0.6
                elif safety_factor >= 1.8:
                    # 保守
                    pb_extra, ti_mult, use_d, td_f = 1.2, 1.3, True, 0.5
                elif safety_factor >= 1.3:
                    # 中等
                    pb_extra, ti_mult, use_d, td_f = 1.1, 1.1, False, 0.3
                else:
                    # 激进
                    pb_extra, ti_mult, use_d, td_f = 1.0, 0.9, False, 0.0
                
                if self._verbose:
                    print(f"   ⚠️ 部分解析: safety={safety_factor}, 推断其他参数")
                
                return ConservativeStrategyParams(
                    safety_factor=safety_factor,
                    pb_extra_factor=pb_extra,
                    ti_multiplier=ti_mult,
                    enable_derivative=use_d,
                    td_factor=td_f,
                    confidence=0.6,
                    reasoning=f"LLM决策(部分): safety={safety_factor:.1f}",
                    risk_factors=["LLM响应不完整"],
                    recommendations=[]
                )
                
        except Exception as e:
            if self._verbose:
                print(f"   ⚠️ 解析失败: {e}")
        
        # 降级：返回默认值
        return ConservativeStrategyParams(
            safety_factor=1.5,
            pb_extra_factor=1.1,
            ti_multiplier=1.1,
            enable_derivative=True,
            td_factor=0.5,
            confidence=0.5,
            reasoning="LLM响应解析失败",
            risk_factors=["LLM响应格式异常"],
            recommendations=[]
        )
