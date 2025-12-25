"""使用真实数据测试 LLM 临界法整定

使用方法:
    1. 确保 Ollama 已启动: ollama serve
    2. 修改 CONFIG 配置
    3. 运行: python -m core.algorithm.model_type.test_llm_with_real_data
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Dict
import requests

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods
from core.algorithm.model_type.model_selector import ModelSelector


# ============================================================
# 配置区域
# ============================================================

CONFIG = {
    # 回路 URI
    # 'loop_uri': "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",  # 101
    'loop_uri': "/pid_zd/b352328ec0cd4a9c958b32815e67a96a",
    # 回路信息（用于 LLM 决策）
    'loop_type': 'flow',  # flow/temperature/pressure/level
    'loop_name': '101回路',
    
    # 测试场景
    'scenarios': [
        {'start_time': '2025-12-18 00:39:41', 'end_time': '2025-12-18 23:39:41'},
    ],
    
    # Ollama 配置
    'ollama_model': 'qwen:7b',
    'ollama_base_url': 'http://localhost:11434',
    
    # 是否输出详细日志
    'verbose': True,
    
    # 日志保存目录
    'log_dir': '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test',
}


# ============================================================
# Ollama 客户端
# ============================================================

class OllamaClient:
    """Ollama 本地模型客户端"""
    
    def __init__(self, model: str = "qwen:7b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
    
    def chat(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,  # 降低随机性，提高输出稳定性
                        "num_predict": 256,  # 限制输出长度，避免冗长回复
                    }
                },
                timeout=120
            )
            response.raise_for_status()
            return response.json()["response"]
        except requests.exceptions.ConnectionError:
            raise ConnectionError("无法连接到 Ollama，请确保已运行 'ollama serve'")
        except Exception as e:
            raise RuntimeError(f"Ollama 调用失败: {e}")


# ============================================================
# 数据获取
# ============================================================

def get_history_data(start_time: int, end_time: int, loop_uri: str = None) -> List[Dict]:
    """获取历史数据"""
    loop_uri = loop_uri or CONFIG['loop_uri']
    
    table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)
    db = get_default_database()
    
    history_data: List[Dict] = process_query_tsdb_data_interpolated(
        db=db,
        table_name=table,
        required_fields=required_fields,
        start_time=start_time,
        end_time=end_time,
        is_filter=False
    )
    
    if not history_data:
        print("❌ 未获取到历史数据")
        return []
    print(f"✅ 获取到历史数据：{len(history_data)} 条")
    return history_data


def detect_tuning_windows(data: List[Dict]) -> Dict:
    """检测扰动段"""
    result = find_high_variability_periods({"history_data": data})
    
    if result.get('qualified_windows'):
        converted_windows = []
        for w in result['qualified_windows']:
            start_ms = w['start_time']
            end_ms = w['end_time']
            start_str = datetime.fromtimestamp(start_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            end_str = datetime.fromtimestamp(end_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            converted_windows.append({
                'start_time': start_ms,
                'end_time': end_ms,
                'start_time_str': start_str,
                'end_time_str': end_str
            })
        result['tuning_window'] = converted_windows
    else:
        result['tuning_window'] = []
    
    return result


def convert_to_arrays(data: List[Dict]) -> tuple:
    """将数据转换为numpy数组"""
    pv_array = np.array([d.get('pv', 0.0) for d in data], dtype=np.float64)
    sv_array = np.array([d.get('sv', 0.0) for d in data], dtype=np.float64)
    mv_array = np.array([d.get('mv', 0.0) for d in data], dtype=np.float64)
    timestamps = np.array([d.get('timestamp', 0) for d in data], dtype=np.int64)
    return pv_array, sv_array, mv_array, timestamps


# ============================================================
# 可视化
# ============================================================

def visualize_fitting_result(data: List[Dict], tuning_input: Dict, 
                              fitting_result: Dict, scenario_name: str = None,
                              llm_used: bool = False):
    """可视化模型拟合结果（含闭环验证）"""
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    
    # 从 fitting_result 提取拟合数据
    fit_data = fitting_result.get('fitting_result', {})
    fit_timestamps = fit_data.get('timestamp', [])
    fit_pv = fit_data.get('pv', [])
    fit_pv_model = fit_data.get('pv_model', [])
    fit_time_array = [datetime.fromtimestamp(ts / 1000) for ts in fit_timestamps] if fit_timestamps else []
    
    # 获取闭环验证数据
    closed_loop_info = fitting_result.get('closed_loop_verification', {})
    has_closed_loop = closed_loop_info and closed_loop_info.get('is_stable') is not None
    
    # 创建图表：如果有闭环数据则4个子图，否则3个
    n_plots = 4 if has_closed_loop else 3
    fig = plt.figure(figsize=(16, 4 * n_plots))
    
    model_type = fitting_result.get('model_type', 'Unknown')
    r2 = fit_data.get('r_squared', 0)
    rmse = fit_data.get('rmse', 0)
    fusion_info = fitting_result.get('fusion_info', {})
    
    # 闭环状态
    cl_status = ""
    if has_closed_loop:
        is_stable = closed_loop_info.get('is_stable', False)
        cl_status = f" | 闭环: {'✅稳定' if is_stable else '❌不稳定'}"
    
    # LLM 标识
    llm_tag = " [🤖LLM]" if llm_used else " [规则引擎]"
    
    fig.suptitle(f'LLM 临界法整定结果{llm_tag} - {model_type} (R²={r2:.4f}, RMSE={rmse:.4f}){cl_status}\n'
                 f'融合方法: {fusion_info.get("method", "N/A")}, 使用段数: {fusion_info.get("n_segments", 0)}, '
                 f'一致性: {fusion_info.get("consistency_score", 0):.2f}', 
                 fontsize=12, fontweight='bold')
    
    # ========== 子图1: PV/SV + 拟合曲线 ==========
    ax1 = fig.add_subplot(n_plots, 1, 1)
    ax1.plot(time_array, pv_array, 'b-', label='PV (实测)', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV (设定值)', linewidth=1.2)
    
    if fit_time_array and fit_pv_model:
        ax1.plot(fit_time_array, fit_pv_model, 'g-', label='PV_model (拟合)', linewidth=1.5, alpha=0.9)
    
    # 标记 tuning_window（扰动段）- 橙色
    tuning_windows = tuning_input.get('tuning_window', [])
    for i, w in enumerate(tuning_windows):
        start_ts = w.get('start_time')
        end_ts = w.get('end_time')
        if start_ts and end_ts:
            start_dt = datetime.fromtimestamp(start_ts / 1000)
            end_dt = datetime.fromtimestamp(end_ts / 1000)
            ax1.axvspan(start_dt, end_dt, alpha=0.15, color='orange', 
                       label='扰动段' if i == 0 else None)
    
    # 标记整定段/振荡段
    segment_info = fitting_result.get('segment_info', [])
    tuning_count = 0
    osc_count = 0
    for seg in segment_info:
        start_ts = seg.get('start_time')
        end_ts = seg.get('end_time')
        seg_type = seg.get('type', 'oscillation')
        if start_ts and end_ts:
            start_dt = datetime.fromtimestamp(start_ts / 1000)
            end_dt = datetime.fromtimestamp(end_ts / 1000)
            if seg_type == 'tuning':
                ax1.axvspan(start_dt, end_dt, alpha=0.3, color='green', 
                           label='整定段' if tuning_count == 0 else None)
                tuning_count += 1
            else:
                ax1.axvspan(start_dt, end_dt, alpha=0.1, color='red', 
                           label='振荡段' if osc_count == 0 else None)
                osc_count += 1
    
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值与模型拟合对比')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(n_plots, 1, 2, sharex=ax1)
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    
    for i, w in enumerate(tuning_windows):
        start_ts = w.get('start_time')
        end_ts = w.get('end_time')
        if start_ts and end_ts:
            start_dt = datetime.fromtimestamp(start_ts / 1000)
            end_dt = datetime.fromtimestamp(end_ts / 1000)
            ax2.axvspan(start_dt, end_dt, alpha=0.15, color='orange')
    
    for seg in segment_info:
        start_ts = seg.get('start_time')
        end_ts = seg.get('end_time')
        seg_type = seg.get('type', 'oscillation')
        if start_ts and end_ts:
            start_dt = datetime.fromtimestamp(start_ts / 1000)
            end_dt = datetime.fromtimestamp(end_ts / 1000)
            color = 'green' if seg_type == 'tuning' else 'red'
            alpha = 0.3 if seg_type == 'tuning' else 0.1
            ax2.axvspan(start_dt, end_dt, alpha=alpha, color=color)
    
    ax2.set_ylabel('MV')
    ax2.set_title('操作值(MV)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 拟合误差或LLM决策信息 ==========
    ax3 = fig.add_subplot(n_plots, 1, 3, sharex=ax1)
    is_oscillation_tuning = 'oscillation' in fusion_info.get('method', '')
    
    if is_oscillation_tuning:
        # 振荡整定模式，显示 LLM 决策信息
        pid_params = fitting_result.get('pid_parameters', {})
        llm_decision = pid_params.get('llm_decision', {})
        
        info_text = "振荡整定模式（临界法）\n"
        info_text += f"pb={pid_params.get('pb', 'N/A')}%, "
        info_text += f"Ti={pid_params.get('ti', 'N/A')}s, "
        info_text += f"Td={pid_params.get('td', 'N/A')}s\n\n"
        
        if llm_decision:
            strategy = llm_decision.get('strategy_params', {})
            info_text += "🤖 LLM 策略参数:\n"
            info_text += f"  safety_factor: {strategy.get('safety_factor', 'N/A')}\n"
            info_text += f"  pb_extra_factor: {strategy.get('pb_extra_factor', 'N/A')}\n"
            info_text += f"  ti_multiplier: {strategy.get('ti_multiplier', 'N/A')}\n"
            info_text += f"  enable_derivative: {strategy.get('enable_derivative', 'N/A')}\n"
            info_text += f"  td_factor: {strategy.get('td_factor', 'N/A')}\n\n"
            info_text += f"理由: {llm_decision.get('reasoning', 'N/A')}"
        else:
            info_text += "使用规则引擎（未调用 LLM）"
        
        ax3.text(0.5, 0.5, info_text, transform=ax3.transAxes, ha='center', va='center',
                fontsize=11, color='darkblue', style='italic',
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
        ax3.set_title('LLM 决策信息')
    elif fit_time_array and fit_pv and fit_pv_model:
        error = np.array(fit_pv) - np.array(fit_pv_model)
        ax3.plot(fit_time_array, error, 'r-', label='误差 (PV - PV_model)', linewidth=0.8)
        ax3.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
        ax3.fill_between(fit_time_array, error, 0, alpha=0.3, color='red')
        ax3.set_title('拟合误差')
    else:
        ax3.set_title('拟合误差')
    
    ax3.set_ylabel('误差')
    ax3.grid(True, alpha=0.3)
    
    # ========== 子图4: 闭环稳定性验证 ==========
    if has_closed_loop:
        ax4 = fig.add_subplot(n_plots, 1, 4)
        
        from core.algorithm.model_type.tuning.pid_calculator import PIDCalculator
        from core.algorithm.model_type.data_models import FusionResult
        
        model_params = fitting_result.get('model_parameters', {})
        pid_params = fitting_result.get('pid_parameters', {})
        
        fusion = FusionResult(
            model_type=model_type,
            K=model_params.get('K', 0),
            T1=model_params.get('T1', 0),
            T2=model_params.get('T2', 0),
            L=model_params.get('L', 0)
        )
        
        calculator = PIDCalculator()
        
        sp_initial = closed_loop_info.get('sp_initial', 50.0)
        sp_final = closed_loop_info.get('sp_final', 60.0)
        pv_initial = closed_loop_info.get('pv_initial', 50.0)
        
        T_ref = fusion.T1 if fusion.T1 > 0 else 10.0
        dt = min(0.1, T_ref / 10)
        dt = max(0.01, dt)
        sim_time = max(200, T_ref * 25)
        n_steps = min(int(sim_time / dt), 10000)
        
        metrics = calculator.simulate_closed_loop(
            K=fusion.K, T1=fusion.T1, T2=fusion.T2, L=fusion.L,
            model_type=fusion.model_type,
            Kp=pid_params.get('kp', 1), Ki=pid_params.get('ki', 0), Kd=pid_params.get('kd', 0),
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            n_steps=n_steps, dt=dt
        )
        
        t_sim = np.arange(len(metrics.pv_history)) * dt
        sp_sim = np.zeros_like(metrics.pv_history)
        sp_sim[:10] = sp_initial
        sp_sim[10:] = sp_final
        
        ax4.plot(t_sim, metrics.pv_history, 'b-', label='PV (闭环响应)', linewidth=1.5)
        ax4.plot(t_sim, sp_sim, 'r--', label='SP (设定值)', linewidth=1.2)
        
        is_stable = closed_loop_info.get('is_stable', False)
        settling_time = closed_loop_info.get('settling_time', -1)
        overshoot = closed_loop_info.get('overshoot', 0)
        rise_time = closed_loop_info.get('rise_time', -1)
        sse = closed_loop_info.get('steady_state_error', 0)
        
        status_text = '✅ 稳定' if is_stable else '❌ 不稳定'
        textstr = f'{status_text}\n'
        textstr += f'调节时间: {settling_time:.1f}s\n' if settling_time >= 0 else '调节时间: N/A\n'
        textstr += f'超调量: {overshoot:.1f}%\n'
        textstr += f'上升时间: {rise_time:.1f}s\n' if rise_time >= 0 else '上升时间: N/A\n'
        textstr += f'稳态误差: {sse:.2f}%'
        
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
        ax4.text(0.98, 0.95, textstr, transform=ax4.transAxes, fontsize=10,
                verticalalignment='top', horizontalalignment='right', bbox=props)
        
        sp_change = abs(sp_final - sp_initial)
        error_band = sp_change * 0.02
        ax4.axhline(y=sp_final + error_band, color='gray', linestyle=':', alpha=0.5, label='±2%误差带')
        ax4.axhline(y=sp_final - error_band, color='gray', linestyle=':', alpha=0.5)
        ax4.fill_between(t_sim, sp_final - error_band, sp_final + error_band, alpha=0.1, color='green')
        
        if settling_time >= 0 and settling_time < t_sim[-1]:
            ax4.axvline(x=settling_time, color='purple', linestyle='--', linewidth=1.5, 
                       label=f'调节时间 ({settling_time:.1f}s)')
        
        ax4.set_xlabel('时间 (s)')
        ax4.set_ylabel('PV / SP')
        ax4.set_title(f'闭环稳定性验证 (Kp={pid_params.get("kp", 0):.3f}, Ki={pid_params.get("ki", 0):.3f}, Kd={pid_params.get("kd", 0):.3f})')
        ax4.legend(loc='lower right')
        ax4.grid(True, alpha=0.3)
        
        # 调整显示范围
        if settling_time >= 0 and settling_time < t_sim[-1]:
            x_max = min(t_sim[-1], max(80, settling_time * 1.3))
        else:
            x_max = t_sim[-1]
        ax4.set_xlim([0, x_max])
        
        pv_min = min(np.min(metrics.pv_history), sp_initial, sp_final)
        pv_max = max(np.max(metrics.pv_history), sp_initial, sp_final)
        y_margin = (pv_max - pv_min) * 0.1
        ax4.set_ylim([pv_min - y_margin, pv_max + y_margin])
    
    plt.tight_layout()
    
    # 保存图表
    os.makedirs(CONFIG['log_dir'], exist_ok=True)
    if scenario_name:
        filename = f'llm_tuning_{scenario_name}.png'
    else:
        filename = f'llm_tuning_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    
    filepath = os.path.join(CONFIG['log_dir'], filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 图表已保存至: {filepath}")
    plt.close()


# ============================================================
# 测试函数
# ============================================================

def test_with_llm():
    """使用 LLM 进行整定测试"""
    print("=" * 70)
    print("使用真实数据测试 LLM 临界法整定")
    print("=" * 70)
    
    # 1. 检查 Ollama 连接
    print("\n📡 检查 Ollama 连接...")
    llm_client = None
    try:
        llm_client = OllamaClient(
            model=CONFIG['ollama_model'],
            base_url=CONFIG['ollama_base_url']
        )
        response = llm_client.chat("回复OK")
        print(f"✅ Ollama 连接成功 (模型: {CONFIG['ollama_model']})")
    except Exception as e:
        print(f"❌ Ollama 连接失败: {e}")
        print("   将使用规则引擎进行整定")
        llm_client = None
    
    # 2. 创建 ModelSelector（带 LLM）
    print("\n📊 创建 ModelSelector...")
    selector = ModelSelector(
        verbose=CONFIG['verbose'],
        llm_client=llm_client,
        process_context={
            'loop_type': CONFIG['loop_type'],
            'loop_name': CONFIG['loop_name']
        }
    )
    
    # 3. 获取数据并整定
    for idx, scenario in enumerate(CONFIG['scenarios'], 1):
        start_time_str = scenario['start_time']
        end_time_str = scenario['end_time']
        
        start_ts = int(datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        
        print(f"\n{'='*70}")
        print(f"场景 {idx}: {start_time_str} ~ {end_time_str}")
        print(f"回路: {CONFIG['loop_name']} ({CONFIG['loop_type']})")
        print(f"{'='*70}")
        
        # 获取数据
        data = get_history_data(start_ts, end_ts)
        if not data:
            continue
        
        # 检测扰动段
        tuning_input = detect_tuning_windows(data)
        qualified_windows = tuning_input.get('qualified_windows', [])
        
        if not qualified_windows:
            print("⚠️ 未检测到扰动段")
            continue
        
        print(f"✅ 检测到 {len(qualified_windows)} 个扰动段")
        
        # 执行整定
        print("\n🔧 开始整定...")
        start_time = time.time()
        
        input_data = {
            'history_data': data,
            'params': {
                'model_type': None,
                'turning_type': None,
                'analyst_column': 'pv'
            },
            'qualified_windows': qualified_windows,
        }
        
        result = selector.run(input_data)
        
        elapsed_time = time.time() - start_time
        print(f"⏱️ 整定耗时: {elapsed_time:.2f} 秒")
        
        # 输出结果
        print_result(result)
        
        # 可视化
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        pid_params = result.get('pid_parameters', {})
        llm_used = 'llm_decision' in pid_params and pid_params['llm_decision']
        visualize_fitting_result(data, tuning_input, result, scenario_name, llm_used=llm_used)


def test_compare_llm_vs_rule():
    """对比 LLM 和规则引擎的整定结果（使用配置开关）"""
    from core.algorithm.model_type.config import Config
    
    print("=" * 70)
    print("对比测试: LLM vs 规则引擎")
    print("=" * 70)
    
    # 检查 Ollama
    llm_client = None
    try:
        llm_client = OllamaClient(
            model=CONFIG['ollama_model'],
            base_url=CONFIG['ollama_base_url']
        )
        llm_client.chat("OK")
        print("✅ Ollama 连接成功")
    except Exception as e:
        print(f"❌ Ollama 连接失败: {e}")
        print("   无法进行对比测试")
        return
    
    # 创建带 LLM 的 ModelSelector
    selector = ModelSelector(
        verbose=False,
        llm_client=llm_client,
        process_context={
            'loop_type': CONFIG['loop_type'],
            'loop_name': CONFIG['loop_name']
        }
    )
    
    for scenario in CONFIG['scenarios']:
        start_time_str = scenario['start_time']
        end_time_str = scenario['end_time']
        
        start_ts = int(datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        
        print(f"\n{'='*70}")
        print(f"场景: {start_time_str} ~ {end_time_str}")
        print(f"回路: {CONFIG['loop_name']} ({CONFIG['loop_type']})")
        print(f"{'='*70}")
        
        # 获取数据
        data = get_history_data(start_ts, end_ts)
        if not data:
            continue
        
        tuning_input = detect_tuning_windows(data)
        qualified_windows = tuning_input.get('qualified_windows', [])
        
        if not qualified_windows:
            print("⚠️ 未检测到扰动段")
            continue
        
        print(f"✅ 检测到 {len(qualified_windows)} 个扰动段")
        
        input_data = {
            'history_data': data,
            'params': {},
            'qualified_windows': qualified_windows,
        }
        
        # ========== 1. 关闭 LLM，使用规则引擎 ==========
        print("\n📊 [1/2] 规则引擎整定 (enable_llm=False)...")
        original_enable_llm = Config.OSCILLATION_TUNING.get('enable_llm', True)
        Config.OSCILLATION_TUNING['enable_llm'] = False
        
        start_time = time.time()
        result_rule = selector.run(input_data)
        time_rule = time.time() - start_time
        
        # ========== 2. 开启 LLM ==========
        print(f"\n🤖 [2/2] LLM 整定 (enable_llm=True)...")
        Config.OSCILLATION_TUNING['enable_llm'] = True
        
        start_time = time.time()
        result_llm = selector.run(input_data)
        time_llm = time.time() - start_time
        
        # 恢复原始配置
        Config.OSCILLATION_TUNING['enable_llm'] = original_enable_llm
        
        # ========== 对比结果 ==========
        print("\n" + "=" * 70)
        print("📊 对比结果")
        print("=" * 70)
        
        print(f"\n{'指标':<20} {'规则引擎':<20} {'LLM':<20} {'差异':<15}")
        print("-" * 75)
        
        # 整定方法
        method_rule = result_rule.get('fusion_info', {}).get('method', 'N/A')
        method_llm = result_llm.get('fusion_info', {}).get('method', 'N/A')
        print(f"{'整定方法':<20} {method_rule:<20} {method_llm:<20}")
        
        # PID 参数对比
        pid_rule = result_rule.get('pid_parameters', {})
        pid_llm = result_llm.get('pid_parameters', {})
        
        def format_diff(v1, v2):
            """计算差异百分比"""
            if v1 == 'N/A' or v2 == 'N/A':
                return '-'
            try:
                v1, v2 = float(v1), float(v2)
                if abs(v1) < 0.001:
                    return f"{v2 - v1:+.3f}"
                diff_pct = (v2 - v1) / abs(v1) * 100
                return f"{diff_pct:+.1f}%"
            except:
                return '-'
        
        params_to_compare = [
            ('pb (%)', 'pb'),
            ('Kp', 'kp'),
            ('Ki', 'ki'),
            ('Kd', 'kd'),
            ('Ti (s)', 'ti'),
            ('Td (s)', 'td'),
        ]
        
        for label, key in params_to_compare:
            v_rule = pid_rule.get(key, 'N/A')
            v_llm = pid_llm.get(key, 'N/A')
            diff = format_diff(v_rule, v_llm)
            print(f"{label:<20} {str(v_rule):<20} {str(v_llm):<20} {diff:<15}")
        
        # 闭环验证对比
        cl_rule = result_rule.get('closed_loop_verification', {})
        cl_llm = result_llm.get('closed_loop_verification', {})
        
        print(f"\n{'闭环稳定':<20} {'✅' if cl_rule.get('is_stable') else '❌':<20} {'✅' if cl_llm.get('is_stable') else '❌':<20}")
        
        settling_rule = cl_rule.get('settling_time', -1)
        settling_llm = cl_llm.get('settling_time', -1)
        settling_rule_str = f"{settling_rule:.1f}s" if settling_rule >= 0 else "N/A"
        settling_llm_str = f"{settling_llm:.1f}s" if settling_llm >= 0 else "N/A"
        print(f"{'调节时间':<20} {settling_rule_str:<20} {settling_llm_str:<20}")
        
        overshoot_rule = cl_rule.get('overshoot', 0)
        overshoot_llm = cl_llm.get('overshoot', 0)
        print(f"{'超调量 (%)':<20} {overshoot_rule:<20} {overshoot_llm:<20}")
        
        # 模型评分对比
        rating_rule = result_rule.get('model_rating', 0)
        rating_llm = result_llm.get('model_rating', 0)
        print(f"{'模型评分':<20} {rating_rule:<20} {rating_llm:<20} {format_diff(rating_rule, rating_llm):<15}")
        
        # 耗时对比
        print(f"\n{'整定耗时':<20} {time_rule:.2f}s{'':<16} {time_llm:.2f}s")
        
        # LLM 决策详情
        if 'oscillation' in method_llm:
            llm_decision = pid_llm.get('llm_decision', {})
            if llm_decision:
                print(f"\n🤖 LLM 策略决策:")
                strategy = llm_decision.get('strategy_params', {})
                if strategy:
                    print(f"   safety_factor: {strategy.get('safety_factor', 'N/A')}")
                    print(f"   pb_extra_factor: {strategy.get('pb_extra_factor', 'N/A')}")
                    print(f"   ti_multiplier: {strategy.get('ti_multiplier', 'N/A')}")
                    print(f"   enable_derivative: {strategy.get('enable_derivative', 'N/A')}")
                    print(f"   td_factor: {strategy.get('td_factor', 'N/A')}")
                print(f"   理由: {llm_decision.get('reasoning', 'N/A')}")
                print(f"   置信度: {llm_decision.get('confidence', 'N/A')}")
                if llm_decision.get('risk_factors'):
                    print(f"   风险因素: {llm_decision.get('risk_factors')}")
        
        # 可视化对比
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        visualize_comparison(data, tuning_input, result_rule, result_llm, scenario_name)


def visualize_comparison(data: List[Dict], tuning_input: Dict,
                         result_rule: Dict, result_llm: Dict, scenario_name: str):
    """可视化 LLM vs 规则引擎对比"""
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    
    pid_rule = result_rule.get('pid_parameters', {})
    pid_llm = result_llm.get('pid_parameters', {})
    cl_rule = result_rule.get('closed_loop_verification', {})
    cl_llm = result_llm.get('closed_loop_verification', {})
    
    fig.suptitle(f'LLM vs 规则引擎对比 - {scenario_name}\n'
                 f'规则引擎: pb={pid_rule.get("pb", "N/A")}%, 闭环{"✅" if cl_rule.get("is_stable") else "❌"} | '
                 f'LLM: pb={pid_llm.get("pb", "N/A")}%, 闭环{"✅" if cl_llm.get("is_stable") else "❌"}',
                 fontsize=12, fontweight='bold')
    
    # ========== 左上: 原始数据 ==========
    ax1 = axes[0, 0]
    ax1.plot(time_array, pv_array, 'b-', label='PV', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV', linewidth=1.2)
    ax1.set_ylabel('PV / SV')
    ax1.set_title('原始数据')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # ========== 右上: MV ==========
    ax2 = axes[0, 1]
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    ax2.set_ylabel('MV')
    ax2.set_title('操作值')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # ========== 左下: 规则引擎闭环响应 ==========
    ax3 = axes[1, 0]
    _plot_closed_loop(ax3, result_rule, '规则引擎')
    
    # ========== 右下: LLM 闭环响应 ==========
    ax4 = axes[1, 1]
    _plot_closed_loop(ax4, result_llm, 'LLM')
    
    plt.tight_layout()
    
    # 保存
    os.makedirs(CONFIG['log_dir'], exist_ok=True)
    filename = f'llm_compare_{scenario_name}.png'
    filepath = os.path.join(CONFIG['log_dir'], filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 对比图表已保存至: {filepath}")
    plt.close()


def _plot_closed_loop(ax, result: Dict, title: str):
    """绘制闭环响应子图"""
    from core.algorithm.model_type.tuning.pid_calculator import PIDCalculator
    from core.algorithm.model_type.data_models import FusionResult
    
    model_params = result.get('model_parameters', {})
    pid_params = result.get('pid_parameters', {})
    cl_info = result.get('closed_loop_verification', {})
    model_type = result.get('model_type', 'FOPDT')
    
    fusion = FusionResult(
        model_type=model_type,
        K=model_params.get('K', 0),
        T1=model_params.get('T1', 0),
        T2=model_params.get('T2', 0),
        L=model_params.get('L', 0)
    )
    
    calculator = PIDCalculator()
    
    sp_initial = cl_info.get('sp_initial', 50.0)
    sp_final = cl_info.get('sp_final', 60.0)
    pv_initial = cl_info.get('pv_initial', 50.0)
    
    T_ref = fusion.T1 if fusion.T1 > 0 else 10.0
    dt = min(0.1, T_ref / 10)
    dt = max(0.01, dt)
    sim_time = max(200, T_ref * 25)
    n_steps = min(int(sim_time / dt), 10000)
    
    metrics = calculator.simulate_closed_loop(
        K=fusion.K, T1=fusion.T1, T2=fusion.T2, L=fusion.L,
        model_type=fusion.model_type,
        Kp=pid_params.get('kp', 1), Ki=pid_params.get('ki', 0), Kd=pid_params.get('kd', 0),
        sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
        n_steps=n_steps, dt=dt
    )
    
    t_sim = np.arange(len(metrics.pv_history)) * dt
    sp_sim = np.zeros_like(metrics.pv_history)
    sp_sim[:10] = sp_initial
    sp_sim[10:] = sp_final
    
    ax.plot(t_sim, metrics.pv_history, 'b-', label='PV', linewidth=1.5)
    ax.plot(t_sim, sp_sim, 'r--', label='SP', linewidth=1.2)
    
    is_stable = cl_info.get('is_stable', False)
    settling_time = cl_info.get('settling_time', -1)
    overshoot = cl_info.get('overshoot', 0)
    
    status = '✅稳定' if is_stable else '❌不稳定'
    textstr = f'{status}\n'
    textstr += f'调节时间: {settling_time:.1f}s\n' if settling_time >= 0 else '调节时间: N/A\n'
    textstr += f'超调量: {overshoot:.1f}%\n'
    textstr += f'pb: {pid_params.get("pb", "N/A")}%'
    
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    ax.text(0.98, 0.95, textstr, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', horizontalalignment='right', bbox=props)
    
    ax.set_xlabel('时间 (s)')
    ax.set_ylabel('PV / SP')
    ax.set_title(f'{title} 闭环响应 (Kp={pid_params.get("kp", 0):.3f}, Ki={pid_params.get("ki", 0):.3f})')
    ax.legend(loc='lower right')
    ax.grid(True, alpha=0.3)
    
    # 调整显示范围
    if settling_time >= 0 and settling_time < t_sim[-1]:
        x_max = min(t_sim[-1], max(80, settling_time * 1.3))
    else:
        x_max = min(t_sim[-1], 100)
    ax.set_xlim([0, x_max])


def print_result(result: Dict):
    """打印整定结果"""
    print("\n" + "=" * 70)
    print("整定结果")
    print("=" * 70)
    
    print(f"\n成功: {result.get('success', False)}")
    print(f"模型类型: {result.get('model_type', 'N/A')}")
    print(f"整定方法: {result.get('fusion_info', {}).get('method', 'N/A')}")
    print(f"模型评分: {result.get('model_rating', 0)}/10")
    
    # 模型参数
    model_params = result.get('model_parameters', {})
    print(f"\n模型参数:")
    print(f"  K: {model_params.get('K', 'N/A')}")
    print(f"  T1: {model_params.get('T1', 'N/A')} s")
    print(f"  T2: {model_params.get('T2', 'N/A')} s")
    print(f"  L: {model_params.get('L', 'N/A')} s")
    
    # PID 参数
    pid_params = result.get('pid_parameters', {})
    print(f"\nPID 参数:")
    print(f"  pb: {pid_params.get('pb', 'N/A')} %")
    print(f"  Kp: {pid_params.get('kp', 'N/A')}")
    print(f"  Ki: {pid_params.get('ki', 'N/A')}")
    print(f"  Kd: {pid_params.get('kd', 'N/A')}")
    print(f"  Ti: {pid_params.get('ti', 'N/A')} s")
    print(f"  Td: {pid_params.get('td', 'N/A')} s")
    
    # 闭环验证
    cl_info = result.get('closed_loop_verification', {})
    print(f"\n闭环验证:")
    print(f"  稳定: {cl_info.get('is_stable', 'N/A')}")
    print(f"  调节时间: {cl_info.get('settling_time', 'N/A')} s")
    print(f"  超调量: {cl_info.get('overshoot', 'N/A')} %")
    
    # LLM 决策（如果有）
    fusion_method = result.get('fusion_info', {}).get('method', '')
    if 'oscillation' in fusion_method:
        print(f"\n🔄 使用了临界法整定")
        llm_decision = pid_params.get('llm_decision', {})
        if llm_decision:
            print(f"\n🤖 LLM 保守策略决策:")
            # 显示策略参数
            strategy_params = llm_decision.get('strategy_params', {})
            if strategy_params:
                print(f"  策略参数:")
                print(f"    safety_factor: {strategy_params.get('safety_factor', 'N/A')}")
                print(f"    pb_extra_factor: {strategy_params.get('pb_extra_factor', 'N/A')}")
                print(f"    ti_multiplier: {strategy_params.get('ti_multiplier', 'N/A')}")
                print(f"    enable_derivative: {strategy_params.get('enable_derivative', 'N/A')}")
                print(f"    td_factor: {strategy_params.get('td_factor', 'N/A')}")
            print(f"  理由: {llm_decision.get('reasoning', 'N/A')}")
            print(f"  置信度: {llm_decision.get('confidence', 'N/A')}")
            if llm_decision.get('risk_factors'):
                print(f"  风险因素: {llm_decision.get('risk_factors')}")
            if llm_decision.get('recommendations'):
                print(f"  建议: {llm_decision.get('recommendations')}")
        else:
            print("  (使用规则引擎，未调用 LLM)")


if __name__ == "__main__":
    # ========== 配置测试模式 ==========
    # True: 对比 LLM vs 规则引擎
    # False: 仅测试 LLM 整定
    COMPARE_MODE = True
    
    if COMPARE_MODE:
        test_compare_llm_vs_rule()
    else:
        test_with_llm()
