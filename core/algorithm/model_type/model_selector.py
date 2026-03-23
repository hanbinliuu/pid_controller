# ============== Pipeline Arch Backward Compatibility ===============
# In v4.1 we refactored ModelSelector into a Pipeline structure located
# under `pipeline.orchestrator`. For backward compatibility with all
# scripts requiring `ModelSelector`, we expose it directly here.
from .pipeline.orchestrator import TuningOrchestrator as ModelSelector

__all__ = ['ModelSelector']

