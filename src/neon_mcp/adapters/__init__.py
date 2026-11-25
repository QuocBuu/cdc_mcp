"""09 Backend & Adapter: isolate MCP logic from SDK files, build tools and hardware access."""

from ..core.tools import Module, Submodule

MODULE = Module(
    number=9, id="adapters", title="Backend & Adapter", kind="infrastructure",
    description="One adapter per external system; modules never call tools or parse formats directly.",
    submodules=[
        Submodule("neon_mdf", "NEON-MDF SDK", "Locate the checkout, version, paths, presets, Python interpreter.",
                  source="adapters/neon_mdf.py"),
        Submodule("device_yaml", "Device description", "Read-only model of mcu-description/devices/*.yaml.",
                  source="adapters/device.py"),
        Submodule("cmake", "CMake/Ninja", "Configure, build, diagnostics, artifacts, generated flash command.",
                  source="adapters/cmake.py"),
        Submodule("kconfig", "Kconfig", "Non-interactive menuconfig with kconfiglib.", source="adapters/kconfig.py"),
        Submodule("elf", "ELF", "pyelftools: sections, segments, symbols, DWARF lines.", source="adapters/elf.py"),
        Submodule("uart", "UART", "Serial port enumeration and bounded capture.", source="adapters/uart.py"),
        Submodule("gdb", "GDB/MI", "GDB Machine Interface client (arm-none-eabi-gdb / gdb-multiarch).",
                  source="adapters/gdb.py"),
        Submodule("openocd", "OpenOCD", "Start/stop OpenOCD with board-verified configs.",
                  source="adapters/openocd.py"),
        Submodule("knowledge_pack", "Knowledge pack files", "Find, read, write and fingerprint versioned packs.",
                  source="adapters/knowledge_pack.py"),
        Submodule("vscode", "VS Code", "Share state with the NEON-MDF VS Code extension.", status="planned"),
    ],
)
