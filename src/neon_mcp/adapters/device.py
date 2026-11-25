"""Read-only model of a NEON-MDF device description (`mcu-description/devices/<DEVICE>.yaml`).

The YAML is the SDK's single hardware source of truth (it also generates the CMSIS
header, linker script, startup vectors and SVD). This adapter only reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..system.errors import InvalidArgumentError, NotFoundError


def _hex(value: int) -> str:
    return f"0x{value:08X}"


@dataclass(frozen=True)
class FieldDef:
    name: str
    bit_offset: int
    bit_width: int
    description: str

    @property
    def mask(self) -> int:
        return ((1 << self.bit_width) - 1) << self.bit_offset

    def bits(self) -> str:
        hi = self.bit_offset + self.bit_width - 1
        return f"[{hi}:{self.bit_offset}]" if self.bit_width > 1 else f"[{self.bit_offset}]"

    def to_dict(self) -> dict:
        return {"name": self.name, "bits": self.bits(), "bit_offset": self.bit_offset,
                "bit_width": self.bit_width, "description": self.description}


@dataclass(frozen=True)
class RegisterView:
    """One named view of a register address (the register itself or one of its aliases)."""
    name: str
    access: str
    reset: int | None
    description: str
    fields: tuple[FieldDef, ...]

    def decode(self, value: int) -> list[dict]:
        decoded = []
        for f in sorted(self.fields, key=lambda f: f.bit_offset):
            raw = (value & f.mask) >> f.bit_offset
            decoded.append({"field": f.name, "bits": f.bits(), "value": raw, "hex": hex(raw),
                            "description": f.description})
        return decoded


@dataclass(frozen=True)
class RegisterDef:
    peripheral: str
    name: str
    offset: int
    address: int
    size: int
    main: RegisterView
    aliases: tuple[RegisterView, ...]

    def views(self) -> tuple[RegisterView, ...]:
        return (self.main, *self.aliases)

    def to_dict(self, with_fields: bool = True) -> dict:
        def view(v: RegisterView) -> dict:
            d: dict[str, Any] = {"name": v.name, "access": v.access,
                                 "reset": _hex(v.reset) if v.reset is not None else None,
                                 "description": v.description}
            if with_fields:
                d["fields"] = [f.to_dict() for f in sorted(v.fields, key=lambda f: f.bit_offset)]
            return d

        data = {"peripheral": self.peripheral, "offset": f"0x{self.offset:03X}",
                "address": _hex(self.address), "size_bits": self.size, **view(self.main)}
        data["name"] = self.name
        if self.aliases:
            data["aliases"] = [view(a) for a in self.aliases]
        return data


@dataclass(frozen=True)
class PeripheralDef:
    name: str
    base: int
    type: str | None
    description: str
    registers: tuple[RegisterDef, ...]

    def register(self, name: str) -> tuple[RegisterDef, RegisterView]:
        key = name.strip().upper()
        for reg in self.registers:
            if reg.name.upper() == key:
                return reg, reg.main
        for reg in self.registers:
            for alias in reg.aliases:
                if alias.name.upper() == key:
                    return reg, alias
        raise NotFoundError(f"{self.name} has no register '{name}'.",
                            "Registers: " + ", ".join(r.name for r in self.registers))


def _int(value: Any, what: str) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise InvalidArgumentError(f"Invalid integer for {what}: {value!r}")


def _view(data: dict, fallback: dict | None = None) -> RegisterView:
    fallback = fallback or {}
    fields = tuple(
        FieldDef(f["name"], int(f["bit_offset"]), int(f.get("bit_width", 1)), (f.get("description") or "").strip())
        for f in data.get("fields", []) or []
    )
    reset = data.get("reset", fallback.get("reset"))
    return RegisterView(
        name=data["name"],
        access=data.get("access", fallback.get("access", "rw")),
        reset=_int(reset, "reset") if reset is not None else None,
        description=(data.get("description") or "").strip(),
        fields=fields,
    )


class DeviceDescription:
    def __init__(self, path: Path, data: dict) -> None:
        self.path = path
        self.raw = data
        self.name: str = data["device"]
        self.vendor: str | None = data.get("vendor")
        self.family: str | None = data.get("family")
        self.arch: str | None = data.get("arch")
        self.description: str = (data.get("description") or "").strip()
        self.cpu: dict = data.get("cpu", {})
        self.memory: list[dict] = [
            {"name": m["name"], "kind": m.get("kind"), "address": _int(m["address"], "memory.address"),
             "size": _int(m["size"], "memory.size")}
            for m in data.get("memory", [])
        ]
        self.interrupts: list[dict] = sorted(
            ({"number": int(i["number"]), "name": i["name"], "description": (i.get("description") or "").strip()}
             for i in data.get("interrupts", [])), key=lambda i: i["number"])
        self.peripherals: list[PeripheralDef] = [self._peripheral(p) for p in data.get("peripherals", [])]

    @staticmethod
    def _peripheral(p: dict) -> PeripheralDef:
        base = _int(p["base"], "peripheral.base")
        regs = []
        for r in p.get("registers", []) or []:
            offset = _int(r["offset"], "register.offset")
            main = _view(r)
            aliases = tuple(_view(a, r) for a in r.get("aliases", []) or [])
            regs.append(RegisterDef(p["name"], r["name"], offset, base + offset, int(r.get("size", 32)), main, aliases))
        return PeripheralDef(p["name"], base, p.get("type"), (p.get("description") or "").strip(), tuple(regs))

    # --- Lookup ------------------------------------------------------------------------------------
    def peripheral(self, name: str) -> PeripheralDef:
        key = name.strip().upper()
        for p in self.peripherals:
            if p.name.upper() == key:
                return p
        raise NotFoundError(f"{self.name} has no peripheral '{name}'.",
                            "Peripherals: " + ", ".join(p.name for p in self.peripherals))

    def register_at(self, address: int) -> RegisterDef:
        for p in self.peripherals:
            for r in p.registers:
                if r.address == address:
                    return r
        raise NotFoundError(f"No register of {self.name} is mapped at {_hex(address)}.")

    def locate(self, address: int) -> dict:
        """What lives at `address`: a peripheral register/instance or a memory region."""
        for p in self.peripherals:
            end = max((r.offset for r in p.registers), default=0) + 4
            if p.base <= address < p.base + max(end, 0x100):
                reg = next((r for r in p.registers if r.address == address), None)
                return {"kind": "peripheral", "peripheral": p.name, "register": reg.name if reg else None,
                        "offset": f"0x{address - p.base:03X}"}
        for m in self.memory:
            if m["address"] <= address < m["address"] + m["size"]:
                return {"kind": m["kind"], "region": m["name"], "offset": f"0x{address - m['address']:X}"}
        return {"kind": "unmapped"}

    def region(self, name: str) -> dict:
        for m in self.memory:
            if m["name"] == name:
                return m
        raise NotFoundError(f"{self.name} has no memory region '{name}'.")

    def profiles(self) -> list[dict]:
        """Memory profiles with absolute addresses for every layout entry."""
        result = []
        for prof in self.raw.get("profile_param", []) or []:
            entry: dict[str, Any] = {"name": prof["name"]}
            for kind in ("flash", "ram"):
                mapping = prof.get(kind)
                if not mapping:
                    continue
                region = self.region(mapping["region"])
                layout = []
                for item in mapping.get("layout", []) or []:
                    offset = _int(item.get("offset", 0), "layout.offset")
                    size = region["size"] - offset if item.get("size") == "remaining" else _int(item["size"], "layout.size")
                    layout.append({"name": item["name"], "usage": item.get("usage"),
                                   "start": _hex(region["address"] + offset),
                                   "end": _hex(region["address"] + offset + size - 1),
                                   "size": size, "description": (item.get("description") or "").strip()})
                entry[kind] = {"region": region["name"], "layout": layout}
            result.append(entry)
        return result

    def application_range(self, profile: str, kind: str) -> tuple[int, int]:
        """(start, size) of the allocatable `application` area for a profile's flash/ram."""
        for prof in self.profiles():
            if prof["name"] == profile and kind in prof:
                for item in prof[kind]["layout"]:
                    if item["usage"] == "allocatable":
                        return int(item["start"], 16), item["size"]
        raise NotFoundError(f"Profile '{profile}' has no allocatable {kind} area.")

    def summary(self) -> dict:
        return {
            "device": self.name, "vendor": self.vendor, "family": self.family, "arch": self.arch,
            "description": self.description, "cpu": self.cpu,
            "memory": [{**m, "address": _hex(m["address"]), "end": _hex(m["address"] + m["size"] - 1)}
                       for m in self.memory],
            "profiles": self.profiles(),
            "peripherals": [{"name": p.name, "base": _hex(p.base), "type": p.type, "registers": len(p.registers)}
                            for p in self.peripherals],
            "interrupts": [{**i, "irqn": f"{i['name']}_IRQn", "vector_slot": 16 + i["number"]}
                           for i in self.interrupts],
            "source": str(self.path),
        }


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime_ns: int) -> DeviceDescription:
    with open(path, encoding="utf-8") as f:
        return DeviceDescription(Path(path), yaml.safe_load(f))


def load_device(path: Path) -> DeviceDescription:
    return _load_cached(str(path), path.stat().st_mtime_ns)


def parse_int(value: int | str, what: str = "value") -> int:
    """Accept 123, '123', '0x7B', '0b1111011' (underscores allowed)."""
    if isinstance(value, bool):
        raise InvalidArgumentError(f"{what} must be an integer, not a boolean.")
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip().replace("_", ""), 0)
    except ValueError as exc:
        raise InvalidArgumentError(f"{what} '{value}' is not an integer (use decimal or 0x hex).") from exc
