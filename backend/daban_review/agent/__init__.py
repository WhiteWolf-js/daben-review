"""agent 层:把数据/指标封装成 in-process MCP 工具,由 Claude 自主调用做情绪属性复盘。"""

from .runner import run_review

__all__ = ["run_review"]
