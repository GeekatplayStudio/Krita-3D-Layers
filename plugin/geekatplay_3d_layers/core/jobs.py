"""
The generation queue: submit → poll → download → library (a port of the Photoshop
plugin's src/host/services/jobs.ts, same timings and rules).

Threads: network calls run on a worker pool; job state only changes on the thread that
calls `tick()` (Krita's UI thread, from a QTimer), so the UI never sees a half-updated job.

Jobs persist in <data>/krita/jobs.json, so closing Krita never loses a running generation:
on load, active jobs resume polling. Polling starts every 2 s and backs off ×1.5 up to
15 s while nothing changes; transient errors (network, 5xx) are retried with longer waits,
other 4xx fail the job immediately. A rate limit (429) waits as long as the service asks
and does not count as an error. The image that was sent stays in krita/jobs/<id>/source.png
until the job finishes, so a failed submission can be retried.
"""
from __future__ import annotations

import shutil
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .http import HttpError
from .library import Library, import_model_result
from .providers.base import ModelResult, Provider, ProviderContext, SubmitInput
from .store import new_id, read_json, write_bytes, write_json

ACTIVE = ("queued", "submitting", "running", "downloading")
MIN_DELAY = 2000
MAX_DELAY = 15_000
MAX_POLL_ERRORS = 6
MAX_CONCURRENT_POLLS = 3
KEEP_FINISHED = 100
SUBMIT_ATTEMPTS = 4
MAX_RATE_LIMIT_WAIT = 5 * 60_000


def is_transient(err: BaseException) -> bool:
    """Worth retrying: network failures, timeouts, 408/429/5xx."""
    if isinstance(err, HttpError):
        return err.status in (408, 429) or err.status >= 500
    return True


def is_rate_limit(err: BaseException) -> bool:
    return isinstance(err, HttpError) and err.status == 429


def is_active(job: Dict[str, Any]) -> bool:
    return job.get("status") in ACTIVE


class JobManager:
    def __init__(
        self,
        root: Path,
        log: Any,
        library: Library,
        provider: Callable[[str], Provider],
        context: Callable[[], ProviderContext],
        now: Callable[[], float] = lambda: int(time.time() * 1000),
        executor: Optional[Executor] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.file = root / "krita" / "jobs.json"
        self.dir = root / "krita" / "jobs"
        self.log = log
        self.library = library
        self.provider = provider
        self.context = context
        self.now = now
        self.executor = executor or ThreadPoolExecutor(max_workers=4, thread_name_prefix="g3d-job")
        self.sleep = sleep
        self.jobs: List[Dict[str, Any]] = []
        self.busy: set = set()
        self._pending: List[Tuple[Future, Callable[[Future], None]]] = []
        self._dirty = False
        self.listeners: List[Callable[[], None]] = []
        #: Messages posted from worker threads ("Saving to library"), applied in tick().
        self._messages: Dict[str, str] = {}

    # ------------------------------------------------------------- state

    def load(self) -> None:
        data = read_json(self.file)
        self.jobs = [j for j in (data.get("jobs") if isinstance(data, dict) else []) or [] if isinstance(j, dict) and j.get("id")]
        for job in self.jobs:
            if not is_active(job):
                continue
            if not job.get("remoteId"):
                # Krita closed while uploading: we don't know whether the service got it.
                self._patch(job, status="failed", error="Interrupted while submitting. Retry to send it again.", meta={**(job.get("meta") or {}), "failedStage": "submit"})
            else:
                self._patch(job, status="running" if job["status"] == "downloading" else job["status"], nextPollAt=self.now(), pollDelayMs=MIN_DELAY, pollErrors=0)
        self.flush()

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self.jobs, key=lambda j: -(j.get("createdAt") or 0))

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return next((j for j in self.jobs if j["id"] == job_id), None)

    def has_active(self) -> bool:
        return any(is_active(j) for j in self.jobs) or bool(self._pending)

    def source_image(self, job_id: str) -> Optional[bytes]:
        try:
            return (self.dir / job_id / "source.png").read_bytes()
        except OSError:
            return None

    # --------------------------------------------------------- lifecycle

    def start(self, provider_id: str, image: bytes, width: int, height: int, has_alpha: bool, name: str, source_preview: Optional[str] = None, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        provider = self.provider(provider_id)
        configured = provider.is_configured(self.context())
        if not configured.configured:
            raise ValueError(configured.hint or f"{provider.label} is not set up yet.")
        now = self.now()
        job: Dict[str, Any] = {
            "id": new_id("job"),
            "providerId": provider_id,
            "name": name,
            "status": "queued",
            "progress": 0,
            "message": "Preparing",
            "createdAt": now,
            "updatedAt": now,
            "meta": {"input": {"width": width, "height": height, "hasAlpha": has_alpha}},
        }
        if source_preview:
            job["sourcePreview"] = source_preview
        if source:
            job["source"] = source
        write_bytes(self.dir / job["id"] / "source.png", image)
        self.jobs.append(job)
        self._trim()
        self._changed()
        self._submit(job)
        return job

    def _run(self, fn: Callable[[], Any], done: Callable[[Future], None]) -> None:
        self._pending.append((self.executor.submit(fn), done))

    def _submit(self, job: Dict[str, Any]) -> None:
        if job["id"] in self.busy:
            return
        provider = self.provider(job["providerId"])
        image = self.source_image(job["id"])
        if image is None:
            self._fail(job, FileNotFoundError("The image for this job is no longer available. Send the layer again."), "submit")
            return
        inp = (job.get("meta") or {}).get("input") or {}
        self.busy.add(job["id"])
        self._patch(job, status="submitting", message=f"Sending to {provider.label}", error=None, progress=0)
        self.log.info(f"Job {job['id']}: submitting \"{job['name']}\" to {provider.label} ({len(image)} bytes)")
        submit_input = SubmitInput(image=image, width=int(inp.get("width") or 0), height=int(inp.get("height") or 0), has_alpha=bool(inp.get("hasAlpha")), name=job["name"])
        ctx = self.context()
        job_id = job["id"]

        def work():
            return self._submit_with_retry(job_id, provider, ctx, submit_input)

        def done(f: Future) -> None:
            self.busy.discard(job_id)
            current = self.get(job_id)
            if not current:
                return
            err = f.exception()
            if err:
                self._fail(current, err, "submit")
                return
            res = f.result()
            meta = {**(current.get("meta") or {}), **(res.meta or {})}
            meta.pop("failedStage", None)
            self._patch(current, remoteId=res.remote_id, status="running", message=f"Submitted to {provider.label}", meta=meta, nextPollAt=self.now() + MIN_DELAY, pollDelayMs=MIN_DELAY, pollErrors=0)
            self.log.info(f"Job {job_id}: {provider.label} task {res.remote_id}")

        self._run(work, done)

    def _submit_with_retry(self, job_id: str, provider: Provider, ctx: ProviderContext, inp: SubmitInput):
        """Runs on a worker: submits, waiting and retrying when the service answers 429."""
        attempt = 1
        while True:
            try:
                return provider.submit(ctx, inp)
            except HttpError as err:
                if not is_rate_limit(err) or attempt >= SUBMIT_ATTEMPTS:
                    raise
                wait = min(MAX_RATE_LIMIT_WAIT, max(5000, err.retry_after_ms if err.retry_after_ms is not None else 15_000 * attempt))
                self.log.warn(f"Job {job_id}: {provider.label} rate limit on submit (attempt {attempt}/{SUBMIT_ATTEMPTS}); retrying in {int(wait)} ms", str(err))
                self._messages[job_id] = f"{provider.label} is busy; trying again in {round(wait / 1000)} s"
                self.sleep(wait / 1000)
                attempt += 1

    def tick(self) -> None:
        """Applies finished work and starts the polls that are due. Call from the UI thread."""
        finished = [p for p in self._pending if p[0].done()]
        self._pending = [p for p in self._pending if not p[0].done()]
        for future, done in finished:
            try:
                done(future)
            except Exception as err:  # noqa: BLE001 - one broken job must not stop the queue
                self.log.error("Job update failed", err)
        for job_id, message in list(self._messages.items()):
            job = self.get(job_id)
            self._messages.pop(job_id, None)
            if job and is_active(job) and job.get("message") != message:
                self._patch(job, message=message)
        now = self.now()
        due = [j for j in self.jobs if j.get("status") in ("running", "queued") and j.get("remoteId") and j["id"] not in self.busy and (j.get("nextPollAt") or 0) <= now]
        for job in due[: max(0, MAX_CONCURRENT_POLLS - len(self.busy))]:
            self._poll(job)
        if self._dirty:
            self.flush()

    def _poll(self, job: Dict[str, Any]) -> None:
        provider = self.provider(job["providerId"])
        ctx = self.context()
        job_id, remote_id, meta, name = job["id"], job["remoteId"], dict(job.get("meta") or {}), job["name"]
        source = self.source_image(job_id)
        self.busy.add(job_id)

        def work():
            res = provider.poll(ctx, remote_id, meta)
            item = None
            if res.state == "succeeded" and res.result:
                # Download straight away, on this worker: the links are signed and expire.
                self._messages[job_id] = "Downloading model"
                try:
                    item = import_model_result(ctx.http, self.library, self.log, res.result, name=name, origin=provider.id, remote_id=remote_id, source=source, on_progress=lambda m: self._messages.__setitem__(job_id, m))
                except Exception as err:  # noqa: BLE001
                    return res, None, err
            return res, item, None

        def done(f: Future) -> None:
            self.busy.discard(job_id)
            current = self.get(job_id)
            if not current or not is_active(current):
                return
            err = f.exception()
            if err:
                self._poll_error(current, provider, err)
                return
            res, item, download_err = f.result()
            new_meta = {**(current.get("meta") or {}), **(res.meta or {})}
            if res.state == "succeeded" and res.result:
                if download_err:
                    self._patch(current, meta=new_meta)
                    self._fail(current, download_err, "download")
                else:
                    self._finished(current, item, new_meta)
                return
            if res.state == "failed":
                self._fail(current, RuntimeError(res.error or f"{provider.label} reported a failure."), "remote")
                return
            if res.state == "cancelled":
                self._patch(current, status="cancelled", message=res.error or "Cancelled", meta=new_meta)
                return
            progress = res.progress if res.progress is not None else current.get("progress", 0)
            advanced = progress != current.get("progress") or res.message != current.get("message")
            delay = MIN_DELAY if advanced else min(MAX_DELAY, round((current.get("pollDelayMs") or MIN_DELAY) * 1.5))
            self._patch(current, status=res.state, progress=progress, message=res.message, meta=new_meta, pollErrors=0, pollDelayMs=delay, nextPollAt=self.now() + delay)

        self._run(work, done)

    def _poll_error(self, job: Dict[str, Any], provider: Provider, err: BaseException) -> None:
        if is_rate_limit(err):
            delay = min(MAX_RATE_LIMIT_WAIT, max(getattr(err, "retry_after_ms", None) or 0, (job.get("pollDelayMs") or MIN_DELAY) * 2))
            self.log.warn(f"Job {job['id']}: {provider.label} rate limit while polling; next check in {int(delay)} ms", str(err))
            self._patch(job, pollDelayMs=delay, nextPollAt=self.now() + delay, message=f"{provider.label} asked to slow down; checking again in {round(delay / 1000)} s")
            return
        errors = (job.get("pollErrors") or 0) + 1
        if not is_transient(err) or errors >= MAX_POLL_ERRORS:
            self._fail(job, err, "poll")
            return
        delay = min(60_000, (job.get("pollDelayMs") or MIN_DELAY) * 2)
        self.log.warn(f"Job {job['id']}: poll error {errors}/{MAX_POLL_ERRORS}, retrying in {delay} ms", str(err))
        self._patch(job, pollErrors=errors, pollDelayMs=delay, nextPollAt=self.now() + delay, message=f"Connection problem, retrying ({errors}/{MAX_POLL_ERRORS})")

    def _finished(self, job: Dict[str, Any], item: Dict[str, Any], meta: Dict[str, Any]) -> None:
        self._patch(job, status="succeeded", progress=100, message="Ready in library", libraryId=item["id"], error=None, meta=meta)
        shutil.rmtree(self.dir / job["id"], ignore_errors=True)
        self.log.info(f"Job {job['id']}: done → library {item['id']}")

    def _fail(self, job: Dict[str, Any], err: BaseException, stage: str) -> None:
        message = str(err) or type(err).__name__
        self.log.error(f"Job {job['id']} failed during {stage}", message)
        self._patch(job, status="failed", error=message, message=None, meta={**(job.get("meta") or {}), "failedStage": stage})

    # ------------------------------------------------------------ actions

    def cancel(self, job_id: str) -> None:
        """Stops tracking a job, and cancels it at the service when the service can."""
        job = self._must(job_id)
        if not is_active(job):
            return
        provider = self.provider(job["providerId"])
        remote_id = job.get("remoteId")
        if remote_id and provider.can_cancel:
            ctx, meta = self.context(), dict(job.get("meta") or {})

            def work():
                provider.cancel(ctx, remote_id, meta)

            def done(f: Future) -> None:
                err = f.exception()
                current = self.get(job_id)
                if current and err:
                    self._patch(current, message=f"Stopped here; the service said: {err}")

            self._run(work, done)
        message = "Cancelled" if not remote_id or provider.can_cancel else f"{provider.label} has no cancel API; the task may still finish there."
        self._patch(job, status="cancelled", message=message)

    def retry(self, job_id: str) -> None:
        job = self._must(job_id)
        if is_active(job):
            return
        stage = (job.get("meta") or {}).get("failedStage")
        provider = self.provider(job["providerId"])
        if job.get("remoteId") and stage in ("download", "poll"):
            # The service finished (or we lost contact): look again and download.
            self._patch(job, status="running", error=None, message="Checking again", nextPollAt=self.now(), pollDelayMs=MIN_DELAY, pollErrors=0)
            if stage == "download":
                ctx, remote_id, meta, job_id_ = self.context(), job["remoteId"], dict(job.get("meta") or {}), job["id"]
                source = self.source_image(job_id_)
                self.busy.add(job_id_)

                def work():
                    result: ModelResult = provider.resolve(ctx, remote_id, meta)
                    return import_model_result(ctx.http, self.library, self.log, result, name=job["name"], origin=provider.id, remote_id=remote_id, source=source)

                def done(f: Future) -> None:
                    self.busy.discard(job_id_)
                    current = self.get(job_id_)
                    if not current:
                        return
                    err = f.exception()
                    if err:
                        self._fail(current, err, "download")
                    else:
                        self._finished(current, f.result(), current.get("meta") or {})

                self._run(work, done)
            return
        self._patch(job, remoteId=None, status="queued", error=None, progress=0, message="Retrying")
        self._submit(job)

    def dismiss(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        if is_active(job):
            raise ValueError("Cancel the job before removing it.")
        self.jobs = [j for j in self.jobs if j["id"] != job_id]
        shutil.rmtree(self.dir / job_id, ignore_errors=True)
        self._changed()

    # ----------------------------------------------------------- plumbing

    def _must(self, job_id: str) -> Dict[str, Any]:
        job = self.get(job_id)
        if not job:
            raise KeyError("That job no longer exists.")
        return job

    def _patch(self, job: Dict[str, Any], **fields: Any) -> None:
        for k, v in fields.items():
            if v is None:
                job.pop(k, None)
            else:
                job[k] = v
        job["updatedAt"] = self.now()
        self._changed()

    def _trim(self) -> None:
        finished = sorted((j for j in self.jobs if not is_active(j)), key=lambda j: -(j.get("createdAt") or 0))
        drop = {j["id"] for j in finished[KEEP_FINISHED:]}
        if drop:
            self.jobs = [j for j in self.jobs if j["id"] not in drop]

    def _changed(self) -> None:
        self._dirty = True
        for fn in list(self.listeners):
            try:
                fn()
            except Exception as err:  # noqa: BLE001
                self.log.error("Job listener failed", err)

    def flush(self) -> None:
        self._dirty = False
        try:
            write_json(self.file, {"jobs": self.jobs})
        except OSError as err:
            self.log.error("Could not save jobs.json", err)

    def shutdown(self) -> None:
        self.flush()
        self.executor.shutdown(wait=False)
