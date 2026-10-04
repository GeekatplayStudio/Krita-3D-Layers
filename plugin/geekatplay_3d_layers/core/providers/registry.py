"""The 3D services, by id. Adding one = a module implementing Provider + one line here."""
from __future__ import annotations

from typing import Dict

from .base import Provider
from .comfyui import ComfyUIProvider
from .hitem3d import Hitem3DProvider
from .meshy import MeshyProvider
from .tripo import TripoProvider

PROVIDERS: Dict[str, Provider] = {p.id: p for p in (MeshyProvider(), TripoProvider(), Hitem3DProvider(), ComfyUIProvider())}


def provider(provider_id: str) -> Provider:
    try:
        return PROVIDERS[provider_id]
    except KeyError:
        raise KeyError(f"Unknown 3D service: {provider_id}") from None
