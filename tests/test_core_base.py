from geekatplay_3d_layers.core.http import Http, HttpError, multipart, retry_after_ms
from geekatplay_3d_layers.core.log import redact
from geekatplay_3d_layers.core.providers.base import format_from_url, to_epoch_ms, to_percent
from geekatplay_3d_layers.core.settings import DEFAULT_SETTINGS, merge, sanitize
from helpers import ScriptedTransport, json_response, parse_multipart, route
import pytest


def test_request_json_errors_carry_the_service_message_and_wait():
    t = ScriptedTransport([route("POST", "https://x/a", json_response({"message": "Too many", "code": 2000, "request_id": "r1"}, 429, {"Retry-After": "7"}))])
    with pytest.raises(HttpError) as err:
        Http(t).request_json("https://x/a", "POST", json_body={"a": 1}, label="Svc")
    assert str(err.value) == "Svc error 429: Too many [code 2000, request r1]"
    assert err.value.retry_after_ms == 7000
    assert t.calls[0].json() == {"a": 1}
    assert t.calls[0].headers["content-type"] == "application/json"


def test_helpers():
    assert to_percent(0.5) == 50 and to_percent("80") == 80 and to_percent(1) == 1 and to_percent(None) is None
    assert to_epoch_ms(1_700_000_000) == 1_700_000_000_000
    assert to_epoch_ms("2026-01-01T00:00:00Z") == 1767225600000
    assert format_from_url("https://a/m.gltf?x=1") == "gltf" and format_from_url("https://a/m.glb") == "glb"
    assert retry_after_ms({"x-ratelimit-reset": "3"}) == 3000
    body, ctype = multipart([{"name": "a", "value": "b"}, {"name": "f", "value": b"\x89PNG", "filename": "x.png", "content_type": "image/png"}])
    parsed = parse_multipart(body, ctype)
    assert parsed["fields"] == {"a": "b"} and parsed["files"]["f"]["bytes"] == b"\x89PNG"
    assert redact('Authorization: Bearer msy_abcdef123 "apiKey": "zzz"') == 'Authorization: Bearer *** "apiKey": "***"'


def test_settings_sanitize():
    assert sanitize(None) == DEFAULT_SETTINGS
    s = sanitize({"defaultProvider": "nope", "send": {"maxEdge": "99999"}, "comfyui": {"url": "192.168.1.5:8188/"}, "meshy": {"aiModel": "meshy-5"}, "hitem3d": {"model": "hitem3dv2.1", "resolution": "512"}})
    assert s["defaultProvider"] == "meshy" and s["send"]["maxEdge"] == 4096
    assert s["comfyui"]["url"] == "http://192.168.1.5:8188"
    assert s["meshy"]["aiModel"] == "meshy-6-lite"
    assert s["hitem3d"]["resolution"] == "1536fast"
    assert merge(DEFAULT_SETTINGS, {"tripo": {"textureQuality": "fast"}})["tripo"]["textureQuality"] == "standard"
