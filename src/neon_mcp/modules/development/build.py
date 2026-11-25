"""Build submodule: CMake configure/build workflow (also used by programming and analysis)."""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ...adapters import cmake
from ...core.tools import WRITES_FILES, ToolRegistry
from ...system.errors import CommandError, InvalidArgumentError, NotFoundError
from ...system.security import Permission
from ...targets.registry import Target

if TYPE_CHECKING:
    from ...core.app import NeonApp

ConfigValue = bool | int | str


@functools.lru_cache(maxsize=4)
def _cmake_version(path: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else None


def require_build_tools() -> None:
    missing = [tool for tool in ("cmake", "ninja", "arm-none-eabi-gcc") if shutil.which(tool) is None]
    if missing:
        raise CommandError(
            "Missing build tools on PATH: " + ", ".join(missing) + ".",
            "Run dev_check_environment for install instructions (guide/Setup.md).")
    cmake_path = shutil.which("cmake")
    version = _cmake_version(cmake_path) if cmake_path else None
    if version is not None and version < (3, 25):
        raise CommandError(
            f"CMake {version[0]}.{version[1]} at {cmake_path} is too old; the SDK presets need 3.25 or later.",
            "Install a newer CMake (cmake.org, Kitware APT repository, or `pip install cmake`).")


def build_layout(app: NeonApp, target: Target, app_dir: Path, build_dir: str | None) -> cmake.BuildLayout:
    resolved = None
    if build_dir:
        resolved = app.workspace.resolve(build_dir, base=app_dir, must_exist=False)
    return cmake.layout(app_dir, target.preset, resolved)


def find_elf(app: NeonApp, elf_path: str | None, app_dir: str | None, build_dir: str | None) -> Path:
    """An explicit ELF (workspace path, relative to app_dir if given) or the app build's only ELF."""
    if elf_path:
        candidate = Path(elf_path)
        if not candidate.is_absolute() and app_dir:
            candidate = app.app_dir(app_dir) / candidate
        return app.workspace.resolve(candidate, kind="file")
    directory = app.app_dir(app_dir)
    lay = build_layout(app, app.target(), directory, build_dir)
    elfs = cmake.artifacts(lay.build_dir)["elf"]
    if not elfs:
        raise NotFoundError(f"No ELF in {lay.build_dir}.", "Build the application first (dev_build).")
    if len(elfs) > 1:
        raise InvalidArgumentError("Several ELF files found; pass elf_path.", ", ".join(elfs))
    return Path(elfs[0])


def configure_vars(target: Target, profile: str | None, secure_boot: bool | None, app_version: str | None,
                   extra: dict[str, Any] | None) -> dict[str, str]:
    variables: dict[str, str] = {}
    if profile is not None:
        allowed = target.profile.get("profiles", [])
        if allowed and profile not in allowed:
            raise InvalidArgumentError(f"Unknown profile '{profile}' for {target.name}; use one of {allowed}.")
        variables["NEON_MDF_PROFILE"] = profile
    if secure_boot is not None:
        if secure_boot and not target.supports("secure_boot"):
            target.require("secure_boot", "secure boot")
        variables["NEON_MDF_SECURE_BOOT"] = "ON" if secure_boot else "OFF"
    if app_version is not None:
        parts = app_version.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise InvalidArgumentError("app_version must look like 1.2.3.")
        variables["NEON_MDF_GT32U2086_APP_VERSION"] = app_version
    for key, value in (extra or {}).items():
        variables[key] = ("ON" if value else "OFF") if isinstance(value, bool) else str(value)
    return variables


def configure(app: NeonApp, lay: cmake.BuildLayout, *, fresh: bool, variables: dict[str, str]) -> dict:
    require_build_tools()
    result = cmake.configure(lay, python=app.python(lay.app_dir), fresh=fresh, cache_vars=variables,
                             timeout_s=min(app.settings.build_timeout_s, 600))
    cache = cmake.read_cache(lay.build_dir)
    return {
        "ok": result.ok,
        "build_dir": str(lay.build_dir),
        "profile": cache.get("NEON_MDF_PROFILE") or "normal",
        "secure_boot": cache.get("NEON_MDF_SECURE_BOOT"),
        "python": cache.get("Python3_EXECUTABLE"),
        "diagnostics": cmake.parse_diagnostics(result.output),
        **{k: v for k, v in result.summary(6000).items() if k in ("command", "returncode", "timed_out",
                                                                   "duration_s", "output")},
    }


def build(app: NeonApp, target: Target, app_dir: Path, *, build_target: str | None = None,
          build_dir: str | None = None, profile: str | None = None, fresh: bool = False,
          variables: dict[str, str] | None = None) -> tuple[dict, cmake.BuildLayout]:
    """Configure when needed (first build, fresh, profile change), then build."""
    target.require("build", "build")
    lay =build_layout(app, target, app_dir, build_dir)
    variables = dict(variables or {})
    cache = cmake.read_cache(lay.build_dir)
    report: dict[str, Any] = {"app_dir": str(app_dir), "build_dir": str(lay.build_dir), "target": target.name}
    current_profile = cache.get("NEON_MDF_PROFILE") or ("normal" if cache else None)
    profile_change = profile is not None and current_profile is not None and profile != current_profile
    if not lay.configured or fresh or profile_change or variables:
        if profile is not None:
            variables.setdefault("NEON_MDF_PROFILE", profile)
        conf = configure(app, lay, fresh=fresh or profile_change, variables=variables)
        report["configure"] = conf
        if not conf["ok"]:
            report.update(ok=False, stage="configure", diagnostics=conf["diagnostics"])
            return report, lay
    require_build_tools()
    result = cmake.build(lay, target=build_target, timeout_s=app.settings.build_timeout_s)
    cache = cmake.read_cache(lay.build_dir)
    report.update({
        "ok": result.ok,
        "stage": "build",
        "profile": cache.get("NEON_MDF_PROFILE") or "normal",
        "diagnostics": cmake.parse_diagnostics(result.output),
        "memory_usage": cmake.parse_memory_usage(result.output),
        "size": cmake.parse_size_report(result.output),
        "artifacts": cmake.artifacts(lay.build_dir),
        "build": result.summary(8000),
    })
    return report, lay


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("development", "build", WRITES_FILES)
    def dev_configure(app_dir: str | None = None, profile: Literal["normal", "xip"] | None = None,
                      fresh: bool = False, build_dir: str | None = None, secure_boot: bool | None = None,
                      app_version: str | None = None, cache_variables: dict[str, ConfigValue] | None = None,
                      target: str | None = None) -> dict[str, Any]:
        """Run `cmake --preset <target>` for an application (generates device files and sdkconfig.h).

        profile: memory profile (normal = internal Flash 0x00020000, xip = QSPI 0x30000000); changing
        it in an existing build directory needs fresh=True or a separate build_dir (e.g.
        "build/GT32U2086-xip"). secure_boot: sign images (needs `cryptography`). cache_variables:
        extra -D values, e.g. {"NEON_APP_FIXED_CLOCK_HZ": 10000000} for templates,
        {"NEON_PRINTF_FIXED_CLOCK_HZ": 10000000} for Printf_Log.
        """
        app.policy.require(Permission.WRITE, "dev_configure")
        tgt = app.target(target)
        tgt.require("build", "configure")
        directory = app.app_dir(app_dir)
        lay = build_layout(app, tgt, directory, build_dir)
        variables = configure_vars(tgt, profile, secure_boot, app_version, cache_variables)
        return configure(app, lay, fresh=fresh, variables=variables)

    @registry.tool("development", "build", WRITES_FILES)
    def dev_build(app_dir: str | None = None, build_target: str | None = None, build_dir: str | None = None,
                  profile: Literal["normal", "xip"] | None = None, fresh: bool = False,
                  target: str | None = None) -> dict[str, Any]:
        """Build an application (configuring first if needed) and report the result.

        Returns ok/stage, compiler/linker diagnostics (file, line, message), linker memory usage
        per region, size report, artifacts (ELF, .map, raw .bin, <app>_image.bin boot image) and
        the tail of the build output. build_target selects a CMake target (default: all).
        A successful build validates compile/link/packaging only, not behaviour on hardware.
        """
        app.policy.require(Permission.WRITE, "dev_build")
        tgt = app.target(target)
        directory = app.app_dir(app_dir)
        report, _ = build(app, tgt, directory, build_target=build_target, build_dir=build_dir,
                          profile=profile, fresh=fresh)
        return report
