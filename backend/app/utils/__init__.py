"""通用工具。"""

from .logging import setup_logging
from .timeutil import now_iso

__all__ = ["now_iso", "setup_logging"]
