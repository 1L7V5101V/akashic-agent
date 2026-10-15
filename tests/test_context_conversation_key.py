"""对话键必须来自 Session 事实，否则 provider 侧缓存亲和无从谈起。

OpenCode Go 用 x-opencode-session 做路由与提示词缓存亲和（官方要求"每个对话
一直送同一个会话 id"），而 driver 只能从 ModelRequest 拿到对话身份；这里锁住
Context 组装请求时把快照的 Session 写进 conversation_key。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from plugins.context.api import Materials, material_data
from plugins.context.plugin import ContextBuilder
from plugins.ledger.contract import ContentPart, Input, Message
from plugins.models.contract import ModelRequest

_SESSION = "conversation"


class _Projection:
    """只实现 Context 需要的最少能力；不接续 opaque provider 状态。"""

    context_window: int | None = None
    max_tool_schemas: int | None = None

    def estimate(self, request: ModelRequest) -> int:
        return len(request.messages)

    def render(
        self,
        messages: Sequence[Message],
        *,
        after_seq: int,
        summary_reference: str | None = None,
        fresh: bool = False,
        current_reminder: str | None = None,
        current_reminder_input_id: str | None = None,
        current_context: str | None = None,
    ) -> ModelRequest:
        _ = (
            messages,
            after_seq,
            summary_reference,
            fresh,
            current_reminder,
            current_reminder_input_id,
            current_context,
        )
        return ModelRequest(messages=())


def _message(message_id: str, seq: int, text: str) -> Message:
    return Message(
        message_id=message_id,
        session_id=_SESSION,
        seq=seq,
        recorded_at=datetime(2026, 10, 14, tzinfo=UTC),
        author="user",
        source="conversation",
        body=Input(parts=(ContentPart(kind="text", value=text),)),
    )


def _build(snapshot: Sequence[Message]) -> ModelRequest:
    return ContextBuilder().build(
        snapshot,
        materials=material_data(Materials("system")),
        model=_Projection(),
        max_output_tokens=64,
    )


def test_build_carries_session_as_conversation_key():
    """组装出的请求带本次对话的 Session id，driver 才能按对话稳定发送会话头。"""
    request = _build((_message("m1", 0, "hi"), _message("m2", 1, "there")))

    assert request.conversation_key == _SESSION
    assert request.system_prompt == ""
    assert request.messages[0] == {"role": "system", "content": "system"}


def test_build_without_snapshot_does_not_invent_conversation_key():
    """没有历史事实的调用不虚构对话键，由 driver 用自己的兜底 id 满足网关要求。"""
    assert _build(()).conversation_key == ""
