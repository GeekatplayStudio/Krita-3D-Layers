"""
Tripo provider (API v3): ports of the Tripo cases in the Photoshop plugin's
src/host/providers/providers.test.ts and latest-api.test.ts, plus resolve and error paths.
"""
from __future__ import annotations

import re

import pytest

from geekatplay_3d_layers.core.http import HttpError
from geekatplay_3d_layers.core.providers import base
from geekatplay_3d_layers.core.providers.tripo import TRIPO_MAX_UPLOAD_BYTES, TripoProvider, build_image_to_model_body, tripo_face_limit_range
from geekatplay_3d_layers.core.settings import DEFAULT_SETTINGS
from helpers import PNG_1PX, ScriptedTransport, context, json_response, parse_multipart, route

BASE = "https://openapi.tripo3d.ai/v3"
SECRETS = {"tripo.apiKey": "tsk_abcdefghijklmnop"}
INPUT = base.SubmitInput(image=PNG_1PX, width=1, height=1, has_alpha=True, name="Chair")
tripo = TripoProvider()


def tripo_settings(**patch):
    return {**DEFAULT_SETTINGS["tripo"], **patch}


def answers(*replies):
    """A reply function that answers with each body in turn (wrapped in Tripo's envelope)."""
    it = iter(replies)
    return lambda call: json_response({"code": 0, "data": next(it)})


def answers_raw(*replies):
    """A reply function that answers with each body in turn, as is."""
    it = iter(replies)
    return lambda call: json_response(next(it))


# ---------------------------------------------------------------- request bodies


def test_body_omits_options_the_chosen_model_does_not_accept():
    assert build_image_to_model_body(DEFAULT_SETTINGS["tripo"], "file_1") == {
        "input": "file_1",
        "model": "v3.1-20260211",
        "texture": True,
        "pbr": True,
        "orientation": "default",
        "auto_size": False,
        "texture_quality": "standard",
        "geometry_quality": "standard",
    }
    p1 = build_image_to_model_body(tripo_settings(model="P1-20260311", smartLowPoly=True), "f")
    for field in ("geometry_quality", "smart_low_poly", "auto_size"):
        assert field not in p1
    v25 = build_image_to_model_body(tripo_settings(model="v2.5-20250123", texture=False, pbr=False, faceLimit=20000), "f")
    assert v25["texture"] is False and v25["pbr"] is False and v25["face_limit"] == 20000
    assert "texture_quality" not in v25 and "geometry_quality" not in v25
    # PBR needs a texture, so it turns texturing on.
    assert build_image_to_model_body(tripo_settings(texture=False, pbr=True), "f")["texture"] is True


def test_body_sends_the_v35_texture_model_with_delight_and_fast_quality_only_with_it():
    t = DEFAULT_SETTINGS["tripo"]
    assert "texture_version" not in build_image_to_model_body(t, "tok")
    v35 = build_image_to_model_body(tripo_settings(textureVersion="v3.5-20260815", delight=False), "tok")
    assert v35["texture_version"] == "v3.5-20260815" and v35["delight"] is False
    assert "delight" not in build_image_to_model_body(tripo_settings(textureVersion="v3.0-20250812"), "tok")
    fast = build_image_to_model_body(tripo_settings(textureQuality="fast"), "tok")
    assert fast["texture_quality"] == "fast" and fast["texture_version"] == "v3.5-20260815" and fast["delight"] is True
    # Untextured models get none of the texture fields.
    bare = build_image_to_model_body(tripo_settings(texture=False, pbr=False, textureVersion="v3.5-20260815"), "tok")
    for field in ("texture_quality", "texture_version", "delight"):
        assert field not in bare


def test_body_keeps_v3_only_fields_off_v25_and_the_p_series():
    v25 = build_image_to_model_body(tripo_settings(model="v2.5-20250123", autoSize=True, smartLowPoly=True), "tok")
    for field in ("auto_size", "geometry_quality", "smart_low_poly"):
        assert field not in v25
    p2 = build_image_to_model_body(tripo_settings(model="P2-20260801", textureVersion="v3.5-20260815", autoSize=True, textureQuality="fast"), "tok")
    for field in ("auto_size", "geometry_quality", "texture_version", "delight"):
        assert field not in p2
    v3 = build_image_to_model_body(tripo_settings(autoSize=True, smartLowPoly=True, geometryQuality="detailed"), "tok")
    assert v3["auto_size"] is True and v3["geometry_quality"] == "detailed" and v3["smart_low_poly"] is True


def test_face_limit_is_clamped_to_each_models_documented_range():
    assert tripo_face_limit_range("P2-20260801", geometry_quality="standard", smart_low_poly=False) == (50, 50_000)
    assert tripo_face_limit_range("v3.0-20250812", geometry_quality="detailed", smart_low_poly=False) == (1, 2_000_000)
    assert tripo_face_limit_range("v4.0-20270101", geometry_quality="standard", smart_low_poly=False) is None
    assert build_image_to_model_body(tripo_settings(model="P1-20260311", faceLimit=100_000), "tok")["face_limit"] == 20_000
    assert build_image_to_model_body(tripo_settings(faceLimit=1_800_000), "tok")["face_limit"] == 1_500_000
    assert build_image_to_model_body(tripo_settings(faceLimit=1_800_000, geometryQuality="detailed"), "tok")["face_limit"] == 1_800_000
    assert build_image_to_model_body(tripo_settings(faceLimit=200, smartLowPoly=True), "tok")["face_limit"] == 500
    assert build_image_to_model_body(tripo_settings(model="v2.5-20250123", faceLimit=900_000, smartLowPoly=True), "tok")["face_limit"] == 500_000
    assert build_image_to_model_body(tripo_settings(model="v4.0-20270101", faceLimit=2_000_000), "tok")["face_limit"] == 2_000_000


# ---------------------------------------------------------------- submit


def test_submit_uploads_the_image_then_creates_the_task():
    t = ScriptedTransport(
        [
            route("POST", f"{BASE}/files", json_response({"code": 0, "data": {"file_token": "file_abc"}})),
            route("POST", f"{BASE}/generation/image-to-model", json_response({"code": 0, "data": {"task_id": "tt1"}})),
        ]
    )
    res = tripo.submit(context(t, {}, SECRETS), INPUT)
    assert res == base.SubmitResult("tt1", {"model": "v3.1-20260211"})
    upload, create = t.calls
    assert upload.headers["content-type"].startswith("multipart/form-data; boundary=")
    form = parse_multipart(upload.body or b"", upload.headers["content-type"])
    assert form["files"]["file"]["filename"] == "image.png" and form["files"]["file"]["bytes"] == PNG_1PX
    assert b"Content-Type: image/png\r\n" in (upload.body or b"")
    assert create.json() == build_image_to_model_body(DEFAULT_SETTINGS["tripo"], "file_abc")
    assert create.headers["content-type"] == "application/json"
    for call in t.calls:
        assert call.headers["authorization"] == "Bearer tsk_abcdefghijklmnop"


def test_submit_accepts_other_token_names_and_needs_ids():
    t = ScriptedTransport(
        [
            route("POST", f"{BASE}/files", answers({"image_token": "img_1"}, {"token": "tok_2"}, {})),
            route("POST", f"{BASE}/generation/image-to-model", answers({"id": "tt2"}, {})),
        ]
    )
    ctx = context(t, {"tripo": {"model": "P1-20260311"}}, SECRETS)
    assert tripo.submit(ctx, INPUT) == base.SubmitResult("tt2", {"model": "P1-20260311"})
    assert t.calls[1].json()["input"] == "img_1"
    with pytest.raises(RuntimeError, match=r"^Tripo did not return a task id\.$"):
        tripo.submit(ctx, INPUT)
    assert t.calls[3].json()["input"] == "tok_2"
    with pytest.raises(RuntimeError, match=r"^Tripo upload did not return a file token\.$"):
        tripo.submit(ctx, INPUT)


def test_submit_surfaces_tripo_error_envelopes():
    t = ScriptedTransport([route("POST", f"{BASE}/files", json_response({"code": 2010, "message": "Insufficient credits", "suggestion": "Top up"}))])
    with pytest.raises(RuntimeError) as err:
        tripo.submit(context(t, {}, SECRETS), INPUT)
    assert str(err.value) == "Tripo upload failed: Insufficient credits (Top up) [code 2010]"

    t = ScriptedTransport(
        [
            route("POST", f"{BASE}/files", json_response({"code": 0, "data": {"file_token": "f"}})),
            route("POST", f"{BASE}/generation/image-to-model", answers_raw({"code": 1004, "msg": "Bad face_limit", "request_id": "req-1"}, {"code": 2000})),
        ]
    )
    ctx = context(t, {}, SECRETS)
    with pytest.raises(RuntimeError) as err:
        tripo.submit(ctx, INPUT)
    assert str(err.value) == "Tripo task creation failed: Bad face_limit [code 1004, request req-1]"
    with pytest.raises(RuntimeError) as err:
        tripo.submit(ctx, INPUT)
    assert str(err.value) == "Tripo task creation failed: code 2000 [code 2000]"


def test_submit_http_errors_keep_the_label_code_and_wait():
    t = ScriptedTransport(
        [
            route("POST", f"{BASE}/files", json_response({"code": 2010, "message": "Not enough credits", "suggestion": "Top up", "request_id": "req-9"}, 403)),
        ]
    )
    with pytest.raises(HttpError) as err:
        tripo.submit(context(t, {}, SECRETS), INPUT)
    assert str(err.value) == "Tripo upload error 403: Not enough credits (Top up) [code 2010, request req-9]"
    busy = ScriptedTransport(
        [
            route("POST", f"{BASE}/files", json_response({"code": 0, "data": {"file_token": "f"}})),
            route("POST", f"{BASE}/generation/image-to-model", json_response({"code": 2000, "message": "Too many concurrent tasks"}, 429, {"Retry-After": "20"})),
        ]
    )
    with pytest.raises(HttpError) as err:
        tripo.submit(context(busy, {}, SECRETS), INPUT)
    assert err.value.status == 429 and err.value.retry_after_ms == 20_000


def test_submit_refuses_images_over_20_mb_before_uploading():
    t = ScriptedTransport([])
    with pytest.raises(RuntimeError) as err:
        tripo.submit(context(t, {}, {"tripo.apiKey": "tsk_x"}), base.SubmitInput(bytes(21 * 1024 * 1024), 1, 1, False, "Big"))
    assert str(err.value) == "The image is 22 MB; Tripo accepts up to 20 MB. Lower Settings → Generation → Max image size, or crop the layer."
    assert t.calls == []
    # Exactly 20 MB is still accepted.
    ok = ScriptedTransport(
        [
            route("POST", f"{BASE}/files", json_response({"code": 0, "data": {"file_token": "f"}})),
            route("POST", f"{BASE}/generation/image-to-model", json_response({"code": 0, "data": {"task_id": "big"}})),
        ]
    )
    assert tripo.submit(context(ok, {}, SECRETS), base.SubmitInput(bytes(TRIPO_MAX_UPLOAD_BYTES), 1, 1, False, "Big")).remote_id == "big"


def test_a_missing_key_stops_before_any_request():
    t = ScriptedTransport([])
    ctx = context(t, {}, {})
    assert tripo.is_configured(ctx) == base.Configured(False, "Add your Tripo API key in Settings.")
    assert tripo.is_configured(context(t, {}, SECRETS)) == base.Configured(True)
    with pytest.raises(RuntimeError, match="Tripo: add your API key in Settings → Tripo."):
        tripo.submit(ctx, INPUT)
    assert tripo.test(ctx) == base.TestResult(False, "Tripo: add your API key in Settings → Tripo.")
    assert t.calls == []


# ---------------------------------------------------------------- poll and resolve


def test_poll_maps_statuses_including_banned_and_expired_as_failures():
    t = ScriptedTransport(
        [
            route(
                "GET",
                f"{BASE}/tasks/tt1",
                answers(
                    {"status": "queued", "progress": 0},
                    {"status": "running", "progress": 40},
                    {"status": "success", "output": {"model_url": "https://x/m.glb", "rendered_image_url": "https://x/r.webp"}},
                    {"status": "banned", "error_code": 2008, "error_message": "Content policy"},
                    {"status": "expired"},
                ),
            )
        ]
    )
    ctx = context(t, {}, SECRETS)
    assert tripo.poll(ctx, "tt1") == base.PollResult("queued", progress=0, message="Waiting in Tripo's queue")
    assert tripo.poll(ctx, "tt1") == base.PollResult("running", progress=40, message="Tripo is generating")
    done = tripo.poll(ctx, "tt1")
    assert done.state == "succeeded" and done.progress == 100
    assert done.result == base.ModelResult(model_url="https://x/m.glb", format="glb", thumbnail_url="https://x/r.webp", name="Tripo model", meta={})
    assert tripo.poll(ctx, "tt1") == base.PollResult("failed", error="Content policy (code 2008)")
    assert tripo.poll(ctx, "tt1") == base.PollResult("failed", error="Tripo task expired")
    assert t.calls[0].headers["authorization"] == "Bearer tsk_abcdefghijklmnop"


def test_poll_other_outcomes():
    t = ScriptedTransport(
        [
            route(
                "GET",
                re.compile(r"/tasks/t1$"),
                answers(
                    {"status": "cancelled"},
                    {"status": "CANCELED"},
                    {"status": "failed"},
                    {"status": "success", "output": {}},
                    {"status": "archived"},
                    {},
                ),
            )
        ]
    )
    ctx = context(t, {}, {"tripo.apiKey": "tsk_x"})
    assert tripo.poll(ctx, "t1") == base.PollResult("cancelled")
    assert tripo.poll(ctx, "t1") == base.PollResult("cancelled")
    assert tripo.poll(ctx, "t1") == base.PollResult("failed", error="Tripo task failed")
    assert tripo.poll(ctx, "t1") == base.PollResult("failed", error="Tripo finished but returned no model URL.")
    # Tripo's v3 migration guide: an unknown status is a failure.
    assert tripo.poll(ctx, "t1") == base.PollResult("failed", error='Tripo reported an unknown task status "archived".')
    assert tripo.poll(ctx, "t1") == base.PollResult("failed", error='Tripo reported an unknown task status "".')


def test_poll_surfaces_an_error_envelope_and_encodes_the_id():
    t = ScriptedTransport([route("GET", f"{BASE}/tasks/a%2Fb", json_response({"code": 2001, "message": "Task not found"}))])
    with pytest.raises(RuntimeError, match=r"^Tripo task query failed: Task not found \[code 2001\]$"):
        tripo.poll(context(t, {}, SECRETS), "a/b")


def test_results_fall_back_to_older_output_fields():
    t = ScriptedTransport(
        [
            route(
                "GET",
                f"{BASE}/tasks/tt1",
                answers(
                    {
                        "status": "success",
                        "type": "image_to_model",
                        "create_time": 1_790_000_000,
                        "consumed_credit": 30,
                        "output": {"pbr_model": "https://x/p.gltf?sig=1", "rendered_image": "https://x/r.png"},
                    },
                    {"status": "success", "input": {"prompt": "  a red chair  "}, "credits_consumed": 40, "output": {"base_model": "https://x/b.glb", "generated_image_url": "https://x/g.png"}},
                ),
            )
        ]
    )
    ctx = context(t, {}, SECRETS)
    first = tripo.resolve(ctx, "tt1")
    assert first == base.ModelResult(
        model_url="https://x/p.gltf?sig=1",
        format="gltf",
        thumbnail_url="https://x/r.png",
        name="Tripo model 2026-09-21 14:13",
        created_at=1_790_000_000_000,
        meta={"type": "image_to_model", "credits": 30},
    )
    second = tripo.resolve(ctx, "tt1")
    assert (second.model_url, second.thumbnail_url, second.name, second.meta) == ("https://x/b.glb", "https://x/g.png", "a red chair", {"credits": 40})


def test_resolve_explains_a_task_without_a_model():
    t = ScriptedTransport([route("GET", f"{BASE}/tasks/tt1", answers({"status": "running"}, {}))])
    ctx = context(t, {}, SECRETS)
    with pytest.raises(RuntimeError, match=r"^Tripo task tt1 has no downloadable model \(status running\)\.$"):
        tripo.resolve(ctx, "tt1")
    with pytest.raises(RuntimeError, match=r"\(status unknown\)\.$"):
        tripo.resolve(ctx, "tt1")


def test_tripo_has_no_cancel():
    assert TripoProvider.can_cancel is False
    with pytest.raises(NotImplementedError):
        tripo.cancel(context(ScriptedTransport([]), {}, SECRETS), "tt1")


# ---------------------------------------------------------------- test()


def test_test_reports_the_balance_with_reserved_credits():
    def check(body, expected):
        t = ScriptedTransport([route("GET", f"{BASE}/account/balance", json_response(body))])
        res = tripo.test(context(t, {}, SECRETS))
        assert res == base.TestResult(True, "Connected to Tripo (API v3).", expected)
        assert t.calls[0].headers["authorization"] == "Bearer tsk_abcdefghijklmnop"

    check({"code": 0, "data": {"balance": 120.5, "frozen": 20}}, "120.5 credits (20 reserved)")
    check({"code": 0, "data": {"balance": 120.5, "frozen": 0}}, "120.5 credits")
    # Decimals written as 200.0, or sent as strings, read the way JavaScript prints them.
    check('{"code": 0, "data": {"balance": 200.0, "frozen": 20.00}}', "200 credits (20 reserved)")
    check({"code": 0, "data": {"balance": "99.50", "frozen": "1.5"}}, "99.5 credits (1.5 reserved)")
    check({"code": 0, "data": {"frozen": 5}}, None)
    check({"code": 0, "data": {"balance": "n/a"}}, None)


def test_test_reports_failures():
    t = ScriptedTransport([route("GET", f"{BASE}/account/balance", json_response({"code": 1002, "message": "Invalid API key"}, 401))])
    assert tripo.test(context(t, {}, SECRETS)) == base.TestResult(False, "Tripo error 401: Invalid API key [code 1002]")
    t = ScriptedTransport([route("GET", f"{BASE}/account/balance", json_response({"code": 1002, "message": "Invalid API key"}))])
    assert tripo.test(context(t, {}, SECRETS)) == base.TestResult(False, "Tripo balance failed: Invalid API key [code 1002]")
