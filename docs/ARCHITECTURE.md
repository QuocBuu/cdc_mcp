# Kiến trúc NEON MCP

Tài liệu này mô tả cách NEON MCP được chia thành **module → submodule → tool**, đúng theo đề xuất
*NEON MCP — System Architecture*. Phần danh mục ở cuối được sinh tự động từ code
(`ToolRegistry`), nên luôn khớp với thực tế.

Có thể xem cùng danh mục này theo ba cách:
- Gọi tool `neon_list_modules`.
- Đọc resource `neon://architecture`.
- Xem `_meta` của từng tool (`neon-mcp/module`, `neon-mcp/submodule`).

## Đối chiếu phạm vi V1

| Module | Implementation V1 (đề xuất) | Trạng thái |
|---|---|---|
| 01 MCP Core | Bắt buộc | ✅ Đủ 6/6 submodule: server, tool/resource registry, prompt manager, session, transport |
| 02 Knowledge | Tra cứu cơ bản | ✅ 4/5 submodule; nguồn Datasheet/TRM/Errata để sau |
| 03 SDK | API, source, example | ✅ 7/7 submodule, có cả Dependency Resolver và Knowledge Pack |
| 04 Development | Build, target, config | ✅ 5/5 submodule: toolchain, project, configuration, code generation, build |
| 05 Debug | Basic debug | ✅ 7/8 submodule qua GDB/MI (OpenOCD hoặc GDB server có sẵn); multicore để sau |
| 06 Programming | Tái sử dụng UART Tool | ✅ 4/4 submodule: image, verify, boot, flash |
| 07 Analysis | Register, exception, ELF | ✅ 4/5 submodule; memory analyzer (file map) để sau |
| 08 Target & Device | Bắt buộc | ✅ Registry, capability, profile GT32U2086, backend Cortex-M; RISC-V/FU3 để sau |
| 09 Backend & Adapter | Bắt buộc | ✅ 9/10 adapter; VS Code để sau |
| 10 System & Security | Bắt buộc | ✅ 6/6 submodule |

**Lưu ý về Debug:** cấu hình OpenOCD của GT32U2086 trong SDK vẫn là placeholder. Vì vậy
`debug_connect` cần một trong hai thứ:
- file cấu hình đã kiểm chứng với probe/board;
- địa chỉ một GDB server đang chạy (OpenOCD, J-Link, pyOCD).

Toàn bộ luồng debug đã được kiểm thử với `gdb-multiarch` và một GDB server giả lập Cortex-M
(`tests/fake_gdbserver.py`), nhưng chưa chạy trên board thật.

## Các lớp và quy tắc phụ thuộc

```text
AI Agent / IDE ──MCP──► core (server, registry, session, prompts, resources, transport)
                              │
           modules/ (02..07: knowledge, sdk, development, debug, programming, analysis)
                              │  chỉ gọi xuống, không gọi lên
           targets/ (08)  ◄───┤  registry, capability, profile, backend kiến trúc (Cortex-M)
           adapters/ (09) ◄───┤  neon_mdf, device_yaml, cmake, kconfig, elf, uart, gdb, openocd
           system/ (10)   ◄───┘  config, workspace, process, security, logging, errors
                              │
                    NEON-MDF SDK checkout (docs, YAML, headers, CMake, tool Python)
```

- **Mỗi submodule là một file** và có hàm `register(registry, app)`. File `__init__.py` của
  module khai báo `MODULE` (danh sách submodule) và gọi `register` của từng file.
- **Module chức năng không chạy lệnh ngoài và không tự parse định dạng file.** Việc đó thuộc về
  adapter.
- **Phần phụ thuộc MCU nằm trong `targets/`**, gồm profile YAML và backend kiến trúc. Các module
  ở trên chỉ hỏi capability của target.
- **Tool được đăng ký qua `registry.tool(module, submodule, annotations)`.** Một submodule đang
  `planned` thì không đăng ký tool được.

## Knowledge pack theo phiên bản NEON-MDF

Dữ liệu chip, C API, tài liệu và thông tin SDK của mỗi bản NEON-MDF được sinh sẵn thành JSON trong
`src/neon_mcp/packs/neon-mdf-<version>/`:

| File | Nội dung |
|---|---|
| `devices/<DEVICE>.json` | Memory map, profile bộ nhớ, interrupt, peripheral → register → bit field (địa chỉ tuyệt đối) |
| `api.json` | Hàm, inline, enum, struct, typedef, macro kèm Doxygen và `file:line` |
| `docs.json` | Tài liệu đã chia theo heading, dùng cho tìm kiếm |
| `sdk.json` | Preset, component (Kconfig, backend, CRM) và example |
| `manifest.json` | Phiên bản SDK, số lượng mục và fingerprint của checkout nguồn |

Khi khởi động, server đọc `neon-mdf/VERSION` của checkout và chọn pack cùng phiên bản:

- **Fingerprint khớp** (checkout đúng bản phát hành): dữ liệu device, API và tài liệu lấy từ pack.
- **Fingerprint khác** (checkout đã sửa hoặc ở giữa hai bản): parse trực tiếp từ checkout để luôn
  khớp với code đang build. File bị sửa trong lúc server chạy cũng được phát hiện qua thời gian
  sửa đổi.
- **Chưa có pack** cho phiên bản đó: parse trực tiếp.

Trạng thái nằm trong `sdk_get_info` (`knowledge_pack`) và `session_get_context`.

- **Sinh pack:** `neon-mcp-pack --sdk <checkout>` (thêm `--force` để sinh lại, `--check` để kiểm
  tra pack có còn khớp với code sinh pack không).
- **Tự động:** workflow `Knowledge packs` chạy mỗi ngày, sinh pack cho tag NEON-MDF mới, commit, rồi
  chạy lại CI và Pages. Cài qua `uvx --from git+...` sẽ nhận pack mới ở lần khởi động sau.
- **Test:** `test_bundled_pack_is_up_to_date` báo lỗi nếu sửa parser mà chưa sinh lại pack.

## Thêm chức năng mới

1. **Thêm tool vào submodule có sẵn:** viết hàm trong file của submodule, dùng decorator
   `@registry.tool("<module>", "<submodule>", READ_ONLY | WRITES_FILES | TOUCHES_HARDWARE)`.
2. **Thêm submodule:** tạo file mới, thêm `Submodule(...)` vào `MODULE` trong `__init__.py`, rồi
   gọi `register` của file đó.
3. **Hoàn thành một submodule planned:** đổi `status` thành implemented, khai báo `source`, rồi
   thêm tool.
4. **Thêm MCU:**
   - Thêm device YAML vào NEON-MDF.
   - Thêm `targets/<name>/target.yaml`.
   - Nếu là kiến trúc CPU mới, thêm backend trong `targets/arch/`.
5. **Danh mục cuối tài liệu:** chạy `python docs/update_catalog.py --sdk ../neon_mdf` sau khi thêm
   hoặc đổi submodule.
6. **Test bắt buộc:** test `test_catalog_matches_architecture` kiểm tra mọi submodule đã
   implemented đều có file nguồn, và mọi tool đều có trong danh mục.

## Danh mục module (sinh từ code)

### 01 MCP Core (`core`) — 7/7 submodule

MCP server lifecycle, tool/resource/prompt registries, sessions and transports.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **server** — Builds the server and assembles every module. | ✅ | `core/server.py` | — |
| **tool_registry** — Registers tools under module/submodule and publishes the catalog. | ✅ | `core/tools.py` | `neon_list_modules` |
| **resource_registry** — neon:// resources with SDK, documentation and device data. | ✅ | `core/resources.py` | `neon://sdk/info`, `neon://architecture`, `neon://docs/index`, `neon://guide/{name}`, `neon://examples/{name}`, `neon://device/{target}` |
| **prompt_manager** — Workflow prompts: new peripheral app, firmware review, HardFault debugging. | ✅ | `core/prompts.py` | prompt `new_peripheral_app`, prompt `firmware_review`, prompt `debug_hardfault` |
| **session_manager** — Per-connection defaults (target, app, serial port, baud). | ✅ | `core/session.py` | `session_get_context`, `session_set_context` |
| **transport** — stdio (default) and Streamable HTTP. | ✅ | `core/transport.py` | — |
| **install_page** — Install guide with live catalog and demos: served at / over HTTP, published on GitHub Pages. | ✅ | `core/web.py` | — |

### 02 Knowledge Module (`knowledge`) — 4/5 submodule

SDK documentation, device data and register knowledge, read from the NEON-MDF checkout.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **documentation** — Index, list and read README, guide/ and example READMEs. | ✅ | `modules/knowledge/documentation.py` | `knowledge_list_documents`, `knowledge_read_document` |
| **search** — Ranked keyword search over documentation sections. | ✅ | `modules/knowledge/search.py` | `knowledge_search` |
| **device_knowledge** — CPU, memory map, profiles, IRQs, boot modes, debug limits, firmware rules. | ✅ | `modules/knowledge/device_knowledge.py` | `knowledge_get_device` |
| **register_knowledge** — Peripheral registers, fields, aliases and IRQs. | ✅ | `modules/knowledge/register_knowledge.py` | `knowledge_get_peripheral` |
| **external_documents** — Index vendor PDFs (datasheet, technical reference manual, errata) for search. | ⏳ planned | — | — |

### 03 SDK Module (`sdk`) — 7/7 submodule

Discovery, components, public C API, source code, examples and dependencies of NEON-MDF.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **sdk_discovery** — SDK version, path, git revision, presets, tools. | ✅ | `modules/sdk/sdk_discovery.py` | `sdk_get_info` |
| **component** — Drivers, console and FreeRTOS with Kconfig switches. | ✅ | `modules/sdk/component.py` | `sdk_list_components` |
| **api** — Functions, types and macros with Doxygen, parsed from headers. | ✅ | `modules/sdk/api.py` | `sdk_search_api` |
| **source** — grep-like search and line-numbered reading. | ✅ | `modules/sdk/source.py` | `sdk_search_source`, `sdk_read_source` |
| **example** — Example applications by keyword or driver used. | ✅ | `modules/sdk/example.py` | `sdk_find_examples` |
| **dependency** — Kconfig switches, includes, CRM clocks and CMake needed for a set of components. | ✅ | `modules/sdk/dependency.py` | `sdk_resolve_dependencies` |
| **knowledge_pack** — Device, API and docs data pre-generated per NEON-MDF release; used when the checkout matches. | ✅ | `modules/sdk/knowledge_pack.py` | — |

### 04 Development Module (`development`) — 5/5 submodule

Toolchain check, project creation, Kconfig configuration, device code generation and builds.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **toolchain** — Check arm-none-eabi-gcc/newlib, CMake >= 3.25, Ninja, Python deps. | ✅ | `modules/development/toolchain.py` | `dev_check_environment` |
| **project** — Create bare-metal or FreeRTOS apps from SDK templates. | ✅ | `modules/development/project.py` | `dev_create_project` |
| **configuration** — Read and change sdkconfig (menuconfig rules). | ✅ | `modules/development/configuration.py` | `dev_get_config`, `dev_set_config` |
| **code_generation** — Preview device files generated from the YAML. | ✅ | `modules/development/code_generation.py` | `dev_generate_device_files` |
| **build** — CMake configure/build with diagnostics, memory usage and artifacts. | ✅ | `modules/development/build.py` | `dev_configure`, `dev_build` |

### 05 Debug Module (`debug`) — 7/8 submodule

GDB/MI session (OpenOCD or existing GDB server), CPU control, registers, memory, peripherals, breakpoints and source-level backtraces.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **session** — Connect/disconnect, OpenOCD lifecycle, target state. | ✅ | `modules/debug/session.py` | `debug_connect`, `debug_disconnect` |
| **cpu** — Halt, continue, step, next, finish, reset. | ✅ | `modules/debug/cpu.py` | `debug_control` |
| **register** — Core registers with xPSR decoding. | ✅ | `modules/debug/register_access.py` | `debug_read_registers` |
| **memory** — Aligned word read/write with memory-map labels. | ✅ | `modules/debug/memory.py` | `debug_read_memory`, `debug_write_memory` |
| **peripheral** — Live peripheral registers decoded with the device YAML. | ✅ | `modules/debug/peripheral.py` | `debug_read_peripheral` |
| **breakpoint** — Hardware breakpoints and watchpoints. | ✅ | `modules/debug/breakpoint.py` | `debug_breakpoint` |
| **source_debug** — Backtrace, source lines and local variables. | ✅ | `modules/debug/source_debug.py` | `debug_backtrace` |
| **multicore** — Per-core selection and state (GT32U2086 is single-core). | ⏳ planned | — | — |

### 06 Programming Module (`programming`) — 4/4 submodule

Inspect and verify BootROM images, boot modes, serial ports and UART programming.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **image** — Decode BootROM headers with gt32u2086_image.py. | ✅ | `modules/programming/image.py` | `prog_inspect_image` |
| **verify** — Pre-programming checks with gt32u2086_flash.py --check-only. | ✅ | `modules/programming/verify.py` | `prog_verify_image` |
| **boot** — Boot modes and the board-side programming procedure. | ✅ | `modules/programming/boot.py` | `prog_list_boot_modes` |
| **flash** — Serial ports and ROMCODE UART programming of internal Flash. | ✅ | `modules/programming/flash.py` | `prog_list_serial_ports`, `prog_flash_uart` |

### 07 Analysis Module (`analysis`) — 4/5 submodule

ELF memory/symbols, register decoding, Cortex-M0 exception decoding and UART log analysis.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **elf** — Sections, Flash/RAM usage per profile, largest symbols, address → file:line. | ✅ | `modules/analysis/elf.py` | `analysis_elf_summary`, `analysis_resolve_address` |
| **exception** — HardFault frame, EXC_RETURN, faulting instruction and probable causes. | ✅ | `modules/analysis/exception.py` | `analysis_decode_exception` |
| **register_decoder** — Raw value → named fields from the device YAML. | ✅ | `modules/analysis/register_decoder.py` | `analysis_decode_register` |
| **log_analyzer** — Capture UART output and summarize logs. | ✅ | `modules/analysis/log_analyzer.py` | `analysis_capture_uart`, `analysis_analyze_log` |
| **memory_analyzer** — Linker map breakdown per object file/library and stack usage (-fstack-usage). | ⏳ planned | — | — |

### 08 Target & Device (`target`) — 4/6 submodule

Device registry built from SDK device YAML plus NEON MCP target profiles and capabilities.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **registry** — Known targets, selection and capability checks. | ✅ | `targets/registry.py` | `target_list` |
| **capabilities** — Capability vocabulary and unavailability notes. | ✅ | `targets/capabilities.py` | — |
| **gt32u2086** — Cortex-M0 preset, board defaults, boot modes, debug limits and firmware rules. | ✅ | `targets/gt32u2086/target.yaml` | — |
| **cortex_m** — ARMv6-M exception names, xPSR/EXC_RETURN, stack frame, core registers, instruction classes. | ✅ | `targets/arch/cortex_m.py` | — |
| **riscv** — CSR/PMP registers and trap decoding for Ibex/CVA6. | ⏳ planned | — | — |
| **fu3** — Ibex/CVA6 RISC-V target, once its device YAML exists in NEON-MDF. | ⏳ planned | — | — |

### 09 Backend & Adapter (`adapters`) — 9/10 submodule

One adapter per external system; modules never call tools or parse formats directly.

| Submodule | Trạng thái | File | Tool / prompt / resource |
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

### 10 System & Security (`system`) — 6/6 submodule

Configuration, workspace sandbox, process control, permission policy, logging and errors.

| Submodule | Trạng thái | File | Tool / prompt / resource |
|---|---|---|---|
| **config** — Settings from CLI options and NEON_MCP_* variables. | ✅ | `system/config.py` | — |
| **workspace** — Every path must stay inside the allowed roots. | ✅ | `system/workspace.py` | — |
| **process** — External commands without a shell, with timeouts and process-group kill. | ✅ | `system/process.py` | — |
| **security** — read / write / hardware permission levels. | ✅ | `system/security.py` | — |
| **logging** — stderr logging (stdout is the MCP stream) and audit records. | ✅ | `system/logging.py` | — |
| **errors** — Typed errors whose message and hint reach the agent. | ✅ | `system/errors.py` | — |
