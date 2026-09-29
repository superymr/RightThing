"""Prompt 模板。

约定：所有 Prompt 都放在这里集中管理，并随 Settings.prompt_version 一起版本化。
改动 Prompt 必须提升版本号，否则旧缓存会被复用，导致「改了没用」的诡异现象。
"""

from .direction import DIRECTION_SYSTEM, DIRECTION_USER_TEMPLATE
from .jd_extract import JD_EXTRACT_SYSTEM, JD_EXTRACT_USER_TEMPLATE

__all__ = [
    "DIRECTION_SYSTEM",
    "DIRECTION_USER_TEMPLATE",
    "JD_EXTRACT_SYSTEM",
    "JD_EXTRACT_USER_TEMPLATE",
]
