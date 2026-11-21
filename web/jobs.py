"""Serial GPU job queue for the web wrapper.

Jobs run one at a time in a background thread:
  photo:     renders the prompt as typed (Python cleanup only, like the desktop app)
  reconcile: Prompt Builder Reconcile; the chosen LLM reconciles the dropdowns against the vision
             and the job returns the prompt + model + settings for the Final prompt box (no render)
  fill:      Fill dropdowns from my vision; the chosen LLM picks dropdown values (no render)
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Optional

import addons
import wan_library
from wan_profiles import record_photo_meta
from web.specs import finalize, turn_needs

APP_ID = "graphical_studio"
MAX_HISTORY = 200
LOG_LINES = 300

_STEP_RE = re.compile(r"(\d+)/(\d+)\s*\[")
_PHOTO_SAVED_RE = re.compile(r"\[(?:Photo|Asset)\s+[^\]]+\]\s+Saved\s+(\S+)")

ACTIVE_STATES = ("queued", "waiting_gpu", "running")
PUBLIC_FIELDS = (
    "id", "kind", "status", "message", "progress", "created", "started", "finished",
    "prompt", "effective_prompt", "notes", "settings", "outputs", "error", "result",
)


class JobQueue:
    def __init__(self, store_path: Path, root_dir: str) -> None:
        self.store_path = store_path
        self.root_dir = root_dir
        self._cond = threading.Condition()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._logs: dict[str, deque[str]] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._stopping = False
        self._load()
        self._thread = threading.Thread(target=self._run_loop, name="gs-job-runner", daemon=True)
        self._thread.start()

    # ---- persistence -------------------------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for job in data.get("jobs", []):
            if not isinstance(job, dict) or "id" not in job:
                continue
            if job.get("status") in ("waiting_gpu", "running") or (job.get("status") == "queued" and "plan" not in job):
                job.update(status="failed", error="Interrupted by a server restart.", finished=time.time())
            self._jobs[job["id"]] = job
            self._order.append(job["id"])
            self._logs[job["id"]] = deque(job.pop("log_tail", []), maxlen=LOG_LINES)

    def _save_locked(self) -> None:
        jobs = []
        for jid in self._order[-MAX_HISTORY:]:
            job = dict(self._jobs[jid])
            job["log_tail"] = list(self._logs.get(jid, ()))[-60:]
            jobs.append(job)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        os.replace(tmp, self.store_path)

    # ---- public API --------------------------------------------------------------------------

    def submit(self, kind: str, prepared: dict[str, Any], max_queued: int) -> dict[str, Any]:
        with self._cond:
            pending = sum(1 for j in self._jobs.values() if j["status"] in ACTIVE_STATES)
            if pending >= max_queued:
                raise OverflowError(f"Queue is full ({pending} jobs waiting).")
            jid = uuid.uuid4().hex[:12]
            job = {
                "id": jid, "kind": kind, "status": "queued", "message": "Queued", "progress": 0,
                "created": time.time(), "started": None, "finished": None,
                "prompt": prepared["prompt"], "effective_prompt": None,
                "notes": list(prepared["notes"]), "settings": prepared["settings"], "plan": prepared,
                "outputs": [], "error": None, "result": None, "cancel": False,
            }
            self._jobs[jid] = job
            self._order.append(jid)
            self._logs[jid] = deque(maxlen=LOG_LINES)
            self._trim_locked()
            self._save_locked()
            self._cond.notify_all()
            return self._public(job)

    def list(self, limit: int = 60) -> list[dict[str, Any]]:
        with self._cond:
            return [self._public(self._jobs[j]) for j in reversed(self._order[-limit:])]

    def get(self, jid: str, with_log: bool = False) -> Optional[dict[str, Any]]:
        with self._cond:
            job = self._jobs.get(jid)
            if not job:
                return None
            out = self._public(job)
            if with_log:
                out["log"] = list(self._logs.get(jid, ()))
            return out

    def cancel(self, jid: str) -> bool:
        with self._cond:
            job = self._jobs.get(jid)
            if not job or job["status"] not in ACTIVE_STATES:
                return False
            job["cancel"] = True
            if job["status"] == "queued":
                self._finish_locked(job, "cancelled", "Cancelled before it started.")
            proc = self._procs.get(jid)
            self._cond.notify_all()
        if proc is not None:
            _kill_group(proc)
        return True

    def stats(self) -> dict[str, Any]:
        with self._cond:
            counts: dict[str, int] = {}
            for j in self._jobs.values():
                counts[j["status"]] = counts.get(j["status"], 0) + 1
            return {"counts": counts}

    def shutdown(self) -> None:
        with self._cond:
            self._stopping = True
            procs = list(self._procs.values())
            self._cond.notify_all()
        for proc in procs:
            _kill_group(proc)
        self._thread.join(timeout=15)

    # ---- internals ---------------------------------------------------------------------------

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        out = {k: job.get(k) for k in PUBLIC_FIELDS}
        out["outputs"] = [p for p in job.get("outputs") or [] if os.path.isfile(p)]  # hide files deleted since
        return out

    def _trim_locked(self) -> None:
        while len(self._order) > MAX_HISTORY:
            old = self._order[0]
            if self._jobs[old]["status"] in ACTIVE_STATES:
                break
            self._order.pop(0)
            self._jobs.pop(old, None)
            self._logs.pop(old, None)

    def _finish_locked(self, job: dict[str, Any], status: str, message: str, error: Optional[str] = None) -> None:
        job.update(status=status, message=message, error=error, finished=time.time())
        if status == "done":
            job["progress"] = 100
        self._save_locked()

    def _note(self, job: dict[str, Any], message: str) -> None:
        with self._cond:
            if job["status"] in ACTIVE_STATES:  # the release note arrives after the job finished
                job["message"] = message
            self._logs[job["id"]].append(f"[GPU] {message}")

    def _next_job(self) -> Optional[dict[str, Any]]:
        with self._cond:
            while not self._stopping:
                for jid in self._order:
                    job = self._jobs[jid]
                    if job["status"] == "queued":
                        return job
                self._cond.wait(timeout=5.0)
        return None

    def _run_loop(self) -> None:
        while not self._stopping:
            job = self._next_job()
            if job is None:
                continue
            plan = job["plan"]
            first_needs = turn_needs(plan)  # the chosen LLM (Ollama) or the whole card
            if addons.REGISTRY.gpu_session_factory is not None:
                with self._cond:
                    job.update(status="waiting_gpu", message="Waiting for a GPU turn...")
                    self._save_locked()
            turn = addons.gpu_session(
                f"{job['kind']} {job['id']}", needs=first_needs, app_id=APP_ID,
                on_status=lambda msg, j=job: self._note(j, msg),
                is_cancelled=lambda j=job: bool(j["cancel"]) or self._stopping,
            )
            try:
                turn.acquire()
                self._run_in_turn(job, turn)
            except InterruptedError as exc:
                with self._cond:
                    self._finish_locked(job, "cancelled", str(exc))
            except Exception as exc:  # generation/prompt errors fail the job, never the runner
                with self._cond:
                    status = "cancelled" if job["cancel"] else "failed"
                    self._finish_locked(job, status, "Could not run on the GPU.", None if job["cancel"] else str(exc)[:400])
            finally:
                turn.release()

    def _run_in_turn(self, job: dict[str, Any], turn) -> None:
        plan = job["plan"]
        k = addons.llm_ui_strings()["result_model_key"]
        llm = plan.get(f"{k}_resolved") or plan.get("llm_resolved") or "the Python fallback"
        pp = addons.pair_provider()
        if plan["kind"] == "reconcile":
            self._note(job, f"{llm} is reconciling your dropdowns with your vision...")
        elif plan["kind"] == "fill":
            self._note(job, f"{llm} is filling the dropdowns from your vision...")
        elif pp and plan["kind"] == pp.kind:
            self._note(job, pp.turn_note(plan))
        fin = finalize(plan)
        with self._cond:
            job["notes"] = list(plan["notes"]) + fin["notes"]
            for n in fin["notes"]:
                self._logs[job["id"]].append(n)
        if plan["kind"] in ("reconcile", "fill"):
            with self._cond:
                job["effective_prompt"] = fin.get("prompt")
                job["result"] = {k: v for k, v in fin.items() if k != "notes"}
                self._finish_locked(job, "done", "Prompt reconciled; review and edit it, then Send."
                                    if plan["kind"] == "reconcile" else "Dropdowns filled; review them.")
            return
        with self._cond:
            job.update(effective_prompt=fin["effective_prompt"], cmd=fin["cmd"], output=fin["output"], cfg=fin["cfg"])
            meta = job["plan"].get("meta")
            if meta is not None:
                meta["effective_prompt"] = fin["effective_prompt"]
        turn.step("exclusive")
        self._execute(job)

    def _execute(self, job: dict[str, Any]) -> None:
        jid = job["id"]
        with self._cond:
            if job["cancel"]:
                self._finish_locked(job, "cancelled", "Cancelled.")
                return
            job.update(status="running", started=time.time(), message="Loading models...")
            self._save_locked()
        log = self._logs[jid]
        try:
            proc = subprocess.Popen(  # nosec B603 - argv list built from validated settings, no shell
                job["cmd"], cwd=self.root_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, start_new_session=True, env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except OSError as exc:
            with self._cond:
                self._finish_locked(job, "failed", "Could not start the generator.", str(exc))
            return
        with self._cond:
            self._procs[jid] = proc
        saved: list[str] = []
        buf = ""
        assert proc.stdout is not None
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch not in ("\r", "\n"):
                buf += ch
                continue
            line, buf = buf.strip(), ""
            if not line:
                continue
            m_step = _STEP_RE.search(line)
            m_saved = _PHOTO_SAVED_RE.search(line)
            with self._cond:
                if m_step:
                    cur, tot = int(m_step.group(1)), max(1, int(m_step.group(2)))
                    job["progress"] = min(99, int(cur * 100 / tot))
                    job["message"] = f"Sampling step {cur}/{tot}"
                    if line.endswith("|") or "it/s" in line or "s/it" in line:
                        continue
                if m_saved:
                    saved.append(m_saved.group(1))
                log.append(line)
        rc = proc.wait()
        with self._cond:
            self._procs.pop(jid, None)
            outputs = saved or ([job["output"]] if os.path.isfile(job["output"]) else [])
            job["outputs"] = [p for p in outputs if os.path.isfile(p)]
            if job["cancel"]:
                self._finish_locked(job, "cancelled", "Cancelled while generating.")
            elif rc == 0 and job["outputs"]:
                self._finish_locked(job, "done", f"Finished in {time.time() - job['started']:.0f}s")
            else:
                tail = next((ln for ln in reversed(log) if "Error" in ln or "error" in ln), f"exit code {rc}")
                self._finish_locked(job, "failed", "Generation failed.", tail[:400])
        if job["status"] == "done":
            self._record_outputs(job)

    def _record_outputs(self, job: dict[str, Any]) -> None:
        """Library row per output (the recipe for Import into Prompt Builder); photo_meta.json too,
        which the desktop app's Save Profile still reads."""
        plan, meta = job["plan"], job["plan"].get("meta")
        lib = plan.get("library") or {}
        for path in job["outputs"]:
            try:
                wan_library.record(
                    path, source=lib.get("source", "web"), prompt=lib.get("prompt") or plan["prompt"],
                    effective_prompt=job.get("effective_prompt") or "", variation=lib.get("variation", ""),
                    settings=job.get("cfg"), builder=lib.get("builder"), reference=lib.get("reference", ""),
                    parent=lib.get("parent", ""))
            except Exception as exc:  # a library hiccup must never fail a finished render
                self._logs[job["id"]].append(f"[Library] could not record {os.path.basename(path)}: {exc}")
            pp = addons.pair_provider()
            if meta and (job["kind"] == "photo" or (pp and job["kind"] == pp.kind)):
                record_photo_meta(path, meta)


def _kill_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(50):
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
