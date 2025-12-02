"""
Path configuration for backend modules
Centralizes sys.path manipulation to avoid duplication
"""
import sys
import os
from pathlib import Path

# Get base directory
BACKEND_DIR = Path(__file__).parent
WEB_TUNING_DIR = BACKEND_DIR.parent

# Check if running in Docker (core is at same level as backend)
if (WEB_TUNING_DIR / "core").exists():
    # Docker environment: core is at /app/core
    CORE_DIR = WEB_TUNING_DIR / "core"
else:
    # Local environment: core is at exp/lambda_adjust/core
    LAMBDA_ADJUST_DIR = WEB_TUNING_DIR.parent
    CORE_DIR = LAMBDA_ADJUST_DIR / "core"

# Add required paths
SYSTEM_TUNING_DIR = CORE_DIR / "algo" / "system_tuning"
MODULES_DIR = BACKEND_DIR / "modules"

# Add to sys.path if not already present
for path in [SYSTEM_TUNING_DIR, MODULES_DIR, CORE_DIR.parent]:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
