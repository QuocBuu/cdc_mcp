# NEON MCP

NEON MCP là MCP server (Model Context Protocol) giúp AI agent như Claude Code, Cursor hay
VS Code làm việc với SDK firmware [NEON-MDF](https://github.com/ftel-cdc/neon_mdf). Qua server
này, agent có thể:

- tra cứu tài liệu, dữ liệu chip/register và C API;
- tìm example, tạo project, chỉnh `sdkconfig`, build;
- kiểm tra image, nạp firmware qua UART và đọc log.

**Nguyên tắc:** NEON MCP chỉ là lớp giao tiếp giữa AI và NEON-MDF, không thay thế SDK. Mọi dữ
liệu và công cụ đều lấy trực tiếp từ checkout NEON-MDF:

| Lấy từ NEON-MDF | Đường dẫn |
|---|---|
| Tài liệu | `guide/`, README của example |
| Dữ liệu chip | `mcu-description/devices/*.yaml` |
| C API | header trong `components/` |
| Template | `tools/templates*` |
| Cấu hình | Kconfig, qua `kconfiglib` |
| Build | CMake preset |
| Nạp firmware | `gt32u2086_flash.py` |
| Image | `gt32u2086_image.py` |

## Trạng thái phiên bản 0.3 — đủ phạm vi V1

NEON MCP gồm **10 module**, mỗi module chia thành các submodule; mỗi submodule là một file riêng.
Tổng cộng có **43 tool, 3 prompt và 6 resource**. Danh mục đầy đủ (module → submodule → file →
tool, kèm trạng thái) nằm trong [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Cũng xem được
bằng tool `neon_list_modules`.

| # | Module | Submodule đã làm | Tool |
|---|---|---|---|
| 01 | MCP Core | server, tool_registry, resource_registry, prompt_manager, session_manager, transport | `neon_list_modules`, `session_get_context`, `session_set_context` |
| 02 | Knowledge | documentation, search, device_knowledge, register_knowledge *(planned: datasheet/TRM/errata)* | `knowledge_*` (5) |
| 03 | SDK | sdk_discovery, component, api, source, example, dependency, knowledge_pack | `sdk_*` (7) |
| 04 | Development | toolchain, project, configuration, code_generation, build | `dev_*` (7) |
| 05 | Debug | session, cpu, register, memory, peripheral, breakpoint, source_debug *(planned: multicore)* | `debug_*` (9) |
| 06 | Programming | image, verify, boot, flash | `prog_*` (5) |
| 07 | Analysis | elf, exception, register_decoder, log_analyzer *(planned: memory_analyzer)* | `analysis_*` (6) |
| 08 | Target & Device | registry, capabilities, gt32u2086, cortex_m *(planned: riscv, fu3)* | `target_list` |
| 09 | Backend & Adapter | neon_mdf, device_yaml, cmake, kconfig, elf, uart, gdb, openocd, knowledge_pack *(planned: vscode)* | (nội bộ) |
| 10 | System & Security | config, workspace, process, security, logging, errors | (nội bộ) |

**Knowledge pack:** dữ liệu chip, C API, tài liệu và SDK của từng bản NEON-MDF được sinh sẵn trong
`src/neon_mcp/packs/neon-mdf-<version>/` (hiện có v1.0.0). Server chọn pack theo `neon-mdf/VERSION`
của checkout và chỉ dùng khi checkout khớp bản phát hành; nếu không thì đọc trực tiếp từ checkout.
Workflow `Knowledge packs` tự sinh pack khi NEON-MDF có tag mới. Chi tiết trong
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#knowledge-pack-theo-phiên-bản-neon-mdf).

**Debug:** SDK chưa có cấu hình OpenOCD đã kiểm chứng cho GT32U2086, nên `debug_connect` cần
một trong hai:
- file cấu hình OpenOCD đã kiểm chứng với board;
- địa chỉ GDB server đang chạy.

GDB dùng `arm-none-eabi-gdb` hoặc `gdb-multiarch`. Phần Debug đã được kiểm thử với GDB server
giả lập, chưa chạy trên board thật.

## Cài nhanh

Trang hướng dẫn cài (có nút cài một chạm cho Cursor và VS Code, kèm demo kết quả tool thật):
**https://quocbuu.github.io/cdc_mcp/**. Workflow `Pages` tự build lại trang sau mỗi lần push lên `main`.

Cần [uv](https://docs.astral.sh/uv/) và một checkout NEON-MDF. Ví dụ với Claude Code:

```sh
git clone --branch v1.0.0 https://github.com/ftel-cdc/neon_mdf.git ~/neon_mdf
claude mcp add --scope user neon-mcp -- uvx --from git+https://github.com/QuocBuu/cdc_mcp neon-mcp --sdk ~/neon_mdf
```

## Cài đặt từ mã nguồn

Cần Python 3.10 trở lên và một checkout NEON-MDF.

```sh
git clone https://github.com/ftel-cdc/neon_mdf.git      # nếu chưa có
cd cdc_mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Để build firmware, máy cần các công cụ SDK yêu cầu (xem `guide/Setup.md` của NEON-MDF):

- `arm-none-eabi-gcc` có kèm newlib;
- **CMake ≥ 3.25**;
- Ninja.

Gọi tool `dev_check_environment` để kiểm tra và nhận hướng dẫn cài phần còn thiếu.

## Chạy server

```sh
.venv/bin/neon-mcp --sdk /path/to/neon_mdf --workspace /path/to/projects
```

| Tùy chọn | Biến môi trường | Ý nghĩa |
|---|---|---|
| `--sdk PATH` | `NEON_MCP_SDK_PATH` | Checkout NEON-MDF. Nếu bỏ trống, server tự tìm qua `NEON_MDF_PATH`, rồi thư mục hiện tại và các thư mục cha, rồi `./neon_mdf` |
| `--workspace PATH` (lặp lại được) | `NEON_MCP_WORKSPACE` | Thư mục mà agent được đọc/ghi. Mặc định là thư mục hiện tại; SDK luôn được thêm vào |
| `--allow-hardware` | `NEON_MCP_ALLOW_HARDWARE=1` | Cho phép mở cổng serial và nạp board. **Mặc định tắt** |
| `--read-only` | `NEON_MCP_READ_ONLY=1` | Cấm tạo project, sửa sdkconfig và build |
| `--sdk-python PATH` | `NEON_MCP_SDK_PYTHON` | Python dùng cho CMake và tool của SDK. Mặc định lấy `.venv` của app/SDK, nếu không có thì dùng Python của NEON MCP |
| `--targets-dir PATH` | `NEON_MCP_TARGETS_DIR` | Thư mục profile target bổ sung |
| `--packs-dir PATH` | `NEON_MCP_PACKS_DIR` | Thư mục knowledge pack bổ sung, được ưu tiên hơn pack đi kèm |
| `--transport streamable-http --host --port` | | Chạy qua HTTP thay cho stdio |

### Claude Code

Tạo file `.mcp.json` ở thư mục gốc workspace:

```json
{
  "mcpServers": {
    "neon-mcp": {
      "command": "/abs/path/cdc_mcp/.venv/bin/neon-mcp",
      "args": ["--sdk", "/abs/path/neon_mdf", "--workspace", "/abs/path/workspace"]
    }
  }
}
```

Nếu cần nạp board, thêm `"--allow-hardware"` vào `args`. Cursor và VS Code dùng cùng cách khai
báo `command`/`args` trong file cấu hình MCP của mỗi IDE.

## Quy trình điển hình cho agent

1. `session_get_context`, rồi `session_set_context(app_dir="examples/Printf_Log")`.
2. Tìm hiểu: `knowledge_search("boot mode 100")`, `sdk_search_api("neon_uart_transmit")`,
   `sdk_find_examples(module="spi")`.
3. Tạo project hoặc sửa code: `dev_create_project("MyApp", "<dir>")`,
   `dev_set_config({"CONFIG_NEON_MDF_DRIVER_SPI": true})`.
4. Build: `dev_build()`. Kết quả gồm diagnostic (file, dòng), mức dùng Flash/RAM và artifact.
5. Kiểm tra: `prog_inspect_image()`, `analysis_elf_summary()`.
6. Nạp và chạy (cần `--allow-hardware`):
   - Agent nhắc người dùng chọn boot mode `100`, rồi gọi `prog_flash_uart(port=...)`.
   - Người dùng bấm RESET khi tool báo sẵn sàng.
   - `analysis_capture_uart(send="r")` để đọc log.
   - Chuyển board về boot mode `000`.
7. Khi firmware bị crash:
   - Có log của fault handler: `analysis_decode_exception(stack_frame=[...], exc_return=...)`.
   - Có debugger: `debug_connect(...)`, rồi `analysis_decode_exception(from_debug_session=True)`.
   - Kết quả cho biết vị trí lỗi (hàm, file:dòng), lệnh gây lỗi và các nguyên nhân khả dĩ, ví dụ truy
     cập byte vào SRAM chỉ cho phép word.

## Bảo mật

- **READ** luôn được phép. **WRITE** (tạo project, sửa sdkconfig, build) tắt được bằng
  `--read-only`. **HARDWARE** (serial, nạp board) chỉ bật khi có `--allow-hardware`.
- Mọi đường dẫn agent truyền vào phải nằm trong workspace root hoặc SDK. Đường dẫn ra ngoài bị
  từ chối.
- Lệnh ngoài chạy không qua shell, stdin đóng, có timeout (build mặc định 900 giây, chỉnh bằng
  `NEON_MCP_BUILD_TIMEOUT`), và bị dừng cả nhóm tiến trình khi quá hạn.
- Tool có annotation MCP: `read_only_hint` cho tool chỉ đọc, `destructive_hint` cho tool nạp board.
  Nhờ vậy client có thể hỏi xác nhận trước khi chạy.

## Cấu trúc

```text
src/neon_mcp/
├── core/                  # 01 MCP Core
│   ├── server.py          #   server: lắp ráp mọi module
│   ├── tools.py           #   tool_registry: Module/Submodule, neon_list_modules
│   ├── resources.py       #   resource_registry: neon://...
│   ├── prompts.py         #   prompt_manager
│   ├── session.py         #   session_manager
│   ├── transport.py       #   stdio / streamable-http
│   └── app.py             #   application context dùng chung
├── modules/
│   ├── knowledge/         # 02: documentation, search, device_knowledge, register_knowledge
│   ├── sdk/               # 03: sdk_discovery, component, api, source, example, dependency, knowledge_pack
│   ├── development/       # 04: toolchain, project, configuration, code_generation, build
│   ├── debug/             # 05: session, cpu, register_access, memory, peripheral, breakpoint, source_debug
│   ├── programming/       # 06: image, verify, boot, flash
│   └── analysis/          # 07: elf, exception, register_decoder, log_analyzer
├── targets/               # 08: registry, capabilities, gt32u2086/target.yaml, arch/cortex_m.py
├── packs/                 # knowledge pack sinh sẵn: neon-mdf-<version>/
├── adapters/              # 09: neon_mdf, device, cmake, kconfig, elf, uart, gdb, openocd, knowledge_pack
└── system/                # 10: config, workspace, process, security, logging, errors
```

Mỗi `modules/<module>/__init__.py` khai báo `MODULE` (danh sách submodule và trạng thái), rồi
gọi `register()` của từng file submodule. Quy tắc phụ thuộc giữa các lớp và cách thêm
tool/submodule được mô tả trong [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Thêm MCU mới

1. Thêm `mcu-description/devices/<NAME>.yaml` vào NEON-MDF. Với file này, các tool tra tài liệu
   và register đã dùng được ngay.
2. Thêm `src/neon_mcp/targets/<name>/target.yaml` (hoặc đặt trong `--targets-dir`), lấy
   `gt32u2086.yaml` làm mẫu. File gồm: preset, các profile bộ nhớ, capability, board, boot mode
   và rules. Có profile này thì build/nạp mới được mở.
3. Nếu kiến trúc CPU mới (ví dụ RISC-V của FU3), cần thêm backend phân tích/debug tương ứng.
   Phần này dự kiến làm ở bản sau.

## Phát triển

```sh
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q            # test với ../neon_mdf, hoặc đặt NEON_MCP_TEST_SDK
.venv/bin/ruff check src tests pages
.venv/bin/python pages/build.py --sdk ../neon_mdf --out _site   # xem trước trang cài đặt: mở _site/index.html
.venv/bin/neon-mcp-pack --sdk ../neon_mdf --check                # pack đi kèm còn khớp với code sinh pack không
.venv/bin/python docs/update_catalog.py --sdk ../neon_mdf        # cập nhật danh mục trong docs/ARCHITECTURE.md
```

Test build thật (`test_build_template`) chỉ chạy khi máy có `arm-none-eabi-gcc`, Ninja và
CMake ≥ 3.25; nếu thiếu thì tự bỏ qua.

GitHub Actions:

| Workflow | Khi nào chạy | Làm gì |
|---|---|---|
| `CI` | push lên `main`, pull request | Lint và chạy test trên NEON-MDF v1.0.0. Có 2 job: Python 3.10, và Python 3.12 kèm toolchain ARM + `gdb-multiarch` để chạy cả test build và debug |
| `Pages` | push lên `main`, chạy tay | Build trang cài đặt từ server thật (danh mục tool, demo, các knowledge pack) rồi deploy lên GitHub Pages |
| `Knowledge packs` | hằng ngày, chạy tay | Sinh pack cho tag NEON-MDF mới, commit, rồi chạy lại CI và Pages. Chạy tay với `force` để sinh lại mọi pack |

Lần đầu bật Pages: vào Settings → Pages → Source, chọn **GitHub Actions**.

## Lộ trình

- **Kiểm chứng trên phần cứng:** chạy `prog_flash_uart`, `analysis_capture_uart` và các tool
  `debug_*` trên board GT32U2086 thật, với cấu hình OpenOCD/probe đã kiểm chứng.
- **Planned submodule:**
  - Knowledge: nguồn Datasheet/TRM/Errata.
  - Debug: multicore.
  - Analysis: memory_analyzer (file map, `-fstack-usage`).
  - Target: RISC-V backend, FU3.
  - Adapter: VS Code.
