import json
import time
from concurrent.futures import Future
from pathlib import Path

import pytest

from geekatplay_3d_layers.core.http import Http, HttpError
from geekatplay_3d_layers.core.jobs import JobManager
from geekatplay_3d_layers.core.library import Library, all_folders, normalize_folder, relocate_folder
from geekatplay_3d_layers.core.log import MemoryLogger
from geekatplay_3d_layers.core.providers.base import Configured, ModelResult, PollResult, Provider, ProviderContext, SubmitResult
from geekatplay_3d_layers.core.secrets import SecretStore, preview
from geekatplay_3d_layers.core.settings import DEFAULT_SETTINGS
from helpers import PNG_1PX, ScriptedTransport, bytes_response, fake_glb, route


class Immediate:
    """An executor that runs work at once (the result is applied on the next tick)."""

    def submit(self, fn, *args):
        f = Future()
        try:
            f.set_result(fn(*args))
        except BaseException as err:  # noqa: BLE001
            f.set_exception(err)
        return f

    def shutdown(self, wait=True):
        pass


class FakeProvider(Provider):
    id = "meshy"
    label = "Fake"
    can_cancel = True

    def __init__(self, polls):
        self.polls = list(polls)
        self.submitted = []
        self.cancelled = []

    def is_configured(self, ctx):
        return Configured(True)

    def submit(self, ctx, inp):
        self.submitted.append(inp)
        return SubmitResult("task-1", {"kind": "image-to-3d"})

    def poll(self, ctx, remote_id, meta=None):
        p = self.polls.pop(0)
        if isinstance(p, BaseException):
            raise p
        return p

    def resolve(self, ctx, remote_id, meta=None):
        return ModelResult("https://cdn/model.glb", thumbnail_url="https://cdn/thumb.png")

    def cancel(self, ctx, remote_id, meta=None):
        self.cancelled.append(remote_id)


def make(tmp_path: Path, polls, now=None):
    log = MemoryLogger()
    transport = ScriptedTransport([route("GET", "https://cdn/model.glb", bytes_response(fake_glb())), route("GET", "https://cdn/thumb.png", bytes_response(PNG_1PX))])
    http = Http(transport, log)
    library = Library(tmp_path, log)
    library.load()
    provider = FakeProvider(polls)
    clock = {"t": 1_000_000.0}
    ctx = ProviderContext(http=http, settings=DEFAULT_SETTINGS, secret=lambda k: "", log=log, now=lambda: clock["t"])
    jobs = JobManager(tmp_path, log, library, lambda _id: provider, lambda: ctx, now=now or (lambda: clock["t"]), executor=Immediate(), sleep=lambda s: None)
    jobs.load()
    return jobs, library, provider, clock


def test_library_is_compatible_with_the_photoshop_plugin(tmp_path):
    # An index written by the Photoshop plugin.
    (tmp_path / "library" / "lib_a").mkdir(parents=True)
    (tmp_path / "library" / "lib_a" / "model.glb").write_bytes(fake_glb())
    index = {"version": 1, "items": [{"id": "lib_a", "name": "Axe", "origin": "meshy", "modelFile": "lib_a/model.glb", "format": "glb", "sizeBytes": 64, "createdAt": 1, "importedAt": 2, "folder": "Props/Weapons"}, {"id": "lib_gone", "name": "Gone", "origin": "local", "modelFile": "lib_gone/model.glb", "format": "glb", "sizeBytes": 1, "createdAt": 1, "importedAt": 1}], "folders": ["Empty"]}
    (tmp_path / "library" / "index.json").write_text(json.dumps(index))
    lib = Library(tmp_path, MemoryLogger())
    lib.load()
    assert [i["id"] for i in lib.list()] == ["lib_a"]  # the item without a file is dropped
    assert lib.folders() == ["Empty", "Props", "Props/Weapons"]
    item = lib.add(name=" Chair ", origin="local", model=fake_glb(), thumbnail=PNG_1PX, folder="Props")
    assert item["modelFile"] == f"{item['id']}/model.glb" and item["thumbFile"] == f"{item['id']}/thumb.png" and item["name"] == "Chair"
    saved = json.loads((tmp_path / "library" / "index.json").read_text())
    assert saved["version"] == 1 and {i["id"] for i in saved["items"]} == {"lib_a", item["id"]} and saved["folders"] == ["Empty", "Props"]
    assert json.loads((tmp_path / "library" / item["id"] / "info.json").read_text())["name"] == "Chair"
    with pytest.raises(ValueError):
        lib.add(name="x", origin="local", model=PNG_1PX)


def test_library_picks_up_changes_made_by_the_other_plugin(tmp_path):
    lib = Library(tmp_path, MemoryLogger())
    lib.load()
    a = lib.add(name="A", origin="local", model=fake_glb())
    # The Photoshop plugin renames A while Krita is open.
    data = json.loads(lib.index_path.read_text())
    data["items"][0]["name"] = "Renamed in Photoshop"
    time.sleep(0.02)
    lib.index_path.write_text(json.dumps(data))
    import os

    os.utime(lib.index_path, (time.time() + 5, time.time() + 5))
    b = lib.add(name="B", origin="local", model=fake_glb())
    names = {i["id"]: i["name"] for i in lib.list()}
    assert names == {a["id"]: "Renamed in Photoshop", b["id"]: "B"}


def test_library_folders_move_rename_delete(tmp_path):
    lib = Library(tmp_path, MemoryLogger())
    lib.load()
    a = lib.add(name="A", origin="local", model=fake_glb())
    lib.create_folder("", "Props")
    lib.move([a["id"]], "Props/Small")
    assert lib.get(a["id"])["folder"] == "Props/Small"
    lib.rename_folder("Props", "Things")
    assert lib.get(a["id"])["folder"] == "Things/Small" and lib.folders() == ["Things", "Things/Small"]
    lib.delete_folder("Things")
    assert lib.get(a["id"])["folder"] == "Small"
    lib.remove_many([a["id"]])
    assert lib.list() == [] and "Small" in lib.folders()
    assert normalize_folder(" a//b\\c: ") == "a/b/c"
    items = [{"folder": "x/y"}]
    assert relocate_folder({"x", "x/y"}, items, "x", "z") == {"z", "z/y"} and items[0]["folder"] == "z/y"
    assert all_folders([], [{"folder": "q/r"}]) == ["q", "q/r"]


def test_job_runs_to_the_library(tmp_path):
    jobs, library, provider, clock = make(tmp_path, [PollResult("running", progress=40, message="Generating"), PollResult("succeeded", result=ModelResult("https://cdn/model.glb", thumbnail_url="https://cdn/thumb.png"))])
    job = jobs.start("meshy", PNG_1PX, 1, 1, False, "Chair")
    assert job["status"] == "submitting" and (tmp_path / "krita" / "jobs" / job["id"] / "source.png").exists()
    jobs.tick()  # applies the submission
    assert job["status"] == "running" and job["remoteId"] == "task-1"
    clock["t"] += 2000
    jobs.tick()  # starts the first poll
    jobs.tick()  # applies it
    assert job["progress"] == 40 and job["message"] == "Generating"
    clock["t"] += 2000
    jobs.tick()
    jobs.tick()
    assert job["status"] == "succeeded" and job["libraryId"]
    item = library.get(job["libraryId"])
    assert item["origin"] == "meshy" and item["remoteId"] == "task-1" and item["thumbFile"].endswith("thumb.png") and item["sourceFile"].endswith("source.png")
    assert not (tmp_path / "krita" / "jobs" / job["id"]).exists()
    assert json.loads((tmp_path / "krita" / "jobs.json").read_text())["jobs"][0]["status"] == "succeeded"


def test_transient_errors_retry_and_fatal_errors_fail(tmp_path):
    jobs, _lib, _p, clock = make(tmp_path, [HttpError("down", 503), HttpError("bad key", 401)])
    job = jobs.start("meshy", PNG_1PX, 1, 1, False, "Chair")
    jobs.tick()
    clock["t"] += 2000
    jobs.tick()
    jobs.tick()
    assert job["status"] == "running" and job["pollErrors"] == 1 and "retrying" in job["message"]
    clock["t"] += 10_000
    jobs.tick()
    jobs.tick()
    assert job["status"] == "failed" and job["error"] == "bad key" and job["meta"]["failedStage"] == "poll"


def test_rate_limit_waits_as_asked_and_resume_after_restart(tmp_path):
    jobs, _lib, _p, clock = make(tmp_path, [HttpError("slow down", 429, retry_after_ms=30_000)])
    job = jobs.start("meshy", PNG_1PX, 1, 1, False, "Chair")
    jobs.tick()
    clock["t"] += 2000
    jobs.tick()
    jobs.tick()
    assert job["status"] == "running" and job["nextPollAt"] == clock["t"] + 30_000 and not job.get("pollErrors")
    # Krita restarts: the job resumes polling.
    again, *_ = make(tmp_path, [])
    assert again.get(job["id"])["status"] == "running" and again.get(job["id"])["pollDelayMs"] == 2000


def test_cancel_and_retry(tmp_path):
    jobs, _lib, provider, clock = make(tmp_path, [])
    job = jobs.start("meshy", PNG_1PX, 1, 1, False, "Chair")
    jobs.tick()
    jobs.cancel(job["id"])
    jobs.tick()
    assert job["status"] == "cancelled" and provider.cancelled == ["task-1"]
    jobs.retry(job["id"])
    assert job["status"] == "submitting" and "remoteId" not in job
    jobs.tick()
    assert job["status"] == "running" and len(provider.submitted) == 2
    with pytest.raises(ValueError):
        jobs.dismiss(job["id"])


def test_secrets_share_the_photoshop_credentials_file(tmp_path):
    (tmp_path / "credentials.json").write_text(json.dumps({"_note": "x", "keys": {"meshy.apiKey": "msy_from_photoshop_1234"}}))
    store = SecretStore(tmp_path)
    assert store.get("meshy.apiKey") == "msy_from_photoshop_1234"
    store.set("tripo.apiKey", " tsk_abcdefgh5678 ")
    data = json.loads((tmp_path / "credentials.json").read_text())
    assert data["keys"] == {"meshy.apiKey": "msy_from_photoshop_1234", "tripo.apiKey": "tsk_abcdefgh5678"}
    store.set("meshy.apiKey", "")
    assert store.get("meshy.apiKey") == ""
    assert preview("msy_from_photoshop_1234") == "msy_…1234"
