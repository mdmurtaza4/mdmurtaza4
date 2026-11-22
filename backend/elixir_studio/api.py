"""Local HTTP API used by the Electron desktop app. Binds to 127.0.0.1 only."""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__, pipeline
from .edl import EDL, Word
from .hardware import detect
from .jobs import JobQueue

ROOT = Path(os.environ.get("ELIXIR_HOME", Path.cwd())).resolve()
PROJECTS = ROOT / "projects"
DB = ROOT / "studio.db"

app = FastAPI(title="ELiXIR AI Video Studio", version=__version__)
QUEUE = JobQueue()


def _db() -> sqlite3.Connection:
    PROJECTS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT, source TEXT, created TEXT)")
    return con


def _project_dir(pid: str) -> Path:
    with closing(_db()) as con:
        if not con.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
            raise HTTPException(404, "Project not found")
    return PROJECTS / pid


class NewProject(BaseModel):
    source: str
    name: str | None = None


class AnalyseRequest(BaseModel):
    model: str | None = None
    device: str | None = None
    language: str | None = None
    transcribe: bool = True


class RenderRequest(BaseModel):
    preset: str = "vertical"


class TranscriptEdit(BaseModel):
    words: list[Word]
    reviewed: bool = True


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/hardware")
def hardware() -> dict:
    return detect().to_dict()


@app.post("/projects")
def create_project(req: NewProject) -> dict:
    src = Path(req.source)
    if not src.is_file():
        raise HTTPException(400, f"File not found: {src}")
    name = req.name or src.stem
    pid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] + "-" + os.urandom(3).hex()
    with closing(_db()) as con, con:
        con.execute("INSERT INTO projects VALUES (?,?,?,?)",
                    (pid, name, str(src.resolve()), datetime.now(UTC).isoformat()))
    (PROJECTS / pid).mkdir(parents=True, exist_ok=True)
    return {"id": pid, "name": name, "source": str(src.resolve())}


@app.get("/projects")
def list_projects() -> list[dict]:
    with closing(_db()) as con:
        rows = con.execute("SELECT id, name, source, created FROM projects ORDER BY created DESC").fetchall()
    return [dict(zip(("id", "name", "source", "created"), r, strict=True)) for r in rows]


@app.get("/projects/{pid}")
def get_project(pid: str) -> dict:
    d = _project_dir(pid)
    edl_path = d / "project.json"
    return {"id": pid, "edl": EDL.load(edl_path).model_dump() if edl_path.exists() else None}


@app.post("/projects/{pid}/analyse")
def analyse(pid: str, req: AnalyseRequest) -> dict:
    d = _project_dir(pid)
    with closing(_db()) as con:
        source = Path(con.execute("SELECT source FROM projects WHERE id=?", (pid,)).fetchone()[0])

    def work(progress):
        edl = pipeline.analyse(d, source, req.model, req.device, req.language, req.transcribe, progress)
        return {"segments": len(edl.segments), "output_duration": edl.output_duration, "words": len(edl.words)}

    return QUEUE.submit("analyse", pid, work).__dict__


@app.put("/projects/{pid}/transcript")
def save_transcript(pid: str, req: TranscriptEdit) -> dict:
    """Teacher-corrected transcript (essential for Urdu/Kashmiri speech and student names)."""
    d = _project_dir(pid)
    edl = EDL.load(d / "project.json")
    edl.words, edl.transcript_reviewed = req.words, req.reviewed
    edl.save(d / "project.json")
    return {"words": len(edl.words), "reviewed": edl.transcript_reviewed}


@app.put("/projects/{pid}/segments")
def save_segments(pid: str, segments: list[dict]) -> dict:
    try:
        edl = pipeline.set_segments(_project_dir(pid), segments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"segments": len(edl.segments), "output_duration": edl.output_duration}


@app.post("/projects/{pid}/render")
def render(pid: str, req: RenderRequest) -> dict:
    d = _project_dir(pid)
    if not (d / "project.json").exists():
        raise HTTPException(409, "Analyse the project before rendering")

    def work(progress):
        out, report = pipeline.produce(d, req.preset, progress=progress)
        return {"output": str(out), "qa": report.to_dict()}

    return QUEUE.submit("render", pid, work).__dict__


@app.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    j = QUEUE.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j.__dict__
