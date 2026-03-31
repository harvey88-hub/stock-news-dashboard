"""pipelines — 파이프라인 정의"""
from .hourly_news import HourlyNewsPipeline
from .daily_stocks import DailyStocksPipeline

__all__ = ["HourlyNewsPipeline", "DailyStocksPipeline"]
