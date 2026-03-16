"""
SelfOptimizeStage 单元测试
=========================

测试两阶段自优化:
Phase 1: Lambda 粗搜 (正常路径)
Phase 2: PB/TI/TD 微调 (所有路径，包括振荡/fallback)

使用方法:
    python -m core.algorithm.model_type.tests.test_self_optimize
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

import numpy as np
from typing import Dict

from core.algorithm.model_type.config import Config
from core.algorithm.model_type.data_models import FusionResult, HistoricalData
from core.algorithm.model_type.pipeline.context import TuningContext
from core.algorithm.model_type.pipeline.stages.stage_05b_self_optimize import SelfOptimizeStage, _normalize_pid_keys
from core.algorithm.model_type.tuning import PIDCalculator


def _make_context(
    K=1.0, T1=20.0, T2=0.0, L=2.0,
    lambda_factor=0.8, loop_type='flow',
    final_result=None, fusion=True,
) -> TuningContext:
    fus = FusionResult(
        model_type='FOPDT', K=K, T1=T1, T2=T2, L=L,
        global_r2=0.85, global_rmse=0.1,
        n_segments_used=2, consistency_score=0.9,
    ) if fusion else None
    n_pts = 300
    sv = np.concatenate([np.full(100, 50.0), np.full(200, 60.0)])
    pv = np.full(n_pts, 50.0)
    mv = np.full(n_pts, 50.0)
    ts = np.arange(n_pts, dtype=np.int64) * 1000 + 1700000000000
    hist_data = HistoricalData(timestamp=ts, sv=sv, pv=pv, mv=mv)
    return TuningContext(
        lambda_factor=lambda_factor, loop_type=loop_type,
        fusion_result=fus, hist_data=hist_data,
        final_result=final_result,
    )


# ---------------------------------------------------------------
# Fix #1: key 格式规范化
# ---------------------------------------------------------------

def test_normalize_pid_keys():
    """测试大小写 key 的规范化"""
    # 小写 → 大写
    result = _normalize_pid_keys({'kp': -0.81, 'ki': -0.06, 'kd': 0.0})
    assert result['Kp'] == -0.81 and result['Ki'] == -0.06
    # 大写优先
    result = _normalize_pid_keys({'Kp': 1.5, 'kp': 999.0, 'Ki': 0.1, 'Kd': 0.0})
    assert result['Kp'] == 1.5
    # 字符串值
    result = _normalize_pid_keys({'kp': '-0.81', 'ki': '-0.06', 'kd': '0.0'})
    assert result['Kp'] == -0.81
    print("  ✅ key 规范化正确")


# ---------------------------------------------------------------
# Phase 1 测试 (正常路径)
# ---------------------------------------------------------------

def test_evaluate_candidate():
    stage = SelfOptimizeStage(PIDCalculator(), verbose=False)
    ctx = _make_context()
    score, detail = stage._evaluate_candidate(ctx.fusion_result, 0.8, 50.0, 60.0, 50.0, 'flow')
    assert isinstance(score, float) and 0 <= score <= 10
    assert 'pb' in detail and 'ti' in detail
    assert 'Kp' in detail['pid_params']  # Fix #1: 确保大写 key
    print(f"  ✅ score={score:.2f}")


def test_execute_normal_path():
    stage = SelfOptimizeStage(PIDCalculator(), verbose=True)
    ctx = _make_context(K=1.5, T1=15.0, L=3.0)
    ctx = stage.execute(ctx)
    assert ctx.lambda_factor > 0 and ctx.final_result is None
    print(f"  ✅ λ={ctx.lambda_factor}, optimized_pid={'有' if ctx.optimized_pid else '无'}")


def test_skip_when_disabled():
    stage = SelfOptimizeStage(PIDCalculator(), verbose=False)
    stage._config = {'enabled': False}
    ctx = _make_context()
    orig = ctx.lambda_factor
    ctx = stage.execute(ctx)
    assert ctx.lambda_factor == orig
    print("  ✅ 配置禁用跳过正常")


# ---------------------------------------------------------------
# Phase 2 测试 (通用)
# ---------------------------------------------------------------

def test_evaluate_pid_directly():
    stage = SelfOptimizeStage(PIDCalculator(), verbose=False)
    ctx = _make_context(K=1.5, T1=15.0, L=3.0)
    pid = PIDCalculator().calculate_from_fusion(ctx.fusion_result, 0.8, loop_type='flow')
    score, d = stage._evaluate_pid(ctx.fusion_result, pid, 50.0, 60.0, 50.0, 'flow')
    assert 0 <= score <= 10 and 'pb' in d
    assert 'cl_metrics' in d  # Fix #3: cl_metrics 应保存
    print(f"  ✅ score={score:.2f}, PB={d['pb']:.2f}, TI={d['ti']:.2f}")


def test_fine_tune_pid():
    stage = SelfOptimizeStage(PIDCalculator(), verbose=False)
    ctx = _make_context(K=1.5, T1=15.0, L=3.0)
    pid = PIDCalculator().calculate_from_fusion(ctx.fusion_result, 0.8, loop_type='flow')
    baseline_score, _ = stage._evaluate_pid(ctx.fusion_result, pid, 50.0, 60.0, 50.0, 'flow')
    tuned_pid, tuned_score, tuned_detail, log = stage._fine_tune_pid(
        ctx.fusion_result, pid, baseline_score, 50.0, 60.0, 50.0, 'flow')
    assert tuned_score >= baseline_score
    # Fix #3: 返回 4 个值 (含 best_detail)
    if tuned_score > baseline_score:
        assert tuned_detail is not None and 'cl_metrics' in tuned_detail
    print(f"  ✅ {baseline_score:.2f} → {tuned_score:.2f} ({len(log)} 候选)")


# ---------------------------------------------------------------
# 振荡/fallback 路径测试 (final_result 已存在)
# ---------------------------------------------------------------

def test_optimize_existing_oscillation_result():
    """模拟振荡整定路径: final_result 已存在，应运行 Phase 2"""
    stage = SelfOptimizeStage(PIDCalculator(), verbose=True)

    final_result = {
        'success': True,
        'model_type': 'FOPDT',
        'model_rating': 8.09,
        'model_parameters': {'K': '-0.6977', 'T1': '15.34', 'T2': '0.0', 'L': '2.39'},
        'pid_parameters': {'kp': -0.81, 'ki': -0.06, 'kd': 0.0, 'pb': 122.88, 'ti': 13.85, 'td': 0.0},
        'fitting_result': {'r_squared': 0.82, 'rmse': 0.36},
        'closed_loop_verification': {'sp_initial': 50.0, 'sp_final': 60.0, 'pv_initial': 50.0},
        'tuning_features': {'tuning_method': 'oscillation_tuning', 'loop_type': ''},
    }

    ctx = _make_context(fusion=False, final_result=final_result)
    original_rating = final_result['model_rating']
    original_cl = final_result['closed_loop_verification'].copy()

    ctx = stage.execute(ctx)

    assert ctx.final_result is not None
    # Fix #1: 检查更新后的 pid_parameters 同时包含大写和小写 key
    pp = ctx.final_result['pid_parameters']
    assert 'Kp' in pp and 'kp' in pp
    # 符号应保持为负
    assert pp['Kp'] < 0
    
    # Fix #3: 如果评分改善了, closed_loop_verification 应该被更新
    new_rating = ctx.final_result['model_rating']
    if new_rating > original_rating:
        cl = ctx.final_result.get('closed_loop_verification', {})
        # 应包含新的闭环指标字段
        assert 'overshoot' in cl or 'settling_time' in cl
    
    print(f"  ✅ 振荡路径 Phase 2: {original_rating} → {new_rating}")


def test_phase2_disabled_skips_fallback():
    """fine_tune_enabled=False 时，振荡路径也应跳过"""
    stage = SelfOptimizeStage(PIDCalculator(), verbose=False)
    stage._config = {**Config.SELF_OPTIMIZE, 'fine_tune_enabled': False}

    final_result = {
        'success': True, 'model_type': 'FOPDT', 'model_rating': 8.09,
        'model_parameters': {'K': '1.0', 'T1': '10.0', 'T2': '0.0', 'L': '1.0'},
        'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0, 'pb': 100.0, 'ti': 20.0, 'td': 0.0},
        'fitting_result': {'r_squared': 0.8}, 'closed_loop_verification': {},
        'tuning_features': {'tuning_method': 'oscillation_tuning'},
    }
    ctx = _make_context(fusion=False, final_result=final_result)
    ctx = stage.execute(ctx)
    assert ctx.final_result['model_rating'] == 8.09
    print("  ✅ Phase 2 禁用时振荡路径跳过正常")


# ---------------------------------------------------------------
# Fix #2: model_parameters 类型防御
# ---------------------------------------------------------------

def test_extract_handles_string_model_params():
    """测试 model_parameters 值为字符串的情况"""
    stage = SelfOptimizeStage(PIDCalculator(), verbose=False)
    final_result = {
        'model_type': 'FOPDT',
        'model_parameters': {'K': '0.7209', 'T1': '23.27', 'T2': '0.0', 'L': '0.0'},
        'pid_parameters': {'kp': '1.23', 'ki': '0.04', 'kd': '0.0'},
        'fitting_result': {'r_squared': 0.98},
        'closed_loop_verification': {},
        'tuning_features': {},
    }
    ctx = _make_context(fusion=False)
    fusion, pid, *_ = stage._extract_from_final_result(final_result, ctx)
    assert abs(fusion.K - 0.7209) < 0.001
    assert abs(pid['Kp'] - 1.23) < 0.01
    print(f"  ✅ 字符串类型 model_parameters 正确转换: K={fusion.K}, Kp={pid['Kp']}")


# ---------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------
if __name__ == '__main__':
    print("=" * 60)
    print("🧪 SelfOptimizeStage 单元测试 (全路径 + Code Review 修复)")
    print("=" * 60)

    tests = [
        test_normalize_pid_keys,
        test_evaluate_candidate,
        test_execute_normal_path,
        test_skip_when_disabled,
        test_evaluate_pid_directly,
        test_fine_tune_pid,
        test_optimize_existing_oscillation_result,
        test_phase2_disabled_skips_fallback,
        test_extract_handles_string_model_params,
    ]

    passed = failed = 0
    for t in tests:
        print(f"\n--- {t.__name__} ---")
        try:
            t()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"结果: {passed} 通过, {failed} 失败")
    print(f"{'='*60}")
    sys.exit(1 if failed > 0 else 0)
