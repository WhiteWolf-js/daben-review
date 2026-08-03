"""全局配置:读 .env,集中管理数据库路径、akshare 降频参数、Claude 中转配置。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/.env(无论 cwd 在哪都稳定加载)
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH)
except ImportError:  # python-dotenv 未装时静默跳过,直接读环境变量
    pass

# 项目根:.../daban-review/
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    # 数据库
    db_path: str = str(DATA_DIR / "daban.db")

    # akshare 降频:每次调用后节流秒数 + 失败重试次数(规避东财 push2 限频)
    ak_throttle: float = float(os.getenv("AK_THROTTLE", "1.2"))
    ak_retries: int = int(os.getenv("AK_RETRIES", "3"))
    ak_backoff: float = float(os.getenv("AK_BACKOFF", "1.5"))

    # Claude:自建 / 中转的 Anthropic 兼容网关
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
    # 持仓截图识别用的模型(单轮 vision,比复盘廉价得多)。默认跟随 claude_model,
    # 想省钱可在 .env 配 VISION_MODEL=<更便宜的模型>,不必改代码。
    vision_model: str = os.getenv("VISION_MODEL", "") or os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

    # 盘中监控通知:飞书自建应用主用,自定义机器人 webhook 备用
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_target: str = os.getenv("FEISHU_TARGET", "")   # open_id(ou_,私聊)或群 chat_id(oc_)
    feishu_webhook: str = os.getenv("FEISHU_WEBHOOK", "")  # 备用
    monitor_interval: int = int(os.getenv("MONITOR_INTERVAL", "60"))  # 常规轮询秒,活跃时段加密到 30s

    # 交互式飞书机器人(monitor/bot.py):私聊发指令查盘 + 自由提问
    feishu_bot_enabled: bool = os.getenv("FEISHU_BOT_ENABLED", "0") == "1"
    # 允许使用的 open_id(逗号分隔)。注意是**本应用下的 open_id**(ou_ 开头),
    # 与 FEISHU_TARGET 里的 union_id(on_)不是一回事;留空则只记日志不回复(防裸奔)。
    feishu_bot_allow: str = os.getenv("FEISHU_BOT_ALLOW", "")

    # 成本估算:美元→人民币汇率(agent 调用成本按 Opus 4.8 官方单价估算,详见 agent/pricing.py)
    usd_cny: float = float(os.getenv("USD_CNY", "7.2"))

    # 复盘海报出图:Playwright 打开本后端自身 serve 的前端页(需先 npm run build 出 dist)
    poster_base_url: str = os.getenv("POSTER_BASE_URL", "http://127.0.0.1:8000")
    poster_timeout_ms: int = int(os.getenv("POSTER_TIMEOUT_MS", "30000"))

    def claude_env(self) -> dict:
        """给 claude-agent-sdk 子进程注入的环境变量。"""
        env = {}
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.anthropic_base_url:
            env["ANTHROPIC_BASE_URL"] = self.anthropic_base_url
        return env


CONFIG = Config()
