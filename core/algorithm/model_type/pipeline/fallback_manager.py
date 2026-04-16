from typing import Optional, List

from .context import TuningContext


class PipelineFallbackManager:
    """
    流水线 fallback 统一入口：
    - 统一调用 oscillation_tuner.try_oscillation_tuning
    - 统一构建输出 build_oscillation_output
    - 统一 fallback 成功/失败日志
    """

    def __init__(self, oscillation_tuner, logger_mixin=None):
        self._oscillation_tuner = oscillation_tuner
        self._logger = logger_mixin

    def _log(self, msg: str):
        if self._logger is not None and hasattr(self._logger, "log"):
            self._logger.log(msg)

    def _is_success(self, osc_result) -> bool:
        if osc_result is None:
            return False
        if isinstance(osc_result, dict):
            return osc_result.get("success", True)
        return True

    def try_fallback(
        self,
        context: TuningContext,
        fit_segments: List,
        fit_results: List,
        *,
        force: bool = False,
        start_log: Optional[str] = None,
        success_log: str = "   ✅ 振荡整定fallback成功",
        fail_log: str = "   ❌ 振荡整定fallback失败",
        output_windows=None,
        output_segments=None,
        output_results=None,
    ) -> bool:
        if start_log:
            self._log(start_log)

        osc_result = self._oscillation_tuner.try_oscillation_tuning(
            fit_segments,
            fit_results,
            context.get_current_pid(),
            force=force,
            tuning_constraints=context.export_tuning_constraints(),
        )
        if not self._is_success(osc_result):
            self._log(fail_log)
            return False

        self._log(success_log)
        windows = context.input_data.tuning_window if output_windows is None else output_windows
        segs = context.original_segments if output_segments is None else output_segments
        results = context.original_results if output_results is None else output_results
        context.final_result = self._oscillation_tuner.build_oscillation_output(
            osc_result,
            context.hist_data,
            context.time_range,
            windows,
            segs,
            results,
            tuning_constraints=context.export_tuning_constraints(),
        )
        return True

