"""
model_type 测试模块的 pytest 配置和共享 fixtures
==============================================

提供测试所需的共享配置和 fixtures。
"""

import pytest
import numpy as np
import sys
import os

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))


# ============================================================
# 基础 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def random_seed():
    """固定的随机种子，确保测试可重复"""
    return 25


@pytest.fixture(autouse=True)
def reset_random_state(random_seed):
    """每个测试前重置随机状态"""
    np.random.seed(random_seed)
    yield


@pytest.fixture(scope="session")
def verbose():
    """默认不输出详细日志"""
    return False


# ============================================================
# ModelSelector Fixtures
# ============================================================

@pytest.fixture(scope="function")
def model_selector(verbose):
    """创建 ModelSelector 实例"""
    from core.algorithm.model_type.model_selector import ModelSelector
    return ModelSelector(verbose=verbose)


@pytest.fixture(scope="session")
def model_selector_verbose():
    """创建详细输出的 ModelSelector 实例"""
    from core.algorithm.model_type.model_selector import ModelSelector
    return ModelSelector(verbose=True)


# ============================================================
# 测试数据 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def test_scenarios():
    """加载测试场景"""
    from core.algorithm.model_type.tests.test_scenarios import TEST_SCENARIOS
    return TEST_SCENARIOS


@pytest.fixture(scope="session")
def realistic_scenarios():
    """加载真实场景"""
    from core.algorithm.model_type.tests.test_scenarios import REALISTIC_SCENARIOS
    return REALISTIC_SCENARIOS


# ============================================================
# 过程模型 Fixtures
# ============================================================

@pytest.fixture
def fopdt_process():
    """创建标准 FOPDT 过程"""
    from core.algorithm.model_type.tests.test_synthetic_tuning import FOPDTProcess
    return FOPDTProcess(K=1.0, T1=30.0, L=5.0)


@pytest.fixture
def pid_controller():
    """创建 PID 控制器"""
    from core.algorithm.model_type.tests.test_synthetic_tuning import PIDController
    return PIDController(Kp=1.0, Ki=0.1, Kd=0.0)
