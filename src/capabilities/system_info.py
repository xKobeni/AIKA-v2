import heapq
import importlib
import math
import ntpath
import platform
import re
import sys
from datetime import UTC, datetime

from src.capabilities.applications import windows_system_directory
from src.capabilities.contracts import Permission, ToolDefinition, ToolExecutionError, ToolInputError, ToolStatus


CPU_INTERVAL = 0.1
DEFAULT_PROCESS_LIMIT = 10
MAX_PROCESS_LIMIT = 25
SOURCE = "Local Windows APIs via psutil and Python platform"
FIELDS = {
    "os": {"name": "text", "version": "text", "build": "count", "architecture": "text"},
    "cpu": {"logical_cores": "count", "physical_cores": "count", "usage_percent": "percent"},
    "memory": {"total_bytes": "positive_bytes", "used_bytes": "bytes", "available_bytes": "bytes", "usage_percent": "percent"},
    "storage": {"system_drive": "drive", "total_bytes": "positive_bytes", "used_bytes": "bytes", "free_bytes": "bytes", "usage_percent": "percent"},
}


def initialize_measurements():
    """Check interfaces without sampling metrics or enumerating processes."""
    if platform.system() != "Windows":
        raise ToolExecutionError("System measurements are supported on Windows only.", status=ToolStatus.UNAVAILABLE)
    try:
        psutil = importlib.import_module("psutil")
    except ImportError:
        raise ToolExecutionError("System measurement dependency psutil is unavailable. Install project dependencies with python -m pip install -e .", status=ToolStatus.UNAVAILABLE) from None
    if not all(callable(getattr(psutil, name, None)) for name in (
        "cpu_count", "cpu_percent", "virtual_memory", "disk_usage", "process_iter",
    )):
        raise ToolExecutionError("The psutil measurement interfaces could not be initialized.", status=ToolStatus.UNAVAILABLE)
    return psutil


def _valid(value, kind: str) -> bool:
    if kind in {"count", "positive_bytes", "bytes"}:
        return type(value) is int and (0 if kind == "bytes" else 1) <= value <= (2**32 - 1 if kind == "count" else 2**64 - 1)
    if kind == "percent":
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100
    if kind == "drive":
        return isinstance(value, str) and re.fullmatch(r"[A-Za-z]:\\", value) is not None
    return isinstance(value, str) and 0 < len(value) <= 160 and value.isprintable()


def _system_drive() -> str:
    directory = windows_system_directory()
    drive = ntpath.splitdrive(str(directory))[0] + "\\" if directory else None
    if not _valid(drive, "drive"):
        raise ValueError("Cannot determine the local Windows system drive.")
    return drive


def validate_snapshot_arguments(arguments: dict) -> dict:
    if (set(arguments) - {"section"} or not isinstance(arguments.get("section", "all"), str)
            or arguments.get("section", "all") not in {*FIELDS, "all"}):
        raise ToolInputError("System snapshot accepts only section: all, cpu, memory, storage, or os.")
    return {"section": arguments.get("section", "all")}


def collect_snapshot(arguments: dict) -> dict:
    psutil = initialize_measurements()
    section = arguments["section"]
    unavailable = []

    def read(path, operation, kind=None):
        try:
            value = operation()
            if value is None or (kind and not _valid(value, kind)):
                raise ValueError("Unavailable field")
            return value
        except Exception:
            unavailable.append(path)
            return None

    measurements = {}
    for group in FIELDS if section == "all" else (section,):
        if group == "os":
            measurements[group] = {
                "name": read("os.name", platform.system, "text"),
                "version": read("os.version", lambda: " ".join(part for part in platform.win32_ver()[:2] if part), "text"),
                "build": read("os.build", lambda: sys.getwindowsversion().build, "count"),
                "architecture": read("os.architecture", platform.machine, "text"),
            }
        elif group == "cpu":
            measurements[group] = {
                "logical_cores": read("cpu.logical_cores", lambda: psutil.cpu_count(logical=True), "count"),
                "physical_cores": read("cpu.physical_cores", lambda: psutil.cpu_count(logical=False), "count"),
                "usage_percent": read("cpu.usage_percent", lambda: psutil.cpu_percent(interval=CPU_INTERVAL), "percent"),
            }
        elif group == "memory":
            memory = read("memory", psutil.virtual_memory)
            total = read("memory.total_bytes", lambda: memory.total, "positive_bytes")
            available = read("memory.available_bytes", lambda: memory.available, "bytes")
            if available is not None and total is not None and available > total:
                available = None
                unavailable.append("memory.available_bytes")
            used = total - available if total is not None and available is not None else None
            measurements[group] = {"total_bytes": total, "used_bytes": used, "available_bytes": available,
                                   "usage_percent": round(used / total * 100, 1) if used is not None else None}
        else:
            drive = read("storage.system_drive", _system_drive, "drive")
            disk = read("storage", lambda: psutil.disk_usage(drive)) if drive else None
            measurements[group] = {"system_drive": drive}
            for field, attribute in (("total_bytes", "total"), ("used_bytes", "used"), ("free_bytes", "free"), ("usage_percent", "percent")):
                measurements[group][field] = read(f"storage.{field}", lambda attr=attribute: getattr(disk, attr), FIELDS[group][field])
    for group, values in measurements.items():
        unavailable.extend(f"{group}.{field}" for field, value in values.items() if value is None)
    if not any(value is not None for values in measurements.values() for field, value in values.items() if field != "system_drive"):
        raise ToolExecutionError("No requested system measurements could be collected.")
    return {"section": section, "measurements": measurements, "collected_at": datetime.now(UTC).isoformat(),
            "source": SOURCE, "unavailable_fields": sorted(set(unavailable))}


def _validate_metadata(data: dict) -> None:
    timestamp = datetime.fromisoformat(data["collected_at"])
    if timestamp.tzinfo is None or timestamp.utcoffset() is None or data["source"] != SOURCE:
        raise ValueError("Invalid measurement provenance.")


def validate_snapshot_output(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {"section", "measurements", "collected_at", "source", "unavailable_fields"}:
        raise ValueError("Invalid snapshot output.")
    _validate_metadata(data)
    section = data["section"]
    groups = set(FIELDS) if section == "all" else {section}
    if not groups <= FIELDS.keys() or not isinstance(data["measurements"], dict) or set(data["measurements"]) != groups:
        raise ValueError("Invalid snapshot sections.")
    allowed_missing = set(FIELDS) | {f"{group}.{field}" for group, fields in FIELDS.items() for field in fields}
    if not isinstance(data["unavailable_fields"], list) or any(path not in allowed_missing for path in data["unavailable_fields"]):
        raise ValueError("Invalid unavailable-field metadata.")
    has_value = False
    for group, values in data["measurements"].items():
        if not isinstance(values, dict) or set(values) != set(FIELDS[group]):
            raise ValueError("Invalid snapshot fields.")
        for field, value in values.items():
            if value is None:
                if f"{group}.{field}" not in data["unavailable_fields"]:
                    raise ValueError("Missing field not reported.")
            elif not _valid(value, FIELDS[group][field]):
                raise ValueError("Invalid measurement value.")
            elif field != "system_drive":
                has_value = True
        if group in {"memory", "storage"}:
            total, used = values["total_bytes"], values["used_bytes"]
            remaining = values["available_bytes" if group == "memory" else "free_bytes"]
            if total is not None and any(value is not None and value > total for value in (used, remaining)):
                raise ValueError("Inconsistent capacity measurements.")
    if not has_value:
        raise ValueError("No valid measurements.")
    return data


def validate_process_arguments(arguments: dict) -> dict:
    limit, sort = arguments.get("limit", DEFAULT_PROCESS_LIMIT), arguments.get("sort", "pid")
    if (set(arguments) - {"limit", "sort"} or type(limit) is not int or not 1 <= limit <= MAX_PROCESS_LIMIT
            or not isinstance(sort, str) or sort not in {"pid", "memory"}):
        raise ToolInputError("Processes accepts limit 1 through 25 and sort pid or memory, without other arguments.")
    return {"limit": limit, "sort": sort}


def _process_name(value) -> str | None:
    if not isinstance(value, str):
        return None
    name = ntpath.basename(value)
    # Names are data: strip terminal controls and bound display length; never query paths or arguments.
    name = "".join(char for char in name if char.isprintable())[:120]
    return name or None


def collect_processes(arguments: dict) -> dict:
    psutil = initialize_measurements()
    counts = {"inaccessible_count": 0, "exited_count": 0, "enumerated_count": 0}

    def rows():
        iterator = iter(psutil.process_iter(attrs=["pid", "name", "memory_info"], ad_value=None))
        while True:
            try:
                process = next(iterator)
            except StopIteration:
                break
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                counts["exited_count"] += 1
                continue
            except psutil.AccessDenied:
                counts["inaccessible_count"] += 1
                continue
            try:
                info = process.info
                pid = info["pid"]
                if type(pid) is not int or pid < 0:
                    continue
                name = _process_name(info.get("name"))
                memory_info = info.get("memory_info")
                memory = getattr(memory_info, "rss", None)
                if not _valid(memory, "bytes"):
                    memory = None
                if name is None or memory is None:
                    counts["inaccessible_count"] += 1
                counts["enumerated_count"] += 1
                yield {"pid": pid, "name": name, "memory_bytes": memory}
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                counts["exited_count"] += 1
            except psutil.AccessDenied:
                counts["inaccessible_count"] += 1

    def key(row):
        return (-(row["memory_bytes"]) if row["memory_bytes"] is not None else math.inf, row["pid"]) if arguments["sort"] == "memory" else row["pid"]

    clear_cache = getattr(psutil.process_iter, "cache_clear", None)
    try:
        if callable(clear_cache):
            clear_cache()
        processes = heapq.nsmallest(arguments["limit"], rows(), key=key)
    except Exception:
        raise ToolExecutionError("The running process snapshot could not be collected.") from None
    finally:
        if callable(clear_cache):
            clear_cache()
    if not processes and (counts["inaccessible_count"] or counts["exited_count"]):
        raise ToolExecutionError("No process entries could be inspected: processes exited or access was denied.")
    return {"processes": processes, "limit": arguments["limit"], "sort": arguments["sort"], **counts,
            "collected_at": datetime.now(UTC).isoformat(), "source": SOURCE}


def validate_process_output(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {"processes", "limit", "sort", "inaccessible_count", "exited_count", "enumerated_count", "collected_at", "source"}:
        raise ValueError("Invalid process output.")
    _validate_metadata(data)
    validate_process_arguments({"limit": data["limit"], "sort": data["sort"]})
    if (not isinstance(data["processes"], list) or len(data["processes"]) > data["limit"]
            or any(type(data[field]) is not int or data[field] < 0 for field in ("inaccessible_count", "exited_count", "enumerated_count"))):
        raise ValueError("Invalid process result bounds.")
    seen = set()
    for row in data["processes"]:
        if (not isinstance(row, dict) or set(row) != {"pid", "name", "memory_bytes"}
                or type(row["pid"]) is not int or row["pid"] < 0 or row["pid"] in seen
                or (row["name"] is not None and (not _valid(row["name"], "text") or _process_name(row["name"]) != row["name"]))
                or (row["memory_bytes"] is not None and not _valid(row["memory_bytes"], "bytes"))):
            raise ValueError("Invalid or private process fields.")
        seen.add(row["pid"])
    return data


def system_tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition("system.snapshot", "Read a current Windows CPU, RAM, system-drive, or OS snapshot.",
                       validate_snapshot_arguments, validate_snapshot_output, Permission.READ_ONLY, collect_snapshot),
        ToolDefinition("system.processes", "Read a bounded process-name, PID, and resident-memory snapshot on request.",
                       validate_process_arguments, validate_process_output, Permission.READ_ONLY, collect_processes),
    )
