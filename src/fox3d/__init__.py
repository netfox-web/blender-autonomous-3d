"""Blender Autonomous 3D / Product R&D Engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.1.0"
__all__ = ["BLENDER_CAPABILITIES", "Platform", "foxstudio_operations", "__version__"]

if TYPE_CHECKING:
    from fox3d.capabilities import BLENDER_CAPABILITIES, foxstudio_operations
    from fox3d.platform import Platform


def __getattr__(name: str):
    if name == "BLENDER_CAPABILITIES":
        from fox3d.capabilities import BLENDER_CAPABILITIES

        return BLENDER_CAPABILITIES
    if name == "Platform":
        from fox3d.platform import Platform

        return Platform
    if name == "foxstudio_operations":
        from fox3d.capabilities import foxstudio_operations

        return foxstudio_operations
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(__all__))
