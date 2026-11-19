"""Opt-in, on-demand metadata only; no titles, screenshots, hooks or stored state."""

import ctypes as C
from ctypes import wintypes as W
from datetime import UTC, datetime
import ntpath
import platform
from typing import TypedDict, Literal

from src.capabilities.contracts import Permission, ToolDefinition, ToolExecutionError, ToolInputError, ToolStatus


SOURCE = "Local Win32 foreground/process and display APIs"
SCOPES = {"all", "foreground", "displays"}
MAX_DISPLAYS = 64
ERRORS = {None, "no_foreground", "process_unavailable", "access_denied", "image_unavailable",
          "foreground_changed", "display_unavailable", "display_changed", "mode_unavailable"}


class DesktopContext(TypedDict):
    capability: Literal["desktop.context"]
    scope: str
    status: Literal["complete", "partial", "unavailable"]
    foreground: dict | None
    displays: dict | None
    collected_at: str
    source: str


class MonitorInfo(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                ("dwFlags", W.DWORD), ("szDevice", W.WCHAR * 32)]


class DisplayMode(C.Structure):
    # The display member of DEVMODEW's printer/display union has the same 16-byte layout.
    _fields_ = [("dmDeviceName", W.WCHAR * 32), ("dmSpecVersion", W.WORD), ("dmDriverVersion", W.WORD),
                ("dmSize", W.WORD), ("dmDriverExtra", W.WORD), ("dmFields", W.DWORD),
                ("dmPosition", W.POINT), ("dmDisplayOrientation", W.DWORD), ("dmDisplayFixedOutput", W.DWORD),
                ("dmColor", W.SHORT), ("dmDuplex", W.SHORT), ("dmYResolution", W.SHORT),
                ("dmTTOption", W.SHORT), ("dmCollate", W.SHORT), ("dmFormName", W.WCHAR * 32),
                ("dmLogPixels", W.WORD), ("dmBitsPerPel", W.DWORD), ("dmPelsWidth", W.DWORD),
                ("dmPelsHeight", W.DWORD), ("dmDisplayFlags", W.DWORD), ("dmDisplayFrequency", W.DWORD),
                ("dmICMMethod", W.DWORD), ("dmICMIntent", W.DWORD), ("dmMediaType", W.DWORD),
                ("dmDitherType", W.DWORD), ("dmReserved1", W.DWORD), ("dmReserved2", W.DWORD),
                ("dmPanningWidth", W.DWORD), ("dmPanningHeight", W.DWORD)]


class WindowsDesktop:
    """Bindings are created only after an enabled, explicit observation request."""

    def __init__(self):
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.callback_type = C.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, C.POINTER(W.RECT), W.LPARAM)
        signatures = [(self.user.GetForegroundWindow, [], W.HWND),
                      (self.user.GetWindowThreadProcessId, [W.HWND, C.POINTER(W.DWORD)], W.DWORD),
                      (self.kernel.OpenProcess, [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
                      (self.kernel.QueryFullProcessImageNameW, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
                      (self.kernel.CloseHandle, [W.HANDLE], W.BOOL),
                      (self.user.EnumDisplayMonitors, [W.HDC, C.POINTER(W.RECT), self.callback_type, W.LPARAM], W.BOOL),
                      (self.user.GetMonitorInfoW, [W.HMONITOR, C.POINTER(MonitorInfo)], W.BOOL),
                      (self.user.EnumDisplaySettingsW, [W.LPCWSTR, W.DWORD, C.POINTER(DisplayMode)], W.BOOL)]
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result

    def window(self):
        return self.user.GetForegroundWindow()

    def pid(self, window):
        value = W.DWORD()
        if not self.user.GetWindowThreadProcessId(window, C.byref(value)):
            raise OSError()
        return value.value

    def image(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION only
        if not handle:
            if C.get_last_error() == 5:
                raise PermissionError()
            raise OSError()
        try:
            size = W.DWORD(32768)
            buffer = C.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size)):
                raise OSError()
            return ntpath.basename(buffer.value)  # Never return the full private path.
        finally:
            self.kernel.CloseHandle(handle)

    def monitors(self):
        handles = []

        @self.callback_type
        def collect(handle, _dc, _rect, _data):
            if len(handles) >= MAX_DISPLAYS:
                return False
            handles.append(handle)
            return True

        if not self.user.EnumDisplayMonitors(None, None, collect, 0):
            raise OSError()
        return handles

    def monitor(self, handle):
        info = MonitorInfo()
        info.cbSize = C.sizeof(info)
        if not self.user.GetMonitorInfoW(handle, C.byref(info)):
            raise OSError()
        return bool(info.dwFlags & 1), info.szDevice

    def resolution(self, device):
        mode = DisplayMode()
        mode.dmSize = C.sizeof(mode)
        if not self.user.EnumDisplaySettingsW(device, 0xFFFFFFFF, C.byref(mode)):
            raise OSError()
        if mode.dmFields & 0x180000 != 0x180000:  # DM_PELSWIDTH | DM_PELSHEIGHT
            raise OSError()
        return mode.dmPelsWidth, mode.dmPelsHeight


def open_windows():
    if platform.system() != "Windows":
        raise ToolExecutionError("Desktop context is supported on Windows only.", status=ToolStatus.UNAVAILABLE)
    try:
        return WindowsDesktop()
    except (OSError, AttributeError):
        raise ToolExecutionError("Required Windows desktop APIs are unavailable.", status=ToolStatus.UNAVAILABLE) from None


def valid_executable(name):
    return (isinstance(name, str) and 0 < len(name) <= 255 and name.isprintable()
            and name.lower().endswith(".exe") and not any(char in name for char in '/\\:<>"|?*'))


def foreground(api):
    value = {"status": "unavailable", "executable": None, "pid": None, "error": "process_unavailable"}
    try:
        window = api.window()
        if not window:
            return {**value, "error": "no_foreground"}
        pid = api.pid(window)
        name = api.image(pid)
        if api.window() != window or api.pid(window) != pid:
            return {**value, "error": "foreground_changed"}
        if not valid_executable(name):
            return {**value, "error": "image_unavailable"}
        return {"status": "complete", "executable": name, "pid": pid, "error": None}
    except PermissionError:
        return {**value, "error": "access_denied"}
    except OSError:
        return value


def displays(api):
    missing = {"status": "unavailable", "count": None, "primary_resolution": None, "monitors": [], "error": "display_unavailable"}
    try:
        handles = api.monitors()
        if not handles or len(handles) > MAX_DISPLAYS or len(set(handles)) != len(handles):
            return missing
        rows = []
        for index, handle in enumerate(handles, 1):
            row = {"id": index, "primary": None, "width_px": None, "height_px": None, "error": "display_unavailable"}
            try:
                primary, device = api.monitor(handle)
                row.update(primary=primary, error="mode_unavailable")
                width, height = api.resolution(device)
                if all(type(n) is int and 0 < n <= 131072 for n in (width, height)):
                    row.update(width_px=width, height_px=height, error=None)
            except OSError:
                pass
            rows.append(row)
        # One consistency check, not polling. Never substitute logical rcMonitor dimensions.
        if set(api.monitors()) != set(handles):
            return {**missing, "error": "display_changed"}
        primary = [row for row in rows if row["primary"] is True]
        resolution = ({"width_px": primary[0]["width_px"], "height_px": primary[0]["height_px"]}
                      if len(primary) == 1 and primary[0]["error"] is None else None)
        complete = resolution is not None and all(row["error"] is None for row in rows)
        return {"status": "complete" if complete else "partial", "count": len(rows),
                "primary_resolution": resolution, "monitors": rows, "error": None}
    except OSError:
        return missing


def validate_arguments(arguments):
    if (set(arguments) - {"scope"} or not isinstance(arguments.get("scope", "all"), str)
            or arguments.get("scope", "all") not in SCOPES):
        raise ToolInputError("Desktop context accepts only scope: all, foreground, or displays.")
    return {"scope": arguments.get("scope", "all")}


def collect_context(arguments) -> DesktopContext:
    api = open_windows()
    scope = arguments["scope"]
    fg = foreground(api) if scope in {"all", "foreground"} else None
    screens = displays(api) if scope in {"all", "displays"} else None
    statuses = [part["status"] for part in (fg, screens) if part is not None]
    status = "complete" if all(s == "complete" for s in statuses) else "unavailable" if all(s == "unavailable" for s in statuses) else "partial"
    return {"capability": "desktop.context", "scope": scope, "status": status, "foreground": fg, "displays": screens,
            "collected_at": datetime.now(UTC).isoformat(), "source": SOURCE}


def validate_output(data):
    if not isinstance(data, dict) or set(data) != {"capability", "scope", "status", "foreground", "displays", "collected_at", "source"}:
        raise ValueError("Invalid desktop result.")
    if data["capability"] != "desktop.context" or data["source"] != SOURCE or data["scope"] not in SCOPES:
        raise ValueError("Invalid desktop provenance.")
    stamp = datetime.fromisoformat(data["collected_at"])
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Missing desktop timestamp zone.")
    fg, screens = data["foreground"], data["displays"]
    for name, part in (("foreground", fg), ("displays", screens)):
        requested = data["scope"] in {"all", name}
        if requested != isinstance(part, dict):
            raise ValueError("Invalid desktop scope.")
        if not requested and part is not None:
            raise ValueError("Unexpected desktop data.")
    if fg is not None:
        if set(fg) != {"status", "executable", "pid", "error"} or fg["error"] not in ERRORS:
            raise ValueError("Invalid foreground fields.")
        if fg["status"] == "complete":
            if not valid_executable(fg["executable"]) or type(fg["pid"]) is not int or not 0 < fg["pid"] < 2**32 or fg["error"] is not None:
                raise ValueError("Invalid verified foreground.")
        elif fg["status"] != "unavailable" or fg["executable"] is not None or fg["pid"] is not None or fg["error"] is None:
            raise ValueError("Invalid unavailable foreground.")
    if screens is not None:
        if set(screens) != {"status", "count", "primary_resolution", "monitors", "error"} or screens["error"] not in ERRORS:
            raise ValueError("Invalid display fields.")
        rows = screens["monitors"]
        if not isinstance(rows, list) or len(rows) > MAX_DISPLAYS:
            raise ValueError("Invalid displays.")
        for index, row in enumerate(rows, 1):
            if (not isinstance(row, dict) or set(row) != {"id", "primary", "width_px", "height_px", "error"}
                    or type(row["id"]) is not int or row["id"] != index or row["error"] not in ERRORS
                    or row["primary"] is not None and type(row["primary"]) is not bool):
                raise ValueError("Invalid monitor.")
            if row["error"] is None:
                if type(row["primary"]) is not bool or not all(type(row[k]) is int and 0 < row[k] <= 131072 for k in ("width_px", "height_px")):
                    raise ValueError("Invalid resolution.")
            elif row["width_px"] is not None or row["height_px"] is not None:
                raise ValueError("Unexpected unavailable resolution.")
        if screens["status"] == "unavailable":
            if rows or screens["count"] is not None or screens["primary_resolution"] is not None or screens["error"] is None:
                raise ValueError("Invalid unavailable displays.")
        else:
            primary = [r for r in rows if r["primary"] is True]
            expected = ({k: primary[0][k] for k in ("width_px", "height_px")}
                        if len(primary) == 1 and primary[0]["error"] is None else None)
            complete = expected is not None and all(r["error"] is None for r in rows)
            if (not rows or type(screens["count"]) is not int or screens["count"] != len(rows)
                    or screens["primary_resolution"] != expected or screens["error"] is not None
                    or screens["status"] != ("complete" if complete else "partial")):
                raise ValueError("Inconsistent displays.")
    statuses = [p["status"] for p in (fg, screens) if p is not None]
    expected = "complete" if all(s == "complete" for s in statuses) else "unavailable" if all(s == "unavailable" for s in statuses) else "partial"
    if data["status"] != expected:
        raise ValueError("Inconsistent collection status.")
    return data


def desktop_tool(enabled=False):
    if type(enabled) is not bool:
        raise ValueError("Desktop context enablement must be boolean.")
    return ToolDefinition("desktop.context", "On-demand foreground executable and active display modes; no window titles or screenshots.",
                          validate_arguments, validate_output, Permission.READ_ONLY, collect_context,
                          enabled=enabled, verify=lambda data: data["status"] == "complete")
