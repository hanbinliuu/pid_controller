import numpy as np
from scipy.optimize import least_squares
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode, TuningMethod
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode, TuningMethod
    from config.settings import Config


class SystemIdentifier:

    """系统辨识与PID整定工具：基于FOPDT模型和Lambda方法"""



    @staticmethod

    def fopdt_model(params, t, u, y0):

        """一阶加纯滞后（FOPDT）模型"""

        K, T, L = params

        y = np.ones_like(t) * y0

        L_int = int(np.round(L))  # 滞后时间（整数化）



        for i in range(len(t)):

            dt = t[i] - t[i - 1] if i > 0 else 1

            u_delay = u[max(0, i - L_int)]  # 滞后输入

            y[i] = y[i - 1] + (K * u_delay - (y[i - 1] - y0)) / T * dt



        return y



    @staticmethod

    def first_order_model(params, t, u, y0):

        """一阶模型（无滞后）"""

        K, T = params

        y = np.ones_like(t) * y0



        for i in range(len(t)):

            dt = t[i] - t[i - 1] if i > 0 else 1

            steady_state = u[i] * K

            y[i] = y[i - 1] + (steady_state - y[i - 1]) / T * dt



        return y



    @staticmethod

    def residuals(params, t, u, y_measured, y0, model_type='fopdt'):

        """最小二乘优化的残差函数"""

        if model_type == 'first_order':

            y_predicted = SystemIdentifier.first_order_model(params, t, u, y0)

        else:

            y_predicted = SystemIdentifier.fopdt_model(params, t, u, y0)

        return y_predicted - y_measured



    @staticmethod

    def identify_fopdt(t, y, u):

        """用最小二乘法辨识FOPDT模型参数（K, T, L）"""

        y0 = np.mean(y[-30:]) if len(y) > 30 else np.mean(y)  # 初始值估计

        max_u = np.max(u)

        max_y = np.max(y)

        gain_guess = (max_y - y0) / max_u if max_u > Config.EPSILON else 0.5



        # 初始猜测与参数边界

        initial_guess = [max(gain_guess, 0.1), 30.0, 5.0]  # K, T, L

        bounds = ([0.05, 5.0, 0.0], [1.5, 150.0, 20.0])



        try:

            result = least_squares(

                SystemIdentifier.residuals,

                initial_guess,

                args=(t, u, y, y0, 'fopdt'),

                bounds=bounds,

                verbose=0

            )

            K, T, L = result.x

        except Exception as e:

            print(f"⚠️ 参数辨识失败：{e}，使用初始猜测值")

            K, T, L = initial_guess



        # 确保参数在合理范围

        K = np.clip(K, 0.05, 1.5)

        T = np.clip(T, 5.0, 150.0)

        L = np.clip(L, 0.0, 20.0)

        return K, T, L



    @staticmethod

    def identify_first_order(t, y, u):

        """用最小二乘法辨识一阶模型参数（K, T）"""

        y0 = np.mean(y[:10]) if len(y) > 10 else np.mean(y)  # 初始值估计

        max_u = np.max(u)

        max_y = np.max(y)

        gain_guess = (max_y - y0) / max_u if max_u > Config.EPSILON else 0.5



        # 初始猜测与参数边界

        initial_guess = [max(gain_guess, 0.1), 1.0]  # K, T

        bounds = ([0.05, 0.1], [2.0, 10.0])



        try:

            result = least_squares(

                SystemIdentifier.residuals,

                initial_guess,

                args=(t, u, y, y0, 'first_order'),

                bounds=bounds,

                verbose=0

            )

            K, T = result.x

        except Exception as e:

            print(f"⚠️ 一阶模型参数辨识失败：{e}，使用初始猜测值")

            K, T = initial_guess



        # 确保参数在合理范围

        K = np.clip(K, 0.05, 2.0)

        T = np.clip(T, 0.1, 10.0)

        return K, T



    @staticmethod

    def lambda_tuning(K, T, L, lambda_val=None, mode=Mode.STANDARD):

        """基于Lambda方法整定PID参数，根据模式调整参数"""

        if lambda_val is None:

            lambda_val = T * 0.8

        print('lambda值是：', lambda_val)

        denominator = K * (lambda_val + L / 2)

        if denominator < Config.EPSILON:

            return 1.0, 20.0, 1.0  # 异常时返回默认安全值



        # 计算Kp, Ti, Td

        Kp = (T + L / 2) / denominator

        Ti = T + L / 2

        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0



        # 根据模式调整参数

        if mode == Mode.ANTI_DISTURBANCE:

            # 抗扰动模式：降低比例增益和微分增益，增加积分时间

            Kp *= 0.8

            Ti *= 1.2

            Td *= 0.7

        elif mode == Mode.ANTI_NOISE:

            # 抗噪声模式：降低比例增益和微分增益，增加积分时间

            Kp *= 0.7

            Ti *= 1.3

            Td *= 0.5

        elif mode == Mode.FLOW_CONTROL:

            # 流量控制模式：降低比例增益，增加积分时间，减少微分

            Kp *= 0.6

            Ti *= 1.5

            Td *= 0.3  # 保持微分但降低



        # 参数限幅

        Kp = np.clip(Kp, 0.5, 6.0)

        Ti = np.clip(Ti, 8.0, 120.0)

        Td = np.clip(Td, 0.0, 25.0)



        # 转换为pb, ti, td

        pb = 100 / Kp if Kp != 0 else 100.0

        ti = Ti

        td = Td



        # 应用全局参数边界保护

        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)

        ti = np.clip(ti, Config.TI_MIN, Config.TI_MAX)

        td = np.clip(td, Config.TD_MIN, Config.TD_MAX)



        return pb, ti, td



    @staticmethod

    def lambda_tuning_for_flow(K, T, L=0.0, mode=None):

        """

        针对流量控制的 PID 整定（快过程）

        假设 L ≈ 0，使用简化 Lambda 方法或经验公式

        """

        # 流量系统通常 L 很小，强制设为 0 避免过度保守

        L = 0.05



        # Lambda 选择：快响应，取较小值（如 T/3 ~ T/2）

        # lambda_val = max(T * 0.8, 0.1)  # 避免除零，最小 0.1s

        lambda_val = 0.8*T



        # 分母保护

        denominator = K * (lambda_val + L / 2)

        if denominator < Config.EPSILON:

            return 1.0, 20.0, 0.0  # 默认安全值（P主导，I弱，D=0）



        # 标准 Lambda 公式

        Kp = (T + L / 2) / denominator

        Ti = T + L / 2

        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0



        # 针对流量的特殊调整

        if mode == Mode.FLOW_CONTROL:

            # 1. 降低 Kp 避免超调（流量易振荡）

            Kp *= 0.6

            # 2. 增大 Ti（减弱积分，防阀门频繁动作）

            Ti *= 1.5

            # 3. 微分通常关闭或极小（流量噪声大）

            Td = 0.0



        # 参数限幅（流量控制更严格）

        Kp = np.clip(Kp, 0.2, 3.0)  # 比例增益更小

        Ti = np.clip(Ti, 5.0, 60.0)  # 积分时间更短但不过激

        Td = 0.0  # 强制关闭微分（推荐）



        # 转换为工程单位

        Pb = 100 / Kp if Kp != 0 else 100.0

        return Pb, Ti, Td



    @staticmethod

    def cohen_coon_tuning(K, T, L):

        """Cohen-Coon 整定方法（适用于FOPDT模型）"""

        if L <= 0 or T <= 0:

            print("⚠️ Cohen-Coon 要求 T > 0 且 L > 0，返回默认参数")

            return 1.0, 20.0, 1.0



        # Cohen-Coon 公式

        Kc = (1 / K) * (T / L) * (4.0 / 3.0 + (L / (4 * T)))

        Ti = L * (32 + 6 * (L / T)) / (13 + 8 * (L / T))

        Td = (4 * L) / (11 + 2 * (L / T))



        # 转换为 pb（比例带 = 100 / Kp）

        pb = 100 / Kc if Kc != 0 else 100.0

        ti = Ti

        td = Td



        # 参数限幅（与 Lambda 方法一致）

        pb = np.clip(pb, 100 / 6.0, 100 / 0.5)  # 对应 Kp ∈ [0.5, 6.0]

        ti = np.clip(ti, 8.0, 120.0)

        td = np.clip(td, 0.0, 25.0)



        return pb, ti, td



    def classify_case(self, temp_data, setpoint, tol=0.5, std_tol=0.2, min_len=10):

        """判断JSON数据属于哪种情形（Case 1 / 2 / 3）"""

        n = len(temp_data)

        if n < 30:  # 数据太少，无法判断

            return "UNKNOWN"



        # 特征1：初始点是否远离设定点

        initial_dev = abs(temp_data[0] - setpoint)

        is_cold_start = initial_dev > 2.0



        # 特征2：前段是否稳态（前50点或1/3数据）

        head_len = min(50, n // 3)

        head_steady = self.is_steady_state(temp_data[:head_len], setpoint, tol, std_tol, min_len)



        # 特征3：尾段是否稳态（最后30点）

        tail_len = min(30, n // 4)

        tail_steady = self.is_steady_state(temp_data[-tail_len:], setpoint, tol, std_tol, min_len)



        # 特征4：是否存在中间扰动（先稳后乱）

        # 检查是否存在"稳态 → 偏离 → 恢复"模式

        has_disturbance = False

        if head_steady:

            # 从 head_len 开始找第一个显著偏离点

            for i in range(head_len, n):

                if abs(temp_data[i] - setpoint) > 1.0:

                    # 再检查后续是否有恢复趋势（可选）

                    has_disturbance = True

                    break



        # 分类

        if is_cold_start and not tail_steady:

            return "CASE_1"  # 全程非稳态，冷启动

        elif head_steady and has_disturbance:

            return "CASE_2"  # 先稳后扰

        elif not head_steady and tail_steady:

            return "CASE_3"  # 有完整升温+稳态过程

        elif head_steady and not has_disturbance and tail_steady:

            return "ALREADY_STABLE"  # 无需整定

        else:

            # 模糊情况：优先按 CASE_3 处理（尝试找首次升温段）

            return "CASE_3_FALLBACK"



    def is_steady_state(self, temps, setpoint, tol=0.5, std_tol=0.2, min_len=10):

        """判断一段温度是否处于稳态"""

        if len(temps) < min_len:

            return False

        within_band = np.all(np.abs(temps - setpoint) <= tol)

        low_std = np.std(temps) < std_tol

        return within_band and low_std



    def find_first_steady_entry(self, temp_data, setpoint, window=20, tol=0.5, std_tol=0.2):

        """找到首次进入稳态的时间点"""

        for i in range(window, len(temp_data)):

            if self.is_steady_state(temp_data[i - window + 1:i + 1], setpoint, tol, std_tol):

                return i - window + 1  # 返回稳态开始索引

        return None



    def find_disturbance_start(self, temp_data, setpoint, steady_head_len, threshold=1.0):

        """定位扰动起始点"""

        for i in range(steady_head_len, len(temp_data)):

            if abs(temp_data[i] - setpoint) > threshold:

                # 可加斜率突变判断：|dT/dt| 突增

                return i

        return None



    def extract_tuning_segment(self, case, t, temp_data, setpoint, u_data=None):

        """根据情形提取有效整定段"""

        if case == "CASE_1":

            # 全程非稳态，整段作为整定段

            if u_data is not None:

                return t, temp_data, u_data

            return t, temp_data

        elif case == "CASE_2":

            # 扰动后恢复段

            head_len = min(50, len(temp_data) // 3)

            start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)

            if start_idx is not None:

                if u_data is not None:

                    return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]

                return t[start_idx:], temp_data[start_idx:]

            else:

                # 如果没找到扰动点，可能数据有问题，返回后半段

                mid = len(t) // 2

                if u_data is not None:

                    return t[mid:], temp_data[mid:], u_data[mid:]

                return t[mid:], temp_data[mid:]

        elif case in ["CASE_3", "CASE_3_FALLBACK"]:

            # 首次升温段

            steady_idx = self.find_first_steady_entry(temp_data, setpoint)

            if steady_idx:

                # 多取一点包含超调或稳定过程

                end_idx = min(steady_idx + 20, len(t))

                if u_data is not None:

                    return t[:end_idx], temp_data[:end_idx], u_data[:end_idx]

                return t[:end_idx], temp_data[:end_idx]

            else:

                # 退化为 CASE_2

                head_len = min(50, len(temp_data) // 3)

                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)

                if start_idx is not None:

                    if u_data is not None:

                        return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]

                    return t[start_idx:], temp_data[start_idx:]

                else:

                    # 如果都找不到，返回前半段

                    mid = len(t) // 2

                    if u_data is not None:

                        return t[:mid], temp_data[:mid], u_data[:mid]

                    return t[:mid], temp_data[:mid]

        else:

            # UNKNOWN 或 ALREADY_STABLE，返回 None

            if u_data is not None:

                return None, None, None

            return None, None



    def auto_tune_from_json(self, t, temp_data, setpoint, tuning_method, mode=Mode.STANDARD, u_data=None):

        """根据JSON数据自动整定PID参数"""

        case = self.classify_case(temp_data, setpoint)

        print(f"📊 JSON数据情形: {case}")



        if case == "ALREADY_STABLE":

            print("✅ 数据已稳定，无需整定")

            return None



        # 提取整定段，如果提供了输入信号数据，也同时提取

        if u_data is not None:

            t_seg, y_seg, u_seg = self.extract_tuning_segment(case, t, temp_data, setpoint, u_data)

        else:

            t_seg, y_seg = self.extract_tuning_segment(case, t, temp_data, setpoint)

            u_seg = None



        if t_seg is None or len(t_seg) < 20:

            print("⚠️ 无法提取有效整定段，数据不足")

            return None



        print(f"📈 提取整定段: {len(t_seg)} 个点")

        # 重置时间轴为从0开始

        t_seg_rel = t_seg - t_seg[0]



        # 如果没有输入信号数据，使用设定值作为默认输入（不理想但至少能运行）

        if u_seg is None:

            print("⚠️ 警告：未提供输入信号数据，使用设定值作为默认输入进行辨识（可能不准确）")

            u_seg = np.full_like(t_seg_rel, setpoint)



        # 拟合FOPDT模型

        try:

            if mode == Mode.FLOW_CONTROL:

                # 流量模式使用一阶模型

                K, T = self.identify_first_order(t_seg_rel, y_seg, u_seg)

                L = 0.0  # 假设无滞后

                print(f"🔍 一阶模型辨识结果: K={K:.3f}, T={T:.3f}")

            else:

                K, T, L = self.identify_fopdt(t_seg_rel, y_seg, u_seg)

                print(f"🔍 FOPDT辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}")

        except Exception as e:

            print(f"❌ 模型拟合失败: {e}")

            return None



        # Lambda整定

        lambda_val = T  # 可配置

        if tuning_method == TuningMethod.LAMBDA:

            if mode == Mode.FLOW_CONTROL:

                pb, ti, td = self.lambda_tuning_for_flow(K, T, L, mode)

            else:

                pb, ti, td = self.lambda_tuning(K, T, L, lambda_val, mode)

        elif tuning_method == TuningMethod.COHEN_COON:

            pb, ti, td = self.cohen_coon_tuning(K, T, L)

        else:

            pb, ti, td = self.lambda_tuning(K, T, L, lambda_val, mode)



        print(f"🎯 计算PID参数: Pb={pb:.2f}%, Ti={ti:.2f}s, Td={td:.2f}s")

        return {"pb": pb, "ti": ti, "td": td, "case": case}





# ----稳定性和扰动判断----
