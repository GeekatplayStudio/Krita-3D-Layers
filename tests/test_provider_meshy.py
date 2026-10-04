"""
Meshy provider: ports of the Meshy cases in the Photoshop plugin's
src/host/providers/providers.test.ts and latest-api.test.ts, plus resolve, cancel and error paths.
"""
from __future__ import annotations

import base64
import re

import pytest

from geekatplay_3d_layers.core.http import HttpError
from geekatplay_3d_layers.core.providers import base
from geekatplay_3d_layers.core.providers.meshy import MeshyProvider, build_image_to_3d_body, clean_key
from geekatplay_3d_layers.core.settings import DEFAULT_SETTINGS
from helpers import PNG_1PX, ScriptedTransport, context, json_response, route

BASE = "https://api.meshy.ai"
SECRETS = {"meshy.apiKey": '"Bearer msy_testkey123456"'}
INPUT = base.SubmitInput(image=PNG_1PX, width=1, height=1, has_alpha=True, name="Chair")
meshy = MeshyProvider()


def meshy_settings(**patch):
    return {**DEFAULT_SETTINGS["meshy"], **patch}


def answers(*replies):
    """A reply function that answers with each body in turn."""
    it = iter(replies)
    return lambda call: json_response(next(it))


# ---------------------------------------------------------------- request bodies


def test_body_sends_only_documented_model_appropriate_options():
    assert build_image_to_3d_body(DEFAULT_SETTINGS["meshy"], "data:x") == {
        "image_url": "data:x",
        "ai_model": "latest",
        "should_texture": True,
        "enable_pbr": True,
        "should_remesh": False,
        "target_formats": ["glb"],
        "alpha_thumbnail": True,
        "moderation": True,
        "image_enhancement": True,
    }
    remesh = build_image_to_3d_body(
        meshy_settings(aiModel="meshy-6", shouldRemesh=True, topology="quad", targetPolycount=50, textureResolution="4k", geometryResolution="4k"), "d"
    )
    assert remesh["topology"] == "quad" and remesh["target_polycount"] == 100
    assert remesh["remove_lighting"] is True and remesh["texture_resolution"] == "4k" and remesh["image_enhancement"] is True
    assert "geometry_resolution" not in remesh  # 4k geometry needs meshy-7.1 / latest

    lite = build_image_to_3d_body(meshy_settings(aiModel="meshy-6-lite", textureResolution="8k"), "d")
    for field in ("texture_resolution", "remove_lighting", "image_enhancement", "topology", "target_polycount"):
        assert field not in lite


def test_body_resolution_and_texture_switches():
    for model in ("latest", "meshy-7.1"):
        assert build_image_to_3d_body(meshy_settings(aiModel=model, geometryResolution="4k"), "d")["geometry_resolution"] == "4k"
    untextured = build_image_to_3d_body(meshy_settings(shouldTexture=False, enablePbr=True, textureResolution="4k"), "d")
    assert untextured["should_texture"] is False and untextured["enable_pbr"] is False
    assert "texture_resolution" not in untextured
    # Remeshing without a polycount sends the topology only.
    plain = build_image_to_3d_body(meshy_settings(shouldRemesh=True, targetPolycount=0), "d")
    assert plain["topology"] == "triangle" and "target_polycount" not in plain


def test_moderation_and_transparent_preview_are_requested():
    assert build_image_to_3d_body(DEFAULT_SETTINGS["meshy"], "d")["alpha_thumbnail"] is True
    assert build_image_to_3d_body(DEFAULT_SETTINGS["meshy"], "d")["moderation"] is True
    assert "moderation" not in build_image_to_3d_body(meshy_settings(moderation=False), "d")


def test_smart_topology_sends_only_its_own_fields():
    body = build_image_to_3d_body(
        meshy_settings(aiModel="meshy-t2", targetPolycount=40_000, shouldRemesh=True, geometryResolution="4k", textureResolution="4k"), "d"
    )
    assert body == {
        "image_url": "d",
        "model_type": "smart-topology",
        "ai_model": "meshy-t2",
        "should_texture": True,
        "enable_pbr": True,
        "target_formats": ["glb"],
        "alpha_thumbnail": True,
        "moderation": True,
        "target_polycount": 15_000,
    }
    assert build_image_to_3d_body(meshy_settings(aiModel="meshy-t2", targetPolycount=50), "d")["target_polycount"] == 100
    assert "target_polycount" not in build_image_to_3d_body(meshy_settings(aiModel="meshy-t2"), "d")


def test_clean_key_accepts_pasted_variants():
    assert clean_key('"Bearer msy_abc"') == "msy_abc"
    assert clean_key("  bearer   msy_abc ") == "msy_abc"
    assert clean_key("'msy_abc'") == "msy_abc"
    assert clean_key("") == "" and clean_key(None) == ""


# ---------------------------------------------------------------- submit


def test_submit_sends_a_data_uri_with_a_clean_bearer_token():
    t = ScriptedTransport([route("POST", f"{BASE}/openapi/v1/image-to-3d", json_response({"result": "task-1"}))])
    res = meshy.submit(context(t, {}, SECRETS), INPUT)
    assert res == base.SubmitResult("task-1", {"kind": "image-to-3d", "aiModel": "latest"})
    call = t.calls[0]
    assert call.headers["authorization"] == "Bearer msy_testkey123456"
    assert call.headers["content-type"] == "application/json"
    body = call.json()
    assert re.match(r"^data:image/png;base64,iVBOR", body["image_url"])
    assert body == build_image_to_3d_body(DEFAULT_SETTINGS["meshy"], "data:image/png;base64," + base64.b64encode(PNG_1PX).decode())


def test_submit_uses_the_chosen_model_and_needs_a_task_id():
    t = ScriptedTransport([route("POST", f"{BASE}/openapi/v1/image-to-3d", answers({"id": "task-2"}, {"result": " "}))])
    ctx = context(t, {"meshy": {"aiModel": "meshy-6"}}, SECRETS)
    assert meshy.submit(ctx, INPUT) == base.SubmitResult("task-2", {"kind": "image-to-3d", "aiModel": "meshy-6"})
    assert t.calls[0].json()["ai_model"] == "meshy-6"
    with pytest.raises(RuntimeError, match="^Meshy did not return a task id.$"):
        meshy.submit(ctx, INPUT)


def test_a_missing_key_stops_before_any_request():
    t = ScriptedTransport([])
    ctx = context(t, {}, {})
    assert meshy.is_configured(ctx) == base.Configured(False, "Add your Meshy API key in Settings.")
    assert meshy.is_configured(context(t, {}, SECRETS)) == base.Configured(True)
    with pytest.raises(RuntimeError, match="Meshy: add your API key in Settings → Meshy."):
        meshy.submit(ctx, INPUT)
    assert meshy.test(ctx) == base.TestResult(False, "Meshy: add your API key in Settings → Meshy.")
    assert t.calls == []


def test_rate_limit_reaches_the_job_manager():
    t = ScriptedTransport([route("POST", f"{BASE}/openapi/v1/image-to-3d", json_response({"message": "Too many requests"}, 429, {"Retry-After": "20"}))])
    with pytest.raises(HttpError) as err:
        meshy.submit(context(t, {}, SECRETS), INPUT)
    assert err.value.status == 429 and err.value.retry_after_ms == 20_000
    assert str(err.value) == "Meshy error 429: Too many requests"


# ---------------------------------------------------------------- poll


def test_poll_maps_task_states_and_results():
    t = ScriptedTransport(
        [
            route(
                "GET",
                re.compile(r"image-to-3d/t1$"),
                answers(
                    {"status": "PENDING", "progress": 0, "preceding_tasks": 3},
                    {"status": "IN_PROGRESS", "progress": 55},
                    {
                        "status": "SUCCEEDED",
                        "progress": 100,
                        "model_urls": {"glb": "https://cdn/m.glb?Expires=1"},
                        "thumbnail_url": "https://cdn/t.png",
                        "created_at": 1_790_000_000_000,
                        "expires_at": 1_790_259_200,
                        "ai_model": "meshy-7.1",
                        "consumed_credits": 20,
                    },
                    {"status": "SUCCEEDED", "model_urls": {}},
                    {"status": "FAILED", "task_error": {"message": "Bad image"}},
                    {"status": "CANCELED"},
                ),
            )
        ]
    )
    ctx = context(t, {}, SECRETS)
    assert meshy.poll(ctx, "t1") == base.PollResult("queued", progress=0, message="3 tasks ahead in Meshy's queue")
    assert meshy.poll(ctx, "t1") == base.PollResult("running", progress=55, message="Meshy is generating")
    done = meshy.poll(ctx, "t1")
    assert done == base.PollResult(
        "succeeded",
        progress=100,
        result=base.ModelResult(
            model_url="https://cdn/m.glb?Expires=1",
            format="glb",
            thumbnail_url="https://cdn/t.png",
            name="Image to 3D 2026-09-21 14:13",
            created_at=1_790_000_000_000,
            meta={"kind": "image-to-3d", "aiModel": "meshy-7.1", "expiresAt": 1_790_259_200_000, "credits": 20},
        ),
    )
    assert meshy.poll(ctx, "t1") == base.PollResult("failed", error="Meshy finished but returned no GLB file.")
    assert meshy.poll(ctx, "t1") == base.PollResult("failed", error="Bad image")
    assert meshy.poll(ctx, "t1") == base.PollResult("cancelled")
    assert t.calls[0].url == f"{BASE}/openapi/v1/image-to-3d/t1" and t.calls[0].headers["authorization"] == "Bearer msy_testkey123456"


def test_poll_fallback_messages():
    t = ScriptedTransport(
        [
            route(
                "GET",
                re.compile(r"image-to-3d/t1$"),
                answers({"status": "PENDING"}, {"status": "FAILED"}, {"status": "EXPIRED"}, {"status": "SOMETHING_NEW", "progress": 0.4}),
            )
        ]
    )
    ctx = context(t, {}, SECRETS)
    assert meshy.poll(ctx, "t1") == base.PollResult("queued", message="Waiting in Meshy's queue")
    assert meshy.poll(ctx, "t1") == base.PollResult("failed", error="Meshy task failed.")
    assert meshy.poll(ctx, "t1") == base.PollResult("failed", error="Meshy task expired.")
    assert meshy.poll(ctx, "t1") == base.PollResult("running", progress=40, message="Meshy is generating")


def test_poll_prefers_the_transparent_preview():
    t = ScriptedTransport(
        [
            route(
                "GET",
                re.compile(r"image-to-3d/t1$"),
                json_response({"status": "SUCCEEDED", "model_urls": {"glb": "https://cdn/m.glb"}, "thumbnail_url": "https://cdn/t.png", "alpha_thumbnail_url": "https://cdn/alpha.png"}),
            )
        ]
    )
    res = meshy.poll(context(t, {}, SECRETS), "t1", {"kind": "image-to-3d"})
    assert res.result is not None and res.result.thumbnail_url == "https://cdn/alpha.png"
    assert BASE == DEFAULT_SETTINGS["meshy"]["baseUrl"]


def test_poll_follows_the_kind_in_meta_and_encodes_the_id():
    t = ScriptedTransport([route("GET", re.compile(r"."), json_response({"status": "IN_PROGRESS"}))])
    ctx = context(t, {}, SECRETS)
    meshy.poll(ctx, "t1", {"kind": "text-to-3d"})
    meshy.poll(ctx, "t1", {"kind": "multi-image-to-3d"})
    meshy.poll(ctx, "t1", {"kind": "something-else"})
    meshy.poll(ctx, "a/b c", None)
    assert [c.url for c in t.calls] == [
        f"{BASE}/openapi/v2/text-to-3d/t1",
        f"{BASE}/openapi/v1/multi-image-to-3d/t1",
        f"{BASE}/openapi/v1/image-to-3d/t1",
        f"{BASE}/openapi/v1/image-to-3d/a%2Fb%20c",
    ]


# ---------------------------------------------------------------- resolve


def test_resolve_tries_each_kind_until_one_knows_the_task():
    t = ScriptedTransport(
        [
            route("GET", f"{BASE}/openapi/v1/image-to-3d/t9", json_response({"message": "Not found"}, 404)),
            route("GET", f"{BASE}/openapi/v1/multi-image-to-3d/t9", json_response({"message": "Not found"}, 404)),
            route("GET", f"{BASE}/openapi/v2/text-to-3d/t9", json_response({"status": "SUCCEEDED", "prompt": "a red chair", "model_urls": {"glb": "https://cdn/c.glb"}})),
        ]
    )
    res = meshy.resolve(context(t, {}, SECRETS), "t9")
    assert res.model_url == "https://cdn/c.glb" and res.name == "a red chair" and res.meta == {"kind": "text-to-3d"}
    assert len(t.calls) == 3


def test_resolve_with_a_kind_asks_one_endpoint_and_explains_a_missing_glb():
    t = ScriptedTransport([route("GET", re.compile(r"image-to-3d/t1$"), json_response({"status": "IN_PROGRESS", "model_urls": {}}))])
    with pytest.raises(RuntimeError, match=r"^Meshy task t1 has no GLB \(status IN_PROGRESS\)\.$"):
        meshy.resolve(context(t, {}, SECRETS), "t1", {"kind": "image-to-3d"})
    assert len(t.calls) == 1
    # A task without GLB is an answer too: the other kinds are not tried.
    t2 = ScriptedTransport([route("GET", re.compile(r"image-to-3d/t1$"), json_response({}))])
    with pytest.raises(RuntimeError, match=r"\(status unknown\)"):
        meshy.resolve(context(t2, {}, SECRETS), "t1")
    assert len(t2.calls) == 1


def test_resolve_stops_on_errors_other_than_404():
    t = ScriptedTransport([route("GET", re.compile(r"."), json_response({"message": "Invalid API key"}, 401))])
    with pytest.raises(HttpError) as err:
        meshy.resolve(context(t, {}, SECRETS), "t1")
    assert err.value.status == 401 and len(t.calls) == 1
    gone = ScriptedTransport([route("GET", re.compile(r"."), json_response({"message": "Not found"}, 404))])
    with pytest.raises(HttpError) as err:
        meshy.resolve(context(gone, {}, SECRETS), "t1")
    assert err.value.status == 404 and len(gone.calls) == 3


# ---------------------------------------------------------------- cancel and test


def test_cancel_deletes_the_task_and_explains_a_refusal():
    assert MeshyProvider.can_cancel is True
    ok = ScriptedTransport([route("DELETE", f"{BASE}/openapi/v2/text-to-3d/t1", json_response({}))])
    meshy.cancel(context(ok, {}, SECRETS), "t1", {"kind": "text-to-3d"})
    assert ok.calls[0].method == "DELETE" and ok.calls[0].headers["authorization"] == "Bearer msy_testkey123456"

    refused = ScriptedTransport([route("DELETE", re.compile(r"image-to-3d/t1$"), json_response({"message": "in progress"}, 409))])
    with pytest.raises(RuntimeError, match="already started"):
        meshy.cancel(context(refused, {}, SECRETS), "t1")
    other = ScriptedTransport([route("DELETE", re.compile(r"image-to-3d/t1$"), json_response({"message": "Server error"}, 500))])
    with pytest.raises(HttpError):
        meshy.cancel(context(other, {}, SECRETS), "t1")


def test_test_checks_the_key_with_the_balance_endpoint():
    ok = meshy.test(context(ScriptedTransport([route("GET", f"{BASE}/openapi/v1/balance", json_response({"balance": 1200}))]), {}, SECRETS))
    assert ok == base.TestResult(True, "Connected to Meshy.", "1200 credits")
    bad = meshy.test(context(ScriptedTransport([route("GET", f"{BASE}/openapi/v1/balance", json_response({"message": "Invalid API key"}, 401))]), {}, SECRETS))
    assert bad == base.TestResult(False, "Meshy error 401: Invalid API key")
    no_balance = meshy.test(context(ScriptedTransport([route("GET", f"{BASE}/openapi/v1/balance", json_response({}))]), {}, SECRETS))
    assert no_balance == base.TestResult(True, "Connected to Meshy.", None)
    assert meshy.is_configured(context(ScriptedTransport([]), {}, {})).configured is False
