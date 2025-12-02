import os
import json
import numpy as np
from scipy import signal
import sys

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import NoiseReductionLevel, Mode
    from ..config.settings import Config
    from ..utils.logger import LoggerSetup
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import NoiseReductionLevel, Mode
    from config.settings import Config
    from utils.logger import LoggerSetup


class DataHandler:

    """数据处理工具：读取、生成、选择数据源"""



    def __init__(self, logger=None):

        self.logger = logger or LoggerSetup.setup_logger()

        self.noise_reduction_level = NoiseReductionLevel.MEDIUM  # 默认降噪强度



    def apply_low_pass_filter(self, data, fs=1.0):

        """

        应用低通滤波器

        :param data: 输入数据数组

        :param fs: 采样频率 (默认为1Hz)

        :return: 滤波后的数据

        """

        params = Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]

        cutoff_freq = params["cutoff_freq"]

        order = params["order"]



        # 计算归一化截止频率

        nyquist_freq = 0.5 * fs

        normalized_cutoff = min(cutoff_freq / nyquist_freq, 0.99)  # 确保在合理范围内



        # 设计Butterworth低通滤波器

        b, a = signal.butter(order, normalized_cutoff, btype='low', analog=False)



        # 应用滤波器 (使用filtfilt避免相位延迟)

        return signal.filtfilt(b, a, data)



    def read_json_data(self, file_path):

        """读取JSON格式的温度数据，支持完整PID数据解析"""

        try:

            with open(file_path, 'r', encoding='utf-8') as f:

                json_data = json.load(f)



            if json_data.get("status") != "success":

                raise ValueError(f"JSON文件状态不是success: {json_data.get('status')}")



            if "data" not in json_data:

                raise ValueError("JSON文件缺少data字段")



            data_list = json_data["data"]

            if not data_list:

                raise ValueError("JSON文件data字段为空")



            # 解析数据 - 包含所有字段

            t, pv_data, mv_data, sv_data = [], [], [], []

            kp_data, ki_data, kd_data, pb_data, ti_data, td_data = [], [], [], [], [], []



            for item in data_list:

                timestamp = item.get("timestamp", 0)

                pv = item.get("pv", 0)  # 过程值，作为实际温度

                mv = item.get("mv", 0)  # 操纵变量

                sv_val = item.get("sv", Config.TARGET_TEMPERATURE)  # 设定值



                # PID参数

                kp = item.get("kp", 0)

                ki = item.get("ki", 0)

                kd = item.get("kd", 0)

                pb = item.get("pb", 100)

                ti = item.get("ti", 20)

                td = item.get("td", 0)



                # 转换时间戳（毫秒转秒）

                time_sec = timestamp / 1000.0

                t.append(time_sec)

                pv_data.append(pv)

                mv_data.append(mv)

                sv_data.append(sv_val)

                kp_data.append(kp)

                ki_data.append(ki)

                kd_data.append(kd)

                pb_data.append(pb)

                ti_data.append(ti)

                td_data.append(td)



            t = np.array(t)

            pv_data = np.array(pv_data)

            mv_data = np.array(mv_data)

            sv_data = np.array(sv_data)

            kp_data = np.array(kp_data)

            ki_data = np.array(ki_data)

            kd_data = np.array(kd_data)

            pb_data = np.array(pb_data)

            ti_data = np.array(ti_data)

            td_data = np.array(td_data)



            # 确保时间序列单调递增

            if not np.all(np.diff(t) >= 0):

                sorted_indices = np.argsort(t)

                t = t[sorted_indices]

                pv_data = pv_data[sorted_indices]

                mv_data = mv_data[sorted_indices]

                sv_data = sv_data[sorted_indices]

                kp_data = kp_data[sorted_indices]

                ki_data = ki_data[sorted_indices]

                kd_data = kd_data[sorted_indices]

                pb_data = pb_data[sorted_indices]

                ti_data = ti_data[sorted_indices]

                td_data = td_data[sorted_indices]



            # 应用低通滤波到温度数据

            pv_data = self.apply_low_pass_filter(pv_data)

            self.logger.info(

                f"对温度数据应用了低通滤波 (降噪强度: {self.noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]['cutoff_freq']})")



            # 对其他数据也应用滤波

            if mv_data is not None:

                mv_data = self.apply_low_pass_filter(mv_data)

            if sv_data is not None:

                sv_data = self.apply_low_pass_filter(sv_data)



            self.logger.info(f"成功读取JSON数据：{file_path}")

            self.logger.info(f"数据范围：{t.min():.0f}s ~ {t.max():.0f}s，共{len(t)}个点")

            self.logger.info(f"数据字段：时间、温度(pv)、操纵变量(mv)、设定值(sv)、PID参数")



            return t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data



        except FileNotFoundError:

            self.logger.error(f"未找到文件 '{file_path}'")

            raise

        except json.JSONDecodeError as e:

            self.logger.error(f"JSON解析失败：{str(e)}")

            raise

        except Exception as e:

            self.logger.error(f"读取失败：{str(e)}")

            raise



    def _generate_default_input_signal(self, t):

        """生成默认输入信号"""

        u = np.zeros_like(t, dtype=np.float64)

        # 分段阶梯输入

        u[t >= 50] += 25.0

        u[t >= 150] += 15.0

        u[t >= 250] -= 5.0

        u[t >= 350] += 20.0

        u[t >= 450] -= 10.0

        # 添加随机噪声并限制范围

        u += np.random.normal(0, 1.5, size=len(t))

        return np.clip(u, Config.MV_MIN, Config.MV_MAX)



    def _generate_flow_input_signal(self, t):

        """生成流量控制的默认输入信号（更平滑）"""

        u = np.zeros_like(t, dtype=np.float64)

        # 平滑的阶跃输入

        u[t >= 50] += 20.0

        u[t >= 150] += 10.0

        u[t >= 250] -= 5.0

        # 添加更多噪声模拟流量波动

        u += np.random.normal(0, 2.0, size=len(t))

        return np.clip(u, Config.MV_MIN, Config.MV_MAX)



    def choose_data_source(self, data_type="dynamic_response"):

        """选择数据来源（仿真生成或读取JSON）"""

        print(f"\n=== 选择{data_type}数据来源 ===")

        print("1. 自动生成非阶跃仿真数据（默认）")

        print("2. 读取外部JSON数据（支持完整PID数据）")



        while True:

            choice = input("请输入选择（1/2，直接回车选1）：").strip() or "1"

            if choice == "1":

                return np.array([]), None, None, None, None, None, None, None, None, None

            elif choice == "2":

                file_path = input(f"请输入{data_type}JSON路径（如'./data.json'）：").strip()

                if not file_path:

                    print("❌ 路径不能为空，请重新输入")

                    continue

                if not os.path.isfile(file_path):

                    print("❌ 文件不存在，请重新输入")

                    continue

                if not file_path.lower().endswith('.json'):

                    print("❌ 文件格式错误，必须是JSON文件，请重新输入")

                    continue

                t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data = self.read_json_data(

                    file_path)

                return t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data

            else:

                print("❌ 输入错误，请选择1或2")



    def choose_mode(self, using_json_data=False):

        """选择运行模式 - 优化逻辑：只有在使用JSON数据时才显示流量控制选项"""

        if using_json_data:

            # JSON数据时，允许选择流量控制模式

            print(f"\n=== 选择控制模式 ===")

            print("1. 温度控制模式")

            print("2. 水阀流量控制模式")



            while True:

                choice = input("请选择控制模式（1-2，直接回车选1）：").strip() or "1"

                if choice == "1":

                    print(f"\n=== 选择运行模式 ===")

                    for i, (key, desc) in enumerate(Config.MODES.items(), 1):

                        if key != Mode.FLOW_CONTROL:  # 温度模式下不显示流量控制模式

                            print(f"{i}. {desc} ({key})")



                    while True:

                        mode_choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"

                        if mode_choice in ["1", "2", "3"]:

                            # 映射到非流量控制模式

                            non_flow_modes = [Mode.STANDARD, Mode.ANTI_DISTURBANCE, Mode.ANTI_NOISE]

                            return non_flow_modes[int(mode_choice) - 1]

                        else:

                            print("❌ 输入错误，请选择1-3")

                elif choice == "2":

                    print(f"\n=== 选择流量控制模式 ===")

                    print("1. 标准流量控制模式")

                    print("2. 抗扰动流量控制模式")

                    print("3. 抗噪声流量控制模式")



                    while True:

                        flow_choice = input("请选择流量控制模式（1-3，直接回车选1）：").strip() or "1"

                        if flow_choice in ["1", "2", "3"]:

                            # 流量控制模式下，所有选项都返回FLOW_CONTROL模式

                            # 实际的控制策略差异在系统内部根据选择的子模式处理

                            return Mode.FLOW_CONTROL

                        else:

                            print("❌ 输入错误，请选择1-3")

                else:

                    print("❌ 输入错误，请选择1或2")

        else:

            # 仿真模式时，也允许选择流量控制选项

            print(f"\n=== 选择控制模式 ===")

            print("1. 温度控制模式")

            print("2. 水阀流量控制模式")



            while True:

                choice = input("请选择控制模式（1-2，直接回车选1）：").strip() or "1"

                if choice == "1":

                    print(f"\n=== 选择运行模式 ===")

                    for i, (key, desc) in enumerate(Config.MODES.items(), 1):

                        if key != Mode.FLOW_CONTROL:  # 温度模式下不显示流量控制模式

                            print(f"{i}. {desc} ({key})")



                    while True:

                        mode_choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"

                        if mode_choice in ["1", "2", "3"]:

                            # 映射到非流量控制模式

                            non_flow_modes = [Mode.STANDARD, Mode.ANTI_DISTURBANCE, Mode.ANTI_NOISE]

                            return non_flow_modes[int(mode_choice) - 1]

                        else:

                            print("❌ 输入错误，请选择1-3")

                elif choice == "2":

                    print(f"\n=== 选择流量控制模式 ===")

                    print("1. 标准流量控制模式")

                    print("2. 抗扰动流量控制模式")

                    print("3. 抗噪声流量控制模式")



                    while True:

                        flow_choice = input("请选择流量控制模式（1-3，直接回车选1）：").strip() or "1"

                        if flow_choice in ["1", "2", "3"]:

                            # 流量控制模式下，所有选项都返回FLOW_CONTROL模式

                            # 实际的控制策略差异在系统内部根据选择的子模式处理

                            return Mode.FLOW_CONTROL

                        else:

                            print("❌ 输入错误，请选择1-3")

                else:

                    print("❌ 输入错误，请选择1或2")



    def choose_noise_reduction_level(self):

        """选择降噪强度"""

        print(f"\n=== 选择降噪强度 ===")

        print("1. 低强度降噪 (截止频率较高，保留更多细节)")

        print("2. 中等强度降噪 (平衡降噪效果和细节保留)")

        print("3. 高强度降噪 (截止频率较低，降噪效果显著)")



        while True:

            choice = input("请选择降噪强度（1-3，直接回车选2）：").strip() or "2"

            if choice in ["1", "2", "3"]:

                levels = [NoiseReductionLevel.LOW, NoiseReductionLevel.MEDIUM, NoiseReductionLevel.HIGH]

                self.noise_reduction_level = levels[int(choice) - 1]

                return self.noise_reduction_level

            else:

                print("❌ 输入错误，请选择1-3")



    def choose_pid_mode(self):

        """选择PID控制模式"""

        print(f"\n=== 选择PID控制模式 ===")

        for i, (key, desc) in enumerate(Config.PID_MODES.items(), 1):

            print(f"{i}. {desc} ({key})")



        while True:

            choice = input("请选择PID模式（1-3，直接回车选1）：").strip() or "1"

            if choice in ["1", "2", "3"]:

                return list(Config.PID_MODES.keys())[int(choice) - 1]

            else:

                print("❌ 输入错误，请选择1-3")



    def choose_tuning_method(self):

        """选择PID整定方法"""

        print(f"\n=== 选择PID整定方法 ===")

        for i, (key, desc) in enumerate(Config.TUNING_METHODS.items(), 1):

            print(f"{i}. {desc} ({key})")



        while True:

            choice = input("请选择整定方法（1-2，直接回车选1）：").strip() or "1"

            if choice in ["1", "2"]:

                return list(Config.TUNING_METHODS.keys())[int(choice) - 1]

            else:

                print("❌ 输入错误，请选择1-2")



    def save_data(self, data, columns, filename):

        """保存数据到CSV"""

        save_path = os.path.join(Config.DATA_SAVE_DIR, filename)

        np.savetxt(

            save_path,

            data,

            delimiter=",",

            header=",".join(columns),

            comments=""

        )

        self.logger.info(f"数据已保存至：{save_path}")

        return save_path



    def save_simulation_to_json(self, time_data, temp_data, valve_data, setpoint, pb_data, ti_data, td_data, kp_data,

                                ki_data, kd_data, start_time, end_time, table_name="PID_FEP_Gateway_Device_001default"):

        """将仿真数据保存为JSON格式"""

        # 转换时间为毫秒时间戳

        timestamps = [int((t + start_time.timestamp()) * 1000) for t in time_data]



        # 构建数据列表

        data_list = []

        for i in range(len(time_data)):

            data_point = {

                "timestamp": timestamps[i],

                "sv": setpoint,

                "ti": ti_data[i] * 10 if len(ti_data) > i else 20,  # 反向缩放显示

                "pb": pb_data[i] if len(pb_data) > i else 100,

                "pv": temp_data[i] if len(temp_data) > i else 0,

                "td": td_data[i] / 2 if len(td_data) > i else 0,  # 反向缩放显示

                "mv": valve_data[i] if len(valve_data) > i else 0,

                "kp": 100 / pb_data[i] if len(pb_data) > i and pb_data[i] != 0 else 5,

                "ki": (100 / pb_data[i]) / ti_data[i] * 10 if len(pb_data) > i and len(ti_data) > i and pb_data[

                    i] != 0 and ti_data[i] != 0 else 0.25,

                "kd": td_data[i] / 2 if len(td_data) > i else 0  # 反向缩放显示

            }

            data_list.append(data_point)



        # 构建JSON结构

        json_result = {

            "status": "success",

            "table": table_name,

            "start_time": datetime.fromtimestamp(start_time.timestamp()).strftime("%Y-%m-%d %H:%M:%S"),

            "end_time": datetime.fromtimestamp(end_time.timestamp()).strftime("%Y-%m-%d %H:%M:%S"),

            "totalRecords": len(data_list),

            "data": data_list

        }



        # 保存到文件

        save_path = os.path.join(Config.DATA_SAVE_DIR, f"simulation_data_{int(start_time.timestamp())}.json")

        with open(save_path, 'w', encoding='utf-8') as f:

            json.dump(json_result, f, ensure_ascii=False, indent=2)



        self.logger.info(f"仿真数据已保存为JSON格式：{save_path}")

        return save_path





# ----水阀流量和温控系统仿真----
