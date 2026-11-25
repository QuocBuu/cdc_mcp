"""10 System & Security: execution environment, permissions and stability."""

from ..core.tools import Module, Submodule

MODULE = Module(
    number=10, id="system", title="System & Security", kind="infrastructure",
    description="Configuration, workspace sandbox, process control, permission policy, logging and errors.",
    submodules=[
        Submodule("config", "Configuration", "Settings from CLI options and NEON_MCP_* variables.",
                  source="system/config.py"),
        Submodule("workspace", "Workspace", "Every path must stay inside the allowed roots.",
                  source="system/workspace.py"),
        Submodule("process", "Process", "External commands without a shell, with timeouts and process-group kill.",
                  source="system/process.py"),
        Submodule("security", "Security", "read / write / hardware permission levels.", source="system/security.py"),
        Submodule("logging", "Logging", "stderr logging (stdout is the MCP stream) and audit records.",
                  source="system/logging.py"),
        Submodule("errors", "Errors", "Typed errors whose message and hint reach the agent.",
                  source="system/errors.py"),
    ],
)
