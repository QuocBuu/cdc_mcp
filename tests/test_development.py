import json
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.anyio


def _toolchain_ready() -> bool:
    if not all(shutil.which(t) for t in ("arm-none-eabi-gcc", "cmake", "ninja")):
        return False
    from neon_mcp.modules.development.build import _cmake_version
    version = _cmake_version(shutil.which("cmake"))
    return version is not None and version >= (3, 25)


HAS_TOOLCHAIN = _toolchain_ready()


async def test_create_project_and_config(call, tmp_path: Path):
    created = await call("dev_create_project", name="MyApp", parent_dir=str(tmp_path))
    app_dir = Path(created["app_dir"])
    assert (app_dir / "Src" / "main.c").read_text().count("MyApp is running") == 1
    presets = json.loads((app_dir / "CMakePresets.json").read_text())
    assert (app_dir / presets["include"][0]).resolve().is_file()

    config = await call("dev_get_config", filter="UART")
    assert any(o["name"] == "CONFIG_NEON_MDF_DRIVER_UART" and o["value"] == "y" for o in config["options"])

    changed = await call("dev_set_config", values={"CONFIG_NEON_MDF_DRIVER_SPI": False})
    assert changed["changes"] == [{"name": "CONFIG_NEON_MDF_DRIVER_SPI", "old": "y", "new": "n"}]
    assert "# CONFIG_NEON_MDF_DRIVER_SPI is not set" in (app_dir / "sdkconfig").read_text()


async def test_set_config_rejects_bad_values(call, sdk_root: Path, tmp_path: Path):
    app_dir = tmp_path / "GPIO_Input_Output"
    shutil.copytree(sdk_root / "examples" / "GPIO_Input_Output", app_dir)
    assert "Unknown Kconfig option" in await call.error("dev_set_config", app_dir=str(app_dir),
                                                       values={"CONFIG_DOES_NOT_EXIST": 1})
    assert "not valid" in await call.error("dev_set_config", app_dir=str(app_dir),
                                           values={"CONFIG_GT32U2086_EXAMPLE_RX_TIMEOUT_POLLS": 0})
    assert "is an int" in await call.error("dev_set_config", app_dir=str(app_dir),
                                           values={"CONFIG_GT32U2086_EXAMPLE_FIXED_CLOCK_HZ": "fast"})
    before = (app_dir / "sdkconfig").read_text()
    assert before == (sdk_root / "examples" / "GPIO_Input_Output" / "sdkconfig").read_text()


async def test_create_project_rejects_bad_name(call, tmp_path: Path):
    assert "Invalid application name" in await call.error("dev_create_project", name="1bad",
                                                          parent_dir=str(tmp_path))


async def test_check_environment_reports(call):
    report = await call("dev_check_environment")
    names = {c["name"] for c in report["checks"]}
    assert {"arm-none-eabi-gcc", "cmake", "ninja", "python"} <= names
    assert report["ready_to_build"] == all(c["ok"] for c in report["checks"] if c["required"])


@pytest.mark.skipif(not HAS_TOOLCHAIN, reason="needs arm-none-eabi-gcc, ninja and CMake >= 3.25")
async def test_build_template(call, tmp_path: Path):
    created = await call("dev_create_project", name="BuildMe", parent_dir=str(tmp_path))
    report = await call("dev_build", app_dir=created["app_dir"])
    assert report["ok"], report["build"]["output"]
    assert any(p.endswith("BuildMe_image.bin") for p in report["artifacts"]["boot_image"])
    inspected = await call("prog_inspect_image", app_dir=created["app_dir"])
    assert all(i["ok"] and i["header"]["flash_addr"] == "0x00020000" for i in inspected["images"])
    verified = await call("prog_verify_image", app_dir=created["app_dir"])
    assert all(i["valid"] and i["image_profile"] == "normal" for i in verified["images"])
    summary = await call("analysis_elf_summary", app_dir=created["app_dir"])
    assert summary["usage"][0]["profile"] == "normal"
