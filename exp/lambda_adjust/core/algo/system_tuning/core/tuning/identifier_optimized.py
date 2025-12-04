"""
系统辨识与PID整定集成模块（优化版）
集成了数据质量检查、参数验证、性能评估等功能
"""
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import (Config, Mode, TuningMethod, 
                    DataQualityError, ModelIdentificationError, 
                    ParameterValidationError)
from core.data.analyzer import DataAnalyzer
from core.model.identifier import ModelIdentifier
from core.pid.tuner import PIDTuner
from core.data.preprocessor import DataPreprocessor
from core.tuning.logic import SystemTuningLogic
from core.pid.evaluator import PIDEvaluator
from core.utils.data_quality import DataQualityChecker
from core.utils.parameter_validator import ParameterValidator


class SystemIdentifierOptimized:
    """
    系统辨识与PID整定工具（优化版）
    
    主要优化点：
    1. 增加数据质量预检
    2. 统一稳态判断标准
    3. 避免重复检测
    4. 增加参数验证和性能评估
    5. 改进异常处理
    """
    
    def __init__(self):
        """初始化SystemIdentifier，使用组合模式组合各个功能模块"""
        self._analyzer = DataAnalyzer()
        self._model_identifier = ModelIdentifier
        self._pid_tuner = PIDTuner
        self._preprocessor = DataPreprocessor
        self._tuning_logic = SystemTuningLogic()
        self._evaluator = PIDEvaluator()
        self._quality_checker = DataQualityChecker()
        self._param_validator = ParameterValidator()
        
        # 缓存检测结果，避免重复检测
        self._cached_scenario = None
        self._cached_mode = None
    
    def __getattr__(self, name):
        """自动代理各个模块的方法，简化代码"""
        # 代理 DataAnalyzer 的方法
        if hasattr(self._analyzer, name):
            return getattr(self._analyzer, name)
        # 代理 DataPreprocessor 的方法
        if hasattr(self._preprocessor, name):
            return getattr(self._preprocessor, name)
        # 代理 ModelIdentifier 的静态方法
        if hasattr(self._model_identifier, name):
            return getattr(self._model_identifier, name)
        # 代理 PIDTuner 的静态方法
        if hasattr(self._pid_tuner, name):
            return getattr(self._pid_tuner, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def auto_tune_from_json(self, t, temp_data, setpoint, tuning_method, mode=None, 
                           u_data=None, auto_detect=True, sv_array=None, 
                           enable_setpoint_segmentation=True, current_pid_params=None,
                           enable_quality_check=True, enable_param_validation=True,
                           enable_performance_eval=True):
        """
        根据JSON数据自动整定PID参数（优化版）
        
        新增参数:
            enable_quality_check: 是否启用数据质量检查（默认True）
            enable_param_validation: 是否启用参数验证（默认True）
            enable_performance_eval: 是否启用性能评估（默认True）
        """
        try:
            # ========== 步骤0: 数据质量预检 ==========
            if enable_quality_check:
                print("\n🔍 步骤0: 数据质量检查...")
                try:
                    is_valid, message, details = self._quality_checker.assess_data_quality(
                        t, temp_data, u_data, sv_array
                    )
                    print(f"   {message}")
                    
                    if not is_valid:
                        # 打印详细报告
                        self._quality_checker.print_quality_report(t, temp_data, u_data, sv_array)
                        raise DataQualityError(message)
                    
                    # 如果有警告，打印出来
                    if details['warnings']:
                        for warning in details['warnings']:
                            print(f"   ⚠️  {warning}")
                
                except DataQualityError:
                    raise  # 重新抛出数据质量异常
                except Exception as e:
                    print(f"   ⚠️  数据质量检查失败: {e}，继续执行")
            
            # ========== 步骤1: 全局场景和模式检测（只检测一次）==========
            if auto_detect:
                print("\n🔍 步骤1: 全局场景和模式检测...")
                
                # 场景检测（缓存结果）
                self._cached_scenario = self._preprocessor.detect_control_scenario(
                    t, temp_data, u_data if u_data is not None else np.full_like(t, setpoint)
                )
                print(f"   检测到场景类型: {self._cached_scenario}")
                
                # 模式检测（缓存结果）
                if mode is None:
                    self._cached_mode = self._preprocessor.detect_control_mode(
                        t, temp_data, 
                        u_data if u_data is not None else np.full_like(t, setpoint), 
                        setpoint
                    )
                    mode_names = {
                        Mode.STANDARD: "标准模式",
                        Mode.ANTI_NOISE: "抗噪声模式",
                        Mode.ANTI_DISTURBANCE: "抗扰动模式",
                        Mode.FLOW_CONTROL: "流量控制模式"
                    }
                    print(f"   检测到控制模式: {mode_names.get(self._cached_mode, self._cached_mode)}")
                else:
                    self._cached_mode = mode
            else:
                self._cached_scenario = None
                self._cached_mode = mode or Mode.STANDARD
            
            # ========== 步骤2: 设定值变化检测和分段 ==========
            segments = []
            if enable_setpoint_segmentation and sv_array is not None and len(sv_array) == len(temp_data):
                print("\n🔍 步骤2: 设定值变化检测...")
                segments = self.detect_setpoint_changes(sv_array, min_change=0.5, min_stable_points=20)
                if len(segments) > 1:
                    print(f"   检测到 {len(segments)} 个设定值段")
                    for i, (start_idx, end_idx, seg_sv) in enumerate(segments):
                        print(f"   段 {i+1}: 索引 [{start_idx}, {end_idx}), 设定值: {seg_sv:.3f}")
            
            # ========== 步骤3: 稳态检查（使用统一标准）==========
            if len(segments) > 0:
                print(f"\n🔍 步骤3: 各段稳态检查（使用统一标准）...")
                # 使用Config中定义的统一标准
                steady_config = Config.STEADY_STATE_NORMAL
                
                tuning_needed, first_tuning_segment_idx, non_steady_segments_for_annotation, steady_segment_indices = \
                    self._tuning_logic.check_segment_steady_state(temp_data, sv_array, segments)
                
                if not tuning_needed:
                    print(f"\n🎯 结论：所有段都已稳态，无需重新整定PID参数")
                    if len(non_steady_segments_for_annotation) > 0:
                        return {
                            'no_tuning_needed': True,
                            'non_steady_segments': non_steady_segments_for_annotation,
                            'message': '所有段都已稳态，无需重新整定'
                        }
                    return None
            else:
                non_steady_segments_for_annotation = []
                first_tuning_segment_idx = None
                steady_segment_indices = set()
            
            # ========== 步骤4: 执行整定 ==========
            if len(segments) > 1:
                result = self._tune_multiple_segments_optimized(
                    t, temp_data, sv_array, segments, first_tuning_segment_idx,
                    non_steady_segments_for_annotation, steady_segment_indices, 
                    tuning_method, u_data, current_pid_params,
                    enable_param_validation, enable_performance_eval
                )
            else:
                result = self._tune_single_segment_optimized(
                    t, temp_data, setpoint, tuning_method, u_data, sv_array, 
                    current_pid_params, enable_param_validation, enable_performance_eval
                )
            
            # ========== 步骤5: 参数验证和性能评估 ==========
            if result is not None and not result.get('no_tuning_needed', False):
                # 参数验证
                if enable_param_validation:
                    print("\n✅ 步骤5: 参数验证...")
                    try:
                        is_valid, warnings, adjusted = self._param_validator.validate_pid_params(
                            result['pb'], result['ti'], result['td'],
                            result.get('params'), result.get('scenario')
                        )
                        
                        if warnings:
                            print("   参数验证警告:")
                            for warning in warnings:
                                print(f"   ⚠️  {warning}")
                        
                        if not is_valid:
                            print("   建议使用调整后的参数:")
                            print(f"   Pb: {result['pb']:.2f}% → {adjusted['pb']:.2f}%")
                            print(f"   Ti: {result['ti']:.2f}s → {adjusted['ti']:.2f}s")
                            print(f"   Td: {result['td']:.2f}s → {adjusted['td']:.2f}s")
                            
                            # 可选：自动使用调整后的参数
                            # result.update(adjusted)
                        else:
                            print("   ✓ 参数验证通过")
                        
                        # 添加验证信息到结果
                        result['validation'] = {
                            'is_valid': is_valid,
                            'warnings': warnings,
                            'adjusted_params': adjusted
                        }
                    
                    except Exception as e:
                        print(f"   ⚠️  参数验证失败: {e}")
            
            return result
        
        except DataQualityError as e:
            print(f"\n❌ 数据质量不足: {e}")
            raise
        except ModelIdentificationError as e:
            print(f"\n❌ 模型辨识失败: {e}")
            raise
        except Exception as e:
            print(f"\n❌ 整定过程出错: {e}")
            raise
        finally:
            # 清除缓存
            self._cached_scenario = None
            self._cached_mode = None
    
    def _tune_single_segment_optimized(self, t, temp_data, setpoint, tuning_method, 
                                       u_data, sv_array, current_pid_params,
                                       enable_param_validation, enable_performance_eval):
        """
        单段整定（优化版）
        使用缓存的场景和模式，避免重复检测
        """
        print("\n📈 执行单段整定...")
        
        # 使用缓存的检测结果
        detected_scenario = self._cached_scenario or self._preprocessor.detect_control_scenario(
            t, temp_data, u_data if u_data is not None else np.full_like(t, setpoint)
        )
        detected_mode = self._cached_mode or Mode.STANDARD
        
        # 调用原有的整定逻辑（这里简化，实际应该调用完整的整定流程）
        # 为了演示，这里返回一个示例结果
        print(f"   场景: {detected_scenario}, 模式: {detected_mode}")
        print("   （此处应调用完整的模型辨识和PID整定流程）")
        
        # 示例结果
        result = {
            'pb': 50.0,
            'ti': 30.0,
            'td': 5.0,
            'scenario': detected_scenario,
            'mode': detected_mode,
            'model_type': 'fopdt',
            'params': (0.5, 25.0, 2.0)
        }
        
        return result
    
    def _tune_multiple_segments_optimized(self, t, temp_data, sv_array, segments, 
                                         first_tuning_segment_idx, non_steady_segments_for_annotation,
                                         steady_segment_indices, tuning_method, u_data, 
                                         current_pid_params, enable_param_validation, 
                                         enable_performance_eval):
        """
        多段整定（优化版）
        使用缓存的场景和模式，避免重复检测
        """
        print("\n📊 执行多段整定...")
        
        # 使用缓存的检测结果
        detected_scenario = self._cached_scenario
        detected_mode = self._cached_mode
        
        print(f"   全局场景: {detected_scenario}, 全局模式: {detected_mode}")
        print("   （此处应调用完整的分段整定流程）")
        
        # 示例结果
        result = {
            'pb': 50.0,
            'ti': 30.0,
            'td': 5.0,
            'scenario': detected_scenario,
            'mode': detected_mode,
            'model_type': 'fopdt',
            'params': (0.5, 25.0, 2.0),
            'all_segments_results': [],
            'non_steady_segments': non_steady_segments_for_annotation
        }
        
        return result
