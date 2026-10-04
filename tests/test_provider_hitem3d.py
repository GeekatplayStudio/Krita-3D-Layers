"""Hitem3D provider (ported from the Photoshop plugin's providers.test.ts and latest-api.test.ts)."""
import base64
import re

import pytest

from geekatplay_3d_layers.core.http import HttpError
from geekatplay_3d_layers.core.providers.base import PollResult, SubmitInput
from geekatplay_3d_layers.core.providers.hitem3d import (
    Hitem3DProvider,
    build_submit_fields,
    clear_hitem3d_token_cache,
    is_expired_token_response,
    read_credentials,
)
from geekatplay_3d_layers.core.settings import DEFAULT_SETTINGS, merge
from helpers import PNG_1PX, ScriptedTransport, context, json_response, parse_multipart, route

BASE = "https://api.hitem3d.ai/open-api/v1"
SECRETS = {"hitem3d.accessKey": "AK123", "hitem3d.secretKey": "SK456"}
INPUT = SubmitInput(image=PNG_1PX, width=1, height=1, has_alpha=True, name="Chair")
hitem3d = Hitem3DProvider()


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    clear_hitem3d_token_cache()
    yield
    clear_hitem3d_token_cache()


def _settings(**patch):
    out = dict(DEFAULT_SETTINGS["hitem3d"])
    out.update(patch)
    return out


def _token(value="t"):
    return route("POST", f"{BASE}/auth/token", json_response({"code": 200, "data": {"accessToken": value}}))


def test_builds_submit_fields_glb_output_pbr_only_where_supported():
    assert build_submit_fields(_settings()) == {"request_type": "3", "model": "hi3dv3.0", "resolution": "2048quality", "format": "2", "rmbg": "1", "pbr": "1"}
    assert build_submit_fields(_settings(model="hitem3dv1.5", resolution="1024", face=500000, removeBackground=False)) == {
        "request_type": "3",
        "model": "hitem3dv1.5",
        "resolution": "1024",
        "format": "2",
        "rmbg": "0",
        "face": "500000",
    }
    assert "pbr" not in build_submit_fields(_settings(requestType="1"))
    assert build_submit_fields(_settings(pbr=False))["pbr"] == "0"


def test_sends_de_shading_only_when_changed_and_supported():
    assert "shading" not in build_submit_fields(_settings())
    assert build_submit_fields(_settings(shading=0.8))["shading"] == "0.8"
    assert build_submit_fields(_settings(shading=0))["shading"] == "0.0"
    assert "shading" not in build_submit_fields(_settings(model="hitem3dv1.5", resolution="1024", shading=0.8))
    assert "shading" not in build_submit_fields(_settings(requestType="1", shading=0.8))
    assert merge(DEFAULT_SETTINGS, {"hitem3d": {"shading": 0.77}})["hitem3d"]["shading"] == 0.8


def test_signs_in_with_basic_ak_sk_caches_the_token_and_re_signs_on_expiry():
    counts = {"token": 0, "query": 0}

    def token(call):
        counts["token"] += 1
        assert call.headers["authorization"] == "Basic " + base64.b64encode(b"AK123:SK456").decode()
        assert call.headers["accept"] == "application/json" and call.headers["content-type"] == "application/json"
        assert call.body == b"{}"
        return json_response({"code": 200, "data": {"accessToken": f"tok{counts['token']}", "tokenType": "Bearer"}})

    def query(call):
        counts["query"] += 1
        if call.headers["authorization"] == "Bearer tok1" and counts["query"] == 2:
            return json_response({"code": 401, "msg": "login expired"})
        return json_response({"code": 200, "data": {"task_id": "h1", "state": "processing"}})

    t = ScriptedTransport([route("POST", f"{BASE}/auth/token", token), route("GET", re.compile(r"query-task\?task_id=h1$"), query)])
    ctx = context(t, {"hitem3d": {"appId": "777"}}, SECRETS)
    assert hitem3d.poll(ctx, "h1").state == "running"
    assert t.calls[1].headers["appid"] == "777"
    # Second poll gets "login expired" → sign in again → retry with tok2.
    assert hitem3d.poll(ctx, "h1").state == "running"
    assert counts["token"] == 2
    assert t.calls[-1].headers["authorization"] == "Bearer tok2"
    assert any("signing in again" in line for line in ctx.log.lines)


def test_the_cached_token_expires_after_50_minutes():
    tokens = []

    def token(call):
        tokens.append(1)
        return json_response({"code": 200, "data": {"accessToken": f"tok{len(tokens)}"}})

    t = ScriptedTransport([route("POST", f"{BASE}/auth/token", token), route("GET", f"{BASE}/balance", json_response({"code": 200, "data": {"totalBalance": 1}}))])
    ctx = context(t, {}, SECRETS)
    clock = [1_790_000_000_000]
    ctx.now = lambda: clock[0]
    hitem3d.test(ctx)
    clock[0] += 49 * 60_000
    hitem3d.test(ctx)
    assert len(tokens) == 1
    clock[0] += 2 * 60_000
    hitem3d.test(ctx)
    assert len(tokens) == 2
    assert t.calls[-1].headers["authorization"] == "Bearer tok2"
    # Another base URL or key is another cache entry.
    other = context(t, {"hitem3d": {"baseUrl": "https://eu.example.com/v1"}}, SECRETS)
    t.routes.append(route("POST", "https://eu.example.com/v1/auth/token", token))
    t.routes.append(route("GET", "https://eu.example.com/v1/balance", json_response({"code": 200, "data": {"balance": 3}})))
    assert hitem3d.test(other).balance == "3 balance"
    assert len(tokens) == 3


def test_gives_up_when_the_new_token_is_refused_too():
    t = ScriptedTransport([_token(), route("GET", f"{BASE}/balance", json_response({"code": 401, "msg": "login expired"}))])
    res = hitem3d.test(context(t, {}, SECRETS))
    assert not res.ok
    assert res.message == "Hitem3D: sign-in expired or the token is invalid. Check the keys in Settings → Hitem3D."
    assert [c.url for c in t.calls] == [f"{BASE}/auth/token", f"{BASE}/balance", f"{BASE}/auth/token", f"{BASE}/balance"]
    # A raw token is not retried (there is nothing to sign in with).
    raw = ScriptedTransport([route("GET", f"{BASE}/balance", json_response({"code": 200, "msg": "token expired"}))])
    assert not hitem3d.test(context(raw, {}, {"hitem3d.accessKey": "tok"})).ok
    assert len(raw.calls) == 1


def test_accepts_ak_sk_in_one_field_and_a_raw_token():
    t = ScriptedTransport(
        [
            route("POST", f"{BASE}/auth/token", json_response({"code": 200, "data": {"accessToken": "t"}})),
            route("GET", f"{BASE}/balance", lambda call: json_response({"code": 200, "data": {"totalBalance": 14 if call.headers["authorization"] == "Bearer t" else 0}})),
        ]
    )
    assert hitem3d.test(context(t, {}, {"hitem3d.accessKey": "AK:SK"})).balance == "14 balance"
    assert t.calls[0].headers["authorization"] == "Basic " + base64.b64encode(b"AK:SK").decode()
    clear_hitem3d_token_cache()
    raw = ScriptedTransport([route("GET", f"{BASE}/balance", lambda call: json_response({"code": 200, "data": {"totalBalance": 5 if call.headers["authorization"] == "Bearer rawtoken" else 0}}))])
    assert hitem3d.test(context(raw, {}, {"hitem3d.accessKey": "rawtoken"})).balance == "5 balance"


def test_reads_credentials_like_the_photoshop_plugin():
    def creds(ak="", sk=""):
        return read_credentials(context(ScriptedTransport([]), {}, {"hitem3d.accessKey": ak, "hitem3d.secretKey": sk}))

    assert creds() is None
    assert creds(sk="SK") is None
    k = creds('"AK1" ', " 'SK1'")
    assert (k.kind, k.ak, k.sk) == ("keys", "AK1", "SK1")
    k = creds("AK2 : SK2 : extra")
    assert (k.kind, k.ak, k.sk) == ("keys", "AK2", "SK2")
    k = creds("Bearer abc.def")
    assert (k.kind, k.token) == ("token", "abc.def")
    assert creds("solo").token == "solo"
    assert hitem3d.is_configured(context(ScriptedTransport([]), {}, {})).configured is False
    assert hitem3d.is_configured(context(ScriptedTransport([]), {}, {})).hint == "Add your Hitem3D Access Key and Secret Key in Settings."
    assert hitem3d.is_configured(context(ScriptedTransport([]), {}, SECRETS)).configured is True


def test_submits_multipart_with_the_image_and_fields():
    t = ScriptedTransport([_token(), route("POST", f"{BASE}/submit-task", json_response({"code": 200, "data": {"task_id": "h9"}, "msg": "success"}))])
    res = hitem3d.submit(context(t, {}, SECRETS), INPUT)
    assert res.remote_id == "h9"
    assert res.meta == {"model": "hi3dv3.0", "resolution": "2048quality"}
    call = t.calls[1]
    assert call.headers["authorization"] == "Bearer t" and call.headers["accept"] == "application/json"
    assert "appid" not in call.headers
    form = parse_multipart(call.body, call.headers["content-type"])
    assert form["files"]["images"]["filename"] == "image.png"
    assert form["files"]["images"]["bytes"] == PNG_1PX
    assert form["fields"] == {"request_type": "3", "model": "hi3dv3.0", "resolution": "2048quality", "format": "2", "rmbg": "1", "pbr": "1"}
    assert re.search(r'name="images"; filename="image.png"\r\nContent-Type: image/png', call.body.decode("latin1"))


def test_maps_documented_and_legacy_query_results():
    replies = [
        {"code": 200, "data": {"state": "queueing"}},
        {"code": 200, "data": {"state": "success", "url": "https://cdn/m.glb", "cover_url": "https://cdn/c.png"}},
        {"code": 200, "data": {"task_status": 4, "task_result": {"model_url": "https://cdn/legacy.glb", "render_url": "r"}}},
        {"code": 200, "data": {"state": "failed", "task_msg": "nope"}},
        {"code": 50010001, "msg": "generate failed"},
    ]
    it = iter(replies)
    t = ScriptedTransport([_token(), route("GET", re.compile(r"query-task"), lambda call: json_response(next(it)))])
    ctx = context(t, {}, SECRETS)
    queued = hitem3d.poll(ctx, "h")
    assert (queued.state, queued.progress, queued.message, queued.meta) == ("queued", 15, "Hitem3D: queueing", {"progress": 15})
    done = hitem3d.poll(ctx, "h")
    assert (done.state, done.progress) == ("succeeded", 100)
    assert done.result.model_url == "https://cdn/m.glb" and done.result.thumbnail_url == "https://cdn/c.png"
    assert done.result.format == "glb" and done.result.name == "Hitem3D h"
    legacy = hitem3d.poll(ctx, "h")
    assert legacy.result.model_url == "https://cdn/legacy.glb" and legacy.result.thumbnail_url == "r"
    assert hitem3d.poll(ctx, "h") == PollResult("failed", error="nope")
    with pytest.raises(RuntimeError, match="credits refunded"):
        hitem3d.poll(ctx, "h")


def test_progress_never_goes_back_and_reports_the_state():
    replies = [
        {"code": 200, "data": {"state": "processing", "process_pct": 0.3}},
        {"code": 200, "data": {"state": "processing"}},
        {"code": 200, "data": {}},
        {"code": 200, "data": {"task_status": -1}},
        {"code": 200, "data": {"state": "success"}},
    ]
    it = iter(replies)
    t = ScriptedTransport([_token(), route("GET", re.compile(r"query-task\?task_id=a%2Fb%20c$"), lambda call: json_response(next(it)))])
    ctx = context(t, {}, SECRETS)
    first = hitem3d.poll(ctx, "a/b c", {"jobKey": 1})
    assert (first.state, first.progress, first.meta) == ("running", 30, {"jobKey": 1, "progress": 30})
    second = hitem3d.poll(ctx, "a/b c", {"progress": 60})
    assert (second.progress, second.message) == (60, "Hitem3D: processing")
    third = hitem3d.poll(ctx, "a/b c")
    assert (third.state, third.progress, third.message) == ("running", 10, "Hitem3D is generating")
    assert hitem3d.poll(ctx, "a/b c") == PollResult("failed", error="Hitem3D generation failed (credits are refunded).")
    assert hitem3d.poll(ctx, "a/b c") == PollResult("failed", error="Hitem3D finished but returned no model URL.")


def test_resolves_fresh_urls():
    replies = [
        {"code": 200, "data": {"id": "asset-1", "state": "success", "url": "https://cdn/m.gltf?Expires=1", "cover_url": "https://cdn/c.png"}},
        {"code": 200, "data": {"state": "processing"}},
    ]
    it = iter(replies)
    t = ScriptedTransport([_token(), route("GET", re.compile(r"query-task\?task_id=abcdefghijk$"), lambda call: json_response(next(it)))])
    ctx = context(t, {}, SECRETS)
    res = hitem3d.resolve(ctx, "abcdefghijk")
    assert (res.model_url, res.format, res.name, res.meta) == ("https://cdn/m.gltf?Expires=1", "gltf", "Hitem3D abcdefgh", {"assetId": "asset-1"})
    with pytest.raises(RuntimeError, match=re.escape("Hitem3D task abcdefghijk has no downloadable model (state processing).")):
        hitem3d.resolve(ctx, "abcdefghijk")


def test_explains_documented_error_codes():
    def submit(call):
        assert parse_multipart(call.body, call.headers["content-type"])["files"]["images"]
        return json_response({"code": 10031002, "msg": "Face not valid"})

    t = ScriptedTransport([route("POST", f"{BASE}/auth/token", json_response({"code": 200, "data": {"accessToken": "tok", "tokenType": "Bearer"}})), route("POST", f"{BASE}/submit-task", submit)])
    with pytest.raises(RuntimeError, match=r"face count is outside the range .* \(Face not valid\) \[code 10031002\]"):
        hitem3d.submit(context(t, {}, SECRETS), INPUT)
    big = SubmitInput(image=bytes(21 * 1024 * 1024), width=1, height=1, has_alpha=True, name="Big")
    with pytest.raises(RuntimeError, match="up to 20 MB") as err:
        hitem3d.submit(context(t, {}, SECRETS), big)
    assert str(err.value).startswith("The image is 22 MB;")
    # Sign-in errors are explained too (the token from above is cached, so forget it first).
    clear_hitem3d_token_cache()
    bad = ScriptedTransport([route("POST", f"{BASE}/auth/token", json_response({"code": 40010000, "msg": "AK/SK error"}))])
    res = hitem3d.test(context(bad, {}, SECRETS))
    assert res.message == "Hitem3D sign-in failed: the Access Key / Secret Key were rejected (AK/SK error) [code 40010000]"
    # Unknown codes show the code when there is no message.
    odd = ScriptedTransport([_token(), route("GET", f"{BASE}/balance", json_response({"code": 777}))])
    assert hitem3d.test(context(odd, {}, SECRETS)).message == "Hitem3D balance failed: code 777 [code 777]"


def test_reports_http_errors_and_missing_keys():
    t = ScriptedTransport([route("POST", f"{BASE}/auth/token", json_response({"message": "Unauthorized"}, 401))])
    assert hitem3d.test(context(t, {}, SECRETS)).message == "Hitem3D auth error 401: Unauthorized"
    with pytest.raises(HttpError):
        hitem3d.poll(context(t, {}, SECRETS), "x")
    none = hitem3d.test(context(ScriptedTransport([]), {}, {}))
    assert (none.ok, none.message) == (False, "Hitem3D: add your Access Key and Secret Key in Settings → Hitem3D.")
    t2 = ScriptedTransport([route("POST", f"{BASE}/auth/token", json_response({"code": 200, "data": {}}))])
    assert hitem3d.test(context(t2, {}, SECRETS)).message == "Hitem3D sign-in returned no token."
    t3 = ScriptedTransport([_token(), route("POST", f"{BASE}/submit-task", json_response({"code": 200, "data": {"task_id": 5}}))])
    with pytest.raises(RuntimeError, match="did not return a task id"):
        hitem3d.submit(context(t3, {}, SECRETS), INPUT)
    assert hitem3d.test(context(ScriptedTransport([_token(), route("GET", f"{BASE}/balance", json_response({"code": 0, "data": {}}))]), {}, SECRETS)).balance is None


def test_recognises_expired_token_answers():
    assert is_expired_token_response({"code": 401, "msg": "login expired"})
    assert not is_expired_token_response({"code": 200, "msg": "ok"})
    assert is_expired_token_response({"code": 500, "message": "invalid token"})
    assert is_expired_token_response({"code": "403"})
    assert not is_expired_token_response("login expired")
    assert not is_expired_token_response(None)
