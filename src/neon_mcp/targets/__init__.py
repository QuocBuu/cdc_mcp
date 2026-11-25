"""08 Target & Device: which MCUs exist and what each one supports."""

from ..core.tools import Module, Submodule

MODULE = Module(
    number=8, id="target", title="Target & Device", kind="infrastructure",
    description="Device registry built from SDK device YAML plus NEON MCP target profiles and capabilities.",
    submodules=[
        Submodule("registry", "Target Registry", "Known targets, selection and capability checks.",
                  source="targets/registry.py"),
        Submodule("capabilities", "Capabilities", "Capability vocabulary and unavailability notes.",
                  source="targets/capabilities.py"),
        Submodule("gt32u2086", "GT32U2086 profile",
                  "Cortex-M0 preset, board defaults, boot modes, debug limits and firmware rules.",
                  source="targets/gt32u2086/target.yaml"),
        Submodule("cortex_m", "ARM Cortex-M backend",
                  "ARMv6-M exception names, xPSR/EXC_RETURN, stack frame, core registers, instruction classes.",
                  source="targets/arch/cortex_m.py"),
        Submodule("riscv", "RISC-V backend", "CSR/PMP registers and trap decoding for Ibex/CVA6.", status="planned"),
        Submodule("fu3", "FU3 profile", "Ibex/CVA6 RISC-V target, once its device YAML exists in NEON-MDF.",
                  status="planned"),
    ],
)
