import numpy as np
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode, DisturbanceType
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode, DisturbanceType
    from config.settings import Config

class DisturbanceGenerator:

    """扰动生成器：生成各种系统扰动"""



    def __init__(self, mode=Mode.STANDARD):

        self.mode = mode



    @staticmethod

    def generate_random_disturbances():

        """生成随机扰动配置 - 考虑更多失效场景，每次最多4种"""

        # 计算合理的扰动数量：根据时间范围和最小间隔动态调整

        time_start_min = 500

        time_start_max = 5000

        time_range = time_start_max - time_start_min  # 可用时间范围：4500秒

        min_separation = 800  # 最小间隔800秒

        max_duration = 250  # 最大持续时间

        

        # 计算理论最大扰动数量：每个扰动至少需要min_separation秒的间隔

        max_possible_disturbances = max(2, int(time_range / (min_separation + max_duration)))

        num_disturbances = min(5, len(Config.DISTURBANCE_TYPES), max_possible_disturbances)



        # 从所有可用的扰动类型中选择num_disturbances种

        available_types = Config.DISTURBANCE_TYPES.copy()

        selected_types = np.random.choice(available_types, size=num_disturbances, replace=False)



        # 优化：预先分配时间段，避免随机生成导致的冲突和无限循环

        # 将时间范围分成num_disturbances个区间，每个区间内随机选择时间点

        time_slots = []

        if num_disturbances > 1:

            slot_size = time_range / num_disturbances

            for i in range(num_disturbances):

                slot_start = time_start_min + i * slot_size

                slot_end = time_start_min + (i + 1) * slot_size - min_separation

                # 在每个区间内随机选择时间点，确保不超出边界

                time_start = np.random.randint(int(slot_start), int(min(slot_end, time_start_max - min_separation)))

                time_slots.append(time_start)

        else:

            time_slots.append(np.random.randint(time_start_min, time_start_max - min_separation))



        # 对时间点进行小幅随机调整，增加随机性（但保持最小间隔）

        time_slots = np.array(time_slots)

        for i in range(len(time_slots)):

            # 在保持最小间隔的前提下，允许小幅随机调整

            if i == 0:

                adjust_range = min(200, (time_slots[i+1] - time_slots[i] - min_separation) // 2) if len(time_slots) > 1 else 200

            elif i == len(time_slots) - 1:

                adjust_range = min(200, (time_slots[i] - time_slots[i-1] - min_separation) // 2)

            else:

                adjust_range = min(200, 

                                   (time_slots[i] - time_slots[i-1] - min_separation) // 2,

                                   (time_slots[i+1] - time_slots[i] - min_separation) // 2)

            if adjust_range > 0:

                time_slots[i] += np.random.randint(-adjust_range, adjust_range)

                time_slots[i] = np.clip(time_slots[i], time_start_min, time_start_max - min_separation)



        disturbances = []

        for i in range(num_disturbances):

            disturbance_type = selected_types[i]

            

            # 随机生成扰动参数

            duration = np.random.randint(80, 250)  # 持续时间 80-250s

            amplitude = np.random.uniform(1.2, 4.0)  # 幅值 1.2-4.0℃



            disturbance = {

                "time": int(time_slots[i]),

                "type": disturbance_type["type"],

                "duration": duration,

                "amplitude": amplitude,

                "description": disturbance_type["description"]

            }

            disturbances.append(disturbance)



        # 按时间排序

        disturbances.sort(key=lambda x: x["time"])



        return disturbances




