from __future__ import annotations

from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, model_validator
from agent.plugin_composition import CredentialRef


def telegram_bot_urls(api_base: str) -> tuple[str, str]:
    """给出 Python Telegram Bot 的 bot 与文件下载基址；两者只差 api_base 前缀。"""

    base = api_base.rstrip("/")
    return f"{base}/bot", f"{base}/file/bot"


class TelegramChannelConfig(BaseModel):
    """校验固定输入中的 Telegram 配置和凭据引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool | None = False
    token: CredentialRef | None = None
    allow_from: tuple[str, ...] = ()
    # 留空即官方端点；自建 Bot API 或反向代理线路在此覆盖。
    api_base: str = "https://api.telegram.org"
    timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_enabled_credentials(self) -> TelegramChannelConfig:
        url = urlsplit(self.api_base)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("api_base 必须是无凭据的 HTTP(S) URL")
        if self.enabled and self.token is None:
            raise ValueError("启用 Telegram channel 需要 token")
        return self
