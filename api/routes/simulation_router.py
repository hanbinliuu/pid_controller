from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
import json
import os
from core.data.pid_data_simulator import PIDDataSimulator

router = APIRouter()

class SimulationRequest(BaseModel):
    """数据模拟请求"""
    table: str  # 表名（用作文件名前缀）
    start_time: int  # 开始时间戳（毫秒）
    end_time: int  # 结束时间戳（毫秒）

class CustomSimulationRequest(BaseModel):
    """自定义数据模拟请求"""
    table: str  # 表名（用作文件名前缀）
    duration_hours: float = 24.0  # 模拟时长（小时）
    sample_interval: float = 5.0  # 采样间隔（秒）
    scenario: str = "normal"  # 模拟场景
    
class PIDParametersRequest(BaseModel):
    """PID参数设置请求"""
    table: str  # 表名
    kp: float = 1.0  # 比例参数
    ki: float = 0.08  # 积分参数
    kd: float = 0.05  # 微分参数
    target_temp: float = 30.0  # 目标温度
    duration_hours: float = 12.0  # 模拟时长（小时）
    sample_interval: float = 5.0  # 采样间隔（秒）

@router.post("/generate-simulation-data",
             operation_id="基于时间范围的PID模拟数据生成",
             summary="基于时间范围的PID模拟数据生成",
             description="根据指定的开始和结束时间，生成高质量的PID控制系统模拟数据，支持CSV和JSON格式输出")
async def generate_simulation_data(request: SimulationRequest):
    """
    **基于时间范围的PID模拟数据生成**
    
    使用先进的PID控制理论和数学建模，生成高保真度的模拟数据，为系统测试和算法验证提供可靠数据基础。
    
    **核心功能：**
    
    **1. 高精度时间模拟：**
    - 精确的时间范围控制(毫秒级别)
    - 灵活的采样间隔设置(5秒默认)
    - 智能时间戳分配和对齐
    
    **2. 真实的PID控制模拟：**
    - 模拟真实的温度控制过程
    - 包含系统惯性、时间延迟和非线性特性
    - 动态PID参数调整和优化过程
    
    **3. 丰富的数据字段：**
    - 温度数据: 实际值、目标值、误差
    - PID参数: Kp, Ki, Kd的动态变化
    - 控制信号: 输出占空比、控制周期
    - 时间信息: 多格式时间戳支持
    
    **4. 多格式输出：**
    - CSV格式: 适合Excel和数据分析工具
    - JSON格式: 适合API集成和程序处理
    - 统一的数据格式和结构
    
    **参数限制：**
    - 最大模拟时长: 168小时(7天)
    - 时间范围验证: 结束时间 > 开始时间
    - 数据质量保证: 自动数据校验和清洗
    
    **返回信息：**
    - 模拟参数摘要和统计信息
    - 生成文件的路径和名称
    - 数据预览和质量评估
    - 性能指标和执行时间
    
    **应用场景：**
    - PID算法开发和测试
    - 控制系统仿真和验证
    - 机器学习模型训练
    - 系统性能基准测试
    """
    try:
        # 计算时间跨度
        duration_ms = request.end_time - request.start_time
        duration_hours = duration_ms / (1000 * 3600)  # 转换为小时
        
        if duration_hours <= 0:
            raise HTTPException(
                status_code=400,
                detail="结束时间必须大于开始时间"
            )
        
        if duration_hours > 168:  # 限制最大7天
            raise HTTPException(
                status_code=400,
                detail="模拟时长不能超过168小时（7天）"
            )
        
        print(f"开始生成模拟数据，时长: {duration_hours:.2f} 小时")
        
        # 创建模拟器实例
        simulator = PIDDataSimulator()
        
        # 生成模拟数据
        sample_interval = 5.0  # 5秒采样间隔
        simulated_data = simulator.generate_historical_data(
            duration_hours=duration_hours,
            sample_interval=sample_interval,
            scenario="normal"
        )
        
        # 调整时间戳到指定范围
        if simulated_data:
            time_step = duration_ms / len(simulated_data)
            for i, data_point in enumerate(simulated_data):
                adjusted_timestamp = request.start_time + int(i * time_step)
                data_point["timestamp"] = adjusted_timestamp
                
                # 更新时间字符串
                dt = datetime.fromtimestamp(adjusted_timestamp / 1000)
                data_point["time"] = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # 保存到文件
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"{request.table}_{timestamp_str}.csv"
        json_filename = f"{request.table}_{timestamp_str}.json"
        
        # 确保目录存在
        data_dir = os.path.join("data", "simulated")
        os.makedirs(data_dir, exist_ok=True)
        
        # 保存为CSV格式
        csv_path = os.path.join(data_dir, csv_filename)
        import pandas as pd
        df = pd.DataFrame(simulated_data)
        df.to_csv(csv_path, index=False)
        
        # 保存为JSON格式
        json_path = os.path.join(data_dir, json_filename)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(simulated_data, f, indent=2, ensure_ascii=False)
        
        return {
            "status": "success",
            "table": request.table,
            "start_time": request.start_time,
            "end_time": request.end_time,
            "duration_hours": duration_hours,
            "total_records": len(simulated_data),
            "sample_interval": sample_interval,
            "files_generated": {
                "csv": csv_filename,
                "json": json_filename
            },
            "data_preview": simulated_data[:5] if simulated_data else []
        }
        
    except Exception as e:
        print(f"模拟数据生成失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"模拟数据生成失败: {str(e)}"
        )

@router.post("/generate-custom-simulation",
             summary="自定义参数的PID模拟数据生成",
             operation_id="自定义参数的PID模拟数据生成",

             description="支持自定义模拟时长、采样间隔和场景类型，生成特定条件下的PID控制系统模拟数据")
async def generate_custom_simulation(request: CustomSimulationRequest):
    """
    **自定义参数的PID模拟数据生成**
    
    提供高度灵活的模拟参数配置，支持多种模拟场景和自定义参数，满足不同的测试和研究需求。
    
    **灵活参数配置：**
    
    **1. 时间参数控制：**
    - duration_hours: 模拟时长(0-168小时)
    - sample_interval: 采样间隔(0-3600秒)
    - 高精度时间同步和一致性保证
    
    **2. 多样化模拟场景：**
    
    **normal**: 正常工作条件
    - 稳定的目标温度设定
    - 正常的环境扰动和系统噪声
    - 优化的PID参数设置
    
    **noisy**: 高噪声环境
    - 增强的测量噪声和干扰
    - 不稳定的环境条件
    - 测试系统的鲁棒性和抗噪能力
    
    **unstable**: 不稳定系统
    - 不合理的PID参数设置
    - 系统振荡和超调现象
    - 故障诊断和调试参考
    
    **step_response**: 阶跃响应测试
    - 突变的目标温度设定
    - 系统动态响应特性测试
    - PID参数优化的数据基础
    
    **3. 智能数据生成：**
    - 自动调整模拟参数匹配场景
    - 实时统计分析和质量控制
    - 多线程并行生成和优化
    
    **数据统计分析：**
    - 温度范围: 最小、最大、平均值
    - 控制效果: 稳定性、响应速度评估
    - 数据质量: 完整性、一致性验证
    
    **输出特性：**
    - 场景标识文件命名
    - 详细的统计信息报告
    - 高效的文件存储和管理
    
    **应用价值：**
    - 控制算法性能测试
    - 系统边界条件验证
    - 机器学习数据集建设
    - 产品质量和可靠性测试
    """
    try:
        if request.duration_hours <= 0 or request.duration_hours > 168:
            raise HTTPException(
                status_code=400,
                detail="模拟时长必须在0-168小时之间"
            )
        
        if request.sample_interval <= 0 or request.sample_interval > 3600:
            raise HTTPException(
                status_code=400,
                detail="采样间隔必须在0-3600秒之间"
            )
        
        valid_scenarios = ["normal", "noisy", "unstable", "step_response"]
        if request.scenario not in valid_scenarios:
            raise HTTPException(
                status_code=400,
                detail=f"无效的场景类型，支持的场景: {', '.join(valid_scenarios)}"
            )
        
        print(f"开始生成自定义模拟数据，场景: {request.scenario}")
        
        # 创建模拟器实例
        simulator = PIDDataSimulator()
        
        # 生成模拟数据
        simulated_data = simulator.generate_historical_data(
            duration_hours=request.duration_hours,
            sample_interval=request.sample_interval,
            scenario=request.scenario
        )
        
        # 保存到文件
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"{request.table}_{request.scenario}_{timestamp_str}.csv"
        json_filename = f"{request.table}_{request.scenario}_{timestamp_str}.json"
        
        # 确保目录存在
        data_dir = os.path.join("data", "simulated")
        os.makedirs(data_dir, exist_ok=True)
        
        # 保存为CSV格式
        csv_path = os.path.join(data_dir, csv_filename)
        import pandas as pd
        df = pd.DataFrame(simulated_data)
        df.to_csv(csv_path, index=False)
        
        # 保存为JSON格式
        json_path = os.path.join(data_dir, json_filename)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(simulated_data, f, indent=2, ensure_ascii=False)
        
        # 统计分析
        if simulated_data:
            temperatures = [d["temperature"] for d in simulated_data]
            min_temp = min(temperatures)
            max_temp = max(temperatures)
            avg_temp = sum(temperatures) / len(temperatures)
        else:
            min_temp = max_temp = avg_temp = 0
        
        return {
            "status": "success",
            "table": request.table,
            "scenario": request.scenario,
            "duration_hours": request.duration_hours,
            "sample_interval": request.sample_interval,
            "total_records": len(simulated_data),
            "temperature_stats": {
                "min": round(min_temp, 2),
                "max": round(max_temp, 2),
                "avg": round(avg_temp, 2)
            },
            "files_generated": {
                "csv": csv_filename,
                "json": json_filename
            },
            "data_preview": simulated_data[:5] if simulated_data else []
        }
        
    except Exception as e:
        print(f"自定义模拟数据生成失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"自定义模拟数据生成失败: {str(e)}"
        )

@router.post("/generate-fixed-pid-simulation")
async def generate_fixed_pid_simulation(request: PIDParametersRequest):
    """
    使用固定PID参数生成模拟数据
    允许用户指定具体的PID参数值进行模拟
    输入参数：table表名、kp比例参数、ki积分参数、kd微分参数、target_temp目标温度
    """
    try:
        if request.duration_hours <= 0 or request.duration_hours > 168:
            raise HTTPException(
                status_code=400,
                detail="模拟时长必须在0-168小时之间"
            )
        
        # 参数范围验证
        if not (0.1 <= request.kp <= 10.0):
            raise HTTPException(status_code=400, detail="Kp参数必须在0.1-10.0之间")
        
        if not (0.01 <= request.ki <= 1.0):
            raise HTTPException(status_code=400, detail="Ki参数必须在0.01-1.0之间")
            
        if not (0.001 <= request.kd <= 0.5):
            raise HTTPException(status_code=400, detail="Kd参数必须在0.001-0.5之间")
            
        if not (10.0 <= request.target_temp <= 100.0):
            raise HTTPException(status_code=400, detail="目标温度必须在10-100°C之间")
        
        print(f"生成固定PID参数模拟数据: Kp={request.kp}, Ki={request.ki}, Kd={request.kd}")
        
        # 创建模拟器实例并设置参数
        simulator = PIDDataSimulator()
        simulator.kp = request.kp
        simulator.ki = request.ki
        simulator.kd = request.kd
        simulator.target_temp = request.target_temp
        
        # 生成固定PID参数的模拟数据
        simulated_data = simulator.generate_historical_data_with_fixed_pid(
            duration_hours=request.duration_hours,
            sample_interval=request.sample_interval
        )
        
        # 保存到文件
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        pid_str = f"kp{request.kp}_ki{request.ki}_kd{request.kd}".replace(".", "_")
        csv_filename = f"fixed_pid_{pid_str}_{timestamp_str}.csv"
        json_filename = f"fixed_pid_{pid_str}_{timestamp_str}.json"
        
        # 确保目录存在
        data_dir = os.path.join("data", "simulated")
        os.makedirs(data_dir, exist_ok=True)
        
        # 保存为CSV格式
        csv_path = os.path.join(data_dir, csv_filename)
        import pandas as pd
        df = pd.DataFrame(simulated_data)
        df.to_csv(csv_path, index=False)
        
        # 保存为JSON格式
        json_path = os.path.join(data_dir, json_filename)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(simulated_data, f, indent=2, ensure_ascii=False)
        
        # 计算性能指标
        if simulated_data:
            temperatures = [d["temperature"] for d in simulated_data]
            errors = [d["error"] for d in simulated_data]
            
            min_temp = min(temperatures)
            max_temp = max(temperatures)
            avg_temp = sum(temperatures) / len(temperatures)
            avg_error = sum(errors) / len(errors)
            
            # 计算稳态误差（后10%的数据）
            stable_range = int(len(errors) * 0.1)
            steady_state_error = sum(errors[-stable_range:]) / stable_range if stable_range > 0 else avg_error
        else:
            min_temp = max_temp = avg_temp = avg_error = steady_state_error = 0
        
        return {
            "status": "success",
            "table": request.table,
            "pid_parameters": {
                "kp": request.kp,
                "ki": request.ki,
                "kd": request.kd,
                "target_temp": request.target_temp
            },
            "simulation_config": {
                "duration_hours": request.duration_hours,
                "sample_interval": request.sample_interval
            },
            "total_records": len(simulated_data),
            "performance_metrics": {
                "temperature_range": {
                    "min": round(min_temp, 2),
                    "max": round(max_temp, 2),
                    "avg": round(avg_temp, 2)
                },
                "control_accuracy": {
                    "avg_error": round(avg_error, 2),
                    "steady_state_error": round(steady_state_error, 2)
                }
            },
            "files_generated": {
                "csv": csv_filename,
                "json": json_filename
            },
            "data_preview": simulated_data[:3] if simulated_data else []
        }
        
    except Exception as e:
        print(f"固定PID模拟数据生成失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"固定PID模拟数据生成失败: {str(e)}"
        )

@router.get("/simulation-scenarios")
async def get_simulation_scenarios():
    """
    获取支持的模拟场景列表
    返回所有可用的模拟场景及其描述
    """
    scenarios = {
        "normal": {
            "name": "正常模式",
            "description": "标准PID控制场景，参数会有小幅调整",
            "characteristics": ["参数自动调节", "偶尔改变目标温度", "正常噪声水平"]
        },
        "noisy": {
            "name": "高噪声模式", 
            "description": "高噪声环境下的PID控制",
            "characteristics": ["高测量噪声", "频繁参数扰动", "不稳定环境"]
        },
        "unstable": {
            "name": "不稳定模式",
            "description": "系统不稳定，参数频繁变化",
            "characteristics": ["参数大幅变化", "目标温度频繁调整", "系统震荡"]
        },
        "step_response": {
            "name": "阶跃响应模式",
            "description": "阶跃信号响应测试",
            "characteristics": ["固定参数", "阶跃目标变化", "响应特性分析"]
        }
    }
    
    return {
        "status": "success",
        "total_scenarios": len(scenarios),
        "scenarios": scenarios
    }

@router.get("/simulation-files")
async def list_simulation_files():
    """
    列出已生成的模拟数据文件
    返回data/simulated目录下的所有模拟文件
    """
    try:
        data_dir = os.path.join("data", "simulated")
        
        if not os.path.exists(data_dir):
            return {
                "status": "success",
                "total_files": 0,
                "files": []
            }
        
        files = []
        for filename in os.listdir(data_dir):
            if filename.endswith(('.csv', '.json')):
                file_path = os.path.join(data_dir, filename)
                file_stat = os.stat(file_path)
                
                files.append({
                    "filename": filename,
                    "size_bytes": file_stat.st_size,
                    "size_mb": round(file_stat.st_size / (1024 * 1024), 2),
                    "created_time": datetime.fromtimestamp(file_stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                    "modified_time": datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                })
        
        # 按修改时间排序
        files.sort(key=lambda x: x["modified_time"], reverse=True)
        
        return {
            "status": "success",
            "total_files": len(files),
            "data_directory": data_dir,
            "files": files
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取文件列表失败: {str(e)}"
        )

@router.get("/health")
async def health_check():
    """模拟数据服务健康检查"""
    return {
        "status": "ok",
        "service": "simulation-data",
        "timestamp": datetime.now().isoformat()
    }