"""真实拉起包含 Jobs 插件与 WebChatChannel 的 Akashic 实例，测试全链路 session/jobs 推送。"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

import pytest
import websockets
from fastapi import FastAPI
import uvicorn

from plugins.jobs.board import JobBoard
from plugins.jobs.contract import JobOutcome, JobSnapshot, JobWatch
from plugins.jobs.plugin import Jobs, Config
from plugins.akashic_clients.web_chat import WebChatChannel
from plugins.akashic_clients.attachments import AttachmentStore


@pytest.mark.asyncio
async def test_real_akashic_jobs_webchat_streaming():
    """验证真实 WebChatChannel 在挂接 Jobs 插件后的 WebSocket session/jobs 推送。"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        upload_store = AttachmentStore(tmp_path / "uploads")
        
        # 1. 实例化真实的 WebChatChannel
        web_channel = WebChatChannel("akashic")
        web_channel.bind_attachment_store(upload_store)

        # 2. 模拟真实 Jobs 插件能力提供方
        board = JobBoard()
        web_channel.bind_job_notices(board)

        # 3. 构造挂载了 WebChatChannel 的真实 FastAPI 应用
        from plugins.akashic_clients.chat_api import create_chat_app
        from unittest.mock import MagicMock
        mock_catalog = MagicMock()
        mock_reader = MagicMock()
        mock_reader.session_id = "akashic:sess-real-test-123"
        mock_reader.head.return_value = -1
        mock_reader.read_tail.return_value = MagicMock(items=[], through_seq=-1, has_more=False, messages=[])
        mock_reader.read_page.return_value = MagicMock(items=[], through_seq=-1, has_more=False, messages=[])
        
        async def fake_follow(after_seq=-1):
            if False:
                yield None

        mock_reader.follow = fake_follow
        mock_catalog.reader.return_value = mock_reader
        
        async def fake_catalog_follow(prefix="", visibility="listed", poll_interval=60):
            if False:
                yield None
        mock_catalog.follow = fake_catalog_follow
        mock_catalog.sessions.return_value = MagicMock(items=[], total=0, next_cursor=None)
        
        async def fake_status(sess_id):
            if False:
                yield {}

        app = create_chat_app(
            workspace=tmp_path,
            channel=web_channel,
            messages=mock_catalog,
            reply_status=fake_status,
            attachment_store=upload_store,
        )

        # 4. 真实拉起 Uvicorn HTTP/WebSocket 服务器
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        while not server.started:
            await asyncio.sleep(0.01)

        # 获取实际监听的端口
        port = None
        for s in server.servers:
            for sock in s.sockets:
                port = sock.getsockname()[1]
                break
            if port:
                break
        assert port is not None, "未能获取动态端口"

        ws_url = f"ws://127.0.0.1:{port}/ws"
        session_id = "akashic:sess-real-test-123"

        # 5. 连接 WebSocket 并启动 session.follow
        async with websockets.connect(ws_url) as ws:
            async def recv_frame(target_type=None):
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = json.loads(raw)
                    if target_type is None or msg.get("type") == target_type:
                        return msg

            # 建立 session follow
            await ws.send(json.dumps({
                "type": "session.follow",
                "version": 2,
                "request_id": "req-1",
                "session_id": session_id,
                "after_seq": -1,
            }))

            # 接收握手帧
            resp1 = await recv_frame("session.following")
            assert resp1["type"] == "session.following"

            # 验证 baseline 快照（此时无任务）
            resp2 = await recv_frame("session/jobs")
            assert resp2["type"] == "session/jobs"
            assert resp2["session_id"] == session_id
            assert resp2["jobs"] == []

            # 6. 后端派发新任务
            started_at = int(time.time() * 1000)
            settle_fut = asyncio.Future()

            job = JobWatch(
                session_id=session_id,
                source="conversation",
                job_id="job-live-99",
                kind="shell",
                label="pytest run",
                collect_hint="查看测试输出",
                settled=lambda: settle_fut,
                started_at=started_at,
            )
            board.register(job)

            # 验证 WebSocket 收到运行中的全量快照推流
            resp3 = await recv_frame("session/jobs")
            assert resp3["type"] == "session/jobs"
            assert len(resp3["jobs"]) == 1
            live_job = resp3["jobs"][0]
            assert live_job["id"] == "job-live-99"
            assert live_job["kind"] == "shell"
            assert live_job["label"] == "pytest run"
            assert live_job["status"] == "running"
            assert live_job["finished_at"] is None

            # 7. 后端任务结算
            board.settle(job, JobOutcome(status="completed", detail="exit 0"))

            # 验证 WebSocket 收到完成状态推流
            resp4 = await recv_frame("session/jobs")
            assert resp4["type"] == "session/jobs"
            assert len(resp4["jobs"]) == 1
            settled_job = resp4["jobs"][0]
            assert settled_job["id"] == "job-live-99"
            assert settled_job["status"] == "completed"
            assert settled_job["detail"] == "exit 0"
            assert settled_job["finished_at"] is not None

        # 8. 优雅停止服务器
        server.should_exit = True
        server.force_exit = True
        await asyncio.wait_for(server_task, timeout=2.0)
