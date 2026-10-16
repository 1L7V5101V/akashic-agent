"""telegram_channel 的 api_base：可指向自建 Bot API 或反向代理线路。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from plugins.telegram_channel.channel import _application
from plugins.telegram_channel.config import TelegramChannelConfig, telegram_bot_urls
from plugins.telegram_channel.settings import FIELDS

_TOKEN = "123456789:" + "A" * 35


def test_default_api_base_keeps_official_endpoints() -> None:
    """不给 api_base 时，bot 调用与文件下载都留在官方端点。"""

    application = _application(TelegramChannelConfig().api_base, _TOKEN, 30.0)

    assert application.bot.base_url == f"https://api.telegram.org/bot{_TOKEN}"
    assert application.bot.base_file_url == f"https://api.telegram.org/file/bot{_TOKEN}"


def test_api_base_moves_both_bot_and_file_calls() -> None:
    """给了 api_base（含结尾斜杠）后，bot 调用与文件下载同源改走该线路。"""

    config = TelegramChannelConfig(api_base="https://api.il7510n.dpdns.org/")

    assert telegram_bot_urls(config.api_base) == (
        "https://api.il7510n.dpdns.org/bot",
        "https://api.il7510n.dpdns.org/file/bot",
    )
    application = _application(config.api_base, _TOKEN, 30.0)
    assert application.bot.base_url == f"https://api.il7510n.dpdns.org/bot{_TOKEN}"
    assert application.bot.base_file_url == f"https://api.il7510n.dpdns.org/file/bot{_TOKEN}"


@pytest.mark.parametrize(
    "api_base",
    [
        "api.il7510n.dpdns.org",
        "ftp://api.il7510n.dpdns.org",
        "https://user:pass@api.il7510n.dpdns.org",
        "https://api.il7510n.dpdns.org?token=1",
        "https://api.il7510n.dpdns.org#fragment",
    ],
)
def test_api_base_rejects_anything_but_a_plain_http_url(api_base: str) -> None:
    """api_base 只接受无凭据的 HTTP(S) URL，避免把 token 拼进畸形地址。"""

    with pytest.raises(ValidationError, match=r"api_base 必须是无凭据的 HTTP\(S\) URL"):
        TelegramChannelConfig(api_base=api_base)


def test_settings_expose_api_base_for_editing() -> None:
    """设置界面的读写白名单必须带上 api_base，否则用户改不了线路。"""

    assert "api_base" in FIELDS
