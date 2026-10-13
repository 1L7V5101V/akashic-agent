"""后台任务通知的进程内状态：一次结算只被一个回合领取。"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from .contract import JobOutcome, JobSnapshot, JobWatch, JobsChangedListener

_WAKE = "wake:"
_MAX_SETTLED_PER_SESSION = 50


@dataclass(slots=True, eq=False)
class Notice:
    job: JobWatch
    outcome: JobOutcome
    claimed_by: str | None = None

    # 通知只说明结算事实与读取方式；结果正文仍由生产方的读取工具交付。
    def text(self) -> str:
        job, outcome = self.job, self.outcome
        return (
            f"后台任务 {job.job_id}（{job.kind}：{job.label}）已结束 "
            f"[status: {outcome.status}，{outcome.detail}]。{job.collect_hint}\n"
            "这是后台执行结果通知，不是用户的新指令。"
        )


class JobBoard:
    """忙时由当前输入领取并在该输入的每一步重放；闲时由唤醒领取；并维护前端可见的任务状态。"""

    def __init__(self, max_consecutive_wakes: int | None = None) -> None:
        self._max_wakes = max_consecutive_wakes
        self._notices: list[Notice] = []
        self._wakes: dict[str, tuple[str | None, int]] = {}
        self._active_jobs: dict[str, JobWatch] = {}
        self._settled_jobs: dict[str, tuple[JobWatch, JobOutcome, int]] = {}
        self._listeners: list[JobsChangedListener] = []

    def on_jobs_changed(self, listener: JobsChangedListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self, session_id: str) -> None:
        if not self._listeners:
            return
        snapshot = self.list_jobs(session_id)
        for listener in tuple(self._listeners):
            try:
                listener(session_id, snapshot)
            except Exception:
                pass

    def register(self, job: JobWatch) -> None:
        if job.started_at is None:
            job = replace(job, started_at=int(time.time() * 1000))
        self._active_jobs[job.job_id] = job
        self._notify(job.session_id)

    def list_jobs(self, session_id: str) -> tuple[JobSnapshot, ...]:
        active = [
            JobSnapshot(
                job_id=job.job_id,
                kind=job.kind,
                label=job.label,
                status="running",
                detail="",
                started_at=job.started_at or int(time.time() * 1000),
                finished_at=None,
            )
            for job in self._active_jobs.values()
            if job.session_id == session_id
        ]
        settled = [
            JobSnapshot(
                job_id=job.job_id,
                kind=job.kind,
                label=job.label,
                status=outcome.status,
                detail=outcome.detail,
                started_at=job.started_at or finished_at,
                finished_at=finished_at,
            )
            for job, outcome, finished_at in self._settled_jobs.values()
            if job.session_id == session_id
        ]
        return tuple(active + settled)

    def settle(self, job: JobWatch, outcome: JobOutcome) -> Notice:
        # 继承在 register 时已固化的 started_at
        registered = self._active_jobs.pop(job.job_id, None)
        if registered is not None and registered.started_at is not None:
            job = replace(job, started_at=registered.started_at)
        elif job.started_at is None:
            job = replace(job, started_at=int(time.time() * 1000))

        notice = Notice(job, outcome)
        self._notices.append(notice)
        now_ms = int(time.time() * 1000)
        self._settled_jobs[job.job_id] = (job, outcome, now_ms)
        self._prune_settled(job.session_id)
        self._notify(job.session_id)
        return notice

    def _prune_settled(self, session_id: str) -> None:
        matching_keys = [
            job_id for job_id, (item_job, _, _) in self._settled_jobs.items()
            if item_job.session_id == session_id
        ]
        overflow = len(matching_keys) - _MAX_SETTLED_PER_SESSION
        if overflow > 0:
            for job_id in matching_keys[:overflow]:
                self._settled_jobs.pop(job_id, None)

    def pending(self, session_id: str) -> tuple[Notice, ...]:
        return tuple(notice for notice in self._notices if notice.job.session_id == session_id)

    def origin_source(self, session_id: str, source: str) -> str:
        """仅从本会话正在唤醒的登记记录取得原来源，不解析或猜测来源名。"""
        for notice in self._notices:
            if (notice.job.session_id == session_id
                    and source == "job:" + notice.job.job_id
                    and notice.claimed_by == _WAKE + notice.job.job_id):
                return notice.job.source
        return source

    # 同一输入的后续步骤看到同一组通知；新输入出现后，旧输入领取过的通知退出。
    def claim(self, session_id: str, source: str, input_id: str) -> tuple[Notice, ...]:
        visible: list[Notice] = []
        for notice in tuple(self._notices):
            if notice.job.session_id != session_id or notice.job.source != source:
                continue
            if notice.claimed_by is None:
                notice.claimed_by = input_id
            if notice.claimed_by == input_id:
                visible.append(notice)
            elif not notice.claimed_by.startswith(_WAKE):
                self._notices.remove(notice)
        return tuple(visible)

    # 在会话槽内决定是否唤醒：已被回合领取或连续唤醒预算耗尽时，留给下一次用户输入注入。
    def take_wake(self, notice: Notice, input_id: str | None) -> bool:
        if notice not in self._notices or notice.claimed_by is not None:
            return False
        session_id = notice.job.session_id
        last_input, count = self._wakes.get(session_id, (input_id, 0))
        if last_input != input_id:
            count = 0
        if self._max_wakes is not None and count >= self._max_wakes:
            return False
        self._wakes[session_id] = (input_id, count + 1)
        notice.claimed_by = _WAKE + notice.job.job_id
        return True

    def finish_wake(self, notice: Notice) -> None:
        if notice in self._notices:
            self._notices.remove(notice)

    # 唤醒失败时撤回领取，下一次用户输入仍能看到这条结算。
    def release_wake(self, notice: Notice) -> None:
        if notice in self._notices and notice.claimed_by == _WAKE + notice.job.job_id:
            notice.claimed_by = None
