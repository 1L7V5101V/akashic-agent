"""OpenCode Go 对话请求必须携带 zen/go 网关要求的会话路由头。

网关缺头时以 400 MissingSessionID 拒绝 POST /chat/completions，而 GET /models
不需要该头；这里用内存传输锁住这两条 wire 事实，避免只靠真机验证。
"""

import json
from collections.abc import Mapping

import httpx
import pytest

from plugins.models.contract import (
    BoundModelDescriptor,
    CapabilitySources,
    DriverConnectionDescriptor,
    ModelCapabilities,
    ModelRequest,
)
from plugins.opencode_go import driver

_SESSION_HEADER = "x-opencode-session"


def _connection() -> DriverConnectionDescriptor:
    return DriverConnectionDescriptor(
        connection_id="connection-1",
        name="OpenCode Go",
        driver_id="opencode-go",
        endpoint="https://opencode.ai/zen/go/v1",
        auth_identity="api-key:test",
        config={},
    )


def _descriptor(model: str = "gpt-5.6-luna") -> BoundModelDescriptor:
    return BoundModelDescriptor(
        binding_id="binding-1",
        plugin_snapshot_id="snapshot-1",
        model_revision=1,
        model_id="model-1",
        connection_id="connection-1",
        driver_id="opencode-go",
        driver_contract_version="1",
        auth_identity="api-key:test",
        model=model,
        role="chat",
        reasoning_effort=None,
        capabilities=ModelCapabilities(),
        capability_sources=CapabilitySources(),
        capability_digest="0" * 64,
    )


def _request(
    messages: tuple[Mapping[str, str], ...] = ({"role": "user", "content": "hi"},)
):
    return ModelRequest(messages=messages)


class _Credential:
    """生成路径只按 scope 与 read() 使用凭证。"""

    connection_id = "connection-1"
    auth_identity = "api-key:test"

    async def read(self) -> Mapping[str, str]:
        return {"access_token": "test-token"}

    async def refresh(self, payload: Mapping[str, str]) -> None:
        raise AssertionError("生成路径不应刷新凭证")

    def exclusive(self):
        raise AssertionError("生成路径不应取凭证独占")


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """用内存传输替换 driver 的 httpx 客户端，保留 open/bind_chat 公开路径。"""

    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        if json.loads(request.content).get("stream"):
            chunk = {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]},
        )

    def client(connection, token=None) -> httpx.AsyncClient:
        _ = token
        return httpx.AsyncClient(
            base_url=connection.base_url,
            transport=httpx.MockTransport(handle),
            timeout=httpx.Timeout(5.0),
            follow_redirects=False,
        )

    monkeypatch.setattr(driver, "_client", client)
    return requests


@pytest.mark.asyncio
async def test_chat_request_carries_one_fallback_session_id_per_binding(
    seen: list[httpx.Request],
):
    """没有对话键的调用（标题、图像、摘要等）在同一边界实例里复用兜底会话 id。"""
    opened = await driver.definition().open(_connection(), _Credential())
    chat = opened.bind_chat(_descriptor(), {})

    assert (await chat.complete(_request())).content == "OK"
    assert (await chat.complete(_request())).content == "OK"

    deltas: list[dict[str, str]] = []

    async def on_delta(delta: dict[str, str]) -> None:
        deltas.append(delta)

    streamed = await chat.complete(
        ModelRequest(messages=_request().messages, on_delta=on_delta)
    )
    assert streamed.content == "OK"
    assert deltas == [{"content_delta": "OK"}]

    assert [request.url.path for request in seen] == ["/zen/go/v1/chat/completions"] * 3
    session_ids = {request.headers[_SESSION_HEADER] for request in seen}
    assert len(session_ids) == 1
    assert session_ids.pop()
    assert all(
        request.headers["authorization"] == "Bearer test-token" for request in seen
    )


@pytest.mark.asyncio
async def test_conversation_key_becomes_the_session_header(seen: list[httpx.Request]):
    """请求自带的对话键就是送出的会话头：同一对话跨 execution 都稳定，网关才能复用缓存。"""
    opened = await driver.definition().open(_connection(), _Credential())
    key = "conversation-1"
    deltas: list[dict[str, str]] = []

    for _ in range(2):
        chat = opened.bind_chat(_descriptor(), {})
        replied = await chat.complete(
            ModelRequest(messages=_request().messages, conversation_key=key)
        )
        assert replied.content == "OK"

    async def on_delta(delta: dict[str, str]) -> None:
        deltas.append(delta)

    streamed = await opened.bind_chat(_descriptor(), {}).complete(
        ModelRequest(
            messages=_request().messages, conversation_key=key, on_delta=on_delta
        )
    )

    assert streamed.content == "OK"
    assert deltas == [{"content_delta": "OK"}]
    assert [request.headers[_SESSION_HEADER] for request in seen] == [key] * 3


@pytest.mark.asyncio
async def test_different_conversations_get_different_session_headers(
    seen: list[httpx.Request],
):
    """不同对话不能被混成同一个缓存路由键。"""
    opened = await driver.definition().open(_connection(), _Credential())

    for key in ("conversation-1", "conversation-2"):
        replied = await opened.bind_chat(_descriptor(), {}).complete(
            ModelRequest(messages=_request().messages, conversation_key=key)
        )
        assert replied.content == "OK"

    assert [request.headers[_SESSION_HEADER] for request in seen] == [
        "conversation-1",
        "conversation-2",
    ]


@pytest.mark.asyncio
async def test_each_binding_without_conversation_key_uses_its_own_fallback_id(
    seen: list[httpx.Request],
):
    """没有对话键时不同绑定实例不共用兜底 id，避免把不同调用混成一个 provider 会话。"""
    opened = await driver.definition().open(_connection(), _Credential())

    first = await opened.bind_chat(_descriptor(), {}).complete(_request())
    second = await opened.bind_chat(_descriptor(), {}).complete(_request())

    assert first.content == second.content == "OK"
    assert seen[0].headers[_SESSION_HEADER] != seen[1].headers[_SESSION_HEADER]


@pytest.mark.asyncio
async def test_model_discovery_sends_no_session_header(
    seen: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
):
    """探测与发现走 GET /models，网关不要求会话头，driver 也不虚构一个。"""
    monkeypatch.setattr(driver, "_load_cli_catalog", lambda: _empty_catalog())
    discover = driver.definition().discover
    assert discover is not None

    assert await discover(_connection(), _Credential()) == ()
    assert [request.url.path for request in seen] == ["/zen/go/v1/models"]
    assert _SESSION_HEADER not in seen[0].headers


async def _empty_catalog() -> dict[str, Mapping[str, object]]:
    return {}


@pytest.mark.asyncio
async def test_http_client_names_the_agent_and_keeps_credentials_per_request():
    """连接客户端用自己的名字自称；凭据不进默认头，仍由每次物理尝试单独携带。"""
    connection = driver._connection_config(_connection())

    async with driver._client(connection) as anonymous:
        assert anonymous.headers["user-agent"] == "akashic-agent"
        assert "authorization" not in anonymous.headers

    async with driver._client(connection, "test-token") as authenticated:
        assert authenticated.headers["user-agent"] == "akashic-agent"
        assert authenticated.headers["authorization"] == "Bearer test-token"
