"""Job model shared by the queue, the store and the API (spec §5)."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum


class Status(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    CONVERTING = "converting"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = frozenset({Status.QUEUED, Status.FETCHING, Status.CONVERTING})


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Job:
    id: str
    url: str
    video_id: str
    quality: str
    title: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    channel: str | None = None
    status: Status = Status.QUEUED
    progress: float = 0.0
    error: str | None = None
    error_code: str | None = None
    filename: str | None = None
    size_bytes: int | None = None
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    kind: str = "youtube"
    source: str | None = None
    source_id: str | None = None
    author: str | None = None
    language: str | None = None
    torrent_hash: str | None = None
    cover: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["status"] = Status(kwargs.get("status") or "queued")
        return cls(**kwargs)


def new_job(url: str, video_id: str, quality: str) -> Job:
    return Job(id=uuid.uuid4().hex[:8], url=url, video_id=video_id, quality=quality)


def new_book_job(source: str, source_id: str, title: str, author: str | None, language: str | None,
                 duration: int | None, cover: str | None, quality: str) -> Job:
    """A store acquisition job; `video_id` doubles as the de-duplication key `<source>:<source_id>`."""
    return Job(id=uuid.uuid4().hex[:8], url="", video_id=f"{source}:{source_id}", quality=quality, kind="book",
               source=source, source_id=source_id, title=title, author=author, language=language,
               duration=duration, cover=cover, thumbnail=cover)
