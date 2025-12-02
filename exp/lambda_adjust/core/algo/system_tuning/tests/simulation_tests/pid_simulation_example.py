import numpy as np
import json
import sys
import os

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
tests_dir = os.path.dirname(current_dir)  # tests目录
system_tuning_dir = os.path.dirname(tests_dir)  # system_tuning目录
sys.path.insert(0, system_tuning_dir)
from core.tuning.identifier import SystemIdentifier
from config import TuningMethod, Mode
from core.pid.simulator import simulate_and_visualize
from core.reporting import TuningReportGenerator
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


def main(json_file_path, output_dir=None, verbose=True, show_plot=False, save_report=True):
    """
    主函数：执行PID整定、仿真和可视化
    
    Args:
        json_file_path: JSON数据文件路径
        output_dir: 输出目录（用于保存图形），如果为None则不保存
        verbose: 是否打印详细信息
        show_plot: 是否显示可视化图形（True显示，False不显示）
        save_report: 是否保存整定报告（默认True）
    """
    print("=" * 80)
    print("PID整定仿真和可视化示例")
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
    
    # 2. PID整定
    print(f"\n🔧 开始PID整定...")
    identifier = SystemIdentifier()
    
    setpoint = np.mean(sv)
    tuning_method = TuningMethod.LAMBDA
    
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
            # 即使无需整定，也输出信息到日志
            if output_dir is not None:
                print(f"   - 输出目录: {output_dir}（无需整定，未生成图片）")
            return
        
        # 检查是否是不需要整定但需要标注非稳态段的情况
        if tuning_result.get('no_tuning_needed', False):
            print(f"⚠️ {tuning_result.get('message', '无需整定，但存在非稳态段需要标注')}")
            # 继续执行可视化，标注非稳态段
            # 这种情况下没有PID参数，跳过参数打印
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
    
    # 2.5. 生成整定报告
    if save_report and tuning_result is not None and not tuning_result.get('no_tuning_needed', False):
        print(f"\n📝 生成整定报告...")
        try:
            # 准备报告数据
            report_generator = TuningReportGenerator()
            
            # 提取原始PID参数（如果有的话）
            original_pid = tuning_result.get('original_pid', {
                'Kp': 0.0,
                'Ki': 0.0,
                'Kd': 0.0
            })
            
            # 提取整定后的PID参数
            tuned_pid = {
                'Kp': tuning_result.get('kp', 0.0),
                'Ki': tuning_result.get('ki', 0.0),
                'Kd': tuning_result.get('kd', 0.0)
            }
            
            # 提取模型参数
            model_params = {
                'model_type': tuning_result.get('model_type', 'Unknown'),
                'fit_score': tuning_result.get('fit_score', 0.0)
            }
            
            # 添加具体的模型参数
            if 'K' in tuning_result:
                model_params['K'] = tuning_result['K']
            if 'tau' in tuning_result:
                model_params['tau'] = tuning_result['tau']
            if 'theta' in tuning_result:
                model_params['theta'] = tuning_result['theta']
            
            # 提取评估指标（如果有的话）
            evaluation_metrics = tuning_result.get('evaluation', {
                'overall': {
                    'score': 75.0,
                    'grade': 'C'
                }
            })
            
            # 提取非稳态段
            non_steady_segments = []
            if 'all_segments_results' in tuning_result:
                for seg_result in tuning_result['all_segments_results']:
                    seg_indices = seg_result.get('segment_indices')
                    if seg_indices:
                        start_idx, end_idx = seg_indices
                        seg_setpoint = seg_result.get('setpoint', setpoint)
                        non_steady_segments.append((start_idx, end_idx, seg_setpoint))
            elif 'segment_indices' in tuning_result:
                start_idx, end_idx = tuning_result['segment_indices']
                non_steady_segments.append((start_idx, end_idx, setpoint))
            
            # 确定案例类型
            case_type = tuning_result.get('scenario', 'UNKNOWN')
            if case_type not in ['CASE_1', 'CASE_2', 'CASE_3', 'ALREADY_STABLE']:
                case_type = 'CASE_3'  # 默认为扰动场景
            
            # 生成报告
            report = report_generator.generate_report(
                case_type=case_type,
                original_pid=original_pid,
                tuned_pid=tuned_pid,
                model_params=model_params,
                evaluation_metrics=evaluation_metrics,
                non_steady_segments=non_steady_segments,
                pv_data=pv,
                sv_data=sv
            )
            
            # 打印报告摘要
            report_generator.print_summary()
            
            # 保存报告文件
            if output_dir is not None:
                base_name = os.path.splitext(os.path.basename(json_file_path))[0]
                report_json_path = os.path.join(output_dir, f"{base_name}_tuning_report.json")
                report_md_path = os.path.join(output_dir, f"{base_name}_tuning_report.md")
                
                report_generator.export_to_json(report_json_path)
                report_generator.export_to_markdown(report_md_path)
                
                print(f"✅ 报告已保存:")
                print(f"   - JSON: {report_json_path}")
                print(f"   - Markdown: {report_md_path}")
        
        except Exception as e:
            print(f"⚠️ 报告生成失败: {e}")
            if verbose:
                import traceback
                traceback.print_exc()
    
    # 3. 提取整定段信息（用于可视化标注）
    # 如果使用了分段整定，优先使用所有段的整定结果
    # 注意：如果 tuning_result 为 None，说明所有段都稳态，无需整定，也不应该进行可视化
    tuning_segment_indices = None
    
    if tuning_result is None:
        # 所有段都稳态，无需整定，也不应该进行可视化
        print("✅ 所有段都已稳态，无需整定，跳过可视化")
        if output_dir is not None:
            print(f"   - 输出目录: {output_dir}（所有段都稳态，未生成图片）")
        return
    
    # 检查是否是不需要整定但需要标注非稳态段的情况
    if tuning_result.get('no_tuning_needed', False):
        # 不需要整定，但需要标注非稳态段，继续执行可视化
        print("📊 无需整定，但需要标注非稳态段，继续可视化")
        tuning_segment_indices = None  # 使用非稳态段作为标注
    
    if 'all_segments_results' in tuning_result:
        # 多段整定：使用所有段的整定结果
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
            # 对于多段整定，tuning_segment_indices 设为 None，让可视化函数使用 all_segments_results
            tuning_segment_indices = None
        elif 'segment_indices' in tuning_result:
            # 如果没有 all_segments_results，但有关键段索引，使用它
            tuning_segment_indices = tuning_result['segment_indices']
            start_idx, end_idx = tuning_segment_indices
            start_idx = max(0, min(start_idx, len(t) - 1))
            end_idx = max(0, min(end_idx, len(t) - 1))
            tuning_segment_indices = (start_idx, end_idx)
            print(f"\n📊 整定段（来自分段整定结果）: 索引 [{start_idx}, {end_idx}], "
                  f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
    elif 'segment_indices' in tuning_result:
        # 使用分段整定的结果（单段）
        tuning_segment_indices = tuning_result['segment_indices']
        start_idx, end_idx = tuning_segment_indices
        # 确保索引在有效范围内
        start_idx = max(0, min(start_idx, len(t) - 1))
        end_idx = max(0, min(end_idx, len(t) - 1))
        tuning_segment_indices = (start_idx, end_idx)
        print(f"\n📊 整定段（来自分段整定结果）: 索引 [{start_idx}, {end_idx}], "
              f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
    else:
        # 优先从tuning_result中获取segment_indices（单段整定时会包含此信息）
        if 'segment_indices' in tuning_result:
            tuning_segment_indices = tuning_result['segment_indices']
            start_idx, end_idx = tuning_segment_indices
            start_idx = max(0, min(start_idx, len(t) - 1))
            end_idx = max(0, min(end_idx, len(t) - 1))
            tuning_segment_indices = (start_idx, end_idx)
            print(f"\n📊 整定段（来自整定结果）: 索引 [{start_idx}, {end_idx}], "
                  f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
        else:
            # 如果没有segment_indices，使用原有的case分类方法
            case = identifier.classify_case(pv, setpoint)
            
            if case in ["CASE_1", "CASE_2", "CASE_3"]:
                # 提取整定段
                if mv is not None:
                    t_seg, y_seg, u_seg = identifier.extract_tuning_segment(case, t, pv, setpoint, mv)
                else:
                    t_seg, y_seg = identifier.extract_tuning_segment(case, t, pv, setpoint)
                
                if t_seg is not None and len(t_seg) > 0:
                    # 找到整定段在原始数据中的索引
                    start_time = t_seg[0]
                    end_time = t_seg[-1]
                    start_idx = np.argmin(np.abs(t - start_time))
                    end_idx = np.argmin(np.abs(t - end_time))
                    tuning_segment_indices = (start_idx, end_idx)
                    print(f"\n📊 整定段（来自case分类）: 索引 [{start_idx}, {end_idx}], "
                          f"时间 [{t[start_idx]:.1f}s, {t[end_idx]:.1f}s]")
    
    # 4. 仿真和可视化
    print(f"\n🎨 开始仿真和可视化...")
    
    # 准备旧PID参数（如果有的话，可以从数据中估计或使用默认值）
    old_pid_params = None  # 可以设置为实际值，如果知道的话
    
    # 生成输出路径
    save_path = None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(json_file_path))[0]
        save_path = os.path.join(output_dir, f"{base_name}_pid_tuning_comparison.png")
    
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
                # 验证文件是否真的存在
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
    # 使用基于当前文件位置的绝对路径
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    VERBOSE = True
    SHOW_PLOT = False  # 设置为True显示图形，False不显示（批量测试时建议False）
    SAVE_REPORT = True  # 设置为True保存整定报告（JSON和Markdown格式）
    
    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print(f"   - 目录是否存在: {os.path.exists(OUTPUT_DIR)}")
    print(f"   - 目录是否可写: {os.access(OUTPUT_DIR, os.W_OK)}")
    
    # 获取所有JSON文件
    json_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.json')]
    json_files.sort()  # 按文件名排序
    
    print("=" * 80)
    print(f"开始批量测试，共 {len(json_files)} 个文件")
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
            main(json_file_path, output_dir=OUTPUT_DIR, verbose=VERBOSE, show_plot=SHOW_PLOT, 
                 save_report=SAVE_REPORT)
            success_count += 1
        except Exception as e:
            print(f"\n❌ 处理文件 {json_file} 时出错: {e}")
            fail_count += 1
            import traceback
            traceback.print_exc()
    
    # 输出总结
    print("\n" + "=" * 80)
    print("批量测试完成")
    print("=" * 80)
    print(f"✅ 成功: {success_count} 个文件")
    print(f"❌ 失败: {fail_count} 个文件")
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print("=" * 80)

