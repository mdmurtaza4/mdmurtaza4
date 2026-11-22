"""Sequential job queue. One heavy job (transcription or render) runs at a time,
which is the main safeguard for a 16 GB RAM machine."""

from __future__ import annotations

import logging
import queue
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str
    project_id: str
    status: str = "queued"  # queued | running | done | failed
    stage: str = "Waiting"
    progress: float = 0.0
    result: dict | None = None
    error: str | None = None
    created: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class JobQueue:
    def __init__(self) -> None:
        self._q: queue.Queue[tuple[Job, Callable]] = queue.Queue()
        self.jobs: dict[str, Job] = {}
        self._worker = threading.Thread(target=self._run, daemon=True, name="elixir-worker")
        self._worker.start()

    def submit(self, kind: str, project_id: str, fn: Callable[[Callable[[str, float], None]], dict]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id)
        self.jobs[job.id] = job
        self._q.put((job, fn))
        return job

    def _run(self) -> None:
        while True:
            job, fn = self._q.get()
            job.status = "running"

            def progress(stage: str, pct: float, job: Job = job) -> None:
                job.stage, job.progress = stage, round(pct, 3)

            try:
                job.result = fn(progress)
                job.status, job.progress = "done", 1.0
            except Exception as exc:  # report every failure to the UI rather than crashing the worker
                log.error("job %s failed: %s\n%s", job.id, exc, traceback.format_exc())
                job.status, job.error = "failed", str(exc)
            finally:
                self._q.task_done()

    def wait_idle(self) -> None:
        self._q.join()
