import numpy as np
import matplotlib.pyplot as plt

from scipy.optimize import least_squares


class FlowValveLambdaTuner:
    """系统辨识与PID整定工具：基于一阶滞后模型和Lambda方法"""

    @staticmethod
    def first_order_model(params, t, u, y0):
        """
        一阶滞后模型（First Order Model）
        G(s) = K / (T*s + 1)

        参数:
            params: [K, T] 增益和时间常数
            t: 时间序列
            u: 输入序列
            y0: 初始输出值
        """
        K, T = params
        n = len(t)
        y = np.ones_like(t) * y0

        for i in range(1, n):
            dt = t[i] - t[i - 1] if i > 0 else 1

            # 一阶滞后差分方程: dy/dt = (K*u - y) / T
            # 离散化: y[i] = y[i-1] + (K*u[i-1] - y[i-1]) / T * dt
            derivative = (K * u[i - 1] - y[i - 1]) / T
            y[i] = y[i - 1] + derivative * dt

        return y

    @staticmethod
    def first_order_model_with_no_lag(params, t, u, y0):
        """
        一阶无滞后模型 - 使用当前输入（无滞后）
        更接近实际物理过程
        """
        K, T = params
        n = len(t)
        y = np.ones_like(t) * y0

        for i in range(1, n):
            dt = t[i] - t[i - 1]

            # 使用当前时刻的输入
            derivative = (K * u[i] - y[i - 1]) / T
            y[i] = y[i - 1] + derivative * dt

        return y

    @staticmethod
    def residuals(params, t, u, y_measured, y0, model_type='standard'):
        """最小二乘优化的残差函数"""
        if model_type == 'standard':
            y_predicted = FlowValveLambdaTuner.first_order_model(params, t, u, y0)
        else:
            y_predicted = FlowValveLambdaTuner.first_order_model_with_no_lag(params, t, u, y0)

        return y_predicted - y_measured

    @staticmethod
    def identify_first_order(t, y, u, model_type='standard'):
        """
        用最小二乘法辨识一阶模型参数（K, T）

        参数:
            t: 时间序列 [s]
            y: 输出响应序列
            u: 输入信号序列
            model_type: 模型类型 ('standard'使用u[i-1], 'no_lag'使用u[i])
        """
        print("=== 一阶模型参数辨识 ===")

        # 初始值估计 - 使用前10个点的平均值
        y0 = np.mean(y[:min(10, len(y))])
        print(f"估计初始值 y0 = {y0:.2f}")

        # 计算增益初始猜测
        u_range = np.ptp(u)  # 输入范围
        y_range = np.ptp(y)  # 输出范围

        if u_range > 1e-6:
            K_guess = y_range / u_range
        else:
            K_guess = 0.8

        K_guess = np.clip(K_guess, 0.1, 5.0)

        # 时间常数初始猜测 - 基于响应速度
        T_guess = FlowValveLambdaTuner._estimate_initial_time_constant(t, y, y0)

        initial_guess = [K_guess, T_guess]
        print(f"初始猜测: K={K_guess:.3f}, T={T_guess:.1f}s")

        # 参数边界
        bounds = ([0.01, 1.0], [10.0, 300.0])  # K_min, T_min; K_max, T_max

        try:
            result = least_squares(
                FlowValveLambdaTuner.residuals,
                initial_guess,
                args=(t, u, y, y0, model_type),
                bounds=bounds,
                method='trf',
                ftol=1e-8,
                xtol=1e-8,
                max_nfev=1000,
                verbose=0
            )

            if result.success:
                K, T = result.x
                cost = result.cost
                print(f"优化成功! 残差平方和: {cost:.6f}")
                print(f"辨识参数: K={K:.4f}, T={T:.2f}s")
            else:
                print(f"优化未完全收敛: {result.message}")
                K, T = result.x

        except Exception as e:
            print(f"c参数辨识失败：{e}")
            print(f"使用初始猜测值: K={initial_guess[0]:.3f}, T={initial_guess[1]:.1f}s")
            K, T = initial_guess

        # 验证参数合理性
        K, T = FlowValveLambdaTuner._validate_parameters(K, T)

        return K, T

    @staticmethod
    def _estimate_initial_time_constant(t, y, y0):
        """估计初始时间常数"""
        if len(y) < 20:
            return 30.0  # 默认值

        # 找到响应达到63.2%的时间
        y_steady = np.mean(y[-10:])  # 稳态值
        y_range = y_steady - y0

        if abs(y_range) < 1e-6:
            return 30.0

        y_target = y0 + 0.632 * y_range

        # 找到达到目标值的时间
        for i in range(len(y)):
            if y[i] >= y_target:
                return t[i] - t[0]

        return 30.0  # 未找到则返回默认值

    @staticmethod
    def _validate_parameters(K, T):
        """验证参数合理性"""
        warnings = []

        if K < 0.05:
            warnings.append("增益K过小，重新调整")
            K = max(K, 0.05)
        elif K > 8.0:
            warnings.append("增益K过大，重新调整")
            K = min(K, 8.0)

        if T < 2.0:
            warnings.append("时间常数T过小，重新调整")
            T = max(T, 2.0)
        elif T > 250.0:
            warnings.append("时间常数T过大，重新调整")
            T = min(T, 250.0)

        for warning in warnings:
            print(f"{warning}")

        return K, T

    @staticmethod
    def lambda_tuning(K, T, lambda_val=None, mode="standard"):
        """
        基于Lambda方法整定PID参数（一阶模型版本）

        对于一阶模型，常用的整定公式：
        - Kp = T / (K * λ)
        - Ti = T
        - Td = 0 (一阶系统通常不需要微分)
        """
        if lambda_val is None:
            # 默认Lambda = 时间常数T
            lambda_val = T

        print(f"Lambda整定: K={K:.3f}, T={T:.1f}s, λ={lambda_val:.1f}")

        if abs(K * lambda_val) < 1e-6:
            print("计算异常，使用安全参数")
            return 1.0, T, 0.0

        # 基于内部模型控制的整定公式
        Kp = T / (K * lambda_val)
        Ti = T
        Td = 0.0  # 一阶系统通常不需要微分

        # 根据模式调整参数
        if mode == "anti_disturbance":
            # 抗扰动模式：更保守
            Kp *= 0.8
            Ti *= 1.2
        elif mode == "anti_noise":
            # 抗噪声模式：更平滑
            Kp *= 0.7
            Ti *= 1.3

        # 参数限幅
        Kp = np.clip(Kp, 0.1, 20.0)
        Ti = np.clip(Ti, 5.0, 300.0)
        Td = 0.0  # 保持为0

        print(f"整定结果: Kp={Kp:.3f}, Ti={Ti:.1f}s, Td={Td:.1f}s")
        return Kp, Ti, Td

    @staticmethod
    def calculate_model_metrics(t, u, y, K, T, model_type='standard'):
        """计算模型拟合指标"""
        y0 = np.mean(y[:10])

        if model_type == 'standard':
            y_pred = FlowValveLambdaTuner.first_order_model([K, T], t, u, y0)
        else:
            y_pred = FlowValveLambdaTuner.first_order_model_with_no_lag([K, T], t, u, y0)

        # 计算各种指标
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        metrics = {
            'R_squared': r_squared,
            'RMSE': np.sqrt(np.mean((y - y_pred) ** 2)),
            'MAE': np.mean(np.abs(y - y_pred)),
            'Max_Error': np.max(np.abs(y - y_pred)),
            'Fit_VAF': 100 * (1 - np.var(y - y_pred) / np.var(y))  # 方差解释百分比
        }

        return metrics, y_pred

    @staticmethod
    def plot_identification_results(t, u, y, K, T, model_type='standard'):
        """绘制辨识结果"""
        metrics, y_pred = FlowValveLambdaTuner.calculate_model_metrics(t, u, y, K, T, model_type)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # 输入输出曲线
        ax1.plot(t, u, 'g-', linewidth=2, label='输入信号', alpha=0.7)
        ax1.set_ylabel('输入 (%)', color='g')
        ax1.tick_params(axis='y', labelcolor='g')
        ax1.legend(loc='upper left')

        ax1_twin = ax1.twinx()
        ax1_twin.plot(t, y, 'bo', markersize=3, alpha=0.6, label='实际输出')
        ax1_twin.plot(t, y_pred, 'r-', linewidth=2, label='模型预测')
        ax1_twin.set_ylabel('输出', color='b')
        ax1_twin.tick_params(axis='y', labelcolor='b')
        ax1_twin.legend(loc='upper right')
        ax1.set_title('一阶模型辨识结果')
        ax1.grid(True, alpha=0.3)

        # 残差图
        residuals = y - y_pred
        ax2.plot(t, residuals, 'k-', alpha=0.7, label='残差')
        ax2.axhline(0, color='r', linestyle='--', alpha=0.5)
        ax2.set_xlabel('时间 (s)')
        ax2.set_ylabel('残差')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        ax2.set_title(f'残差分析 (R² = {metrics["R_squared"]:.4f})')

        # 添加参数信息
        param_text = f"""一阶模型参数:
            增益 K = {K:.4f}
            时间常数 T = {T:.2f} s

            拟合指标:
            R² = {metrics['R_squared']:.4f}
            RMSE = {metrics['RMSE']:.4f}
            MAE = {metrics['MAE']:.4f}
            方差解释 = {metrics['Fit_VAF']:.1f}%
        """

        plt.figtext(0.02, 0.02, param_text, bbox=dict(facecolor='white', alpha=0.8))

        plt.tight_layout()
        plt.show()

        return metrics
