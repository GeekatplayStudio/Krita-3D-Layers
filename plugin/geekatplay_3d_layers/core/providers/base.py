"""
The contract every 3D service implements (a port of the Photoshop plugin's
src/host/providers/types.ts).

Providers are plain classes with no Krita or Qt dependencies. They get HTTP, the settings,
a secret reader and a logger through ProviderContext and make synchronous calls: the job
manager runs them on worker threads. Each one is unit-tested against scripted HTTP
responses (tests/test_provider_*.py). Adding a service = one module implementing Provider
plus one line in registry.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..http import Http
from ..log import Logger

#: Keys in credentials.json (shared with the Photoshop plugin).
SECRET_KEYS = ("meshy.apiKey", "tripo.apiKey", "hitem3d.accessKey", "hitem3d.secretKey")

PROVIDER_IDS = ("meshy", "tripo", "hitem3d", "comfyui")
PROVIDER_LABELS = {"meshy": "Meshy", "tripo": "Tripo", "hitem3d": "Hitem3D", "comfyui": "ComfyUI (local)", "local": "Imported file"}


@dataclass
class ProviderContext:
    http: Http
    #: The whole settings dict (core/settings.py); a provider reads its own section.
    settings: Dict[str, Any]
    #: Reads a secret by key ("meshy.apiKey"); "" when not set.
    secret: Callable[[str], str]
    log: Logger
    #: Epoch milliseconds (injectable for tests).
    now: Callable[[], float] = lambda: int(time.time() * 1000)


@dataclass
class SubmitInput:
    #: PNG bytes of the layer or selection.
    image: bytes
    width: int
    height: int
    #: True when the image has transparent pixels (a cut-out object).
    has_alpha: bool
    #: Human name for the task ("Chair (selection)").
    name: str


@dataclass
class SubmitResult:
    remote_id: str
    #: Saved with the job; handed back to poll()/resolve()/cancel().
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResult:
    """A finished model ready to download. URLs are usually signed and short-lived."""

    model_url: str
    format: str = "glb"  # "glb" | "gltf"
    thumbnail_url: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    name: Optional[str] = None
    created_at: Optional[float] = None
    #: Small, credential-free summary kept in the library for transparency.
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PollResult:
    state: str  # "queued" | "running" | "succeeded" | "failed" | "cancelled"
    progress: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[ModelResult] = None
    #: Updated meta to persist (e.g. a refine stage).
    meta: Optional[Dict[str, Any]] = None


@dataclass
class TestResult:
    ok: bool
    message: str
    #: Remaining credits/balance when the service reports it.
    balance: Optional[str] = None


@dataclass
class Configured:
    configured: bool
    hint: Optional[str] = None


class Provider:
    id: str = ""
    label: str = ""
    can_cancel: bool = False

    def is_configured(self, ctx: ProviderContext) -> Configured:
        raise NotImplementedError

    def test(self, ctx: ProviderContext) -> TestResult:
        """Checks the key/address and reports the balance when possible."""
        raise NotImplementedError

    def submit(self, ctx: ProviderContext, inp: SubmitInput) -> SubmitResult:
        raise NotImplementedError

    def poll(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> PollResult:
        raise NotImplementedError

    def resolve(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> ModelResult:
        """Fresh download URLs for a finished task."""
        raise NotImplementedError

    def cancel(self, ctx: ProviderContext, remote_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------- helpers


def to_percent(value: Any) -> Optional[int]:
    """0-1 fractions and 0-100 numbers/strings → a clamped percentage."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
    elif isinstance(value, str):
        try:
            n = float(value)
        except ValueError:
            return None
    else:
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    pct = n * 100 if 0 < n <= 1 and not n.is_integer() else n
    return max(0, min(100, round(pct)))


def to_epoch_ms(value: Any) -> Optional[float]:
    """Seconds, milliseconds or an ISO string → epoch ms."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return value * 1000 if value < 1e12 else float(value)
    if isinstance(value, str) and value.strip():
        try:
            n = float(value)
            if n > 0:
                return n * 1000 if n < 1e12 else n
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            return None
    return None


def s(v: Any) -> Optional[str]:
    """A non-empty trimmed string, or None."""
    return v.strip() if isinstance(v, str) and v.strip() else None


def obj(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def lst(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def format_from_url(url: str) -> str:
    """"model.glb?Expires=…" → "glb"; anything else defaults to glb."""
    return "gltf" if url.split("?")[0].lower().endswith(".gltf") else "glb"
