"""RightThing 正事后端。

分层约定（详见 PLAN.md 第 3 节）：

    api/         HTTP 契约，不写业务逻辑
    services/    业务编排、事务、缓存
    sources/     只负责拿到原始 JD 文本
    llm/         Prompt、调用、重试、JSON 校验
    analytics/   归一化、聚合、排名、缺口计算（纯函数，不碰网络）
    models/      数据模型

设计红线：LLM 只做「理解与抽取」，代码做「统计与排名」。
"""

__version__ = "0.1.0"
