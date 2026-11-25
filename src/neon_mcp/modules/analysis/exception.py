"""Exception submodule: decode a Cortex-M0 HardFault from its stacked frame.

ARMv6-M has no fault status registers, so the evidence is the exception stack frame
(r0-r3, r12, lr, pc, xpsr), EXC_RETURN, the active exception number and the faulting
instruction. Inputs come from the user (log/debugger dump) or a live debug session.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...adapters.device import DeviceDescription, parse_int
from ...core.tools import READ_ONLY, ToolRegistry
from ...system.errors import InvalidArgumentError, NeonError
from ...system.process import run
from ...system.security import Permission
from ...targets.arch import cortex_m
from ..debug.session import get_manager
from ..development.build import find_elf
from .elf import resolve_addresses

if TYPE_CHECKING:
    from ...core.app import NeonApp

GENERIC_CAUSES = [
    "Byte/halfword access to GT32U2086 SRAM (SRAM is aligned-32-bit only): uint8_t/uint16_t buffers, packed "
    "structs, or newlib/third-party code not built with the SDK policy.",
    "Unaligned 32-bit access (always faults on Cortex-M0), e.g. casting a byte pointer to uint32_t *.",
    "Access to an unmapped address or a peripheral whose CRM clock/reset is not enabled.",
    "Branch to an address without the Thumb bit (INVSTATE), e.g. corrupted function pointer or return address.",
    "Stack overflow corrupting the frame/return address (check stack size, FreeRTOS task stacks are in words).",
    "BKPT without a debugger, SVC with interrupts masked, or an undefined instruction.",
]


def disassemble(elf: Path, address: int) -> dict[str, str] | None:
    objdump = shutil.which("arm-none-eabi-objdump")
    if objdump is None:
        return None
    result = run([objdump, "-d", f"--start-address=0x{address:x}", f"--stop-address=0x{address + 4:x}", str(elf)],
                 elf.parent, timeout_s=30)
    for line in result.output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().rstrip(":").lower() == f"{address:x}":
            operands = parts[3].split(";")[0].split("@")[0].strip() if len(parts) > 3 else ""
            return {"bytes": parts[1].strip(), "mnemonic": parts[2].strip(), "operands": operands,
                    "text": f"{parts[2].strip()} {operands}".strip()}
    return None


def _executable(device: DeviceDescription, address: int) -> bool:
    for profile in device.profiles():
        for kind in ("flash", "ram"):
            try:
                start, size = device.application_range(profile["name"], kind)
            except NeonError:
                continue
            if start <= address < start + size:
                return True
    return device.locate(address).get("region") == "BOOT_ROM"


def analyze(device: DeviceDescription, frame: dict[str, int], exc_return: int | None,
            handler_xpsr: int | None, elf: Path | None) -> dict[str, Any]:
    interrupts = device.interrupts
    findings: list[dict[str, str]] = []

    def finding(severity: str, cause: str, explanation: str) -> None:
        findings.append({"severity": severity, "cause": cause, "explanation": explanation})

    stacked_xpsr = cortex_m.decode_xpsr(frame["xpsr"], interrupts)
    pc, lr = frame["pc"], frame["lr"]
    result: dict[str, Any] = {
        "stack_frame": {k: f"0x{v:08X}" for k, v in frame.items()},
        "stacked_xpsr": stacked_xpsr,
        "pc": {"value": f"0x{pc:08X}", "location": device.locate(pc)},
        "lr": {"value": f"0x{lr:08X}", "location": device.locate(lr)},
    }
    if handler_xpsr is not None:
        active = cortex_m.decode_xpsr(handler_xpsr, interrupts)
        result["active_exception"] = active["exception"]
    if exc_return is not None:
        decoded = cortex_m.decode_exc_return(exc_return)
        result["exc_return"] = decoded
        if not decoded["valid"]:
            finding("info", "LR is not an EXC_RETURN value",
                    "Pass LR as read at handler entry; with a wrong value the chosen stack (MSP/PSP) may be wrong.")

    if elf is not None:
        try:
            symbols = resolve_addresses(elf, [pc, lr])
            result["pc"]["symbol"], result["lr"]["symbol"] = symbols[0], symbols[1]
        except NeonError as exc:
            result["symbol_error"] = str(exc)

    if not stacked_xpsr["thumb"]:
        finding("high", "INVSTATE: Thumb bit clear in the stacked xPSR",
                "The CPU tried to execute in ARM state, which Cortex-M cannot. Usually a branch to an "
                "address with bit 0 clear: a corrupted or hand-built function pointer, or a smashed return address.")
    if pc & 1:
        finding("medium", "Stacked PC is odd",
                "Hardware always stacks an even PC: the frame was probably read from the wrong stack "
                "(MSP vs PSP) or is corrupted.")
    if not _executable(device, pc):
        finding("high", "PC outside executable memory",
                f"0x{pc:08X} is {device.locate(pc)}; execution jumped through a corrupted pointer or return "
                "address, or a stack overflow overwrote the frame. The caller is near LR.")
    if lr >= 0xFFFFFFF0:
        finding("info", "Stacked LR is an EXC_RETURN value",
                "The fault happened inside an exception handler, shortly after it was entered.")
    if stacked_xpsr["exception_number"]:
        finding("info", f"Fault occurred while handling {stacked_xpsr['exception']}",
                "Check that handler (and the IRQ's CRM clock and peripheral state).")

    instruction = disassemble(elf, pc) if elf is not None and _executable(device, pc) else None
    if instruction:
        kind = cortex_m.classify_instruction(instruction["mnemonic"])
        instruction["class"] = kind
        result["instruction"] = instruction
        address = cortex_m.effective_address(instruction["operands"], frame)
        if address is not None:
            instruction["effective_address"] = f"0x{address:08X}"
            instruction["target"] = device.locate(address)
        target_kind = device.locate(address)["kind"] if address is not None else None
        if kind == "narrow_memory_access" and target_kind in (None, "ram"):
            finding("high", f"Byte/halfword access '{instruction['text']}'"
                            + (f" to SRAM 0x{address:08X}" if address is not None else ""),
                    "GT32U2086 SRAM only accepts aligned 32-bit accesses; narrow accesses raise a bus error, which "
                    "escalates to HardFault on Cortex-M0. Use uint32_t storage and the SDK <string.h> functions.")
        elif kind in ("word_memory_access", "narrow_memory_access") and address is not None:
            if kind == "word_memory_access" and address % 4:
                finding("high", f"Unaligned word access to 0x{address:08X}",
                        "Cortex-M0 faults on every unaligned LDR/STR; check pointer casts and packed structures.")
            elif target_kind == "unmapped":
                finding("high", f"Access to unmapped address 0x{address:08X}",
                        "The pointer is invalid (NULL, uninitialized or corrupted).")
            elif target_kind == "peripheral":
                finding("medium", f"Peripheral access at 0x{address:08X} ({instruction['target'].get('peripheral')})",
                        "A bus error here usually means the peripheral's CRM clock or reset release is missing, "
                        "or the register access width is wrong.")
        elif kind == "breakpoint":
            finding("high", "BKPT instruction", "A breakpoint instruction without an attached debugger causes HardFault.")
        elif kind == "supervisor_call":
            finding("high", "SVC instruction",
                    "SVC executed while interrupts are masked (PRIMASK=1, e.g. before the scheduler starts) "
                    "escalates to HardFault.")
        elif kind == "undefined":
            finding("high", "Undefined instruction", "Corrupted code, data executed as code, or a wrong CPU target.")
    elif elf is None:
        result["note"] = "No ELF: pass elf_path/app_dir to get symbols, source lines and the faulting instruction."
    elif shutil.which("arm-none-eabi-objdump") is None:
        result["note"] = "arm-none-eabi-objdump not found: the faulting instruction was not disassembled."

    result["findings"] = findings or [{"severity": "unknown", "cause": "No specific cause identified",
                                       "explanation": "Check the common Cortex-M0 HardFault causes listed below."}]
    result["common_causes"] = GENERIC_CAUSES
    return result


def register(registry: ToolRegistry, app: NeonApp) -> None:

    @registry.tool("analysis", "exception", READ_ONLY)
    def analysis_decode_exception(stack_frame: list[int | str] | None = None, exc_return: int | str | None = None,
                                  handler_xpsr: int | str | None = None, from_debug_session: bool = False,
                                  elf_path: str | None = None, app_dir: str | None = None,
                                  build_dir: str | None = None, target: str | None = None) -> dict[str, Any]:
        """Decode a Cortex-M0 HardFault/exception and suggest probable causes.

        stack_frame: the 8 words at the stacking SP, in order r0, r1, r2, r3, r12, lr, pc, xpsr (e.g. from
        a fault handler log). exc_return: LR at handler entry (0xFFFFFFF9 MSP / 0xFFFFFFFD PSP).
        handler_xpsr: xPSR inside the handler (gives the active exception). from_debug_session=True reads
        all of these from the halted target via debug_connect instead (needs --allow-hardware).
        With an ELF (elf_path or app_dir) PC/LR are mapped to function and file:line and the faulting
        instruction is disassembled (arm-none-eabi-objdump) to check GT32U2086's word-only SRAM rule,
        alignment and unmapped accesses.
        """
        device = app.target(target).device()
        stack_pointer = None
        if from_debug_session:
            app.policy.require(Permission.HARDWARE, "analysis_decode_exception (debug session)")
            manager = get_manager(app)
            with manager.lock:
                regs = manager.registers(["lr", "xpsr", "msp", "psp", "sp"])
                if "lr" not in regs or "xpsr" not in regs:
                    raise NeonError("The GDB server did not report lr/xpsr.")
                exc_value, handler_value = regs["lr"], regs["xpsr"]
                use_psp = cortex_m.decode_exc_return(exc_value).get("stack") == "PSP"
                stack_pointer = regs.get("psp" if use_psp else "msp", regs.get("sp"))
                if stack_pointer is None:
                    raise NeonError("Cannot determine the stack pointer from the debug session.")
                words = manager.read_words(stack_pointer, 8)
        else:
            if not stack_frame or len(stack_frame) < 8:
                raise InvalidArgumentError(
                    "stack_frame needs 8 words: r0, r1, r2, r3, r12, lr, pc, xpsr.",
                    "Or connect a debugger and use from_debug_session=True.")
            words = [parse_int(w, "stack word") & 0xFFFFFFFF for w in stack_frame[:8]]
            exc_value = parse_int(exc_return, "exc_return") if exc_return is not None else None
            handler_value = parse_int(handler_xpsr, "handler_xpsr") if handler_xpsr is not None else None
        elf = None
        elf_note = None
        if elf_path or app_dir:
            elf = find_elf(app, elf_path, app_dir, build_dir)
        elif app.session.app_dir:
            try:
                elf = find_elf(app, None, None, build_dir)
            except NeonError as exc:
                elf_note = str(exc)
        result = analyze(device, dict(zip(cortex_m.STACK_FRAME, words, strict=True)), exc_value, handler_value, elf)
        result["elf"] = str(elf) if elf else None
        if stack_pointer is not None:
            result["stack_pointer"] = f"0x{stack_pointer:08X}"
        if elf_note:
            result["elf_note"] = elf_note
        return result
