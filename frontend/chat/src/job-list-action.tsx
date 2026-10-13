import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import styles from "./job-list-action.module.css";

export interface JobView {
  id: string;
  kind: string;
  label: string;
  status: "running" | "stopping" | "completed" | "failed" | "timeout" | "killed";
  detail: string;
  started_at: number;
  finished_at?: number | null;
}

export interface JobListActionProps {
  jobs: JobView[];
}

function isLive(job: JobView): boolean {
  return job.status === "running" || job.status === "stopping";
}

function dotClass(status: JobView["status"]): string {
  switch (status) {
    case "running":
      return styles.dotRunning;
    case "stopping":
    case "killed":
      return styles.dotWarning;
    case "completed":
      return styles.dotDone;
    case "failed":
    case "timeout":
      return styles.dotError;
    default:
      return styles.dotDone;
  }
}

function statusLabel(status: JobView["status"]): string {
  switch (status) {
    case "running":
      return "运行中";
    case "stopping":
      return "停止中";
    case "completed":
      return "已完成";
    case "killed":
      return "已终止";
    case "failed":
      return "失败";
    case "timeout":
      return "超时";
    default:
      return status;
  }
}

function formatDuration(elapsedMs: number): string {
  const total = Math.max(0, Math.floor(elapsedMs / 1000));
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  if (hours > 0) return `${hours}小时${minutes}分`;
  if (minutes > 0) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
}

function ordered(jobs: JobView[]): JobView[] {
  return [...jobs].sort((left, right) => {
    const liveLeft = isLive(left);
    if (liveLeft !== isLive(right)) return liveLeft ? -1 : 1;
    if (liveLeft) return left.started_at - right.started_at;
    const finished = (right.finished_at ?? right.started_at) - (left.finished_at ?? left.started_at);
    return finished !== 0 ? finished : left.started_at - right.started_at;
  });
}

export function JobListAction({ jobs }: JobListActionProps) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const rows = useMemo(() => ordered(jobs), [jobs]);
  const liveCount = useMemo(() => jobs.filter(isLive).length, [jobs]);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent): void => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
    };
  }, [open]);

  // 时钟仅在面板展开且存在活跃任务时跳动
  useEffect(() => {
    if (!open || liveCount === 0) return;
    setNow(Date.now());
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [open, liveCount]);

  useEffect(() => {
    if (jobs.length === 0 && open) setOpen(false);
  }, [jobs.length, open]);

  if (jobs.length === 0) return null;

  const countLabel = liveCount > 0 ? `${liveCount} 项进行中` : `${jobs.length} 项已结算`;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div ref={rootRef} className={styles.root} onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.trigger}
        aria-expanded={open}
        aria-label={countLabel}
        data-testid="job-list-trigger"
        onClick={() => {
          setNow(Date.now());
          setOpen((current) => !current);
        }}
      >
        {liveCount > 0 ? <span className={`${styles.dot} ${styles.dotOngoing} ${styles.triggerDot}`} /> : null}
        <span className={styles.count}>{countLabel}</span>
        <svg
          className={`${styles.chevron} ${open ? styles.triggerOpen : ""}`}
          width="12"
          height="12"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M4 6l4 4 4-4" />
        </svg>
      </button>
      {open ? (
        <ul className={styles.menu} aria-label="后台任务列表" data-testid="job-list-popover">
          {rows.map((job) => {
            const live = isLive(job);
            const elapsed = live ? now - job.started_at : (job.finished_at ?? job.started_at) - job.started_at;
            const duration = formatDuration(elapsed);
            const status = statusLabel(job.status);
            return (
              <li
                key={job.id}
                className={`${styles.row} ${live ? "" : styles.rowSettled}`}
                data-testid={`job-row-${job.id}`}
              >
                <span className={`${styles.dot} ${dotClass(job.status)} ${styles.rowDot}`} />
                <span className={styles.kind}>{job.kind}</span>
                <span className={styles.label} title={job.label}>
                  {job.label}
                </span>
                <span className={styles.status} title={job.detail || status}>
                  {job.detail || status}
                </span>
                <span className={styles.duration} title={duration}>
                  {duration}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
