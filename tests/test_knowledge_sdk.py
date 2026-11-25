import pytest

pytestmark = pytest.mark.anyio


async def test_search_and_read_document(call):
    found = await call("knowledge_search", query="boot mode 100 RESET", limit=3)
    assert found["results"][0]["document"] == "guide/GT32U2086BootModes.md"
    doc = await call("knowledge_read_document", document="MenuConfig", heading="Used in C code")
    assert doc["document"] == "guide/MenuConfig.md" and "sdkconfig.h" in doc["content"]
    listing = await call("knowledge_list_documents", category="guide")
    assert any(d["path"] == "guide/Setup.md" for d in listing["documents"])


async def test_device_and_peripheral(call):
    device = await call("knowledge_get_device")
    assert device["device"] == "GT32U2086" and device["rules"]
    assert any(i["name"] == "USART0" and i["vector_slot"] == 19 for i in device["interrupts"])
    uart = await call("knowledge_get_peripheral", peripheral="UART0", register="LSR")
    assert uart["base"] == "0x440D0000" and uart["interrupts"][0]["name"] == "USART0"
    assert uart["register"]["name"] == "LSR"


async def test_api_search_exact(call):
    result = await call("sdk_search_api", query="neon_uart_transmit")
    exact = result["exact"]
    assert exact["module"] == "uart" and "timeout_polls" in exact["signature"]
    assert [p["name"] for p in exact["doc"]["params"]][:2] == ["huart", "data"]
    assert exact["implementation"].startswith("neon-mdf/components/driver/uart/platform/gt32u2086/neon_uart.c:")
    assert any(t["name"] == "neon_uart_handle_t" for t in exact["related_types"])


async def test_api_search_keywords(call):
    result = await call("sdk_search_api", query="read pin", kind="function", limit=5)
    assert result["matches"][0]["name"] == "neon_gpio_read_pin"


async def test_components_examples_source(call):
    comps = {c["name"]: c for c in (await call("sdk_list_components"))["components"]}
    assert comps["uart"]["kconfig"] == "CONFIG_NEON_MDF_DRIVER_UART"
    assert comps["gpio"]["always_built"] and comps["adc"]["requires_crm_clock"]
    assert "console" in comps and "freertos" in comps
    examples = await call("sdk_find_examples", module="spi")
    assert "SPI_W5500" in [e["name"] for e in examples["examples"]]
    hits = await call("sdk_search_source", pattern="function(neon_mdf_add_executable", path_glob="*.cmake")
    assert hits["matches"][0]["file"] == "neon-mdf/tools/cmake/project.cmake"
    src = await call("sdk_read_source", path=hits["matches"][0]["file"], start_line=1, max_lines=5)
    assert src["end_line"] == 5


async def test_sdk_info(call, sdk_root):
    info = await call("sdk_get_info")
    assert "GT32U2086" in info["presets"] and "uart" in info["api_modules"]
    version_file = sdk_root / "neon-mdf" / "VERSION"
    expected = version_file.read_text().strip() if version_file.is_file() else None
    assert info["sdk_version"] == expected
    assert (await call("session_get_context"))["sdk_version"] == expected
