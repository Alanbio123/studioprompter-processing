"""Trabalhos: uma pasta temporária por vídeo + estado em memória. Nada fica mais de 1 hora."""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

TTL_SECONDS = 60 * 60  # privacidade: no máximo 1 hora no servidor


@dataclass
class Stage:
    status: str = 'idle'  # idle | processing | done | failed
    progress: float = 0.0  # 0 a 1
    detail: str | None = None  # modo (limpeza) ou filtro+formato (vídeo final)


@dataclass
class JobState:
    job_id: str
    folder: Path
    created: float
    uploaded: bool = False
    clean: Stage = field(default_factory=Stage)
    render: Stage = field(default_factory=Stage)

    def public(self) -> dict:
        return {
            'uploaded': self.uploaded,
            'clean': {'status': self.clean.status, 'progress': round(self.clean.progress, 3),
                      'mode': self.clean.detail},
            'render': {'status': self.render.status, 'progress': round(self.render.progress, 3)},
            'simulated': False,
        }


class JobStore:
    def __init__(self, root: Path, ttl: float = TTL_SECONDS, clock=time.time):
        self.root = root
        self.ttl = ttl
        self.clock = clock
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()
        root.mkdir(parents=True, exist_ok=True)

    def get_or_create(self, job_id: str) -> JobState:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                folder = self.root / job_id
                folder.mkdir(parents=True, exist_ok=True)
                state = JobState(job_id=job_id, folder=folder, created=self.clock())
                self._jobs[job_id] = state
            return state

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def delete(self, job_id: str) -> None:
        with self._lock:
            state = self._jobs.pop(job_id, None)
        folder = state.folder if state else self.root / job_id
        shutil.rmtree(folder, ignore_errors=True)

    def expire(self) -> list[str]:
        """Apaga os trabalhos com mais de 1 hora (inclusive pastas órfãs após reinício)."""
        now = self.clock()
        with self._lock:
            old = [job_id for job_id, s in self._jobs.items() if now - s.created > self.ttl]
        for job_id in old:
            self.delete(job_id)
        known = set(self._jobs)
        for folder in self.root.iterdir():
            if folder.is_dir() and folder.name not in known and now - folder.stat().st_mtime > self.ttl:
                shutil.rmtree(folder, ignore_errors=True)
                old.append(folder.name)
        return old
