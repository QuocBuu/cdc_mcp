from pathlib import Path

import pytest

from neon_mcp.targets.arch import cortex_m

pytestmark = pytest.mark.anyio

EXPECTED_MODULES = ["core", "knowledge", "sdk", "development", "debug", "programming", "analysis",
                    "target", "adapters", "system"]


async def test_catalog_matches_architecture(call):
    catalog = await call("neon_list_modules")
    modules = catalog["modules"]
    assert [m["id"] for m in modules] == EXPECTED_MODULES
    assert [m["number"] for m in modules] == [f"{i:02d}" for i in range(1, 11)]
    tools = [t for m in modules for t in m["tools"]]
    assert len(tools) == len(set(tools)) == catalog["tool_count"]
    for module in modules:
        for sub in module["submodules"]:
            if sub["status"] == "implemented":
                assert sub["source"], f"{module['id']}/{sub['name']} has no source file"
                assert (Path(__file__).parents[1] / "src" / "neon_mcp" / sub["source"]).exists(), sub["source"]
            else:
                assert not sub["tools"]
    debug = await call("neon_list_modules", module="debug")
    names = {s["name"]: s for s in debug["modules"][0]["submodules"]}
    assert names["multicore"]["status"] == "planned" and "debug_connect" in names["session"]["tools"]


async def test_every_tool_is_catalogued(call):
    listed = {t.name for t in (await call.client.list_tools()).tools}
    catalog = await call("neon_list_modules")
    assert listed == {t for m in catalog["modules"] for t in m["tools"]}


async def test_prompts_and_resources(call):
    prompts = {p.name for p in (await call.client.list_prompts()).prompts}
    assert prompts == {"new_peripheral_app", "firmware_review", "debug_hardfault"}
    rendered = await call.client.get_prompt("new_peripheral_app", {"peripheral": "SPI"})
    assert "sdk_resolve_dependencies" in rendered.messages[0].content.text
    arch = await call.client.read_resource("neon://architecture")
    assert '"debug"' in arch.contents[0].text


async def test_dependency_resolver(call, sdk_root: Path):
    result = await call("sdk_resolve_dependencies", modules=["adc", "printf", "freertos"],
                        app_dir=str(sdk_root / "examples" / "GPIO_Input_Output"))
    adc = next(c for c in result["components"] if c["component"] == "adc")
    assert adc["crm"]["calls"][0] == "neon_crm_peripheral_clock_enable(NEON_CRM_PERIPHERAL_ADC);"
    assert adc["kconfig"]["option"] == "CONFIG_NEON_MDF_DRIVER_ADC"
    assert "ADC_Sampling" in adc["examples"]
    assert any("neon_mdf_add_freertos" in line for line in result["cmake"])
    console = next(c for c in result["components"] if c["component"] == "console")
    assert console["kconfig"]["option"] == "CONFIG_NEON_MDF_DRIVER_UART"
    assert "Unknown component" in await call.error("sdk_resolve_dependencies", modules=["warpdrive"])


async def test_generate_device_files(call, tmp_path: Path):
    result = await call("dev_generate_device_files", output_dir=str(tmp_path / "gen"), profile="xip")
    names = {Path(f["path"]).name for f in result["files"]}
    assert "GT32U2086.h" in names and any(n.endswith(".ld") for n in names)


async def test_log_analyzer(call):
    log = "boot\n[INFO] counter=1\n[PASS] crc ok\n[FAIL] spi timeout at 0x00020A3C\nHardFault!\n"
    summary = await call("analysis_analyze_log", text=log)
    assert summary["verdict"] == "fail" and summary["tags"] == {"INFO": 1, "PASS": 1, "FAIL": 1}
    assert summary["addresses"] == ["0x00020A3C"] and summary["suspicious_lines"] == ["HardFault!"]


def test_cortex_m_backend():
    assert cortex_m.decode_exc_return(0xFFFFFFFD)["stack"] == "PSP"
    assert not cortex_m.decode_exc_return(0x12345678)["valid"]
    assert cortex_m.decode_xpsr(0x01000013, [{"number": 3, "name": "USART0"}])["exception"] == "IRQ3 USART0"
    assert cortex_m.classify_instruction("ldrb") == "narrow_memory_access"
    assert cortex_m.classify_instruction("bic") == "other"
    assert cortex_m.effective_address("r3, [r0, #4]", {"r0": 0x01001000}) == 0x01001004


async def test_exception_without_elf(call):
    frame = ["0x0", "0x1", "0x2", "0x3", "0xC", "0x00020101", "0xDEADBEEE", "0x00000000"]
    result = await call("analysis_decode_exception", stack_frame=frame, exc_return="0xFFFFFFFD",
                        handler_xpsr="0x3")
    causes = " | ".join(f["cause"] for f in result["findings"])
    assert result["active_exception"] == "HardFault" and result["exc_return"]["stack"] == "PSP"
    assert "INVSTATE" in causes and "PC outside executable memory" in causes
    assert "too few" not in causes
    assert "8 words" in await call.error("analysis_decode_exception", stack_frame=["0x1"])
