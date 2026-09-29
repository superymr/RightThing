"""服务层：编排、缓存、后台任务、看板读取。

刻意不在本 `__init__` 里 re-export 子模块符号：`llm/` 与 `services/` 互相引用，
过早导入会制造循环导入。需要什么就显式 `from .orchestrator import ...`。
"""
