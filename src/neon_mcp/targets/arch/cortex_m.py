"""ARM Cortex-M (ARMv6-M) architecture backend: exception numbers, xPSR, EXC_RETURN,
exception stack frames, core register set and instruction classification.

Cortex-M0 has no fault status registers (no CFSR/HFSR/BFAR): every fault escalates to
HardFault, so the stacked frame and the faulting instruction are the main evidence.
"""

from __future__ import annotations

import re

SYSTEM_EXCEPTIONS = {1: "Reset", 2: "NMI", 3: "HardFault", 11: "SVCall", 14: "PendSV", 15: "SysTick"}
STACK_FRAME = ("r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr")
CORE_REGISTERS = (*(f"r{i}" for i in range(13)), "sp", "lr", "pc", "xpsr", "msp", "psp", "primask", "control")
EXC_RETURN = {
    0xFFFFFFF1: {"returns_to": "handler mode", "stack": "MSP"},
    0xFFFFFFF9: {"returns_to": "thread mode", "stack": "MSP"},
    0xFFFFFFFD: {"returns_to": "thread mode", "stack": "PSP"},
}
_NARROW = re.compile(r"^(ldrb|strb|ldrh|strh|ldrsb|ldrsh)(\.n|\.w)?$")
_WORD = re.compile(r"^(ldr|str|ldm|stm|ldmia|stmia|push|pop)(\.n|\.w)?$")
_BRANCH = re.compile(r"^(b|bl|blx|bx|cbz|cbnz|b(eq|ne|cs|cc|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al))(\.n|\.w)?$")
_MEMORY_OPERAND = re.compile(r"\[(r\d{1,2}|sp|ip)(?:,\s*#(-?(?:0x[0-9a-f]+|\d+)))?\]", re.IGNORECASE)


def exception_name(number: int, interrupts: list[dict]) -> str:
    if number == 0:
        return "Thread mode (no exception)"
    if number in SYSTEM_EXCEPTIONS:
        return SYSTEM_EXCEPTIONS[number]
    if number >= 16:
        irq = number - 16
        for item in interrupts:
            if item["number"] == irq:
                return f"IRQ{irq} {item['name']}"
        return f"IRQ{irq} (undeclared)"
    return f"Reserved exception {number}"


def decode_xpsr(value: int, interrupts: list[dict]) -> dict:
    number = value & 0x3F  # ARMv6-M IPSR is 6 bits
    return {
        "value": f"0x{value:08X}",
        "exception_number": number,
        "exception": exception_name(number, interrupts),
        "thumb": bool(value & (1 << 24)),
        "flags": {"N": bool(value >> 31 & 1), "Z": bool(value >> 30 & 1), "C": bool(value >> 29 & 1),
                  "V": bool(value >> 28 & 1)},
    }


def decode_exc_return(value: int) -> dict:
    info = EXC_RETURN.get(value & 0xFFFFFFFF)
    if info is None:
        return {"value": f"0x{value:08X}", "valid": False,
                "meaning": "Not an ARMv6-M EXC_RETURN (expected 0xFFFFFFF1, 0xFFFFFFF9 or 0xFFFFFFFD)."}
    return {"value": f"0x{value:08X}", "valid": True, **info,
            "meaning": f"Exception taken from {info['returns_to']}; frame stacked on {info['stack']}"
                       + (" (FreeRTOS task stack)" if info["stack"] == "PSP" else "") + "."}


def classify_instruction(mnemonic: str) -> str:
    m = mnemonic.lower()
    if _NARROW.match(m):
        return "narrow_memory_access"
    if _WORD.match(m):
        return "word_memory_access"
    if m.startswith("bkpt"):
        return "breakpoint"
    if m.startswith("svc"):
        return "supervisor_call"
    if m in ("udf", ".word", ".short", "undefined", "(bad)") or m.startswith("udf"):
        return "undefined"
    if _BRANCH.match(m):
        return "branch"
    return "other"


def effective_address(operands: str, frame: dict[str, int]) -> int | None:
    """Address of `[rN, #imm]` when rN is one of the stacked registers (r0-r3, r12)."""
    match = _MEMORY_OPERAND.search(operands)
    if not match:
        return None
    base = match.group(1).lower()
    base = "r12" if base == "ip" else base
    if base not in frame:
        return None
    offset = int(match.group(2), 0) if match.group(2) else 0
    return (frame[base] + offset) & 0xFFFFFFFF
