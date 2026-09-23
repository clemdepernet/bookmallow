"""Persist the job list to state.json atomically (spec §5, §6.8)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Iterable

from .jobs import Job

log = logging.getLogger(__name__)
VERSION = 1


class StateStore:
    def __init__(self, path: Path, max_jobs: int = 50):
        self.path = Path(path)
        self.max_jobs = max_jobs

    def load(self) -> list[Job]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            rows = data["jobs"]
            if not isinstance(rows, list):
                raise TypeError("jobs is not a list")
        except (ValueError, TypeError, KeyError) as exc:
            bad = self.path.with_name(self.path.name + ".bad")
            log.warning("state file unreadable (%s); moving it to %s", exc, bad)
            os.replace(self.path, bad)
            return []
        jobs: list[Job] = []
        for row in rows:
            try:
                jobs.append(Job.from_dict(row))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                log.warning("skipping unreadable job entry (%s): %r", exc, row)
        return jobs

    def trim(self, jobs: list[Job]) -> list[Job]:
        """Drop the oldest finished jobs so at most max_jobs remain; active jobs are never dropped."""
        excess = len(jobs) - self.max_jobs
        if excess <= 0:
            return list(jobs)
        drop: set[str] = set()
        for job in sorted((j for j in jobs if not j.is_active), key=lambda j: j.created_at):
            if excess <= 0:
                break
            drop.add(job.id)
            excess -= 1
        return [j for j in jobs if j.id not in drop]

    def save(self, jobs: Iterable[Job]) -> list[Job]:
        kept = self.trim(list(jobs))
        payload = {"version": VERSION, "jobs": [j.to_dict() for j in kept]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        return kept
