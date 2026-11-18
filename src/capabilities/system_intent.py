import re

from src.capabilities.contracts import ToolRequest, ToolResult, ToolStatus
from src.capabilities.system_info import CPU_INTERVAL


STORAGE_SPACE = r"(?:(?:free|available|remaining) )?(?:storage(?: space)?|disk space|space)"


def _text(prompt: str) -> str:
    text = prompt.replace("’", "'").strip().casefold()
    text = re.sub(r"^(?:hey\s+)?aika[, :]\s*", "", text)
    return re.sub(r"^please\s+", "", text.rstrip(".?!").strip())


def _matches(pattern: str, text: str) -> bool:
    return re.fullmatch(pattern, text) is not None


def _storage_request(text: str) -> bool:
    scope = r"on my (?:pc|computer|system drive)"
    return _matches(
        rf"how much {STORAGE_SPACE} (?:do i have(?: left)?|is (?:(?:left|available|free)(?: {scope})?|{scope}))|"
        rf"(?:what is|what's|check|show) my {STORAGE_SPACE}|how full is my system drive", text,
    )


def system_request(prompt: str) -> ToolRequest | None:
    raw = prompt.strip().casefold()
    direct = re.fullmatch(r"/system(?:\s+(.*))?", raw, re.DOTALL)
    if direct:
        return ToolRequest("system.snapshot", {"unsupported": True} if direct[1] else {})
    direct = re.fullmatch(r"/processes(?:\s+(.*))?", raw, re.DOTALL)
    if direct:
        limit = direct[1]
        return ToolRequest("system.processes", {} if limit is None else {
            "limit": int(limit) if re.fullmatch(r"[0-9]{1,3}", limit) else None,
        })
    text = _text(prompt)
    if _matches(r"(?:show|list)(?: me)? (?:(?:my|the) )?(?:(?:currently )?running processes|processes)|what processes are (?:currently )?running", text):
        return ToolRequest("system.processes", {})
    if _matches(r"which processes (?:are )?(?:using|use) (?:the )?most (?:ram|memory)", text):
        return ToolRequest("system.processes", {"sort": "memory"})
    top = re.fullmatch(r"(?:show|list)(?: me)? (?:the )?top ([0-9]+) processes by (?:memory|ram)", text)
    if top:
        return ToolRequest("system.processes", {"limit": int(top[1]) if len(top[1]) <= 3 else None, "sort": "memory"})
    section = None
    if _matches(r"(?:what is|what's) my (?:cpu|processor) (?:usage|utilization)|how busy is my processor|how many (?:cpu |processor )?cores do i have", text):
        section = "cpu"
    elif _matches(r"(?:what is|what's) my (?:ram|memory) usage|how much (?:ram|memory) (?:do i have|am i (?:currently )?using|is my (?:computer|pc) (?:currently )?using|is (?:currently )?(?:being )?used)", text):
        section = "memory"
    elif _storage_request(text):
        section = "storage"
    elif _matches(r"what windows version am i (?:using|running)|what (?:os|operating system) am i (?:using|running)", text):
        section = "os"
    elif _matches(r"(?:show|check)(?: me)? my (?:pc specs|system information|system info|computer specs)|(?:what's|what is) my system information|why is my (?:pc|computer) (?:so )?slow", text):
        section = "all"
    return ToolRequest("system.snapshot", {"section": section}) if section else None


def unsupported_measurement(prompt: str) -> str | None:
    text = _text(prompt)
    if re.search(r"\b(?:my|the) (?:cpu|processor)\b", text) and re.search(r"\b(?:temperature|temp|overheating|overheat)\b", text):
        return "CPU temperature monitoring is not implemented. I cannot determine overheating from CPU utilization alone."
    if _matches(
        rf"(?:how much {STORAGE_SPACE} (?:is (?:left|available|free)|do i have(?: left)?)|"
        rf"(?:what is|what's|check|show) my {STORAGE_SPACE}) (?:on|in) my .+|"
        r"how full is my .+ drive", text,
    ):
        if re.search(r"\b(?:google drive|onedrive|dropbox|cloud)\b", text):
            return "Cloud-storage account measurements are not implemented. I can measure only the local Windows system drive."
        return "Storage measurements currently cover only the Windows system drive. Other drives and storage locations are not implemented."
    return None


def gib(value: int | None) -> str:
    return "unavailable" if value is None else f"{value / (1024 ** 3):.2f} GiB"


def _percent(value) -> str:
    return "unavailable" if value is None else f"{value:.1f}%"


def format_system_result(result: ToolResult, prompt: str) -> str:
    if result.status != ToolStatus.SUCCESS or not result.verified or result.data is None:
        return f"System information error: {result.error or 'No verified measurement is available.'}"
    data = result.data
    lines = []
    if result.tool == "system.processes":
        lines = ["Running processes (resident memory; snapshot only):", "PID | Name | RAM"]
        for row in data["processes"]:
            lines.append(f"{row['pid']} | {row['name'] or '(name unavailable)'} | {gib(row['memory_bytes'])}")
        if not data["processes"]:
            lines.append("No process entries were returned by this snapshot.")
        lines.append(f"Showing {len(data['processes'])} of {data['enumerated_count']} readable process entries; sorted by {data['sort']}.")
        if data["inaccessible_count"] or data["exited_count"]:
            lines.append(f"Partly inaccessible or denied: {data['inaccessible_count']}; exited during inspection: {data['exited_count']}.")
        lines.append("Processes do not prove that application windows are open or responsive.")
    else:
        lines = ["AIKA System Information"]
        for group, values in data["measurements"].items():
            if group == "os":
                lines.extend([
                    f"Operating System: {values['name'] or 'unavailable'} {values['version'] or '(version unavailable)'}",
                    f"Windows Build: {values['build'] if values['build'] is not None else 'unavailable'}",
                    f"Architecture: {values['architecture'] or 'unavailable'}",
                ])
            elif group == "cpu":
                lines.extend([
                    f"CPU Usage: {_percent(values['usage_percent'])} (momentary {CPU_INTERVAL:g} s sample)",
                    f"Logical Cores: {values['logical_cores'] if values['logical_cores'] is not None else 'unavailable'}",
                    f"Physical Cores: {values['physical_cores'] if values['physical_cores'] is not None else 'unavailable'}",
                ])
            elif group == "memory":
                lines.extend([f"RAM: {gib(values['used_bytes'])} / {gib(values['total_bytes'])} used ({_percent(values['usage_percent'])})",
                              f"Available RAM: {gib(values['available_bytes'])} (available includes reclaimable memory; it is not just free memory)"])
            else:
                lines.extend([f"System Drive: {values['system_drive'] or 'unavailable'}",
                              f"Storage: {gib(values['free_bytes'])} free; {gib(values['used_bytes'])} / {gib(values['total_bytes'])} used ({_percent(values['usage_percent'])})"])
        if data["unavailable_fields"]:
            lines.append("Unavailable fields: " + ", ".join(data["unavailable_fields"]))
        if _matches(r"why is my (?:pc|computer) (?:so )?slow", _text(prompt)):
            lines.append("A single snapshot cannot diagnose why your PC is slow. These measurements describe only the sampled moment; temperature is not measured.")
    lines.append(f"Collected: {data['collected_at']} | Source: {data['source']}")
    return "\n".join(lines)


def guard_system_claim(answer: str) -> str:
    if re.search(
        r"\b(?:i (?:measured|checked|inspected|scanned) (?:your|the) (?:cpu|ram|memory|disk|storage|system|processes)|"
        r"your (?:cpu|ram|memory|disk|storage|pc|computer|system|windows)(?:[^\n.!?]{0,100})\d|"
        r"(?:you have|you're using|you are using) \d+(?:\.\d+)?\s*(?:gib|gb|mib|mb)\b|"
        r"(?:running process(?:es)?|process id|pid)\s*[:(=]?\s*\d|"
        r"(?:you're|you are|your (?:pc|computer) is) running windows \d|"
        r"^\s*(?:cpu(?: usage)?|ram|memory(?: usage)?|storage|disk(?: usage)?|windows version)\s*[:=]\s*(?:\d|windows)|"
        r"\b[\w.-]+\.exe\b[^\n]{0,60}\b\d+)", answer, re.IGNORECASE | re.MULTILINE,
    ):
        return "I haven't collected a live system measurement for this reply. Use /system or /processes for a current verified snapshot."
    return answer
