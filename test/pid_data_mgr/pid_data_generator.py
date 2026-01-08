"""
PID整定所需DCS数据生成程序
功能：生成与样例文件格式一致的DCS数据，包含时间戳、回路标签、PID参数等
"""

import pandas as pd
from datetime import datetime, timedelta
import random
import argparse
from typing import List, Dict, Optional


class PIDDataGenerator:
    """
    PID整定DCS数据生成器类

    主要功能：
    1. 生成符合工业DCS系统格式的PID数据
    2. 支持自定义数据长度、时间范围、PID参数范围
    3. 生成真实的过程值(PV)和操纵值(MV)变化趋势
    4. 支持保存为CSV文件
    """

    def __init__(self):
        # 默认配置参数
        self.default_config = {
            "start_time": "2024-05-20 14:00:00",
            "time_interval": 1,  # 时间间隔（秒）
            "data_length": 100,  # 数据条数
            "loop_tag": "T-101_Temp_Control",  # 回路标签
            "sv_range": (80.0, 90.0),  # 设定值范围
            "pv_base_range": (78.0, 92.0),  # 过程值基础范围
            "mv_range": (35.0, 45.0),  # 操纵值范围
            "p_range": (150.0, 350.0),  # 比例系数范围
            "i_range": (40.0, 70.0),  # 积分系数范围
            "d_range": (2.0, 6.0),  # 微分系数范围
            "noise_level": 0.15,  # 数据噪声水平
            "trend_strength": 0.3  # 趋势变化强度
        }

    @staticmethod
    def generate_timestamp(start_time: str, time_interval: int, data_length: int) -> List[str]:
        """
        生成时间戳列表

        Args:
            start_time: 起始时间字符串，格式如"2024-05-20 14:00:00"
            time_interval: 时间间隔（秒）
            data_length: 数据条数

        Returns:
            格式化的时间戳列表
        """
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        timestamps = []

        for i in range(data_length):
            current_dt = start_dt + timedelta(seconds=i * time_interval)
            # 格式化为样例格式：YYYY-MM-DD HH:MM:SS.000
            timestamps.append(current_dt.strftime("%Y-%m-%d %H:%M:%S.000"))

        return timestamps

    @staticmethod
    def generate_pid_parameters(config: Dict,
                                change_point_ratio: float = 0.1) -> Dict[str, List[float]]:
        """
        生成PID相关参数（SV, PV, MV, P, I, D）

        Args:
            config: 配置字典
            change_point_ratio: 参数变化点比例（0-1）

        Returns:
            包含所有PID参数的字典
        """
        data_length = config["data_length"]
        parameters = {
            "SV": [], "PV": [], "MV": [],
            "PB": [], "TI": [], "TD": []
        }

        # 1. 生成设定值(SV) - 基本稳定，偶尔小幅度变化
        base_sv = random.uniform(*config["sv_range"])
        sv_change_points = int(data_length * change_point_ratio)

        for i in range(data_length):
            if i % sv_change_points == 0 and i != 0:
                base_sv += random.uniform(-1.0, 1.0)
                # 确保在设定范围内
                base_sv = max(config["sv_range"][0], min(base_sv, config["sv_range"][1]))

            # 添加少量噪声
            sv = base_sv + random.gauss(0, config["noise_level"] * 0.5)
            parameters["SV"].append(round(sv, 1))

        # 2. 生成过程值(PV) - 围绕SV波动，有趋势性
        base_pv = random.uniform(*config["pv_base_range"])
        trend_direction = 1 if random.random() > 0.5 else -1

        for i in range(data_length):
            # 每20个数据点可能改变趋势方向
            if i % 20 == 0 and i != 0:
                trend_direction = 1 if random.random() > 0.5 else -1

            # PV变化 = 趋势变化 + 随机波动 + 与SV的关联
            trend_change = trend_direction * random.uniform(0, config["trend_strength"])
            random_noise = random.gauss(0, config["noise_level"])
            sv_correlation = (parameters["SV"][i] - base_sv) * 0.3

            pv = base_pv + trend_change + random_noise + sv_correlation
            pv = max(config["pv_base_range"][0], min(pv, config["pv_base_range"][1]))
            parameters["PV"].append(round(pv, 1))

            base_pv = pv  # 下一个PV基于当前PV

        # 3. 生成操纵值(MV) - 与PV变化负相关
        base_mv = random.uniform(*config["mv_range"])

        for i in range(data_length):
            if i == 0:
                mv = base_mv
            else:
                # MV变化与PV变化负相关（PV升高则MV降低，反之亦然）
                pv_change = parameters["PV"][i] - parameters["PV"][i - 1]
                mv_adjustment = -pv_change * random.uniform(1.5, 2.5)

                # 添加随机波动
                mv = parameters["MV"][i - 1] + mv_adjustment + random.gauss(0, config["noise_level"] * 0.8)
                mv = max(config["mv_range"][0], min(mv, config["mv_range"][1]))

            parameters["MV"].append(round(mv, 1))

        # 4. 生成PID参数（P, I, D）- 阶段性变化
        p_values = [random.uniform(*config["p_range"]) for _ in range(2)]
        i_values = [random.uniform(*config["i_range"]) for _ in range(2)]
        d_values = [random.uniform(*config["d_range"]) for _ in range(2)]

        # 参数切换点
        param_change_point = int(data_length * 0.6)  # 大约60%处切换参数

        for i in range(data_length):
            if i < param_change_point:
                p = p_values[0]
                i_val = i_values[0]
                d = d_values[0]
            else:
                p = p_values[1]
                i_val = i_values[1]
                d = d_values[1]

            # 添加微小波动
            parameters["PB"].append(round(p + random.gauss(0, 2.0), 1))
            parameters["TI"].append(round(i_val + random.gauss(0, 1.0), 1))
            parameters["TD"].append(round(d + random.gauss(0, 0.2), 1))

        return parameters

    def generate_dataframe(self, config: Optional[Dict] = None) -> pd.DataFrame:
        """
        生成完整的PID数据DataFrame

        Args:
            config: 自定义配置字典， None则使用默认配置

        Returns:
            包含完整PID数据的DataFrame
        """
        # 使用默认配置或合并自定义配置
        final_config = self.default_config.copy()
        if config:
            final_config.update(config)

        # 生成各字段数据
        timestamps = self.generate_timestamp(
            final_config["start_time"],
            final_config["time_interval"],
            final_config["data_length"]
        )

        pid_params = self.generate_pid_parameters(final_config)

        # 构建DataFrame
        data = {
            "timestamp": timestamps,
            "loop_tag": [final_config["loop_tag"]] * final_config["data_length"],
            "SV": pid_params["SV"],
            "PV": pid_params["PV"],
            "MV": pid_params["MV"],
            "PB": pid_params["PB"],
            "TI": pid_params["TI"],
            "TD": pid_params["TD"]
        }

        df = pd.DataFrame(data)

        # 确保数值类型正确
        numeric_columns = ["SV", "PV", "MV", "PB", "TI", "TD"]
        for col in numeric_columns:
            df[col] = df[col].astype(float)

        return df

    def save_to_csv(self, df: pd.DataFrame, file_path: str = "PID整定所需DCS数据_生成.csv") -> None:
        """
        将DataFrame保存为CSV文件

        Args:
            df: 要保存的DataFrame
            file_path: 输出文件路径
        """
        df.to_csv(file_path, index=False, encoding="utf-8")
        print(f"数据已成功保存到: {file_path}")
        print(f"生成数据规模: {df.shape[0]} 行 × {df.shape[1]} 列")


def main():
    """主函数 - 命令行接口"""
    parser = argparse.ArgumentParser(description="PID数据生成工具")

    # 命令行参数
    parser.add_argument("-o", "--output", default="D:/pid_test_data.csv",
                        help="输出CSV文件路径，默认: pid_test_data.csv")
    parser.add_argument("-l", "--length", type=int, default=100,
                        help="数据条数，默认: 100")
    parser.add_argument("-t", "--interval", type=int, default=1,
                        help="时间间隔（秒），默认: 1")
    parser.add_argument("-s", "--start",
                        default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        help="起始时间，格式: YYYY-MM-DD HH:MM:SS，默认: 当前时间")
    parser.add_argument("-tag", "--loop_tag", default="T_101_Temp_Control",
                        help="回路标签，默认: T-101_Temp_Control")

    args = parser.parse_args()

    # 创建生成器实例
    generator = PIDDataGenerator()

    # 自定义配置
    custom_config = {
        "data_length": args.length,
        "time_interval": args.interval,
        "start_time": args.start,
        "loop_tag": args.loop_tag
    }

    # 生成数据并保存
    print("=== PID数据生成工具 ===")
    print(f"配置信息:")
    print(f"  数据条数: {args.length}")
    print(f"  时间间隔: {args.interval} 秒")
    print(f"  起始时间: {args.start}")
    print(f"  回路标签: {args.loop_tag}")
    print(f"  输出文件: {args.output}")
    print("\\n正在生成数据...")

    df = generator.generate_dataframe(custom_config)
    generator.save_to_csv(df, args.output)

    # 显示数据预览
    print("\\n数据预览（前5行）:")
    print(df.head())


if __name__ == "__main__":
    main()
    # df = pd.read_csv("D:/pid_test_data.csv")
    # FileImportService._process_timestamps(df)
    # print(df)