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
        """构建策略选择 Prompt（LLM 选择策略代码而非数值参数）"""
        
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
        
        prompt = f"""你是工业PID整定专家。根据过程特征选择最合适的整定策略。

## 当前过程特征
- 回路类型: {loop_type_cn}
- 系统速度: {speed_class}（临界周期Pu={Pu:.0f}秒）
- 过程增益: K={K_approx:.2f}，临界增益Ku={Ku:.2f}
- 稳定裕度: Ku/K={ku_k_ratio:.1f}（{margin}）
- 数据质量: {data_quality:.0%}
- 估计置信度: {confidence:.0%}
- 振荡程度: {oscillation_ratio:.0%}
- 阀门问题: {valve_problem}

## 可选策略
A - 标准整定：适用于一般场景，数据质量好，过程稳定
B - 保守整定：适用于不确定场景，数据质量中等或置信度低
C - 快速整定：适用于响应速度优先，数据质量好，稳定裕度大
D - 抗扰动整定：适用于存在外部扰动，需要更稳健的控制
E - 阀门问题整定：适用于阀门死区或粘滞问题

## 选择指南
- 数据质量>80% + 稳定裕度大 → C（快速）
- 数据质量>60% + 无特殊问题 → A（标准）
- 数据质量<60% 或 置信度<60% → B（保守）
- 振荡程度>70% → D（抗扰动）
- 阀门问题 → E（阀门）

## 输出格式
只输出一个字母（A/B/C/D/E），代表你选择的策略。

你的选择:"""
        
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
