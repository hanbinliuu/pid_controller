"""
模型类型检测器测试

测试ModelTypeDetector的各种场景
"""

import numpy as np
import sys
import os

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 从本地模块导入
from config import Config, ModelType
from identifier import ModelIdentifier
from model_type_detector import ModelTypeDetector, HistoricalData, detect_model_type


def generate_fopdt_data(K=0.8, T=30.0, L=5.0, n_points=500, dt=1.0, noise=0.05):
    """生成FOPDT模型响应数据"""
    t = np.arange(n_points) * dt
    
    # 阶跃输入
    u = np.zeros(n_points)
    u[50:] = 10.0
    
    # FOPDT响应
    y = np.zeros(n_points)
    y0 = 20.0
    y[0] = y0
    
    L_samples = int(L / dt)
    for i in range(1, n_points):
        u_delayed = u[max(0, i - L_samples)]
        dy = (K * u_delayed - (y[i-1] - y0)) / T * dt
        y[i] = y[i-1] + dy + np.random.normal(0, noise)
    
    return t, y, u


def generate_first_order_data(K=0.8, T=10.0, n_points=300, dt=1.0, noise=0.02):
    """生成纯一阶模型响应数据（无滞后）"""
    t = np.arange(n_points) * dt
    
    # 阶跃输入
    u = np.zeros(n_points)
    u[30:] = 10.0
    
    # 一阶响应
    y = np.zeros(n_points)
    y0 = 20.0
    y[0] = y0
    
    for i in range(1, n_points):
        dy = (K * u[i] - (y[i-1] - y0)) / T * dt
        y[i] = y[i-1] + dy + np.random.normal(0, noise)
    
    return t, y, u


def generate_second_order_data(K=0.8, T1=5.0, T2=10.0, n_points=300, dt=1.0, noise=0.02):
    """生成二阶模型响应数据"""
    t = np.arange(n_points) * dt
    
    # 阶跃输入
    u = np.zeros(n_points)
    u[30:] = 10.0
    
    # 二阶响应
    y = np.zeros(n_points)
    x1 = 20.0
    y0 = 20.0
    y[0] = y0
    
    for i in range(1, n_points):
        u_eff = K * u[i]
        dx1 = (u_eff - x1) / T1 * dt
        x1 = x1 + dx1
        dy = (x1 - y[i-1]) / T2 * dt
        y[i] = y[i-1] + dy + np.random.normal(0, noise)
    
    return t, y, u


def generate_integral_delay_data(K=0.1, L=2.0, n_points=300, dt=1.0, noise=0.1):
    """生成积分-延迟模型响应数据"""
    t = np.arange(n_points) * dt
    
    # 阶跃输入
    u = np.zeros(n_points)
    u[30:] = 5.0
    
    # 积分响应
    y = np.zeros(n_points)
    y0 = 50.0
    y[0] = y0
    
    L_samples = int(L / dt)
    for i in range(1, n_points):
        u_delayed = u[max(0, i - L_samples)]
        y[i] = y[i-1] + K * u_delayed * dt + np.random.normal(0, noise)
    
    return t, y, u


def create_json_data(t, y, u, sv_value=25.0):
    """将numpy数组转换为JSON格式数据"""
    base_ts = 1764752400000  # 基准时间戳
    data = []
    for i in range(len(t)):
        data.append({
            "timestamp": int(base_ts + t[i] * 1000),
            "sv": sv_value,
            "pv": float(y[i]),
            "mv": float(u[i]),
            "auto": 255,
            "ti": 3.0,
            "pb": 73.1,
            "td": 1.5,
            "kp": 1.37,
            "ki": 0.46,
            "kd": 2.05
        })
    return data


def test_fopdt_detection():
    """测试FOPDT模型检测"""
    print("\n" + "="*60)
    print("测试 FOPDT 模型检测 - 新输出格式")
    print("="*60)
    
    t, y, u = generate_fopdt_data(K=0.8, T=30.0, L=5.0)
    json_data = create_json_data(t, y, u)
    
    detector = ModelTypeDetector(verbose=True)
    result = detector.detect(json_data)
    
    print(f"\n检测结果:")
    print(f"  model_type: {result['model_type']}")
    print(f"  model_rating: {result['model_rating']}")
    print(f"  start_time: {result['start_time']}")
    print(f"  end_time: {result['end_time']}")
    
    # 验证输出格式
    assert 'model_type' in result
    assert 'model_rating' in result
    assert 'start_time' in result
    assert 'end_time' in result
    assert isinstance(result['model_rating'], float)
    assert 0 <= result['model_rating'] <= 10
    
    print(f"\n✅ 测试通过: 输出格式正确")


def test_first_order_detection():
    """测试一阶模型检测"""
    print("\n" + "="*60)
    print("测试 FIRST_ORDER 模型检测")
    print("="*60)
    
    t, y, u = generate_first_order_data(K=0.8, T=5.0)
    json_data = create_json_data(t, y, u)
    
    detector = ModelTypeDetector(verbose=True)
    result = detector.detect(json_data)
    
    print(f"\n检测结果:")
    print(f"  model_type: {result['model_type']}")
    print(f"  model_rating: {result['model_rating']}")
    
    # 验证输出格式
    assert 'model_type' in result
    assert 'model_rating' in result
    print(f"\n✅ 测试通过: 识别为 {result['model_type']}, 评分 {result['model_rating']}")


def test_integral_delay_detection():
    """测试积分-延迟模型检测"""
    print("\n" + "="*60)
    print("测试 INTEGRAL_DELAY 模型检测")
    print("="*60)
    
    t, y, u = generate_integral_delay_data(K=0.1, L=1.0)
    json_data = create_json_data(t, y, u, sv_value=55.0)
    
    detector = ModelTypeDetector(verbose=True)
    result = detector.detect(json_data)
    
    print(f"\n检测结果:")
    print(f"  model_type: {result['model_type']}")
    print(f"  model_rating: {result['model_rating']}")
    
    # 验证输出格式
    assert 'model_type' in result
    assert 'model_rating' in result
    print(f"\n✅ 测试通过: 识别为 {result['model_type']}, 评分 {result['model_rating']}")


def test_convenience_function():
    """测试便捷函数"""
    print("\n" + "="*60)
    print("测试便捷函数 detect_model_type")
    print("="*60)
    
    t, y, u = generate_fopdt_data()
    json_data = create_json_data(t, y, u)
    
    result = detect_model_type(json_data, verbose=True)
    print(f"\n检测结果: {result}")
    
    # 验证返回类型是字典
    assert isinstance(result, dict)
    assert 'model_type' in result
    assert 'model_rating' in result
    assert 'start_time' in result
    assert 'end_time' in result
    print(f"\n✅ 测试通过: 返回格式正确")


def test_historical_data_parsing():
    """测试HistoricalData数据解析"""
    print("\n" + "="*60)
    print("测试 HistoricalData 数据解析")
    print("="*60)
    
    # 用户提供的示例数据格式
    sample_data = [
        {
            "timestamp": 1764752400000,
            "sv": 3,
            "auto": 255,
            "ti": 3,
            "pb": 73.1,
            "pv": 1.9,
            "td": 1.5,
            "mv": 8.742,
            "kp": 1.3679890560875514,
            "ki": 0.4559963520291838,
            "kd": 2.051983584131327
        },
        {
            "timestamp": 1764752401000,
            "sv": 3,
            "auto": 255,
            "ti": 3,
            "pb": 73.1,
            "pv": 1.9,
            "td": 1.5,
            "mv": 8.742,
            "kp": 1.3679890560875514,
            "ki": 0.4559963520291838,
            "kd": 2.051983584131327
        },
        {
            "timestamp": 1764752402000,
            "sv": 3,
            "auto": 255,
            "ti": 3,
            "pb": 73.1,
            "pv": 2.1,
            "td": 1.5,
            "mv": 8.5,
            "kp": 1.3679890560875514,
            "ki": 0.4559963520291838,
            "kd": 2.051983584131327
        }
    ]
    
    hist_data = HistoricalData.from_json(sample_data)
    
    print(f"时间戳数组: {hist_data.timestamp}")
    print(f"PV数组: {hist_data.pv}")
    print(f"SV数组: {hist_data.sv}")
    print(f"MV数组: {hist_data.mv}")
    
    t = hist_data.to_time_array()
    print(f"相对时间数组（秒）: {t}")
    
    assert len(hist_data.pv) == 3
    assert hist_data.pv[0] == 1.9
    assert hist_data.pv[2] == 2.1
    assert t[0] == 0.0
    assert t[1] == 1.0  # 1000ms = 1s
    
    print(f"\n✅ 测试通过: 数据解析正确")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*60)
    print("开始运行模型类型检测器测试")
    print("="*60)
    
    try:
        test_historical_data_parsing()
        test_fopdt_detection()
        test_first_order_detection()
        test_integral_delay_detection()
        test_convenience_function()
        
        print("\n" + "="*60)
        print("🎉 所有测试通过!")
        print("="*60)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        raise
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()
