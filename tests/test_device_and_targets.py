import pytest

from neon_mcp.adapters.device import load_device, parse_int
from neon_mcp.adapters.neon_mdf import NeonMdfSdk
from neon_mcp.system.errors import CapabilityError, InvalidArgumentError, NotFoundError
from neon_mcp.targets.registry import TargetRegistry


def test_gt32u2086_profiles(sdk_root):
    device = load_device(sdk_root / "neon-mdf/mcu-description/devices/GT32U2086.yaml")
    assert device.cpu["core"] == "cortex-m0"
    assert device.application_range("normal", "flash") == (0x00020080, 0x7FF80)
    assert device.application_range("xip", "flash") == (0x30000080, 0x3FF80)
    ram_start, ram_size = device.application_range("normal", "ram")
    assert ram_start == 0x01001000 and ram_start + ram_size == 0x01020000


def test_register_lookup_and_decode(sdk_root):
    device = load_device(sdk_root / "neon-mdf/mcu-description/devices/GT32U2086.yaml")
    uart = device.peripheral("uart0")
    reg, view = uart.register("IER")  # alias of IER_DLM
    assert reg.name == "IER_DLM" and view.name == "IER"
    fields = {f["field"]: f["value"] for f in view.decode(0b10011)}
    assert fields["ERBI"] == 1 and fields["ETBEI"] == 1 and fields["AUCLR"] == 1
    assert device.register_at(reg.address) is reg
    with pytest.raises(NotFoundError):
        uart.register("NOPE")


def test_parse_int():
    assert parse_int("0x1F") == 31 and parse_int("1_000") == 1000 and parse_int(7) == 7
    with pytest.raises(InvalidArgumentError):
        parse_int("twelve")


def test_registry_capabilities(sdk_root):
    registry = TargetRegistry(NeonMdfSdk(sdk_root))
    target = registry.get(None)
    assert target.name == "GT32U2086" and target.supports("uart_flash")
    with pytest.raises(CapabilityError, match="placeholder"):
        target.require("jtag_debug", "debug")
    with pytest.raises(NotFoundError):
        registry.get("FU9")
