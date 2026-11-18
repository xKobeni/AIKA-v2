import ctypes
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.capabilities.contracts import Permission, ToolDefinition, ToolExecutionError, ToolInputError, ToolStatus


# Targets are code-owned; local configuration may disable IDs, never add commands or arguments.
APPROVED_APPS = {
    "notepad": ("Notepad", "notepad.exe"),
    "calculator": ("Windows Calculator", "calc.exe"),
    "spotify": ("Spotify", None),
}


def windows_system_directory() -> Path | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_directory = kernel32.GetSystemDirectoryW
    get_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_directory.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_directory(buffer, len(buffer))
    if not 0 < length < len(buffer):
        return None
    directory = Path(buffer.value)
    if not directory.is_absolute() or directory.drive.startswith("\\\\"):
        return None
    return directory


@dataclass(frozen=True)
class Application:
    app_id: str
    display_name: str
    target: Path | None
    launch_method: str
    enabled: bool = True
    permission: Permission = Permission.LOCAL_ACTION


class ApplicationRegistry:
    def __init__(self):
        self.system_directory = windows_system_directory()
        self._apps: dict[str, Application] = {}

    def register(self, app: Application) -> None:
        if not isinstance(app.app_id, str):
            raise ValueError("Invalid application identifier.")
        if app.app_id in self._apps:
            raise ValueError("Duplicate application registration.")
        if app.app_id not in APPROVED_APPS or type(app.enabled) is not bool or app.permission is not Permission.LOCAL_ACTION:
            raise ValueError("Invalid application definition.")
        name, filename = APPROVED_APPS[app.app_id]
        expected = self.system_directory / filename if self.system_directory and filename else None
        if app.display_name != name or app.launch_method != ("executable" if filename else "unavailable") or app.target != expected:
            raise ValueError("Application target must match its approved Windows identity.")
        if app.target is not None:
            self.validate_target(app)
        self._apps[app.app_id] = app

    def validate_target(self, app: Application) -> None:
        filename = APPROVED_APPS[app.app_id][1]
        target = app.target
        if (self.system_directory is None or filename is None or not isinstance(target, Path)
                or not target.is_absolute() or target != self.system_directory / filename
                or ".." in target.parts or target.drive.startswith("\\\\")):
            raise ValueError("Invalid approved executable location.")
        try:
            if target.resolve() != target:
                raise ValueError("Redirected executable locations are not allowed.")
            if target.exists() and (target.is_symlink() or getattr(target.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("Executable reparse points are not allowed.")
        except OSError:
            raise ValueError("Cannot validate the approved executable location.") from None

    def lookup(self, app_id: str) -> Application:
        if not isinstance(app_id, str) or app_id not in self._apps:
            raise ToolInputError("Unsupported application target. Use /apps to see approved applications.")
        return self._apps[app_id]

    def list_apps(self) -> tuple[Application, ...]:
        return tuple(self._apps.values())

    def availability(self, app: Application) -> str:
        if self.system_directory is None:
            return "WINDOWS_UNAVAILABLE"
        if app.target is None:
            return "UNAVAILABLE"
        try:
            self.validate_target(app)
            return "AVAILABLE" if app.target.is_file() else "MISSING"
        except (OSError, ValueError):
            return "INVALID_TARGET"


def create_applications(disabled: tuple[str, ...] = ()) -> ApplicationRegistry:
    if any(app_id not in APPROVED_APPS for app_id in disabled):
        raise ValueError("Unknown disabled application ID.")
    registry = ApplicationRegistry()
    for app_id, (name, filename) in APPROVED_APPS.items():
        target = registry.system_directory / filename if registry.system_directory and filename else None
        registry.register(Application(app_id, name, target, "executable" if filename else "unavailable", app_id not in disabled))
    return registry


def _launch(app: Application) -> dict:
    # No PATH lookup, shell, user arguments, scripts, or elevation; GUI visibility is user-requested.
    try:
        process = subprocess.Popen(
            [str(app.target)], shell=False, cwd=str(app.target.parent),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
        )
    except OSError:
        raise ToolExecutionError("Windows could not start the approved application.") from None
    data = {"application": app.app_id, "launch_state": "initiated", "pid": process.pid,
            "process_observed": False, "exit_code": None}
    try:
        exit_code = process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        data.update(launch_state="verified", process_observed=True)
        return data
    data["exit_code"] = exit_code
    if exit_code != 0:
        data["launch_state"] = "failed"
        raise ToolExecutionError("The application launcher exited with an error.", data=data)
    # Store launchers may hand off to another PID. A zero exit code cannot verify that app.
    return data


def application_tool(apps: ApplicationRegistry) -> ToolDefinition:
    def validate_arguments(arguments: dict) -> dict:
        if set(arguments) != {"app_id"}:
            raise ToolInputError("Application launcher requires exactly one application ID: app_id.")
        if arguments["app_id"] == "":
            raise ToolInputError("Which registered application do you mean: Notepad, Windows Calculator, or Spotify? Use /apps to check availability.")
        apps.lookup(arguments["app_id"])
        return arguments

    def launch(arguments: dict) -> dict:
        app = apps.lookup(arguments["app_id"])
        if not app.enabled:
            raise ToolExecutionError("This application is disabled in local configuration.", status=ToolStatus.DISABLED)
        available = apps.availability(app)
        if available != "AVAILABLE":
            reason = "No audited Spotify launch method is enabled." if app.app_id == "spotify" else "The approved Windows executable is unavailable or unsafe."
            raise ToolExecutionError(reason, status=ToolStatus.UNAVAILABLE)
        return _launch(app)

    def validate_output(data: object) -> dict:
        if (not isinstance(data, dict) or set(data) != {"application", "launch_state", "pid", "process_observed", "exit_code"}
                or data["application"] not in APPROVED_APPS or type(data["pid"]) is not int or data["pid"] <= 0
                or type(data["process_observed"]) is not bool or data["launch_state"] not in {"verified", "initiated"}
                or (data["exit_code"] is not None and type(data["exit_code"]) is not int)
                or (data["process_observed"] != (data["launch_state"] == "verified"))
                or (data["process_observed"] and data["exit_code"] is not None)
                or (not data["process_observed"] and data["exit_code"] != 0)):
            raise ValueError("Invalid application execution evidence.")
        return data

    return ToolDefinition(
        "app.open", "Launch an explicitly requested approved Windows application.",
        validate_arguments, validate_output, Permission.LOCAL_ACTION, launch,
        verify=lambda data: data["launch_state"] == "verified" and data["process_observed"],
    )
