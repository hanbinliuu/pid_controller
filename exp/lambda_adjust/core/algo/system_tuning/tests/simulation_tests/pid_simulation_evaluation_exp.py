"""
PID整定与评估集成示例
集成了PID参数整定、性能评估和可视化功能
"""
import numpy as np
import json
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
tests_dir = os.path.dirname(current_dir)  # tests目录
system_tuning_dir = os.path.dirname(tests_dir)  # system_tuning目录
sys.path.insert(0, system_tuning_dir)
from core.tuning.identifier import SystemIdentifier
from config import TuningMethod, Mode
from core.pid.simulator import simulate_and_visualize
from core.pid.evaluator import PIDEvaluator, EvaluationMetrics
import matplotlib.pyplot as plt


def load_json_data(json_file_path):
    """
    从JSON文件加载数据
    
    Args:
        json_file_path: JSON文件路径
        
    Returns:
        t: 时间数组（秒）
        pv: 过程值数组
        mv: 控制输出数组
        sv: 设定值数组
    """
    with open(json_file_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    if 'data' not in json_data:
        raise ValueError("JSON数据必须包含'data'字段")
    
    data_list = json_data['data']
    
    # 提取数据
    timestamps, pv_list, mv_list, sv_list = [], [], [], []
    
    for item in data_list:
        if 'timestamp' in item:
            timestamps.append(item['timestamp'])
        if 'pv' in item:
            pv_list.append(item['pv'])
        if 'mv' in item:
            mv_list.append(item['mv'])
        if 'sv' in item:
            sv_list.append(item['sv'])
    
    # 确保数据长度一致
    min_len = min(len(timestamps), len(pv_list))
    timestamps = np.array(timestamps[:min_len])
    pv = np.array(pv_list[:min_len])
    mv = np.array(mv_list[:min_len]) if mv_list else None
    sv = np.array(sv_list[:min_len]) if sv_list else None
    
    # 转换时间戳为相对时间（秒）
    if timestamps[0] > 1e10:  # 毫秒时间戳
        timestamps = timestamps / 1000.0
    t = timestamps - timestamps[0]
    
    # 如果没有SV，使用PV的平均值作为设定值
    if sv is None:
        sv = np.full_like(pv, np.mean(pv))
    
    return t, pv, mv, sv


def main(json_file_path, output_dir=None, verbose=True, show_plot=False, enable_evaluation=True):
    """
    主函数：执行PID整定、评估、仿真和可视化
    
    Args:
        json_file_path: JSON数据文件路径
        output_dir: 输出目录（用于保存图形），如果为None则不保存
        verbose: 是否打印详细信息
        show_plot: 是否显示可视化图形（True显示，False不显示）
        enable_evaluation: 是否启用PID参数评估（默认True）
    """
    print("=" * 80)
    print("PID整定、评估与可视化示例")
    print("=" * 80)
    
    # 1. 加载数据
    print(f"\n📂 加载数据: {json_file_path}")
    try:
        t, pv, mv, sv = load_json_data(json_file_path)
        print(f"✅ 数据加载成功: {len(t)} 个数据点")
        print(f"   - 时间范围: {t[0]:.1f}s ~ {t[-1]:.1f}s")
        print(f"   - PV范围: [{np.min(pv):.2f}, {np.max(pv):.2f}]")
        if mv is not None:
            print(f"   - MV范围: [{np.min(mv):.2f}, {np.max(mv):.2f}]")
        print(f"   - SV: {np.mean(sv):.2f}")
    except Exception as e:
        print(f"❌ 数据加载失败: {e}")
        return
    
    # 2. 初始化整定器和评估器
    print(f"\n🔧 初始化整定器和评估器...")
    identifier = SystemIdentifier()
    evaluator = PIDEvaluator(settling_band=0.02, settling_duration=50) if enable_evaluation else None
    
    setpoint = np.mean(sv)
    tuning_method = TuningMethod.LAMBDA
    
    # 3. PID整定
    print(f"\n🔧 开始PID整定...")
    try:
        tuning_result = identifier.auto_tune_from_json(
            t, pv, setpoint, tuning_method,
            mode=None,  # 自动检测模式
            u_data=mv,
            auto_detect=True,
            sv_array=sv,  # 传递完整的设定值数组，支持分段整定
            enable_setpoint_segmentation=True  # 启用分段整定
        )
        
        if tuning_result is None:
            print("⚠️ 整定失败或数据已稳定，无需整定")
            if output_dir is not None:
                print(f"   - 输出目录: {output_dir}（无需整定，未生成图片）")
            return
        
        # 检查是否是不需要整定但需要标注非稳态段的情况
        if tuning_result.get('no_tuning_needed', False):
            print(f"⚠️ {tuning_result.get('message', '无需整定，但存在非稳态段需要标注')}")
        else:
            print(f"\n✅ 整定完成!")
            print(f"   - 新PID参数: Pb={tuning_result.get('pb', 'N/A'):.2f}%, "
                  f"Ti={tuning_result.get('ti', 'N/A'):.2f}s, Td={tuning_result.get('td', 'N/A'):.2f}s")
            print(f"   - 模型类型: {tuning_result.get('model_type', 'N/A')}")
            print(f"   - 场景: {tuning_result.get('scenario', 'N/A')}")
            print(f"   - 模式: {tuning_result.get('mode', 'N/A')}")
        
    except Exception as e:
        print(f"❌ 整定失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 4. 对整定段进行仿真，然后评估新参数
    # 正确流程：新参数仿真 → 评估仿真结果能否跟踪SV
    evaluation_results = []
    if enable_evaluation and tuning_result is not None and not tuning_result.get('no_tuning_needed', False):
        print(f"\n🎨 开始对整定段进行仿真（用于评估）...")
        
        # 导入仿真所需模块
        from core.pid.simulator import simulate_system_with_pid
        from core.model.identifier import ModelIdentifier
        
        # 提取模型信息
        model_type = tuning_result.get('model_type', 'fopdt')
        model_params = tuning_result.get('params', None)
        
        if model_params is None:
            print(f"   ⚠️ 模型参数为空，无法进行仿真评估")
        else:
            # 模型映射
            MODEL_TYPE_MAP = {
                'fopdt': ModelIdentifier.fopdt_model,
                'first_order': ModelIdentifier.fopdt_model,
                'second_order': ModelIdentifier.second_order_model,
                'integral_delay': ModelIdentifier.integral_delay_model
            }
            system_model = MODEL_TYPE_MAP.get(model_type, ModelIdentifier.fopdt_model)
            
            # 处理一阶模型参数
            if model_type in ['fopdt', 'first_order'] and len(model_params) == 2:
                model_params = (model_params[0], model_params[1], 0.0)
            
            # 提取新PID参数
            new_pid_params = {
                'pb': tuning_result.get('pb', 100.0),
                'ti': tuning_result.get('ti', 0.0),
                'td': tuning_result.get('td', 0.0)
            }
            
            print(f"   - 模型类型: {model_type}")
            print(f"   - 新PID参数: Pb={new_pid_params['pb']:.2f}%, Ti={new_pid_params['ti']:.2f}s, Td={new_pid_params['td']:.2f}s")
        
        print(f"\n📊 开始评估新参数的性能（基于仿真结果）...")
        
        # 检查是否有多段整定结果
        if 'all_segments_results' in tuning_result:
            all_segments_results = tuning_result.get('all_segments_results', [])
            print(f"   检测到 {len(all_segments_results)} 个整定段，逐段评估")
            
            for seg_idx, seg_result in enumerate(all_segments_results, 1):
                seg_indices = seg_result.get('segment_indices')
                if seg_indices is not None:
                    start_idx, end_idx = seg_indices
                    start_idx = max(0, min(start_idx, len(t) - 1))
                    end_idx = max(0, min(end_idx, len(t) - 1))
                    
                    # 对该段进行仿真并评估
                    try:
                        # 提取该段数据
                        t_seg = t[start_idx:end_idx]
                        sv_seg = sv[start_idx:end_idx]
                        
                        # 确定初始值（从整定段开始位置）
                        initial_pv = pv[start_idx] if start_idx < len(pv) else pv[0]
                        initial_mv = mv[start_idx] if mv is not None and start_idx < len(mv) else None
                        
                        # 获取该段的PID参数
                        seg_pid_params = {
                            'pb': seg_result.get('pb', new_pid_params['pb']),
                            'ti': seg_result.get('ti', new_pid_params['ti']),
                            'td': seg_result.get('td', new_pid_params['td'])
                        }
                        
                        print(f"\n   【段 {seg_idx} 仿真】")
                        print(f"   - 索引范围: [{start_idx}, {end_idx}]")
                        print(f"   - 初始PV: {initial_pv:.3f}")
                        print(f"   - 设定值: {np.mean(sv_seg):.3f}")
                        
                        # 仿真该段
                        pv_seg_sim, mv_seg_sim = simulate_system_with_pid(
                            t_seg, system_model, model_params, seg_pid_params,
                            setpoint=np.mean(sv_seg),
                            initial_pv=initial_pv,
                            initial_mv=initial_mv,
                            verbose=False,
                            setpoint_array=sv_seg,
                            mv_reference=mv[start_idx:end_idx] if mv is not None else None,
                            pv_reference=pv[start_idx:end_idx]
                        )
                        
                        print(f"   - 仿真完成: {len(pv_seg_sim)} 个点")
                        print(f"   - 最终PV: {pv_seg_sim[-1]:.3f}")
                        print(f"   - 最终误差: {abs(pv_seg_sim[-1] - sv_seg[-1]):.4f}")
                        
                        # 评估仿真结果（启用SV变化初期排除功能）
                        metrics = evaluator.evaluate(
                            pv_seg_sim, sv_seg, mv_seg_sim,  # ← 使用仿真数据
                            exclude_sv_transition=True  # 排除SV变化初期，避免IAE虚高
                        )
                        
                        # 显示排除信息
                        eval_start = evaluator._find_steady_state_start(pv_seg_sim, sv_seg)
                        if eval_start > 0:
                            print(f"   ℹ️  排除SV调整期间: 前 {eval_start} 个点（索引 0-{eval_start-1}）")
                            print(f"   ℹ️  实际评估点数: {len(pv_seg_sim) - eval_start} 个点")
                        
                        evaluation_results.append({
                            'segment_index': seg_idx,
                            'segment_range': (start_idx, end_idx),
                            'metrics': metrics,
                            'pid_params': {
                                'pb': seg_result.get('pb', 'N/A'),
                                'ti': seg_result.get('ti', 'N/A'),
                                'td': seg_result.get('td', 'N/A')
                            }
                        })
                        
                        print(f"\n   【段 {seg_idx} 评估结果（基于仿真）】")
                        print(f"   索引范围: [{start_idx}, {end_idx}]")
                        print(f"   PID参数: Pb={seg_result.get('pb', 'N/A'):.2f}%, "
                              f"Ti={seg_result.get('ti', 'N/A'):.2f}s, Td={seg_result.get('td', 'N/A'):.2f}s")
                        print(f"   综合评分: {metrics.overall_score:.2f} ({metrics.grade})")
                        print(f"   稳态误差: {metrics.steady_state_error:.4f}")
                        print(f"   IAE:      {metrics.iae:.2f}")
                        print(f"   振荡次数: {metrics.oscillation_count}")
                        print(f"   控制变化: {metrics.tv:.2f}")
                        
                        # 给出建议
                        if metrics.overall_score < 40:
                            print(f"   ⚠️  评分较低，建议重新整定")
                        elif metrics.overall_score < 55:
                            print(f"   ⚡ 评分一般，可以优化")
                        elif metrics.overall_score < 70:
                            print(f"   ✓  评分良好")
                        else:
                            print(f"   ✓  评分优秀")
                            
                    except Exception as e:
                        print(f"   ⚠️ 段 {seg_idx} 评估失败: {e}")
        else:
            # 单段整定，对整个数据段进行仿真并评估
            try:
                # 确定初始值
                initial_pv = pv[0] if len(pv) > 0 else 0.0
                initial_mv = mv[0] if mv is not None and len(mv) > 0 else None
                
                print(f"\n   【全段仿真】")
                print(f"   - 数据点数: {len(t)}")
                print(f"   - 初始PV: {initial_pv:.3f}")
                print(f"   - 设定值: {np.mean(sv):.3f}")
                
                # 仿真整个数据段
                pv_simulated, mv_simulated = simulate_system_with_pid(
                    t, system_model, model_params, new_pid_params,
                    setpoint=np.mean(sv),
                    initial_pv=initial_pv,
                    initial_mv=initial_mv,
                    verbose=False,
                    setpoint_array=sv,
                    mv_reference=mv,
                    pv_reference=pv
                )
                
                print(f"   - 仿真完成: {len(pv_simulated)} 个点")
                print(f"   - 最终PV: {pv_simulated[-1]:.3f}")
                print(f"   - 最终误差: {abs(pv_simulated[-1] - sv[-1]):.4f}")
                
                # 评估仿真结果（启用SV变化初期排除功能）
                metrics = evaluator.evaluate(
                    pv_simulated, sv, mv_simulated,  # ← 使用仿真数据
                    exclude_sv_transition=True  # 排除SV变化初期，避免IAE虚高
                )
                
                # 显示排除信息
                eval_start = evaluator._find_steady_state_start(pv_simulated, sv)
                if eval_start > 0:
                    print(f"   ℹ️  排除SV调整期间: 前 {eval_start} 个点（索引 0-{eval_start-1}）")
                    print(f"   ℹ️  实际评估点数: {len(pv_simulated) - eval_start} 个点")
                
                evaluation_results.append({
                    'segment_index': 1,
                    'segment_range': (0, len(pv)),
                    'metrics': metrics,
                    'pid_params': {
                        'pb': tuning_result.get('pb', 'N/A'),
                        'ti': tuning_result.get('ti', 'N/A'),
                        'td': tuning_result.get('td', 'N/A')
                    }
                })
                
                print(f"\n   【整体评估结果（基于仿真）】")
                print(f"   PID参数: Pb={tuning_result.get('pb', 'N/A'):.2f}%, "
                      f"Ti={tuning_result.get('ti', 'N/A'):.2f}s, Td={tuning_result.get('td', 'N/A'):.2f}s")
                print(f"   综合评分: {metrics.overall_score:.2f} ({metrics.grade})")
                print(f"   稳态误差: {metrics.steady_state_error:.4f}")
                print(f"   IAE:      {metrics.iae:.2f}")
                print(f"   振荡次数: {metrics.oscillation_count}")
                print(f"   控制变化: {metrics.tv:.2f}")
                
                # 生成详细报告
                report = evaluator.generate_report(metrics)
                print(report)
                    
            except Exception as e:
                print(f"   ⚠️ 评估失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 输出评估统计
        if len(evaluation_results) > 0:
            scores = [r['metrics'].overall_score for r in evaluation_results]
            print(f"\n   【评估统计】")
            print(f"   评估段数: {len(evaluation_results)}")
            print(f"   平均评分: {np.mean(scores):.2f}")
            print(f"   最高评分: {max(scores):.2f}")
            print(f"   最低评分: {min(scores):.2f}")
            
            # 保存评估结果到文件
            if output_dir is not None:
                eval_file = os.path.join(output_dir, 
                                        f"{os.path.splitext(os.path.basename(json_file_path))[0]}_evaluation.json")
                try:
                    import json as json_module
                    eval_data = {
                        'file': json_file_path,
                        'segments': [
                            {
                                'segment_index': r['segment_index'],
                                'segment_range': r['segment_range'],
                                'pid_params': r['pid_params'],
                                'metrics': r['metrics'].to_dict()
                            }
                            for r in evaluation_results
                        ],
                        'statistics': {
                            'count': len(evaluation_results),
                            'avg_score': float(np.mean(scores)),
                            'max_score': float(max(scores)),
                            'min_score': float(min(scores))
                        }
                    }
                    with open(eval_file, 'w', encoding='utf-8') as f:
                        json_module.dump(eval_data, f, indent=2, ensure_ascii=False)
                    print(f"   ✅ 评估结果已保存: {eval_file}")
                except Exception as e:
                    print(f"   ⚠️ 保存评估结果失败: {e}")
            
            # 暂时移除仿真对比图生成，因为需要重新设计
            # TODO: 在可视化后生成，使用与可视化相同的仿真数据
            pass
    
    # 6. 提取整定段信息（用于可视化标注）
    tuning_segment_indices = None
    
    if tuning_result is None:
        print("✅ 所有段都已稳态，无需整定，跳过可视化")
        if output_dir is not None:
            print(f"   - 输出目录: {output_dir}（所有段都稳态，未生成图片）")
        return
    
    # 检查是否是不需要整定但需要标注非稳态段的情况
    if tuning_result.get('no_tuning_needed', False):
        print("📊 无需整定，但需要标注非稳态段，继续可视化")
        tuning_segment_indices = None
    
    if 'all_segments_results' in tuning_result:
        all_segments_results = tuning_result.get('all_segments_results', [])
        if len(all_segments_results) > 0:
            print(f"\n📊 检测到 {len(all_segments_results)} 个整定段:")
            for seg_result in all_segments_results:
                seg_idx = seg_result.get('segment_index', 0)
                seg_indices = seg_result.get('segment_indices')
                if seg_indices is not None:
                    start_idx, end_idx = seg_indices
                    start_idx = max(0, min(start_idx, len(t) - 1))
                    end_idx = max(0, min(end_idx, len(t) - 1))
                    print(f"   段 {seg_idx}: 索引 [{start_idx}, {end_idx}], "
                          f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
            tuning_segment_indices = None
        elif 'segment_indices' in tuning_result:
            tuning_segment_indices = tuning_result['segment_indices']
            start_idx, end_idx = tuning_segment_indices
            start_idx = max(0, min(start_idx, len(t) - 1))
            end_idx = max(0, min(end_idx, len(t) - 1))
            tuning_segment_indices = (start_idx, end_idx)
            print(f"\n📊 整定段（来自分段整定结果）: 索引 [{start_idx}, {end_idx}], "
                  f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
    elif 'segment_indices' in tuning_result:
        tuning_segment_indices = tuning_result['segment_indices']
        start_idx, end_idx = tuning_segment_indices
        start_idx = max(0, min(start_idx, len(t) - 1))
        end_idx = max(0, min(end_idx, len(t) - 1))
        tuning_segment_indices = (start_idx, end_idx)
        print(f"\n📊 整定段（来自分段整定结果）: 索引 [{start_idx}, {end_idx}], "
              f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
    else:
        if 'segment_indices' in tuning_result:
            tuning_segment_indices = tuning_result['segment_indices']
            start_idx, end_idx = tuning_segment_indices
            start_idx = max(0, min(start_idx, len(t) - 1))
            end_idx = max(0, min(end_idx, len(t) - 1))
            tuning_segment_indices = (start_idx, end_idx)
            print(f"\n📊 整定段（来自整定结果）: 索引 [{start_idx}, {end_idx}], "
                  f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
        else:
            case = identifier.classify_case(pv, setpoint)
            
            if case in ["CASE_1", "CASE_2", "CASE_3"]:
                if mv is not None:
                    t_seg, y_seg, u_seg = identifier.extract_tuning_segment(case, t, pv, setpoint, mv)
                else:
                    t_seg, y_seg = identifier.extract_tuning_segment(case, t, pv, setpoint)
                
                if t_seg is not None and len(t_seg) > 0:
                    start_time = t_seg[0]
                    end_time = t_seg[-1]
                    start_idx = np.argmin(np.abs(t - start_time))
                    end_idx = np.argmin(np.abs(t - end_time))
                    tuning_segment_indices = (start_idx, end_idx)
                    print(f"\n📊 整定段（来自case分类）: 索引 [{start_idx}, {end_idx}], "
                          f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
    
    # 7. 可视化（仿真已在评估前完成）
    print(f"\n🎨 开始可视化...")
    
    old_pid_params = None
    
    # 生成输出路径
    save_path = None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(json_file_path))[0]
        save_path = os.path.join(output_dir, f"{base_name}_pid_tuning_evaluation.png")
    
    try:
        fig = simulate_and_visualize(
            t, pv, mv, sv,
            tuning_result,
            tuning_segment_indices=tuning_segment_indices,
            old_pid_params=old_pid_params,
            save_path=save_path,
            verbose=verbose,
            show_plot=show_plot
        )
        
        if fig is not None:
            print(f"\n✅ 仿真和可视化完成!")
            if save_path:
                print(f"   - 图片已保存: {save_path}")
                if os.path.exists(save_path):
                    file_size = os.path.getsize(save_path)
                    print(f"   - 文件大小: {file_size / 1024:.2f} KB")
                else:
                    print(f"   ⚠️ 警告: 文件路径存在但文件未找到: {save_path}")
        else:
            print(f"\n⚠️ 仿真或可视化失败")
            if save_path:
                print(f"   - 预期保存路径: {save_path}")
            
    except Exception as e:
        print(f"❌ 仿真或可视化失败: {e}")
        import traceback
        traceback.print_exc()
        return


if __name__ == "__main__":
    
    # 配置参数
    DATA_DIR = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/data_simulation/zhongkong'
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(BASE_DIR, "output_evaluation")
    VERBOSE = True
    SHOW_PLOT = False
    
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print(f"   - 目录是否存在: {os.path.exists(OUTPUT_DIR)}")
    print(f"   - 目录是否可写: {os.access(OUTPUT_DIR, os.W_OK)}")
    
    # 获取所有JSON文件
    json_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.json')]
    json_files.sort()
    
    print("=" * 80)
    print(f"开始批量测试（带评估），共 {len(json_files)} 个文件")
    print(f"数据目录: {DATA_DIR}")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 80)
    
    success_count = 0
    fail_count = 0
    
    # 遍历所有JSON文件进行测试
    for idx, json_file in enumerate(json_files, 1):
        json_file_path = os.path.join(DATA_DIR, json_file)
        print(f"\n{'='*80}")
        print(f"[{idx}/{len(json_files)}] 处理文件: {json_file}")
        print(f"{'='*80}")
        
        try:
            main(json_file_path, output_dir=OUTPUT_DIR, verbose=VERBOSE, 
                 show_plot=SHOW_PLOT, enable_evaluation=True)
            success_count += 1
        except Exception as e:
            print(f"\n❌ 处理文件 {json_file} 时出错: {e}")
            fail_count += 1
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("批量测试完成")
    print("=" * 80)
    print(f"✅ 成功: {success_count} 个文件")
    print(f"❌ 失败: {fail_count} 个文件")
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print("=" * 80)
