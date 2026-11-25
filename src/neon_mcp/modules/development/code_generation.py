"""Code Generation submodule: run the SDK's device generator (YAML → CMSIS header, startup,
linker script, SVD, image fragment) to preview or inspect its output.

CMake already regenerates these files inside every build directory; this tool exists so an
agent can inspect generated output for a profile without building. Never edit generated
files: change the device YAML or the generator instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ...core.tools import WRITES_FILES, ToolRegistry
from ...system.errors import CommandError
from ...system.process import run
from ...system.security import Permission

if TYPE_CHECKING:
    from ...core.app import NeonApp


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("development", "code_generation", WRITES_FILES)
    def dev_generate_device_files(output_dir: str, profile: Literal["normal", "xip"] = "normal",
                                  target: str | None = None) -> dict[str, Any]:
        """Generate the device files (CMSIS header, mcu_device.h, startup, linker script, SVD, image
        CMake fragment) from the target's device YAML into output_dir, using the SDK's generate.py.

        For inspection only: builds generate their own copy under build/<preset>/generated/.
        """
        app.policy.require(Permission.WRITE, "dev_generate_device_files")
        tgt = app.target(target)
        device = tgt.device()
        out = app.workspace.resolve(output_dir, must_exist=False)
        out.mkdir(parents=True, exist_ok=True)
        generator = app.sdk.sdk_dir / "mcu-description" / "tools" / "generate.py"
        result = run([app.python(None), str(generator), "--device", device.name, "--profile", profile,
                      "--output-dir", str(out)], app.sdk.root, timeout_s=120)
        if not result.ok:
            raise CommandError("Device generation failed.", result.output.strip()[-1500:])
        files = sorted(p for p in out.rglob("*") if p.is_file())
        return {"device": device.name, "profile": profile, "output_dir": str(out),
                "source_yaml": str(device.path),
                "files": [{"path": str(p), "size": p.stat().st_size} for p in files],
                "log": result.output.strip()[-2000:]}

