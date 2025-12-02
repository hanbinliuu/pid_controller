"""
测试数据生成器

用于生成符合不同模型类型的测试数据（.json格式），用于算法调整和测试。
"""

import json
import numpy as np
import os
import sys
from typing import Dict, List, Optional
from datetime import datetime

# 处理导入路径，使其既可以作为模块导入，也可以直接运行
if __name__ == '__main__':
    # 直接运行时，需要设置路径使相对导入能工作
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    # 设置包名
    __package__ = 'autoselect_model'
    from .model_types import ModelType
    from .model_detector import ModelDetector
else:
    # 作为模块导入时，使用相对导入
    from .model_types import ModelType
    from .model_detector import ModelDetector


class DataGenerator:
    """测试数据生成器"""
    
    def __init__(self):
        """初始化生成器"""
        self.detector = ModelDetector()
    
    def generate_test_data(self,
                          model_type: str,
                          params: Dict[str, float],
                          duration: float = 300.0,
                          dt: float = 0.5,
                          noise_level: float = 0.01,
                          input_type: str = "step") -> Dict:
        """
        生成测试数据
        
        Args:
            model_type: 模型类型 ("first_order", "fopdt", "second_order")
            params: 模型参数字典
                - first_order: {"K": float, "T": float}
                - fopdt: {"K": float, "T": float, "L": float}
                - second_order: {"K": float, "T1": float, "T2": float}
            duration: 数据持续时间（秒）
            dt: 采样间隔（秒）
            noise_level: 噪声水平
            input_type: 输入信号类型 ("step", "multi_step", "random")
        
        Returns:
            生成的JSON格式数据字典
        """
        # 生成时间序列
        t = np.arange(0, duration, dt)
        if len(t) == 0:
            t = np.array([0.0])
        
        # 生成输入信号
        u = self._generate_input_signal(t, input_type)
        
        # 初始值
        y0 = 0.0
        
        # 根据模型类型生成输出
        if model_type == "first_order":
            params_array = np.array([params["K"], params["T"]])
            y = self.detector.first_order_model(params_array, t, u, y0)
        elif model_type == "fopdt":
            params_array = np.array([params["K"], params["T"], params["L"]])
            y = self.detector.fopdt_model(params_array, t, u, y0)
        elif model_type == "second_order":
            params_array = np.array([params["K"], params["T1"], params["T2"]])
            y = self.detector.second_order_model(params_array, t, u, y0)
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")
        
        # 添加噪声
        if noise_level > 0:
            noise = np.random.normal(0, noise_level * np.std(y), len(y))
            y = y + noise
        
        # 转换为JSON格式
        data_list = []
        base_timestamp = int(datetime.now().timestamp() * 1000)
        
        for i, (time_val, pv_val, mv_val) in enumerate(zip(t, y, u)):
            data_list.append({
                "timestamp": base_timestamp + int(time_val * 1000),
                "pv": float(pv_val),
                "mv": float(mv_val)
            })
        
        return {
            "status": "success",
            "model_type": model_type,
            "parameters": params,
            "duration": duration,
            "dt": dt,
            "noise_level": noise_level,
            "input_type": input_type,
            "data": data_list
        }
    
    def _generate_input_signal(self, t: np.ndarray, input_type: str) -> np.ndarray:
        """
        生成输入信号
        
        Args:
            t: 时间数组
            input_type: 输入类型 ("step", "multi_step", "random")
        
        Returns:
            输入信号数组
        """
        if input_type == "step":
            # 阶跃信号：在t=50时从0跳到1
            u = np.zeros_like(t)
            step_idx = int(len(t) * 0.1)  # 10%处开始阶跃
            u[step_idx:] = 1.0
            return u
        
        elif input_type == "multi_step":
            # 多阶跃信号
            u = np.zeros_like(t)
            n_steps = 3
            step_size = len(t) // (n_steps + 1)
            for i in range(1, n_steps + 1):
                step_idx = i * step_size
                if step_idx < len(t):
                    u[step_idx:] = i * 0.5
            return u
        
        elif input_type == "random":
            # 随机信号
            u = np.random.uniform(0, 1, len(t))
            return u
        
        else:
            raise ValueError(f"不支持的输入类型: {input_type}")
    
    def generate_batch(self,
                      output_dir: str,
                      num_samples_per_model: int = 10,
                      duration: float = 300.0,
                      dt: float = 0.5,
                      noise_level: float = 0.01) -> List[Dict]:
        """
        批量生成测试数据
        
        Args:
            output_dir: 输出目录
            num_samples_per_model: 每个模型类型的样本数量
            duration: 数据持续时间（秒）
            dt: 采样间隔（秒）
            noise_level: 噪声水平
        
        Returns:
            生成的文件信息列表
        """
        os.makedirs(output_dir, exist_ok=True)
        
        model_types = ["first_order", "fopdt", "second_order"]
        generated_files = []
        
        for model_type in model_types:
            for i in range(num_samples_per_model):
                # 生成参数
                params = self._generate_params(model_type)
                
                # 生成数据
                data = self.generate_test_data(
                    model_type=model_type,
                    params=params,
                    duration=duration,
                    dt=dt,
                    noise_level=noise_level,
                    input_type="step"
                )
                
                # 保存文件
                filename = f"test_{model_type}_{i:03d}.json"
                filepath = os.path.join(output_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                generated_files.append({
                    "filepath": filepath,
                    "filename": filename,
                    "model_type": model_type,
                    "parameters": params
                })
        
        return generated_files
    
    def _generate_params(self, model_type: str) -> Dict[str, float]:
        """
        生成模型参数
        
        Args:
            model_type: 模型类型
        
        Returns:
            参数字典
        """
        if model_type == "first_order":
            return {
                "K": np.random.uniform(0.3, 1.0),
                "T": np.random.uniform(10.0, 100.0)
            }
        elif model_type == "fopdt":
            return {
                "K": np.random.uniform(0.3, 1.0),
                "T": np.random.uniform(10.0, 100.0),
                "L": np.random.uniform(1.0, 20.0)
            }
        elif model_type == "second_order":
            return {
                "K": np.random.uniform(0.3, 1.0),
                "T1": np.random.uniform(5.0, 50.0),
                "T2": np.random.uniform(5.0, 50.0)
            }
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")




if __name__ == "__main__":
    generator = DataGenerator()
    
    print("=" * 60)
    print("开始生成测试数据")
    print("=" * 60)
    
    generated_files = generator.generate_batch(
        output_dir='/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/core/algo/model_select/autoselect_model/data_generation',
        num_samples_per_model=20,
        duration=300.0,
        dt=0.5,
        noise_level=0.01
    )
    
    print("\n" + "=" * 60)
    print("生成完成！")
    print("=" * 60)
    print(f"总共生成 {len(generated_files)} 个测试数据文件")
    
    # 统计各模型类型数量
    model_counts = {}
    for file_info in generated_files:
        model_type = file_info["model_type"]
        model_counts[model_type] = model_counts.get(model_type, 0) + 1
    
    print("\n各模型类型数量:")
    for model_type, count in model_counts.items():
        print(f"  {model_type}: {count} 个")
    
    print(f"\n输出目录: {generated_files[0]['filepath'] if generated_files else 'N/A'}")