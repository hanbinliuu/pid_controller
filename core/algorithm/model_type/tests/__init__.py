"""model_type 测试模块
====================

测试文件说明:
- test_synthetic_tuning.py: 合成数据稳定率测试 (121场景, 基准: 105/121 = 86.8%)
- test_model_selector_real.py: 真实数据整定测试
- test_scenarios.py: 测试场景定义 (TEST_SCENARIOS, REALISTIC_SCENARIOS)
- visualization_utils.py: 共享可视化工具模块 (visualize_fitting_result 等)
- test_llm_with_real_data.py: LLM + 真实数据测试
- run_failed_scenarios.py: 重跑失败场景
- conftest.py: pytest 共享 fixtures

运行方式:
    python -m core.algorithm.model_type.tests.test_synthetic_tuning

注意事项:
    ⚠️ 过程模型类(FOPDTProcess等)必须定义在 test_synthetic_tuning.py 内，
       移动到独立文件会改变 np.random 状态导致稳定率回归。

测试结果保存在 results/ 目录下。
"""

# 导出测试场景供外部使用
from .test_scenarios import TEST_SCENARIOS, REALISTIC_SCENARIOS

# 导出共享可视化工具
from .visualization_utils import (
    resolve_process_model_type,
    normalize_pid_params,
    convert_to_arrays,
    simulate_pid_prediction,
    visualize_fitting_result,
    visualize_new_pid_simulation,
    visualize_raw_data,
)

__all__ = [
    'TEST_SCENARIOS', 'REALISTIC_SCENARIOS',
    'resolve_process_model_type', 'normalize_pid_params',
    'convert_to_arrays', 'simulate_pid_prediction',
    'visualize_fitting_result', 'visualize_new_pid_simulation',
    'visualize_raw_data',
]

