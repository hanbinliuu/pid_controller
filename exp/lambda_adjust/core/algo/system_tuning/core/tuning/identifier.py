"""系统辨识与PID整定集成模块：负责协调各个功能模块完成整定任务（优化版）"""
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import (Config, Mode, TuningMethod,
                    DataQualityError, ModelIdentificationError,
                    ParameterValidationError, InsufficientDataError)
from core.data.analyzer import DataAnalyzer
from core.model.identifier import ModelIdentifier
from core.pid.tuner import PIDTuner
from core.data.preprocessor import DataPreprocessor
from core.tuning.logic import SystemTuningLogic
from core.pid.evaluator import PIDEvaluator
from core.utils.data_quality import DataQualityChecker
from core.utils.parameter_validator import ParameterValidator


class SystemIdentifier:
    """系统辨识与PID整定工具：基于FOPDT模型和Lambda方法（优化后的组合模式版本）"""
    
    def __init__(self):
        """初始化SystemIdentifier，使用组合模式组合各个功能模块（优化版）"""
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
                           enable_performance_eval=False):
        """
        根据JSON数据自动整定PID参数（优化版）- 自动检测场景、模型类型和控制模式
        支持设定值变化场景的分段整定
        
        Args:
            t: 时间数组
            temp_data: 温度/输出数据
            setpoint: 设定值（如果sv_array提供且enable_setpoint_segmentation=True，此参数可能被忽略）
            tuning_method: 整定方法 (TuningMethod.LAMBDA 或 TuningMethod.COHEN_COON)
            mode: 控制模式，如果为None且auto_detect=True则自动检测
            u_data: 输入数据（可选）
            auto_detect: 是否启用自动检测（模型类型和模式）
            sv_array: 设定值数组（可选，用于检测设定值变化）
            enable_setpoint_segmentation: 是否启用设定值分段整定（默认True）
            current_pid_params: 当前PID参数（可选，用于闭环辨识增强），格式: {'pb': xx, 'ti': xx, 'td': xx}
            enable_quality_check: 是否启用数据质量检查（默认True）🆕
            enable_param_validation: 是否启用参数验证（默认True）🆕
            enable_performance_eval: 是否启用性能评估（默认False）🆕
            
        Returns:
            dict: 整定结果字典，如果启用分段整定且检测到多个段，返回最后一个段的整定结果
        """
        try:
            # ========== 步骤0: 数据质量预检 🆕 ==========
            if enable_quality_check:
                print("\n🔍 步骤0: 数据质量检查...")
                try:
                    is_valid, message, details = self._quality_checker.assess_data_quality(
                        t, temp_data, u_data, sv_array
                    )
                    print(f"   {message}")
                    
                    if not is_valid:
                        print("   ⚠️  数据质量不足，详细信息:")
                        for issue in details['issues']:
                            print(f"      - {issue}")
                        raise DataQualityError(message)
                    
                    # 如果有警告，打印出来
                    if details['warnings']:
                        for warning in details['warnings']:
                            print(f"   ⚠️  {warning}")
                
                except DataQualityError:
                    raise  # 重新抛出数据质量异常
                except Exception as e:
                    print(f"   ⚠️  数据质量检查失败: {e}，继续执行")
            
            # ========== 步骤1: 全局场景和模式检测（只检测一次，避免重复）🆕 ==========
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
                    mode = self._cached_mode
                else:
                    self._cached_mode = mode
            else:
                self._cached_scenario = None
                self._cached_mode = mode or Mode.STANDARD
            
            # ========== 步骤2: 设定值变化检测和分段 ==========
            segments = []
            if enable_setpoint_segmentation and sv_array is not None and len(sv_array) == len(temp_data):
                segments = self.detect_setpoint_changes(sv_array, min_change=0.5, min_stable_points=20)
                if len(segments) > 1:
                    print(f"🔍 检测到 {len(segments)} 个设定值段，将进行分段检查")
                    for i, (start_idx, end_idx, seg_sv) in enumerate(segments):
                        print(f"   段 {i+1}: 索引 [{start_idx}, {end_idx}), 设定值: {seg_sv:.3f}")
                elif len(segments) == 1:
                    # 只检测到一个段，但可能设定值有变化但变化不够明显
                    # 检查设定值是否有明显变化（使用更宽松的阈值）
                    sv_std = np.std(sv_array)
                    sv_range = np.max(sv_array) - np.min(sv_array)
                    if sv_range > 0.3:  # 设定值有明显变化
                        print(f"⚠️ 设定值有明显变化（范围: {sv_range:.3f}），但未检测到分段，尝试手动分段")
                        # 尝试找到设定值变化最明显的位置
                        sv_diff = np.abs(np.diff(sv_array))
                        if len(sv_diff) > 0:
                            max_change_idx = np.argmax(sv_diff)
                            if max_change_idx > 50 and max_change_idx < len(sv_array) - 50:
                                # 在变化点前后分段
                                segments = [
                                    (0, max_change_idx, np.median(sv_array[:max_change_idx])),
                                    (max_change_idx, len(sv_array), np.median(sv_array[max_change_idx:]))
                                ]
                                print(f"   手动分段: 段1 [0, {max_change_idx}), 段2 [{max_change_idx}, {len(sv_array)})")
            
            # ========== 步骤3: 稳态检查（使用统一标准）🆕 ==========
            if len(segments) > 0:
                print(f"\n🔍 步骤3: 检查各段的稳态情况（使用统一标准）...")
                tuning_needed, first_tuning_segment_idx, non_steady_segments_for_annotation, steady_segment_indices = \
                    self._tuning_logic.check_segment_steady_state(temp_data, sv_array, segments)
                
                # 如果不需要整定，返回非稳态段信息用于标注
                if not tuning_needed:
                    print(f"\n🎯 结论：所有段都已稳态或响应正常，无需重新整定PID参数")
                    if len(non_steady_segments_for_annotation) > 0:
                        return {
                            'no_tuning_needed': True,
                            'non_steady_segments': non_steady_segments_for_annotation,
                            'message': '所有段都已稳态，无需重新整定，但存在非稳态段需要标注'
                        }
                    return None
            else:
                # 没有分段，使用单段逻辑
                non_steady_segments_for_annotation = []
                first_tuning_segment_idx = None
                steady_segment_indices = set()
            
            # ========== 步骤4: 执行整定 ==========
            if len(segments) > 1:
                result = self._tune_multiple_segments(
                    t, temp_data, sv_array, segments, first_tuning_segment_idx,
                    non_steady_segments_for_annotation, steady_segment_indices, tuning_method, mode, u_data, auto_detect,
                    current_pid_params
                )
            else:
                # 原有逻辑：单段整定（当未检测到设定值分段时）
                result = self._tune_single_segment_legacy(
                    t, temp_data, setpoint, tuning_method, mode, u_data, auto_detect, sv_array, current_pid_params
                )
            
            # ========== 步骤5: 参数验证和性能评估 🆕 ==========
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
            import traceback
            traceback.print_exc()
            raise
        finally:
            # 清除缓存
            self._cached_scenario = None
            self._cached_mode = None
    
    def _tune_multiple_segments(self, t, temp_data, sv_array, segments, first_tuning_segment_idx,
                               non_steady_segments_for_annotation, steady_segment_indices, tuning_method, mode, u_data, auto_detect,
                               current_pid_params=None):
        """
        对多个段进行整定（简化版）
        
        关键逻辑：
        1. 从first_tuning_segment_idx开始整定
        2. 第一次整定后，后续是否需要整定完全基于新参数仿真轨迹的稳态判断
        3. 记录所有非稳态段用于标注
        """
        print(f"\n📊 开始分段整定...")
        last_result = None
        prev_tuning_result = None
        prev_segment_end_idx = None
        prev_segment_end_pv = None
        all_segments_results = []
        
        for seg_idx, (start_idx, end_idx, seg_setpoint) in enumerate(segments):
            # 跳过前面已稳态的段
            if seg_idx < first_tuning_segment_idx:
                print(f"\n⏭️  跳过段 {seg_idx + 1}: 已稳态，无需整定")
                prev_segment_end_idx = end_idx
                prev_segment_end_pv = temp_data[min(end_idx, len(temp_data) - 1)]
                continue
            
            print(f"\n🎯 整定段 {seg_idx + 1}/{len(segments)}: 设定值 = {seg_setpoint:.3f}")
            
            # 提取当前段的数据
            # 如果前一段已经整定过，使用前一段的新参数仿真出的PV轨迹
            use_simulated_data = False
            if seg_idx > 0 and prev_tuning_result is not None:
                # 使用前一段的整定结果进行仿真
                y_seg = self._simulate_segment_with_prev_params(
                    t, temp_data, sv_array, start_idx, end_idx, seg_setpoint,
                    prev_tuning_result, prev_segment_end_pv, u_data
                )
                use_simulated_data = True
                print(f"   ✅ 使用前一段参数仿真出当前段的PV轨迹")
            else:
                # 第一段或前一段未整定，使用原始数据
                y_seg = temp_data[start_idx:end_idx]
            
            t_seg = t[start_idx:end_idx]
            u_seg = u_data[start_idx:end_idx] if u_data is not None else None
            
            # 检查当前段是否稳态（使用仿真数据或原始数据）
            segment_len = len(y_seg)
            tail_len = max(30, int(segment_len * 0.3)) if segment_len >= 50 else min(20, segment_len)
            tail_segment = y_seg[-tail_len:] if segment_len >= tail_len else y_seg
            
            is_steady = self.is_steady_state(tail_segment, seg_setpoint, tol=0.3, std_tol=0.15, min_len=20)
            
            if is_steady:
                print(f"✅ 段 {seg_idx + 1} 在当前PID仿真下已处于稳态，跳过整定")
                prev_segment_end_idx = end_idx
                prev_segment_end_pv = y_seg[-1] if len(y_seg) > 0 else temp_data[min(end_idx, len(temp_data) - 1)]
                continue
            
            # 进行整定
            print(f"   📈 开始整定段 {seg_idx + 1}...")
            
            # 提取当前段的SV数据
            sv_seg = sv_array[start_idx:end_idx] if sv_array is not None else None
            
            result = self._tune_single_segment(
                t_seg, y_seg, seg_setpoint, tuning_method, mode, u_seg, auto_detect,
                sv_seg=sv_seg, current_pid_params=current_pid_params
            )
            
            if result is not None:
                result['segment_index'] = seg_idx + 1
                result['segment_setpoint'] = seg_setpoint
                result['segment_indices'] = (start_idx, end_idx)
                result['used_simulated_data'] = use_simulated_data
                
                all_segments_results.append(result)
                last_result = result
                
                # 保存用于下一段
                prev_tuning_result = result
                prev_segment_end_idx = end_idx
                prev_segment_end_pv = y_seg[-1] if len(y_seg) > 0 else temp_data[min(end_idx, len(temp_data) - 1)]
                
                print(f"✅ 段 {seg_idx + 1} 整定完成" + ("（基于前一段参数仿真）" if use_simulated_data else "（基于原始数据）"))
            else:
                print(f"⚠️ 段 {seg_idx + 1} 整定失败，跳过")
                prev_segment_end_idx = end_idx
                prev_segment_end_pv = temp_data[min(end_idx, len(temp_data) - 1)]
        
        if last_result is not None:
            last_result['all_segments_results'] = all_segments_results
            last_result['non_steady_segments'] = non_steady_segments_for_annotation
            return last_result
        
        return None
    
    def _simulate_segment_with_prev_params(self, t, temp_data, sv_array, start_idx, end_idx, seg_setpoint,
                                           prev_tuning_result, prev_segment_end_pv, u_data):
        """
        使用前一段的整定结果仿真当前段的PV轨迹
        """
        try:
            from ..pid.simulator import simulate_system_with_pid
            from ..model.identifier import ModelIdentifier
            
            prev_pid_params = {
                'pb': prev_tuning_result.get('pb', 100.0),
                'ti': prev_tuning_result.get('ti', 0.0),
                'td': prev_tuning_result.get('td', 0.0)
            }
            prev_model_type = prev_tuning_result.get('model_type', 'fopdt')
            prev_model_params = prev_tuning_result.get('params', None)
            
            if prev_model_params is None:
                return temp_data[start_idx:end_idx]
            
            MODEL_TYPE_MAP = {
                'fopdt': ModelIdentifier.fopdt_model,
                'first_order': ModelIdentifier.fopdt_model,
                'second_order': ModelIdentifier.second_order_model,
                'integral_delay': ModelIdentifier.integral_delay_model
            }
            prev_system_model = MODEL_TYPE_MAP.get(prev_model_type, ModelIdentifier.fopdt_model)
            
            if prev_model_type in ['fopdt', 'first_order'] and len(prev_model_params) == 2:
                prev_model_params = (prev_model_params[0], prev_model_params[1], 0.0)
            
            t_seg = t[start_idx:end_idx]
            sv_seg = sv_array[start_idx:end_idx] if sv_array is not None else np.full(len(t_seg), seg_setpoint)
            initial_pv = prev_segment_end_pv if prev_segment_end_pv is not None else temp_data[start_idx]
            initial_mv = u_data[start_idx] if u_data is not None and start_idx < len(u_data) else None
            
            y_seg_simulated, _ = simulate_system_with_pid(
                t_seg, prev_system_model, prev_model_params, prev_pid_params,
                seg_setpoint, initial_pv=initial_pv, initial_mv=initial_mv,
                verbose=False, setpoint_array=sv_seg,
                mv_reference=u_data[start_idx:end_idx] if u_data is not None else None,
                pv_reference=temp_data[start_idx:end_idx]
            )
            
            return y_seg_simulated
        except Exception as e:
            print(f"   ⚠️ 使用前一段参数仿真失败: {e}，改用原始数据")
            return temp_data[start_idx:end_idx]
    
    def _tune_single_segment_legacy(self, t, temp_data, setpoint, tuning_method, mode, u_data, auto_detect, sv_array, current_pid_params=None):
        """
        单段整定（原有逻辑，用于未检测到分段的情况）
        """
        # 检测CASE类型
        case = self.classify_case(temp_data, setpoint, sv_array=sv_array)
        print(f"📊 JSON数据情形: {case}")

        if case == "ALREADY_STABLE":
            print("✅ 数据已稳定，pv已趋于sv，无需整定")
            return None
        
        # 对于CASE_2，检查SV调整后是否最终稳态
        if case == "CASE_2" and sv_array is not None and len(sv_array) == len(temp_data):
            sv_segments = self.detect_setpoint_changes(sv_array, min_change=0.5, min_stable_points=20)
            if len(sv_segments) > 0:
                last_seg_start, last_seg_end, last_seg_sv = sv_segments[-1]
                tail_len = max(30, (last_seg_end - last_seg_start) // 4)
                if tail_len > 0 and last_seg_end - tail_len >= last_seg_start:
                    tail_segment = temp_data[last_seg_end - tail_len:last_seg_end]
                    is_tail_steady = self.is_steady_state(tail_segment, last_seg_sv, tol=1.0, std_tol=0.5, min_len=20)
                    if is_tail_steady:
                        print(f"✅ CASE_2: SV调整后最终已稳态，无需重新整定")
                        # 记录非稳态段用于标注
                        non_steady_segments = []
                        for seg_start, seg_end, seg_sv in sv_segments[:-1]:
                            seg_data = temp_data[seg_start:seg_end]
                            if not self.is_steady_state(seg_data, seg_sv, tol=1.0, std_tol=0.5, min_len=20):
                                non_steady_segments.append((seg_start, seg_end, seg_sv))
                        if len(non_steady_segments) > 0:
                            return {
                                'no_tuning_needed': True,
                                'non_steady_segments': non_steady_segments,
                                'message': 'CASE_2: SV调整后最终已稳态，无需重新整定，但存在非稳态段需要标注'
                            }
                return None

        # 提取整定段
        if u_data is not None:
            t_seg, y_seg, u_seg = self.extract_tuning_segment(case, t, temp_data, setpoint, u_data)
        else:
            t_seg, y_seg = self.extract_tuning_segment(case, t, temp_data, setpoint)
            u_seg = None

        if t_seg is None or len(t_seg) < 20:
            print("⚠️ 无法提取有效整定段，数据不足")
            return None

        # 找到整定段在原始数据中的索引（用于可视化标注）
        start_time = t_seg[0]
        end_time = t_seg[-1]
        start_idx = np.argmin(np.abs(t - start_time))
        end_idx = np.argmin(np.abs(t - end_time))
        segment_indices = (start_idx, end_idx)
        
        # 执行整定
        # 提取整定段对应的SV数据
        sv_seg = sv_array[start_idx:end_idx] if sv_array is not None and len(sv_array) == len(temp_data) else None
        
        result = self._tune_single_segment(
            t_seg - t_seg[0], y_seg, setpoint, tuning_method, mode, u_seg, auto_detect,
            sv_seg=sv_seg, current_pid_params=current_pid_params
        )
        
        # 添加整定段索引信息到结果中（用于可视化标注）
        if result is not None:
            result['segment_indices'] = segment_indices
            result['case'] = case
            print(f"📊 整定段索引: [{start_idx}, {end_idx}], 时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
        
        return result
    
    def _tune_single_segment(self, t_seg, y_seg, setpoint, tuning_method, mode, u_seg, auto_detect, 
                            sv_seg=None, current_pid_params=None):
        """
        对单个数据段进行整定（内部方法，用于分段整定）
        
        Args:
            t_seg: 时间数组（段）
            y_seg: 输出数据（段）
            setpoint: 设定值
            tuning_method: 整定方法
            mode: 控制模式
            u_seg: 输入数据（段）
            auto_detect: 是否自动检测
            sv_seg: 设定值数组（段，可选，用于闭环辨识增强）
            current_pid_params: 当前PID参数（可选，用于闭环辨识增强）
            
        Returns:
            dict: 整定结果字典
        """
        if t_seg is None or len(t_seg) < 20:
            print("⚠️ 无法提取有效整定段，数据不足")
            return None

        print(f"📈 提取整定段: {len(t_seg)} 个点")
        # 重置时间轴为从0开始
        t_seg_rel = t_seg - t_seg[0]

        # 🔧 验证sv_seg的有效性
        if sv_seg is not None:
            if len(sv_seg) != len(y_seg):
                print(f"⚠️ 警告: sv_seg长度({len(sv_seg)})与y_seg长度({len(y_seg)})不匹配，禁用闭环辨识")
                sv_seg = None
            elif np.any(np.isnan(sv_seg)) or np.any(np.isinf(sv_seg)):
                print(f"⚠️ 警告: sv_seg包含NaN或Inf，禁用闭环辨识")
                sv_seg = None

        # 如果没有输入信号数据，使用设定值作为默认输入（不理想但至少能运行）
        if u_seg is None:
            print("⚠️ 警告：未提供输入信号数据，使用设定值作为默认输入进行辨识（可能不准确）")
            u_seg = np.full_like(t_seg_rel, setpoint)

        # 使用缓存的场景和模式（如果可用）🆕
        if self._cached_scenario is not None:
            detected_scenario = self._cached_scenario
            print(f"🔍 使用缓存的场景类型: {detected_scenario}")
        else:
            detected_scenario = self.detect_control_scenario(t_seg_rel, y_seg, u_seg)
            print(f"🔍 自动检测场景类型: {detected_scenario}")
        
        if self._cached_mode is not None:
            mode = self._cached_mode
            mode_names = {
                Mode.STANDARD: "标准模式",
                Mode.ANTI_NOISE: "抗噪声模式",
                Mode.ANTI_DISTURBANCE: "抗扰动模式",
                Mode.FLOW_CONTROL: "流量控制模式"
            }
            print(f"🔍 使用缓存的控制模式: {mode_names.get(mode, mode)}")
        elif mode is None and auto_detect:
            detected_mode = self.detect_control_mode(t_seg_rel, y_seg, u_seg, setpoint)
            mode = detected_mode
            mode_names = {
                Mode.STANDARD: "标准模式",
                Mode.ANTI_NOISE: "抗噪声模式",
                Mode.ANTI_DISTURBANCE: "抗扰动模式",
                Mode.FLOW_CONTROL: "流量控制模式"
            }
            print(f"🔍 自动检测控制模式: {mode_names.get(mode, mode)}")
        elif mode is None:
            mode = Mode.STANDARD

        # 🔧 保存原始数据副本（用于可视化，避免预处理影响显示）
        y_seg_original = y_seg.copy()
        u_seg_original = u_seg.copy() if u_seg is not None else None
        t_seg_rel_original = t_seg_rel.copy()
        
        # 根据场景选择数据预处理
        if detected_scenario == 'temperature':
            # 温控场景：使用温控预处理
            try:
                t_seg_rel, y_seg, u_seg = self.preprocess_temperature_data(t_seg_rel, y_seg, u_seg)
                print("✅ 已应用温控数据预处理（去除瞬态、热损失补偿、平滑）")
            except Exception as e:
                print(f"⚠️ 温控预处理失败: {e}，继续使用原始数据")
        elif detected_scenario == 'level':
            # 液位场景：使用液位预处理
            try:
                t_seg_rel, y_seg, u_seg = self.preprocess_level_data(t_seg_rel, y_seg, u_seg, noise_reduction='medium')
                print("✅ 已应用液位数据预处理（异常值移除、噪声滤波、周期性波动去除）")
            except Exception as e:
                print(f"⚠️ 液位预处理失败: {e}，继续使用原始数据")

        # 数据验证：确保没有NaN或Inf
        if np.any(np.isnan(y_seg)) or np.any(np.isinf(y_seg)):
            print(f"❌ 错误：y_seg包含NaN或Inf值，无法进行模型拟合")
            print(f"   y_seg统计: min={np.nanmin(y_seg):.3f}, max={np.nanmax(y_seg):.3f}, mean={np.nanmean(y_seg):.3f}")
            print(f"   NaN数量: {np.sum(np.isnan(y_seg))}, Inf数量: {np.sum(np.isinf(y_seg))}")
            return None
        
        if np.any(np.isnan(u_seg)) or np.any(np.isinf(u_seg)):
            print(f"❌ 错误：u_seg包含NaN或Inf值，无法进行模型拟合")
            print(f"   u_seg统计: min={np.nanmin(u_seg):.3f}, max={np.nanmax(u_seg):.3f}, mean={np.nanmean(u_seg):.3f}")
            print(f"   NaN数量: {np.sum(np.isnan(u_seg))}, Inf数量: {np.sum(np.isinf(u_seg))}")
            return None
        
        if np.any(np.isnan(t_seg_rel)) or np.any(np.isinf(t_seg_rel)):
            print(f"❌ 错误：t_seg_rel包含NaN或Inf值")
            return None
        
        # 自动模型类型检测和辨识
        detected_model_type = None
        model_params = None
        K, T, L = None, None, None
        
        try:
            # 确定模型类型
            if mode == Mode.FLOW_CONTROL:
                detected_model_type = 'first_order'
            else:
                detected_model_type = self.detect_model_type(t_seg_rel, y_seg, u_seg, detected_scenario)
                if auto_detect:
                    print(f"🔍 自动检测模型类型: {detected_model_type}")
            
            # 根据模型类型进行辨识（使用统一方法，支持闭环辨识增强）
            if detected_model_type == 'first_order':
                # 一阶模型已合并到 fopdt（L=0），但保持兼容性
                K, T, L = self.identify_fopdt(
                    t_seg_rel, y_seg, u_seg,
                    sv=sv_seg, current_pid_params=current_pid_params
                )
                # 对于一阶模型，强制 L=0
                L = 0.0
                model_params = (K, T, L)
                print(f"🔍 一阶模型辨识结果（FOPDT with L=0）: K={K:.3f}, T={T:.3f}, L={L:.3f}")
            elif detected_model_type == 'second_order':
                K, T1, T2 = self.identify_second_order(t_seg_rel, y_seg, u_seg)
                model_params = (K, T1, T2)
                # 为了兼容 Lambda 整定方法，需要等效的 T 和 L
                # 二阶模型可以近似为 FOPDT：T ≈ T1 + T2, L ≈ 0
                T = T1 + T2
                L = 0.0
                print(f"🔍 二阶模型辨识结果: K={K:.3f}, T1={T1:.3f}, T2={T2:.3f} (等效 T={T:.3f})")
            elif detected_model_type == 'fopdt':
                K, T, L = self.identify_fopdt(
                    t_seg_rel, y_seg, u_seg,
                    sv=sv_seg, current_pid_params=current_pid_params
                )
                model_params = (K, T, L)
                print(f"🔍 FOPDT模型辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}")
            elif detected_model_type == 'fopdt_with_heat_loss':
                ambient_temp = np.min(y_seg) if len(y_seg) > 0 else 0.0
                K, T, L, alpha = self.identify_fopdt_with_heat_loss(t_seg_rel, y_seg, u_seg, ambient_temp)
                model_params = (K, T, L, alpha)
                print(f"🔍 带热损失FOPDT辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}, α={alpha:.4f}")
            elif detected_model_type == 'integral_delay':
                K, L = self.identify_integral_delay(t_seg_rel, y_seg, u_seg)
                T = 100  # 大时间常数表示积分特性
                model_params = (K, L)
                print(f"🔍 积分-延迟模型辨识结果: K={K:.3f}, L={L:.3f} (积分系统)")
            else:
                # 默认使用FOPDT
                detected_model_type = 'fopdt'
                K, T, L = self.identify_fopdt(
                    t_seg_rel, y_seg, u_seg,
                    sv=sv_seg, current_pid_params=current_pid_params
                )
                model_params = (K, T, L)
                print(f"🔍 FOPDT模型辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}")
        except Exception as e:
            print(f"❌ 模型拟合失败: {e}")
            return None

        # 根据场景选择整定方法（恢复到仅使用基础 Lambda/Cohen-Coon 逻辑）
        lambda_val = T
        if tuning_method == TuningMethod.COHEN_COON and detected_model_type != 'integral_delay':
            # Cohen-Coon方法主要用于FOPDT模型
            pb, ti, td = self.cohen_coon_tuning(K, T, L)
        else:
            # Lambda方法（默认）或积分-延迟模型使用Lambda方法
            if mode == Mode.FLOW_CONTROL:
                pb, ti, td = self.lambda_tuning_for_flow(K, T, L, mode)
            elif detected_scenario == 'temperature':
                pb, ti, td = self.lambda_tuning_for_temperature_control(K, T, L, lambda_val, mode)
            elif detected_scenario == 'level':
                pb, ti, td = self.lambda_tuning_for_level_control(K, T, L, mode)
            else:
                pb, ti, td = self.lambda_tuning(K, T, L, lambda_val, mode)

        print(f"🎯 新PID参数（用于更新旧参数，使pv趋于sv）: Pb={pb:.2f}%, Ti={ti:.2f}s, Td={td:.2f}s")
        return {
            "pb": pb, 
            "ti": ti, 
            "td": td, 
            "case": "CASE_1",  # 分段整定时，每个段都视为CASE_1
            "scenario": detected_scenario,
            "model_type": detected_model_type,
            "mode": mode,
            "params": model_params
        }

    @staticmethod
    def auto_identify_from_json(json_data, setpoint=None, tuning_method=TuningMethod.LAMBDA):
        """
        从JSON数据自动识别模型类型和控制模式，并完成PID整定
        目标：重新整定PID参数，使pv趋于sv并稳定
        
        支持的JSON格式（标准格式，带data字段）:
        {
          "data": [
            {"timestamp": 1761642000000, "pv": 5, "mv": 13.0, "sv": 5, ...},
            ...
          ]
        }
        
        Args:
            json_data: JSON数据（必须是包含'data'字段的字典）
            setpoint: 设定值（如果json_data中没有，会从数据中的sv字段提取或使用默认值）
            tuning_method: 整定方法 (TuningMethod.LAMBDA 或 TuningMethod.COHEN_COON)
            
        Returns:
            dict: 包含新的PID参数、检测到的模型类型、控制模式等信息
                {
                    'pb': 比例带,
                    'ti': 积分时间,
                    'td': 微分时间,
                    'model_type': 模型类型,
                    'mode': 控制模式,
                    'scenario': 场景类型,
                    'case': 数据情形,
                    'params': 模型参数
                }
        """
        identifier = SystemIdentifier()
        
        # 检查JSON数据格式
        if not isinstance(json_data, dict):
            raise ValueError("JSON数据必须是字典格式，包含'data'字段")
        
        if 'data' not in json_data:
            raise ValueError("JSON数据必须包含'data'字段")
        
        if not isinstance(json_data['data'], list) or len(json_data['data']) == 0:
            raise ValueError("JSON数据中的'data'字段必须是非空数组")
        
        # 从data数组中提取数据
        data_list = json_data['data']
        
        # 提取时间戳、输出、输入、设定值
        timestamps, pv_list, mv_list, sv_list = [], [], [], []
        
        for item in data_list:
            if not isinstance(item, dict):
                continue
            if 'timestamp' in item:
                timestamps.append(item['timestamp'])
            if 'pv' in item:
                pv_list.append(item['pv'])
            if 'mv' in item:
                mv_list.append(item['mv'])
            if 'sv' in item:
                sv_list.append(item['sv'])
        
        if not timestamps:
            raise ValueError("JSON数据中的data数组必须包含 'timestamp' 字段")
        if not pv_list:
            raise ValueError("JSON数据中的data数组必须包含 'pv' 字段")
        
        # 确保数据长度一致
        min_len = min(len(timestamps), len(pv_list))
        timestamps = np.array(timestamps[:min_len])
        pv_list = np.array(pv_list[:min_len])
        mv_list = np.array(mv_list[:min_len]) if mv_list else None
        sv_list = np.array(sv_list[:min_len]) if sv_list else None
        
        # 转换时间戳为相对时间（秒）
        if timestamps[0] > 1e10:  # 毫秒时间戳
            timestamps = timestamps / 1000.0
        t = timestamps - timestamps[0]
        y = pv_list
        u = mv_list
        
        # 设定值：优先使用参数，其次使用数据中的sv，最后使用默认值
        if setpoint is None:
            setpoint = np.mean(sv_list) if sv_list is not None and len(sv_list) > 0 else (np.mean(y) if len(y) > 0 else 0.0)
        
        # 评估数据质量
        if sv_list is not None and len(sv_list) > 0:
            error = np.abs(y - sv_list)
            print(f"📊 数据质量评估:")
            print(f"   pv与sv平均误差: {np.mean(error):.3f}")
            print(f"   pv与sv最大误差: {np.max(error):.3f}")
            print(f"   设定值: {setpoint:.3f}")
            print(f"   数据点数: {len(y)}")
        
        # 使用自动整定方法
        return identifier.auto_tune_from_json(
            t, y, setpoint, tuning_method,
            mode=None,  # 自动检测
            u_data=u,
            auto_detect=True  # 启用自动检测
        )
