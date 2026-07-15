"""中医望诊系统核心包(tcm-tongue-system)。

四个核心 module(dimensions / record / scoring / confidence)仅依赖标准库;
retrieval/ 子包提供 Grep + 同义词 + RAG 混合检索;paths 集中路径配置。

用法(仓库根目录在 sys.path 上,例如以仓库根为工作目录):

    from src.dimensions import VisionDimension
    from src.record import DailyRecord
    from src.retrieval import retrieve
"""
