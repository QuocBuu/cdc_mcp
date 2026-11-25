"""Command line entry point: `neon-mcp` or `python -m neon_mcp`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import transport
from .core.app import NeonApp
from .core.server import create_server
from .system import logging as neon_logging
from .system.config import Settings
from .system.errors import NeonError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="neon-mcp", description="NEON MCP server for the NEON-MDF SDK.")
    parser.add_argument("--version", action="version", version=f"neon-mcp {__version__}")
    parser.add_argument("--sdk", type=Path, help="NEON-MDF checkout (default: discover; env NEON_MCP_SDK_PATH)")
    parser.add_argument("--workspace", type=Path, action="append", default=None,
                        help="allowed workspace root, repeatable (default: current directory; env NEON_MCP_WORKSPACE)")
    parser.add_argument("--allow-hardware", action="store_true", default=None,
                        help="allow serial ports and UART programming (env NEON_MCP_ALLOW_HARDWARE=1)")
    parser.add_argument("--read-only", action="store_true", default=None,
                        help="forbid project creation, sdkconfig edits and builds (env NEON_MCP_READ_ONLY=1)")
    parser.add_argument("--sdk-python", type=Path, help="Python interpreter for CMake/SDK tools (env NEON_MCP_SDK_PYTHON)")
    parser.add_argument("--targets-dir", type=Path, help="extra target profile directory (env NEON_MCP_TARGETS_DIR)")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="streamable-http bind address")
    parser.add_argument("--port", type=int, default=8000, help="streamable-http port")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser.parse_args(argv)


def build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    if args.sdk is not None:
        settings.sdk_path = args.sdk
    if args.workspace:
        settings.workspace_roots = list(args.workspace)
    if args.allow_hardware:
        settings.allow_hardware = True
    if args.read_only:
        settings.read_only = True
    if args.sdk_python is not None:
        settings.sdk_python = args.sdk_python
    if args.targets_dir is not None:
        settings.targets_dir = args.targets_dir
    return settings


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    neon_logging.setup(args.log_level)  # stderr only: stdout carries the MCP stream on stdio
    try:
        app = NeonApp(build_settings(args))
    except NeonError as exc:
        print(f"neon-mcp: {exc}", file=sys.stderr)
        return 2
    server = create_server(app)
    try:
        transport.run(server, args.transport, args.host, args.port)
    finally:
        app.close()  # stop GDB/OpenOCD started by a debug session
    return 0


if __name__ == "__main__":
    sys.exit(main())
