"""06 Programming Module: packaging and programming firmware (reusing the SDK UART tool)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tools import Module, Submodule, ToolRegistry
from . import boot, flash, image, verify

if TYPE_CHECKING:
    from ...core.app import NeonApp

MODULE = Module(
    number=6, id="programming", title="Programming Module",
    description="Inspect and verify BootROM images, boot modes, serial ports and UART programming.",
    submodules=[
        Submodule("image", "Image", "Decode BootROM headers with gt32u2086_image.py.",
                  source="modules/programming/image.py"),
        Submodule("verify", "Verify", "Pre-programming checks with gt32u2086_flash.py --check-only.",
                  source="modules/programming/verify.py"),
        Submodule("boot", "Boot", "Boot modes and the board-side programming procedure.",
                  source="modules/programming/boot.py"),
        Submodule("flash", "Flash", "Serial ports and ROMCODE UART programming of internal Flash.",
                  source="modules/programming/flash.py"),
    ],
)


def register(registry: ToolRegistry, app: NeonApp) -> None:
    for submodule in (image, verify, boot, flash):
        submodule.register(registry, app)
