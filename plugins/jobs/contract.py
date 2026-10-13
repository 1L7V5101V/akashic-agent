"""后台任务完成通知的公共合同；生产方只登记等待入口，投递归 jobs 插件。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from agent.plugin_composition import ServiceKey

JobOutcomeStatus = Literal["completed", "failed", "timeout", "killed"]
JobSnapshotStatus = Literal["running", "stopping", "completed", "failed", "timeout", "killed"]


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    kind: str
    label: str
    status: JobSnapshotStatus
    detail: str
    started_at: int
    finished_at: int | None = None

    def to_wire(self) -> dict[str, object]:
        return {
            "id": self.job_id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True, slots=True)
class JobOutcome:
    status: JobOutcomeStatus
    detail: str


# settled 在任务结算时返回结果；返回 None 表示模型已收走结果或任务被显式停止，不再通知。
@dataclass(frozen=True, slots=True)
class JobWatch:
    session_id: str
    source: str
    job_id: str
    kind: str
    label: str
    collect_hint: str
    settled: Callable[[], Awaitable[JobOutcome | None]]
    started_at: int | None = None


JobsChangedListener = Callable[[str, tuple[JobSnapshot, ...]], None]


class JobNotices(Protocol):
    def watch(self, job: JobWatch) -> None: ...

    def origin_source(self, session_id: str, source: str) -> str:
        """当前唤醒可访问登记任务的原来源；其他会话和来源保持原样。"""
        ...

    def list_jobs(self, session_id: str) -> tuple[JobSnapshot, ...]:
        """返回指定会话当前可见的完整任务快照。"""
        ...

    def on_jobs_changed(self, listener: JobsChangedListener) -> Callable[[], None]:
        """订阅会话级任务快照变化。返回反注册函数。"""
        ...


JOB_NOTICES = ServiceKey[JobNotices]("jobs.notices.v1")
