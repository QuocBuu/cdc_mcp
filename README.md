# NEON MCP

[![CI](https://github.com/QuocBuu/cdc_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/QuocBuu/cdc_mcp/actions/workflows/ci.yml)
[![Install page](https://img.shields.io/badge/install-quocbuu.github.io%2Fcdc__mcp-0b8a7a)](https://quocbuu.github.io/cdc_mcp/)

NEON MCP is a [Model Context Protocol](https://modelcontextprotocol.io) server that gives AI coding
agents (Claude Code, Cursor, VS Code, Claude Desktop, Codex) the
[NEON-MDF](https://github.com/ftel-cdc/neon_mdf) firmware SDK for the GT32U2086 (Cortex-M0).

With it, an agent can:

- **Look up the chip:** documentation, memory map, boot modes, peripherals, registers and bit fields.
- **Use the SDK:** the C API with its documentation, driver sources, examples and the Kconfig,
  clocks and includes a feature needs.
- **Create and build projects:** templates, `sdkconfig` options, CMake builds with diagnostics and
  memory usage.
- **Flash and run:** check images, program over UART, capture and summarize the board's log.
- **Debug:** GDB sessions through OpenOCD or a running GDB server.
- **Analyze crashes:** decode a HardFault down to the faulting instruction and source line.

NEON MCP does not replace the SDK: it reads your NEON-MDF checkout and runs the SDK's own tools,
so the agent always works with the SDK you build with.

## Quick start

The install page lists the supported NEON-MDF releases and chips, the command for each client
(with one-click buttons for Cursor and VS Code) and example requests: **https://quocbuu.github.io/cdc_mcp/**

With [uv](https://docs.astral.sh/uv/) and Claude Code:

```sh
git clone --branch v1.0.0 https://github.com/ftel-cdc/neon_mdf.git ~/neon_mdf
claude mcp add --scope user neon-mcp -- uvx --from git+https://github.com/QuocBuu/cdc_mcp neon-mcp --sdk ~/neon_mdf
```

Building firmware also needs `arm-none-eabi-gcc` with newlib, **CMake ≥ 3.25** and Ninja (see
`guide/Setup.md` in NEON-MDF). The `dev_check_environment` tool reports anything missing.

## Running the server

```sh
neon-mcp --sdk /path/to/neon_mdf --workspace /path/to/projects
```

| Option | Environment variable | Description |
|---|---|---|
| `--sdk PATH` | `NEON_MCP_SDK_PATH` | NEON-MDF checkout. If omitted: `NEON_MDF_PATH`, then the current directory and its parents, then `./neon_mdf` |
| `--workspace PATH` (repeatable) | `NEON_MCP_WORKSPACE` | Directories the agent may read and write. Defaults to the current directory; the SDK is always included |
| `--allow-hardware` | `NEON_MCP_ALLOW_HARDWARE=1` | Allow serial ports, flashing and debugging. **Off by default** |
| `--read-only` | `NEON_MCP_READ_ONLY=1` | Forbid project creation, `sdkconfig` edits and builds |
| `--sdk-python PATH` | `NEON_MCP_SDK_PYTHON` | Python used for CMake and the SDK tools. Defaults to the app's or SDK's `.venv`, else NEON MCP's own Python |
| `--targets-dir PATH` | `NEON_MCP_TARGETS_DIR` | Extra target profile directory |
| `--packs-dir PATH` | `NEON_MCP_PACKS_DIR` | Extra knowledge pack directory, searched before the bundled packs |
| `--transport streamable-http --host --port` | | Serve over HTTP instead of stdio |

**HTTP mode.** With `--transport streamable-http`, clients connect to `http://<host>:<port>/mcp`,
and `http://<host>:<port>/` serves the install page with that URL filled in. The endpoint has no
authentication: keep the default `--host 127.0.0.1`, or expose it only on a trusted network,
preferably with `--read-only`.

**Client configuration.** For a checkout installed from source, add a `.mcp.json` at the
workspace root (Cursor and VS Code use the same `command`/`args` in their own MCP config files):

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

Add `"--allow-hardware"` to `args` to flash or debug a board.

## Typical agent workflow

1. `session_get_context`, then `session_set_context(app_dir="examples/Printf_Log")`.
2. Research: `knowledge_search("boot mode 100")`, `sdk_search_api("neon_uart_transmit")`,
   `sdk_find_examples(module="spi")`, `sdk_resolve_dependencies(["adc"])`.
3. Create or edit: `dev_create_project("MyApp", "<dir>")`,
   `dev_set_config({"CONFIG_NEON_MDF_DRIVER_SPI": true})`.
4. Build: `dev_build()` returns diagnostics (file, line), flash/RAM usage and artifacts.
5. Check: `prog_verify_image()`, `analysis_elf_summary()`.
6. Flash and run (requires `--allow-hardware`):
   - the agent asks the user to select boot mode `100`, then calls `prog_flash_uart(port=...)`;
   - the user presses RESET when the tool is ready;
   - `analysis_capture_uart(send="r")` reads the log;
   - the board goes back to boot mode `000`.
7. On a crash:
   - from a fault handler's log: `analysis_decode_exception(stack_frame=[...], exc_return=...)`;
   - with a debugger: `debug_connect(...)`, then `analysis_decode_exception(from_debug_session=True)`.

   The result gives the faulting function and `file:line`, the instruction, and likely causes,
   such as a byte access to the word-only SRAM.

## SDK data per release

The device, C API, documentation and SDK data of each NEON-MDF release are pre-generated in
`src/neon_mcp/packs/neon-mdf-<version>/` (currently v1.0.0). At startup the server selects the
pack matching the checkout's `neon-mdf/VERSION` and uses it when the checkout matches the release;
otherwise it reads the checkout directly. The `Knowledge packs` workflow generates a pack for each
new NEON-MDF release. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#knowledge-packs).

## Debugging hardware

The SDK's OpenOCD configuration for the GT32U2086 is still a placeholder, so `debug_connect` needs
either an OpenOCD configuration verified with your probe and board, or the address of a running
GDB server (OpenOCD, J-Link, pyOCD). GDB is `arm-none-eabi-gdb` or `gdb-multiarch`.

The debug tools are tested end to end against a simulated Cortex-M0 GDB server; flashing and
debugging have not yet been validated on a physical board.

## Security

- **Read** access is always allowed. **Write** (project creation, `sdkconfig`, builds) can be
  disabled with `--read-only`. **Hardware** (serial ports, flashing, debugging) requires
  `--allow-hardware`.
- Every path the agent passes must be inside a workspace root or the SDK.
- External commands run without a shell, with stdin closed and a timeout (builds: 900 s,
  `NEON_MCP_BUILD_TIMEOUT`); the whole process group is stopped on timeout.
- Tools carry MCP annotations (`read_only_hint`, `destructive_hint`) so clients can ask for
  confirmation before flashing.

## Project layout

```text
src/neon_mcp/
├── core/          # MCP server, tool/resource/prompt registries, session, transports, install page
├── modules/       # knowledge, sdk, development, debug, programming, analysis
├── targets/       # target registry and capabilities, GT32U2086 profile, Cortex-M backend
├── adapters/      # NEON-MDF, device YAML, CMake, Kconfig, ELF, UART, GDB/MI, OpenOCD, knowledge packs
├── system/        # configuration, workspace sandbox, processes, permissions, logging, errors
├── packs/         # pre-generated SDK data: neon-mdf-<version>/
└── web/           # install page
```

Each submodule is one file. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the layers,
their dependency rules, how to add tools, and the full module catalog.

## Supporting a new MCU

1. Add `mcu-description/devices/<NAME>.yaml` to NEON-MDF. Documentation and register tools work
   with it immediately.
2. Add `src/neon_mcp/targets/<name>/target.yaml` (or put it in `--targets-dir`), using the
   GT32U2086 profile as a template: preset, memory profiles, capabilities, board, boot modes and
   rules. Builds and flashing are enabled once the profile exists.
3. A new CPU architecture (for example RISC-V) also needs an analysis/debug backend in
   `targets/arch/`.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q                                   # uses ../neon_mdf, or NEON_MCP_TEST_SDK
.venv/bin/ruff check src tests pages docs
.venv/bin/neon-mcp-pack --sdk ../neon_mdf --check               # bundled pack still matches the generator
.venv/bin/python docs/update_catalog.py --sdk ../neon_mdf       # refresh the catalog in docs/ARCHITECTURE.md
.venv/bin/python pages/build.py --sdk ../neon_mdf --out _site   # preview the install page
```

The firmware build test runs only when `arm-none-eabi-gcc`, Ninja and CMake ≥ 3.25 are installed;
the debug session test also needs `gdb-multiarch` or `arm-none-eabi-gdb`.

| Workflow | Trigger | What it does |
|---|---|---|
| `CI` | push to `main`, pull requests | Lint and tests against NEON-MDF v1.0.0, on Python 3.10 and on Python 3.12 with the ARM toolchain and `gdb-multiarch` |
| `Pages` | push to `main`, manual | Builds the install page and deploys it to GitHub Pages |
| `Knowledge packs` | daily, manual | Generates packs for new NEON-MDF releases, commits them, then reruns CI and Pages (`force` regenerates every pack) |

GitHub Pages must use **GitHub Actions** as its source (Settings → Pages).

## Roadmap

- Validate flashing, UART capture and debugging on a physical GT32U2086 board with a verified
  OpenOCD configuration.
- Datasheet, TRM and errata sources for the Knowledge module.
- Memory analysis from map files and `-fstack-usage`.
- Multi-core debugging, a RISC-V backend and the FU3 target.
- Shared state with the NEON-MDF VS Code extension.
