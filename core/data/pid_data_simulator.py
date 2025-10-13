#!/usr/bin/env python3
"""
PID控制数据模拟器
独立的数据生成工具，用于创建模拟的PID控制系统数据
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import csv
import random
import math
from pathlib import Path


class PIDDataSimulator:
    """PID控制数据模拟器"""
    
    def __init__(self):
        """初始化模拟器参数"""
        self.current_temp = 25.0      # 当前温度
        self.target_temp = 30.0       # 目标温度
        self.kp = 1.2                 # 比例参数
        self.ki = 0.08                # 积分参数
        self.kd = 0.05                # 微分参数
        self.control_period = 100     # 控制周期(ms)
        self.max_duty = 100           # 最大占空比(%)
        
        # PID控制状态变量
        self.integral_error = 0.0     # 积分误差累积
        self.previous_error = 0.0     # 上次误差
        self.noise_factor = 0.3       # 噪声系数
        
        # 环境参数
        self.ambient_temp = 22.0      # 环境温度
        self.thermal_mass = 50.0      # 热质量系数
        self.heat_loss_coeff = 0.02   # 散热系数
        
        print("PID数据模拟器初始化完成")
    
    def reset_state(self):
        """重置模拟器状态"""
        self.current_temp = 25.0
        self.target_temp = 30.0
        self.integral_error = 0.0
        self.previous_error = 0.0
        print("模拟器状态已重置")
    
    def simulate_pid_step(self, dt: float = 1.0) -> Dict[str, Any]:
        """
        模拟一步PID控制过程
        
        Args:
            dt: 时间步长（秒）
            
        Returns:
            Dict: 包含当前时刻所有PID参数的数据记录
        """
        # 计算温度误差
        error = self.target_temp - self.current_temp
        
        # 积分项计算
        self.integral_error += error * dt
        # 防止积分饱和
        self.integral_error = max(-100, min(100, self.integral_error))
        
        # 微分项计算
        derivative_error = (error - self.previous_error) / dt if dt > 0 else 0
        
        # PID控制输出计算
        pid_output = (self.kp * error + 
                     self.ki * self.integral_error + 
                     self.kd * derivative_error)
        
        # 限制输出范围
        pid_output = max(-self.max_duty, min(self.max_duty, pid_output))
        
        # 模拟物理温度变化
        heat_input = max(0, pid_output) * 0.015  # 加热输入（只有正值有效）
        heat_loss = (self.current_temp - self.ambient_temp) * self.heat_loss_coeff
        
        # 添加测量噪声
        measurement_noise = random.gauss(0, self.noise_factor)
        
        # 更新温度（简化的热力学模型）
        temp_change = (heat_input - heat_loss) * dt / self.thermal_mass
        self.current_temp += temp_change + measurement_noise * dt
        
        # 保存当前误差用于下次微分计算
        self.previous_error = error
        
        # 偶尔调整PID参数（模拟参数优化过程）
        if random.random() < 0.03:  # 3%概率调整参数
            self._adjust_pid_parameters()
        
        # 偶尔改变目标温度（模拟设定点变化）
        if random.random() < 0.01:  # 1%概率改变目标
            self._change_target_temperature()
        
        # 构建数据记录
        return {
            "timestamp": int(datetime.now().timestamp() * 1000),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "temperature": round(self.current_temp, 2),
            "target_temp": round(self.target_temp, 2),
            "kp": round(self.kp, 3),
            "ki": round(self.ki, 3),
            "kd": round(self.kd, 3),
            "control_period": self.control_period,
            "max_duty": self.max_duty,
            "pid_output": round(pid_output, 2),
            "error": round(error, 2),
            "integral_error": round(self.integral_error, 2),
            "derivative_error": round(derivative_error, 2),
            "heat_input": round(heat_input, 3),
            "heat_loss": round(heat_loss, 3)
        }
    
    def _adjust_pid_parameters(self):
        """随机调整PID参数"""
        # 小幅调整参数，模拟自动调节过程
        self.kp += random.uniform(-0.1, 0.1)
        self.ki += random.uniform(-0.01, 0.01)
        self.kd += random.uniform(-0.005, 0.005)
        
        # 确保参数在合理范围内
        self.kp = max(0.1, min(5.0, self.kp))
        self.ki = max(0.01, min(0.5, self.ki))
        self.kd = max(0.001, min(0.2, self.kd))
    
    def _change_target_temperature(self):
        """改变目标温度"""
        # 在合理范围内随机设置新目标
        new_targets = [25.0, 28.0, 30.0, 32.0, 35.0, 40.0]
        self.target_temp = random.choice(new_targets)
    
    def generate_historical_data(
        self, 
        duration_hours: float = 24, 
        sample_interval: float = 10.0,
        scenario: str = "normal"
    ) -> List[Dict[str, Any]]:
        """
        生成指定时长的历史模拟数据
        
        Args:
            duration_hours: 模拟时长（小时）
            sample_interval: 采样间隔（秒）
            scenario: 模拟场景 ("normal", "noisy", "unstable", "step_response")
            
        Returns:
            List[Dict]: 模拟的PID历史数据列表
        """
        print(f"开始生成 {scenario} 场景的模拟数据...")
        print(f"时长: {duration_hours} 小时, 采样间隔: {sample_interval} 秒")
        
        # 根据场景调整参数
        self._setup_scenario(scenario)
        
        data_points = []
        total_steps = int(duration_hours * 3600 / sample_interval)
        start_time = datetime.now() - timedelta(hours=duration_hours)
        
        for i in range(total_steps):
            # 计算当前历史时间
            current_time = start_time + timedelta(seconds=i * sample_interval)
            
            # 模拟一步
            data_point = self.simulate_pid_step(sample_interval)
            
            # 更新为历史时间
            data_point["timestamp"] = int(current_time.timestamp() * 1000)
            data_point["time"] = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            # 添加场景特定的变化
            self._apply_scenario_effects(data_point, i, total_steps, scenario)
            
            data_points.append(data_point)
            
            # 进度提示
            if i % 1000 == 0 and i > 0:
                progress = (i / total_steps) * 100
                print(f"生成进度: {progress:.1f}% ({i}/{total_steps})")
        
        print(f"模拟数据生成完成! 共 {len(data_points)} 条记录")
        return data_points
    
    def generate_historical_data_with_fixed_pid(
        self, 
        duration_hours: float = 24, 
        sample_interval: float = 10.0
    ) -> List[Dict[str, Any]]:
        """
        使用固定PID参数生成历史模拟数据（不会随机调整PID参数）
        
        Args:
            duration_hours: 模拟时长（小时）
            sample_interval: 采样间隔（秒）
            
        Returns:
            List[Dict]: 模拟的PID历史数据列表
        """
        print(f"开始生成固定PID参数的模拟数据...")
        print(f"时长: {duration_hours} 小时, 采样间隔: {sample_interval} 秒")
        print(f"固定PID参数: Kp={self.kp}, Ki={self.ki}, Kd={self.kd}")
        
        data_points = []
        total_steps = int(duration_hours * 3600 / sample_interval)
        start_time = datetime.now() - timedelta(hours=duration_hours)
        
        # 保存原始PID参数
        original_kp, original_ki, original_kd = self.kp, self.ki, self.kd
        
        for i in range(total_steps):
            # 计算当前历史时间
            current_time = start_time + timedelta(seconds=i * sample_interval)
            
            # 模拟一步（但不调整PID参数）
            data_point = self.simulate_pid_step_fixed(sample_interval)
            
            # 更新为历史时间
            data_point["timestamp"] = int(current_time.timestamp() * 1000)
            data_point["time"] = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            # 确保PID参数保持固定
            data_point["kp"] = round(original_kp, 3)
            data_point["ki"] = round(original_ki, 3) 
            data_point["kd"] = round(original_kd, 3)
            
            data_points.append(data_point)
            
            # 进度提示
            if i % 1000 == 0 and i > 0:
                progress = (i / total_steps) * 100
                print(f"生成进度: {progress:.1f}% ({i}/{total_steps})")
        
        print(f"✅ 固定PID参数数据生成完成! 共 {len(data_points)} 条记录")
        print(f"   PID参数保持不变: Kp={original_kp}, Ki={original_ki}, Kd={original_kd}")
        return data_points
    
    def simulate_pid_step_fixed(self, dt: float = 1.0) -> Dict[str, Any]:
        """
        模拟一步PID控制过程（固定PID参数，不会随机调整）
        
        Args:
            dt: 时间步长（秒）
            
        Returns:
            Dict: 包含当前时刻所有PID参数的数据记录
        """
        # 计算温度误差
        error = self.target_temp - self.current_temp
        
        # 积分项计算
        self.integral_error += error * dt
        # 防止积分饱和
        self.integral_error = max(-100, min(100, self.integral_error))
        
        # 微分项计算
        derivative_error = (error - self.previous_error) / dt if dt > 0 else 0
        
        # PID控制输出计算
        pid_output = (self.kp * error + 
                     self.ki * self.integral_error + 
                     self.kd * derivative_error)
        
        # 限制输出范围
        pid_output = max(-self.max_duty, min(self.max_duty, pid_output))
        
        # 模拟物理温度变化
        heat_input = max(0, pid_output) * 0.015  # 加热输入（只有正值有效）
        heat_loss = (self.current_temp - self.ambient_temp) * self.heat_loss_coeff
        
        # 添加测量噪声
        measurement_noise = random.gauss(0, self.noise_factor)
        
        # 更新温度（简化的热力学模型）
        temp_change = (heat_input - heat_loss) * dt / self.thermal_mass
        self.current_temp += temp_change + measurement_noise * dt
        
        # 保存当前误差用于下次微分计算
        self.previous_error = error
        
        # 偶尔改变目标温度（但不调整PID参数）
        if random.random() < 0.008:  # 0.8%概率改变目标，比原来更少
            self._change_target_temperature()
        
        # 构建数据记录（PID参数保持不变）
        return {
            "timestamp": int(datetime.now().timestamp() * 1000),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "temperature": round(self.current_temp, 2),
            "target_temp": round(self.target_temp, 2),
            "kp": round(self.kp, 3),
            "ki": round(self.ki, 3),
            "kd": round(self.kd, 3),
            "control_period": self.control_period,
            "max_duty": self.max_duty,
            "pid_output": round(pid_output, 2),
            "error": round(error, 2),
            "integral_error": round(self.integral_error, 2),
            "derivative_error": round(derivative_error, 2),
            "heat_input": round(heat_input, 3),
            "heat_loss": round(heat_loss, 3)
        }
    
    def _setup_scenario(self, scenario: str):
        """根据场景设置初始参数"""
        if scenario == "normal":
            self.noise_factor = 0.3
            self.kp, self.ki, self.kd = 1.2, 0.08, 0.05
        elif scenario == "noisy":
            self.noise_factor = 1.0  # 更大噪声
            self.kp, self.ki, self.kd = 1.5, 0.1, 0.03
        elif scenario == "unstable":
            self.noise_factor = 0.5
            self.kp, self.ki, self.kd = 3.0, 0.2, 0.001  # 高增益，可能振荡
        elif scenario == "step_response":
            self.noise_factor = 0.1  # 低噪声
            self.kp, self.ki, self.kd = 1.0, 0.05, 0.08
    
    def _apply_scenario_effects(self, data_point: Dict, step: int, total_steps: int, scenario: str):
        """应用场景特定效果"""
        if scenario == "step_response":
            # 阶跃响应：在特定时间点改变目标温度
            progress = step / total_steps
            if 0.2 < progress < 0.25 or 0.5 < progress < 0.55 or 0.8 < progress < 0.85:
                if random.random() < 0.1:
                    self.target_temp = random.choice([28.0, 32.0, 35.0])
        
        elif scenario == "unstable":
            # 不稳定场景：偶尔大幅改变参数
            if random.random() < 0.005:
                self.kp += random.uniform(-1.0, 1.0)
                self.kp = max(0.5, min(5.0, self.kp))
    
    def save_to_json(self, data: List[Dict[str, Any]], filename: Optional[str] = None) -> str:
        """保存数据为JSON格式"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pid_simulation_{timestamp}.json"
        
        # 创建保存目录
        save_dir = Path("../../data/simulated")
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / filename
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            file_size = file_path.stat().st_size / 1024
            print(f"JSON文件已保存: {file_path}")
            print(f"文件大小: {file_size:.1f} KB, 记录数: {len(data)}")
            return str(file_path)
            
        except Exception as e:
            print(f"保存JSON文件失败: {str(e)}")
            raise
    
    def save_to_csv(self, data: List[Dict[str, Any]], filename: Optional[str] = None) -> str:
        """保存数据为CSV格式"""
        if not data:
            raise ValueError("没有数据可保存")
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pid_simulation_{timestamp}.csv"
        
        # 创建保存目录
        save_dir = Path("../../data/simulated")
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / filename
        
        try:
            fieldnames = list(data[0].keys())
            
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(data)
            
            file_size = file_path.stat().st_size / 1024
            print(f"📊 CSV文件已保存: {file_path}")
            print(f"📈 文件大小: {file_size:.1f} KB, 记录数: {len(data)}")
            return str(file_path)
            
        except Exception as e:
            print(f"❌ 保存CSV文件失败: {str(e)}")
            raise
    
    def save_as_tsdb_format(
        self, 
        data: List[Dict[str, Any]], 
        table_name: str = "pid_simulation",
        filename: Optional[str] = None
    ) -> str:
        """保存为TSDB API响应格式"""
        if not data:
            raise ValueError("没有数据可保存")
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tsdb_format_{timestamp}.json"
        
        # 定义列顺序
        columns = [
            "time", "temperature", "target_temp", "kp", "ki", "kd", 
            "control_period", "max_duty", "pid_output", "error"
        ]
        
        # 转换数据为TSDB格式
        values = []
        for record in data:
            row = []
            for col in columns:
                if col == "time":
                    row.append(record.get("time", record.get("timestamp")))
                else:
                    row.append(record.get(col, 0))
            values.append(row)
        
        # 构造TSDB响应格式
        tsdb_response = {
            "code": 0,
            "message": "模拟数据查询成功",
            "results": [
                {
                    "table": table_name,
                    "data": [
                        {
                            "tags": {
                                "source": "simulation", 
                                "type": "pid_control",
                                "scenario": "normal",
                                "device": "simulator_v1"
                            },
                            "columns": columns,
                            "values": values
                        }
                    ],
                    "continuation_point": None
                }
            ]
        }
        
        # 保存文件
        save_dir = Path("../../data/simulated")
        save_dir.mkdir(parents=True, exist_ok=True)
        file_path = save_dir / filename
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(tsdb_response, f, indent=2, ensure_ascii=False)
            
            file_size = file_path.stat().st_size / 1024
            print(f"🗄️  TSDB格式文件已保存: {file_path}")
            print(f"📋 表名: {table_name}, 记录数: {len(values)}")
            print(f"💾 文件大小: {file_size:.1f} KB")
            return str(file_path)
            
        except Exception as e:
            print(f"❌ 保存TSDB格式文件失败: {str(e)}")
            raise
    
    def create_sample_datasets(self) -> Dict[str, List[str]]:
        """创建多个示例数据集"""
        print("🚀 开始创建PID模拟数据集...")
        saved_files = {"json": [], "csv": [], "tsdb": []}
        
        scenarios = [
            ("normal", 24, 10.0, "正常控制场景"),
            ("noisy", 12, 5.0, "高噪声场景"),
            ("unstable", 6, 2.0, "不稳定控制场景"),
            ("step_response", 4, 1.0, "阶跃响应场景")
        ]
        
        for scenario, hours, interval, description in scenarios:
            print(f"\n📊 生成{description} ({scenario})...")
            
            # 重置状态
            self.reset_state()
            
            # 生成数据
            data = self.generate_historical_data(hours, interval, scenario)
            
            # 保存为不同格式
            json_file = self.save_to_json(data, f"{scenario}_data.json")
            csv_file = self.save_to_csv(data, f"{scenario}_data.csv")
            tsdb_file = self.save_as_tsdb_format(data, f"pid_{scenario}", f"{scenario}_tsdb.json")
            
            saved_files["json"].append(json_file)
            saved_files["csv"].append(csv_file)
            saved_files["tsdb"].append(tsdb_file)
        
        print("\n✅ 所有示例数据集创建完成!")
        print("\n📁 保存的文件:")
        for format_type, files in saved_files.items():
            print(f"\n{format_type.upper()} 格式:")
            for file_path in files:
                print(f"  📄 {file_path}")
        
        return saved_files
    
    def generate_statistics(self, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成数据统计信息"""
        if not data:
            return {}
        
        temps = [d["temperature"] for d in data]
        targets = [d["target_temp"] for d in data]
        errors = [d["error"] for d in data]
        
        stats = {
            "record_count": len(data),
            "time_span": {
                "start": data[0]["time"],
                "end": data[-1]["time"],
                "duration_hours": len(data) * 10 / 3600  # 假设10秒间隔
            },
            "temperature": {
                "min": min(temps),
                "max": max(temps),
                "avg": sum(temps) / len(temps),
                "std": math.sqrt(sum((t - sum(temps)/len(temps))**2 for t in temps) / len(temps))
            },
            "target_temp": {
                "min": min(targets),
                "max": max(targets),
                "avg": sum(targets) / len(targets)
            },
            "control_performance": {
                "avg_error": sum(errors) / len(errors),
                "max_error": max(abs(e) for e in errors),
                "steady_state_error": sum(errors[-100:]) / min(100, len(errors))
            }
        }
        
        return stats


def generate_data_with_fixed_pid(
    kp: float, 
    ki: float, 
    kd: float,
    target_temp: float = 30.0,
    hours: float = 24, 
    interval: float = 10.0, 
    save_formats: List[str] = ["json", "csv"],
    filename_prefix: str = "fixed_pid"
) -> Dict[str, str]:
    """根据固定PID参数生成数据的函数
    
    Args:
        kp: 比例参数
        ki: 积分参数  
        kd: 微分参数
        target_temp: 目标温度
        hours: 模拟时长（小时）
        interval: 采样间隔（秒）
        save_formats: 保存格式列表
        filename_prefix: 文件名前缀
        
    Returns:
        Dict: 保存的文件路径字典
    """
    print(f"🎯 使用固定PID参数生成数据:")
    print(f"   PID参数: Kp={kp}, Ki={ki}, Kd={kd}")
    print(f"   目标温度: {target_temp}°C")
    print(f"   时长: {hours}小时, 采样间隔: {interval}秒")
    
    # 创建模拟器并设置固定PID参数
    simulator = PIDDataSimulator()
    simulator.kp = kp
    simulator.ki = ki
    simulator.kd = kd
    simulator.target_temp = target_temp
    
    # 生成数据（使用"fixed"场景，不会随机调整PID参数）
    data = simulator.generate_historical_data_with_fixed_pid(hours, interval)
    
    # 保存文件
    saved_files = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pid_suffix = f"kp{kp}_ki{ki}_kd{kd}".replace(".", "_")
    
    if "json" in save_formats:
        filename = f"{filename_prefix}_{pid_suffix}_{timestamp}.json"
        saved_files['json'] = simulator.save_to_json(data, filename)
    
    if "csv" in save_formats:
        filename = f"{filename_prefix}_{pid_suffix}_{timestamp}.csv"
        saved_files['csv'] = simulator.save_to_csv(data, filename)
    
    if "tsdb" in save_formats:
        filename = f"{filename_prefix}_{pid_suffix}_tsdb_{timestamp}.json"
        table_name = f"pid_fixed_{pid_suffix}"
        saved_files['tsdb'] = simulator.save_as_tsdb_format(data, table_name, filename)
    
    # 打印统计信息
    stats = simulator.generate_statistics(data)
    print(f"\n📈 数据统计:")
    print(f"  记录数: {stats['record_count']}")
    print(f"  温度范围: {stats['temperature']['min']:.1f} - {stats['temperature']['max']:.1f}°C")
    print(f"  平均误差: {stats['control_performance']['avg_error']:.2f}°C")
    print(f"  PID参数固定: Kp={kp}, Ki={ki}, Kd={kd}")
    
    return saved_files


def quick_generate_data(
    hours: float = 24, 
    interval: float = 10.0, 
    scenario: str = "normal",
    save_formats: List[str] = ["json", "csv"]
) -> Dict[str, str]:
    """快速生成PID模拟数据的便捷函数"""
    print(f"🎯 快速生成PID数据: {hours}小时, {scenario}场景")
    
    simulator = PIDDataSimulator()
    data = simulator.generate_historical_data(hours, interval, scenario)
    
    saved_files = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if "json" in save_formats:
        filename = f"quick_{scenario}_{timestamp}.json"
        saved_files['json'] = simulator.save_to_json(data, filename)
    
    if "csv" in save_formats:
        filename = f"quick_{scenario}_{timestamp}.csv"
        saved_files['csv'] = simulator.save_to_csv(data, filename)
    
    if "tsdb" in save_formats:
        filename = f"quick_{scenario}_tsdb_{timestamp}.json"
        saved_files['tsdb'] = simulator.save_as_tsdb_format(data, f"pid_{scenario}", filename)
    
    # 打印统计信息
    stats = simulator.generate_statistics(data)
    print(f"\n📈 数据统计:")
    print(f"  记录数: {stats['record_count']}")
    print(f"  温度范围: {stats['temperature']['min']:.1f} - {stats['temperature']['max']:.1f}°C")
    print(f"  平均误差: {stats['control_performance']['avg_error']:.2f}°C")
    
    return saved_files


if __name__ == "__main__":
    print("🎮 PID数据模拟器")
    print("=" * 50)
    
    # 创建模拟器实例
    simulator = PIDDataSimulator()
    
    # 选择操作
    print("\n请选择操作:")
    print("1. 创建完整示例数据集")
    print("2. 快速生成24小时正常数据")
    print("3. 生成自定义数据")
    print("4. 使用固定PID参数生成数据")
    print("5. 退出")
    
    choice = input("\n请输入选择 (1-5): ").strip()
    
    if choice == "1":
        simulator.create_sample_datasets()
    
    elif choice == "2":
        quick_generate_data(24, 10.0, "normal", ["json", "csv", "tsdb"])
    
    elif choice == "3":
        try:
            hours = float(input("请输入模拟时长（小时）[24]: ") or "24")
            interval = float(input("请输入采样间隔（秒）[10]: ") or "10")
            scenario = input("请输入场景类型 (normal/noisy/unstable/step_response) [normal]: ") or "normal"
            
            if scenario not in ["normal", "noisy", "unstable", "step_response"]:
                scenario = "normal"
            
            quick_generate_data(hours, interval, scenario, ["json", "csv", "tsdb"])
            
        except ValueError:
            print("❌ 输入格式错误，使用默认参数")
            quick_generate_data()
    
    elif choice == "4":
        try:
            print("\n🔧 输入固定PID参数:")
            kp = float(input("请输入Kp参数 [1.5]: ") or "1.5")
            ki = float(input("请输入Ki参数 [0.1]: ") or "0.1")
            kd = float(input("请输入Kd参数 [0.05]: ") or "0.05")
            target_temp = float(input("请输入目标温度 [30.0]: ") or "30.0")
            hours = float(input("请输入模拟时长（小时）[12]: ") or "12")
            interval = float(input("请输入采样间隔（秒）[5]: ") or "5")
            
            generate_data_with_fixed_pid(
                kp=kp, ki=ki, kd=kd, 
                target_temp=target_temp,
                hours=hours, interval=interval,
                save_formats=["json", "csv", "tsdb"]
            )
            
        except ValueError:
            print("❌ 输入格式错误，使用默认参数")
            generate_data_with_fixed_pid(1.5, 0.1, 0.05, 30.0, 12, 5.0, ["json", "csv", "tsdb"])
    
    elif choice == "5":
        print("👋 再见!")
    
    else:
        print("❌ 无效选择，使用默认操作")
        quick_generate_data()
    
    print("\n🎉 程序执行完成!")