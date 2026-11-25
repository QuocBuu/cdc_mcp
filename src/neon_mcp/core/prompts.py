"""Prompt Manager: reusable workflows that tell the agent which NEON MCP tools to chain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..system.errors import NeonError
from .tools import ToolRegistry

if TYPE_CHECKING:
    from .app import NeonApp


def _rules(app: NeonApp) -> str:
    try:
        rules = app.target().profile.get("rules", [])
    except NeonError:  # prompts must render even without a usable target
        rules = []
    return "\n".join(f"- {rule}" for rule in rules) or "- (call knowledge_get_device for target rules)"


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.prompt("new_peripheral_app", "Create, configure, build and run a new app that uses a peripheral.")
    def new_peripheral_app(peripheral: str, app_name: str = "MyApp", template: str = "baremetal") -> str:
        return f"""Create a NEON-MDF application named {app_name} that uses {peripheral}.

1. sdk_find_examples(module="{peripheral.lower()}") and read the closest example's README and Src/.
2. sdk_resolve_dependencies(modules=["{peripheral.lower()}", "printf"]) for Kconfig switches, includes and CRM clocks.
3. sdk_search_api(...) for every driver function you call; follow the documented parameters and
   timeout_polls semantics (poll counts, not milliseconds).
4. dev_create_project(name="{app_name}", parent_dir=<workspace dir>, template="{template}").
5. Write Src/main.c (and extra sources added to neon_mdf_add_executable in CMakeLists.txt).
6. dev_set_config(values=<set_config from step 2>), then dev_build(); fix every reported diagnostic.
7. prog_verify_image(); then, only with the user's go-ahead and boot mode 100, prog_flash_uart(port=...).
8. analysis_capture_uart(...) to check the log; switch the board back to boot mode 000.

Firmware rules for this target:
{_rules(app)}
"""

    @registry.prompt("firmware_review", "Review firmware source against NEON-MDF and target rules.")
    def firmware_review(path: str) -> str:
        return f"""Review the firmware source at {path} for a NEON-MDF target.

Read the file (sdk_read_source) and check each driver call against its header (sdk_search_api with the
exact name: parameters, return status, notes). Report findings with file:line, most severe first.

Check in particular:
{_rules(app)}
- Every neon_status_t result is checked; init/config order matches the driver documentation.
- Interrupt handlers use the generated *_IRQHandler names; NVIC and __enable_irq() are set up last.
- Coding convention V1.3 (knowledge_read_document("NEON_Coding_Convention_V1.3")): naming, braces, Doxygen.
"""

    @registry.prompt("debug_hardfault", "Find the cause of a HardFault on the target.")
    def debug_hardfault(app_dir: str = "") -> str:
        where = f' (app_dir="{app_dir}")' if app_dir else ""
        return f"""Diagnose a HardFault{where}.

1. Get the exception evidence:
   - With a debugger: debug_connect(...), debug_control(action="halt"), then
     analysis_decode_exception(from_debug_session=True{', app_dir="' + app_dir + '"' if app_dir else ''}).
   - Without: ask for the fault handler's dump (8 stacked words r0,r1,r2,r3,r12,lr,pc,xpsr, plus LR at
     handler entry) and call analysis_decode_exception(stack_frame=[...], exc_return=...).
2. Read the source around the faulting PC and LR (sdk_read_source on the reported file:line);
   debug_backtrace() if a debugger is attached.
3. Explain the most likely cause from the findings, then propose a minimal fix.
4. Rebuild (dev_build) and confirm on the board.

Most frequent causes on GT32U2086: byte/halfword access to word-only SRAM, unaligned 32-bit access,
peripheral used before its CRM clock is enabled, stack overflow, function pointer without the Thumb bit.
"""
