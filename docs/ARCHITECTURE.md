# NEON MCP architecture

NEON MCP is organized as **modules → submodules → tools**. Each submodule is one Python file, and
every tool is registered under the submodule that owns it. The catalog at the end of this document
is generated from the code (`ToolRegistry`), so it always matches what the server exposes.

The same catalog is available at runtime:

- the `neon_list_modules` tool;
- the `neon://architecture` resource;
- the `_meta` of each tool (`neon-mcp/module`, `neon-mcp/submodule`).

## Modules

| # | Module | Role |
|---|---|---|
| 01 | MCP Core | Server, tool/resource/prompt registries, sessions, transports, install page |
| 02 | Knowledge | Documentation search, device and register knowledge |
| 03 | SDK | SDK discovery, components, C API, sources, examples, dependencies, knowledge packs |
| 04 | Development | Toolchain check, project creation, Kconfig, device code generation, builds |
| 05 | Debug | GDB/MI sessions, CPU control, registers, memory, peripherals, breakpoints, backtraces |
| 06 | Programming | Image inspection and verification, boot modes, UART programming |
| 07 | Analysis | ELF, Cortex-M exception decoding, register decoding, UART logs |
| 08 | Target & Device | Target registry, capabilities, MCU profiles, CPU architecture backends |
| 09 | Backend & Adapter | One adapter per external system (SDK, CMake, Kconfig, ELF, UART, GDB, OpenOCD, packs) |
| 10 | System & Security | Configuration, workspace sandbox, processes, permissions, logging, errors |

## Layers and dependency rules

```text
AI agent / IDE ──MCP──► core (server, registries, session, prompts, resources, transports)
                              │
           modules/ (02–07: knowledge, sdk, development, debug, programming, analysis)
                              │  calls downward only
           targets/ (08)  ◄───┤  registry, capabilities, profiles, CPU backends (Cortex-M)
           adapters/ (09) ◄───┤  neon_mdf, device_yaml, cmake, kconfig, elf, uart, gdb, openocd, packs
           system/ (10)   ◄───┘  config, workspace, process, security, logging, errors
                              │
                    NEON-MDF checkout (docs, device YAML, headers, CMake, Python tools)
```

- **One file per submodule**, each with a `register(registry, app)` function. A module's
  `__init__.py` declares its `MODULE` (submodules and status) and calls each file's `register`.
- **Functional modules neither run external commands nor parse file formats**; adapters do.
- **MCU-specific knowledge lives in `targets/`**: profile YAML and CPU architecture backends.
  Modules only ask a target for its capabilities.
- **Tools are registered with `registry.tool(module, submodule, annotations)`.** A submodule
  marked `planned` cannot register tools.

## Knowledge packs

The device, C API, documentation and SDK data of each NEON-MDF release are pre-generated as JSON
in `src/neon_mcp/packs/neon-mdf-<version>/`:

| File | Contents |
|---|---|
| `devices/<DEVICE>.json` | Memory map, memory profiles, interrupts, peripherals → registers → bit fields (absolute addresses) |
| `api.json` | Functions, inline functions, enums, structs, typedefs and macros with Doxygen and `file:line` |
| `docs.json` | Documentation split by heading, used for search |
| `sdk.json` | Presets, components (Kconfig, backends, CRM) and examples |
| `manifest.json` | SDK version, counts, devices and the fingerprint of the source checkout |

At startup the server reads `neon-mdf/VERSION` from the checkout and selects the pack of that
version:

- **Matching fingerprint** (an unmodified release): device, API and documentation data come from
  the pack.
- **Different fingerprint** (a modified checkout, or one between releases): the checkout is parsed
  directly, so answers match the code being built. Files edited while the server runs are detected
  by modification time.
- **No pack** for that version: the checkout is parsed directly.

The status is reported by `sdk_get_info` (`knowledge_pack`) and `session_get_context`.

- **Generate:** `neon-mcp-pack --sdk <checkout>` (`--force` regenerates, `--check` reports whether
  the bundled pack still matches the generator).
- **Automation:** the `Knowledge packs` workflow runs daily, generates packs for new NEON-MDF
  releases, commits them, then reruns CI and Pages. Installs that run from git
  (`uvx --from git+...`) pick up new packs on their next start.
- **Tests:** `test_bundled_pack_is_up_to_date` fails when a parser changes without regenerating
  the pack.

## Install page

`src/neon_mcp/web/index.html` is filled with data from the server itself (`core/web.py`): the
user-facing capability groups, tool reference, SDK data per release and real output of read-only
tools. The Streamable HTTP transport serves it at `/`; `pages/build.py` builds the same page for
GitHub Pages. Every tool must belong to one capability group in `core/web.py` (checked by tests).

## Hardware debugging

The SDK's OpenOCD configuration for the GT32U2086 is still a placeholder, so `debug_connect` needs
either a configuration verified with the probe and board, or the address of a running GDB server
(OpenOCD, J-Link, pyOCD). The debug flow is tested with `gdb-multiarch` against a simulated
Cortex-M0 GDB server (`tests/fake_gdbserver.py`), not yet on a physical board.

## Extending NEON MCP

1. **Add a tool to an existing submodule:** write the function in the submodule's file and decorate
   it with `@registry.tool("<module>", "<submodule>", READ_ONLY | WRITES_FILES | TOUCHES_HARDWARE)`.
   Add it to a capability group in `core/web.py`.
2. **Add a submodule:** create the file, add a `Submodule(...)` to the module's `MODULE`, and call
   the file's `register`.
3. **Implement a planned submodule:** set its status to implemented, set `source`, then add tools.
4. **Add an MCU:**
   - add the device YAML to NEON-MDF;
   - add `targets/<name>/target.yaml`;
   - for a new CPU architecture, add a backend in `targets/arch/`.
5. **Refresh the catalog below:** `python docs/update_catalog.py --sdk ../neon_mdf`.
6. **Required tests:** `test_catalog_matches_architecture` checks that every implemented submodule
   has a source file and every tool is in the catalog.

## Module catalog (generated from code)

### 01 MCP Core (`core`) — 7/7 submodules

MCP server lifecycle, tool/resource/prompt registries, sessions and transports.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **server** — Builds the server and assembles every module. | ✅ | `core/server.py` | — |
| **tool_registry** — Registers tools under module/submodule and publishes the catalog. | ✅ | `core/tools.py` | `neon_list_modules` |
| **resource_registry** — neon:// resources with SDK, documentation and device data. | ✅ | `core/resources.py` | `neon://sdk/info`, `neon://architecture`, `neon://docs/index`, `neon://guide/{name}`, `neon://examples/{name}`, `neon://device/{target}` |
| **prompt_manager** — Workflow prompts: new peripheral app, firmware review, HardFault debugging. | ✅ | `core/prompts.py` | prompt `new_peripheral_app`, prompt `firmware_review`, prompt `debug_hardfault` |
| **session_manager** — Per-connection defaults (target, app, serial port, baud). | ✅ | `core/session.py` | `session_get_context`, `session_set_context` |
| **transport** — stdio (default) and Streamable HTTP. | ✅ | `core/transport.py` | — |
| **install_page** — Install guide with live catalog and demos: served at / over HTTP, published on GitHub Pages. | ✅ | `core/web.py` | — |

### 02 Knowledge Module (`knowledge`) — 4/5 submodules

SDK documentation, device data and register knowledge, read from the NEON-MDF checkout.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **documentation** — Index, list and read README, guide/ and example READMEs. | ✅ | `modules/knowledge/documentation.py` | `knowledge_list_documents`, `knowledge_read_document` |
| **search** — Ranked keyword search over documentation sections. | ✅ | `modules/knowledge/search.py` | `knowledge_search` |
| **device_knowledge** — CPU, memory map, profiles, IRQs, boot modes, debug limits, firmware rules. | ✅ | `modules/knowledge/device_knowledge.py` | `knowledge_get_device` |
| **register_knowledge** — Peripheral registers, fields, aliases and IRQs. | ✅ | `modules/knowledge/register_knowledge.py` | `knowledge_get_peripheral` |
| **external_documents** — Index vendor PDFs (datasheet, technical reference manual, errata) for search. | ⏳ planned | — | — |

### 03 SDK Module (`sdk`) — 7/7 submodules

Discovery, components, public C API, source code, examples and dependencies of NEON-MDF.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **sdk_discovery** — SDK version, path, git revision, presets, tools. | ✅ | `modules/sdk/sdk_discovery.py` | `sdk_get_info` |
| **component** — Drivers, console and FreeRTOS with Kconfig switches. | ✅ | `modules/sdk/component.py` | `sdk_list_components` |
| **api** — Functions, types and macros with Doxygen, parsed from headers. | ✅ | `modules/sdk/api.py` | `sdk_search_api` |
| **source** — grep-like search and line-numbered reading. | ✅ | `modules/sdk/source.py` | `sdk_search_source`, `sdk_read_source` |
| **example** — Example applications by keyword or driver used. | ✅ | `modules/sdk/example.py` | `sdk_find_examples` |
| **dependency** — Kconfig switches, includes, CRM clocks and CMake needed for a set of components. | ✅ | `modules/sdk/dependency.py` | `sdk_resolve_dependencies` |
| **knowledge_pack** — Device, API and docs data pre-generated per NEON-MDF release; used when the checkout matches. | ✅ | `modules/sdk/knowledge_pack.py` | — |

### 04 Development Module (`development`) — 5/5 submodules

Toolchain check, project creation, Kconfig configuration, device code generation and builds.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **toolchain** — Check arm-none-eabi-gcc/newlib, CMake >= 3.25, Ninja, Python deps. | ✅ | `modules/development/toolchain.py` | `dev_check_environment` |
| **project** — Create bare-metal or FreeRTOS apps from SDK templates. | ✅ | `modules/development/project.py` | `dev_create_project` |
| **configuration** — Read and change sdkconfig (menuconfig rules). | ✅ | `modules/development/configuration.py` | `dev_get_config`, `dev_set_config` |
| **code_generation** — Preview device files generated from the YAML. | ✅ | `modules/development/code_generation.py` | `dev_generate_device_files` |
| **build** — CMake configure/build with diagnostics, memory usage and artifacts. | ✅ | `modules/development/build.py` | `dev_configure`, `dev_build` |

### 05 Debug Module (`debug`) — 7/8 submodules

GDB/MI session (OpenOCD or existing GDB server), CPU control, registers, memory, peripherals, breakpoints and source-level backtraces.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **session** — Connect/disconnect, OpenOCD lifecycle, target state. | ✅ | `modules/debug/session.py` | `debug_connect`, `debug_disconnect` |
| **cpu** — Halt, continue, step, next, finish, reset. | ✅ | `modules/debug/cpu.py` | `debug_control` |
| **register** — Core registers with xPSR decoding. | ✅ | `modules/debug/register_access.py` | `debug_read_registers` |
| **memory** — Aligned word read/write with memory-map labels. | ✅ | `modules/debug/memory.py` | `debug_read_memory`, `debug_write_memory` |
| **peripheral** — Live peripheral registers decoded with the device YAML. | ✅ | `modules/debug/peripheral.py` | `debug_read_peripheral` |
| **breakpoint** — Hardware breakpoints and watchpoints. | ✅ | `modules/debug/breakpoint.py` | `debug_breakpoint` |
| **source_debug** — Backtrace, source lines and local variables. | ✅ | `modules/debug/source_debug.py` | `debug_backtrace` |
| **multicore** — Per-core selection and state (GT32U2086 is single-core). | ⏳ planned | — | — |

### 06 Programming Module (`programming`) — 4/4 submodules

Inspect and verify BootROM images, boot modes, serial ports and UART programming.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **image** — Decode BootROM headers with gt32u2086_image.py. | ✅ | `modules/programming/image.py` | `prog_inspect_image` |
| **verify** — Pre-programming checks with gt32u2086_flash.py --check-only. | ✅ | `modules/programming/verify.py` | `prog_verify_image` |
| **boot** — Boot modes and the board-side programming procedure. | ✅ | `modules/programming/boot.py` | `prog_list_boot_modes` |
| **flash** — Serial ports and ROMCODE UART programming of internal Flash. | ✅ | `modules/programming/flash.py` | `prog_list_serial_ports`, `prog_flash_uart` |

### 07 Analysis Module (`analysis`) — 4/5 submodules

ELF memory/symbols, register decoding, Cortex-M0 exception decoding and UART log analysis.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **elf** — Sections, Flash/RAM usage per profile, largest symbols, address → file:line. | ✅ | `modules/analysis/elf.py` | `analysis_elf_summary`, `analysis_resolve_address` |
| **exception** — HardFault frame, EXC_RETURN, faulting instruction and probable causes. | ✅ | `modules/analysis/exception.py` | `analysis_decode_exception` |
| **register_decoder** — Raw value → named fields from the device YAML. | ✅ | `modules/analysis/register_decoder.py` | `analysis_decode_register` |
| **log_analyzer** — Capture UART output and summarize logs. | ✅ | `modules/analysis/log_analyzer.py` | `analysis_capture_uart`, `analysis_analyze_log` |
| **memory_analyzer** — Linker map breakdown per object file/library and stack usage (-fstack-usage). | ⏳ planned | — | — |

### 08 Target & Device (`target`) — 4/6 submodules

Device registry built from SDK device YAML plus NEON MCP target profiles and capabilities.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **registry** — Known targets, selection and capability checks. | ✅ | `targets/registry.py` | `target_list` |
| **capabilities** — Capability vocabulary and unavailability notes. | ✅ | `targets/capabilities.py` | — |
| **gt32u2086** — Cortex-M0 preset, board defaults, boot modes, debug limits and firmware rules. | ✅ | `targets/gt32u2086/target.yaml` | — |
| **cortex_m** — ARMv6-M exception names, xPSR/EXC_RETURN, stack frame, core registers, instruction classes. | ✅ | `targets/arch/cortex_m.py` | — |
| **riscv** — CSR/PMP registers and trap decoding for Ibex/CVA6. | ⏳ planned | — | — |
| **fu3** — Ibex/CVA6 RISC-V target, once its device YAML exists in NEON-MDF. | ⏳ planned | — | — |

### 09 Backend & Adapter (`adapters`) — 9/10 submodules

One adapter per external system; modules never call tools or parse formats directly.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **neon_mdf** — Locate the checkout, version, paths, presets, Python interpreter. | ✅ | `adapters/neon_mdf.py` | — |
| **device_yaml** — Read-only model of mcu-description/devices/*.yaml. | ✅ | `adapters/device.py` | — |
| **cmake** — Configure, build, diagnostics, artifacts, generated flash command. | ✅ | `adapters/cmake.py` | — |
| **kconfig** — Non-interactive menuconfig with kconfiglib. | ✅ | `adapters/kconfig.py` | — |
| **elf** — pyelftools: sections, segments, symbols, DWARF lines. | ✅ | `adapters/elf.py` | — |
| **uart** — Serial port enumeration and bounded capture. | ✅ | `adapters/uart.py` | — |
| **gdb** — GDB Machine Interface client (arm-none-eabi-gdb / gdb-multiarch). | ✅ | `adapters/gdb.py` | — |
| **openocd** — Start/stop OpenOCD with board-verified configs. | ✅ | `adapters/openocd.py` | — |
| **knowledge_pack** — Find, read, write and fingerprint versioned packs. | ✅ | `adapters/knowledge_pack.py` | — |
| **vscode** — Share state with the NEON-MDF VS Code extension. | ⏳ planned | — | — |

### 10 System & Security (`system`) — 6/6 submodules

Configuration, workspace sandbox, process control, permission policy, logging and errors.

| Submodule | Status | File | Tools / prompts / resources |
|---|---|---|---|
| **config** — Settings from CLI options and NEON_MCP_* variables. | ✅ | `system/config.py` | — |
| **workspace** — Every path must stay inside the allowed roots. | ✅ | `system/workspace.py` | — |
| **process** — External commands without a shell, with timeouts and process-group kill. | ✅ | `system/process.py` | — |
| **security** — read / write / hardware permission levels. | ✅ | `system/security.py` | — |
| **logging** — stderr logging (stdout is the MCP stream) and audit records. | ✅ | `system/logging.py` | — |
| **errors** — Typed errors whose message and hint reach the agent. | ✅ | `system/errors.py` | — |
