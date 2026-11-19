import platform
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from src.capabilities import create_registry
from src.capabilities.applications import create_applications
from src.capabilities.contracts import Permission, ToolExecutionError, ToolRequest, ToolStatus
from src.capabilities.system_info import initialize_measurements
from src.capabilities.web_search import ENDPOINT, MAX_RESULTS, SearchRouter
from src.capabilities.executor import ToolExecutor
from src.config import ConfigError, Settings, load_config
from src.intelligence.ollama_client import ModelUnavailable, OllamaClient, OllamaError
from src.storage.conversation_store import ConversationStore
from src.storage.database import DATABASE_NAME, StorageError


MINIMUM_PYTHON = (3, 12)
RUNTIME_FILES = (
    "aika.py",
    "src/__init__.py",
    "src/cli.py",
    "src/config.py",
    "src/diagnostics.py",
    "src/intelligence/conversation.py",
    "src/intelligence/ollama_client.py",
    "src/intelligence/planning.py",
    "src/intelligence/dataflow.py",
    "src/intelligence/prompt_budget.py",
    "src/storage/conversation_store.py",
    "src/storage/database.py",
    "src/memory/store.py",
    "src/memory/cli.py",
    "src/memory/chat.py",
    "src/memory/intent.py",
    "src/memory/retrieval.py",
    "src/capabilities/__init__.py",
    "src/capabilities/contracts.py",
    "src/capabilities/registry.py",
    "src/capabilities/executor.py",
    "src/capabilities/calculator.py",
    "src/capabilities/intent.py",
    "src/capabilities/discovery.py",
    "src/capabilities/language.py",
    "src/capabilities/applications.py",
    "src/capabilities/application_intent.py",
    "src/capabilities/system_info.py",
    "src/capabilities/system_intent.py",
    "src/capabilities/web_search.py",
    "src/capabilities/web_intent.py",
    "src/capabilities/web_reader.py",
    "src/capabilities/web_content.py",
    "src/capabilities/web_answer.py",
    "src/capabilities/web_read_intent.py",
    "src/capabilities/web_diagnostics.py",
    "src/capabilities/research.py",
    "src/capabilities/web_budget.py",
)


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str


def check_python(version: tuple[int, ...]) -> Check:
    installed = ".".join(map(str, version[:3]))
    if version[:2] < MINIMUM_PYTHON:
        return Check("FAIL", "Python", f"Found {installed}. Python 3.12 or newer is required.")
    return Check("PASS", "Python", f"Found {installed}, which meets the 3.12+ requirement.")


def check_data_dir(directory: Path) -> Check:
    for candidate in (directory, *directory.parents):
        try:
            mode = candidate.stat().st_mode
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return Check("FAIL", "Data directory", "Cannot inspect AIKA_DATA_DIR or its parent.")
        if not stat.S_ISDIR(mode):
            return Check("FAIL", "Data directory", "AIKA_DATA_DIR or one of its parents is not a directory.")
        if candidate == directory:
            return Check("PASS", "Data directory", "The configured directory exists.")
        return Check("WARN", "Data directory", "The directory does not exist yet. An existing parent was found.")
    return Check("FAIL", "Data directory", "No existing parent was found for AIKA_DATA_DIR.")


def inspect_runtime() -> tuple[Settings | None, list[Check]]:
    checks = [check_python(tuple(sys.version_info[:3]))]
    root = Path(__file__).parent.parent
    try:
        has_metadata = (root / "pyproject.toml").is_file()
        missing = [name for name in RUNTIME_FILES if not (root / name).is_file()]
    except OSError:
        checks.append(Check("FAIL", "Runtime files", "Could not inspect the runtime directory."))
        return None, checks

    if has_metadata:
        checks.append(Check("PASS", "Project directory", "Found the project root beside the runtime module."))
    elif missing:
        checks.append(Check("WARN", "Project directory", "No source project metadata beside the runtime module."))
    else:
        checks.append(Check("PASS", "Project directory", "Installed runtime; source project metadata is not required."))

    if missing:
        checks.append(Check("FAIL", "Runtime files", f"Missing {', '.join(missing)}."))
    else:
        checks.append(Check("PASS", "Runtime files", "All required Python files are present."))

    if platform.system() == "Windows":
        checks.append(Check("PASS", "Environment", "Running on the Windows target platform."))
    else:
        checks.append(Check("WARN", "Environment", "This checkpoint targets Windows for manual acceptance."))

    try:
        settings = load_config()
    except ConfigError as exc:
        checks.append(Check("FAIL", "Configuration", str(exc)))
        return None, checks

    checks.append(Check("PASS", "Configuration", "Environment settings passed validation."))
    checks.append(Check("PASS", "Configuration mode", settings.configuration_mode))
    checks.append(Check("PASS", "Configuration sources", " < ".join(("defaults", *settings.configuration_sources)) + " (highest priority last; values hidden)."))
    checks.append(Check("PASS", "User configuration", "Present and readable." if "user" in settings.configuration_sources else "Absent; optional."))
    checks.append(Check("PASS", "Development .env", "Loaded from verified source checkout." if "development .env" in settings.configuration_sources else "Not used."))
    checks.append(check_data_dir(settings.data_dir))
    return settings, checks


def inspect_storage(data_dir: Path) -> list[Check]:
    try:
        if (data_dir / DATABASE_NAME).exists():
            store = ConversationStore(data_dir, create=False)
            store.verify()
            detail = "The existing conversation database is compatible, passed integrity checks, and is writable."
            if store.schema_version >= 2:
                memory = Check("PASS", "Structured Memory", "READY. Fact and revision tables are accessible.")
            else:
                memory = Check("WARN", "Structured Memory", "Schema upgrade pending. Chat or a memory command initializes it.")
        else:
            parent = next(path for path in (data_dir, *data_dir.parents) if path.is_dir())
            with TemporaryDirectory(dir=parent) as probe:
                ConversationStore(Path(probe)).verify()
            detail = "A temporary database passed schema and write checks. Chat or memory will create the AIKA database."
            memory = Check("WARN", "Structured Memory", "Temporary schema verified. The configured database has not been created yet.")
    except StorageError as exc:
        return [Check("FAIL", "SQLite", str(exc)), Check("WARN", "Structured Memory", "Unavailable until storage is repaired.")]
    except (OSError, StopIteration):
        return [Check("FAIL", "SQLite", "Cannot verify writable storage. Check AIKA_DATA_DIR and its permissions.")]
    checks = [Check("PASS", "SQLite", detail), memory]
    if memory.status == "PASS":
        checks.append(Check("PASS", "Conversation Memory", "Explicit recall, corrections, and confirmed deletion are available."))
    return checks


def inspect_ollama(settings: Settings) -> list[Check]:
    try:
        with OllamaClient(settings) as client:
            client.check_model()
    except ModelUnavailable as exc:
        model = Check("WARN", "Model", str(exc))
    except OllamaError as exc:
        return [
            Check("WARN", "Ollama", str(exc)),
            Check("WARN", "Model", f"Could not verify {settings.model}."),
        ]
    else:
        model = Check("PASS", "Model", f"{settings.model} is installed locally.")
    return [Check("PASS", "Ollama", "The local model API responded."), model]


def inspect_tools() -> list[Check]:
    try:
        registry = create_registry()
        count = len(registry.list_tools())
        result = ToolExecutor(registry).execute(ToolRequest("calculator.evaluate", {"expression": "0.1 + 0.2"}))
        ready = result.status == ToolStatus.SUCCESS and result.verified and result.data == {"result": "0.3"}
    except Exception:
        return [Check("FAIL", "Tool Registry", "Registration or validation failed."),
                Check("FAIL", "Calculator", "Unavailable.")]
    return [Check("PASS", "Tool Registry", "Initialized."),
            Check("PASS" if ready else "FAIL", "Calculator", "Available; execution probe passed." if ready else "Execution probe failed."),
            Check("PASS", "Tools Registered", str(count))]


def inspect_applications(settings: Settings) -> list[Check]:
    try:
        apps = create_applications(settings.disabled_apps)
        tool = create_registry(apps).lookup("app.open")
        compatible = apps.system_directory is not None
        checks = [Check("PASS" if compatible else "WARN", "Application Launcher",
                        "Registered; Windows system directory resolved. No applications launched." if compatible else "Windows launch support is unavailable."),
                  Check("PASS", "Registered Applications", str(len(apps.list_apps())))]
        for app in apps.list_apps():
            available = apps.availability(app)
            status = "FAIL" if available == "INVALID_TARGET" else "PASS" if available == "AVAILABLE" else "WARN"
            detail = f"{available}; {'ENABLED' if app.enabled else 'DISABLED'}; {tool.permission}."
            if available == "AVAILABLE":
                detail += " Approved executable exists; application readiness not verified."
            if app.app_id == "spotify":
                detail += " No audited Spotify launch target is configured; installation not inferred."
            checks.append(Check(status, app.display_name, detail))
        return checks
    except (OSError, ValueError, LookupError):
        return [Check("FAIL", "Application Launcher", "Approved application registration or target validation failed.")]


def inspect_system_tools() -> list[Check]:
    try:
        psutil = initialize_measurements()
        registry = create_registry()
        for name in ("system.snapshot", "system.processes"):
            tool = registry.lookup(name)
            if tool.permission != Permission.READ_ONLY or not isinstance(tool.input_contract({}), dict):
                raise ValueError("Invalid system tool contract.")
    except ToolExecutionError as exc:
        return [Check("WARN" if platform.system() != "Windows" else "FAIL", "System Information", str(exc))]
    except Exception:
        return [Check("FAIL", "System Information", "System tool registration or contract initialization failed.")]
    return [Check("PASS", "System Information", "Windows supported; snapshot/process tools registered READ_ONLY; contracts initialized."),
            Check("PASS", "Measurement Dependency", f"psutil {psutil.__version__}; measurement interfaces available. No metrics sampled or processes enumerated.")]


def inspect_web_search(settings: Settings) -> list[Check]:
    provider = SearchRouter(settings.web_search_enabled, settings.tavily_api_key, settings.web_search_provider,
                            settings.web_search_fallback_enabled, settings.web_search_fallback_provider)
    try:
        tool = create_registry(web_search=provider).lookup("web.search")
        if tool.permission != Permission.READ_ONLY or tool.input_contract({"query": "diagnostic contract probe"})["max_results"] != MAX_RESULTS:
            raise ValueError("Invalid search contract")
        tool.output_contract({"query": "diagnostic contract probe", "provider": "tavily", "results": [],
                              "retrieved_at": "2000-01-01T00:00:00+00:00", "discarded_count": 0})
    except Exception:
        return [Check("WARN", "Web Search", "Unavailable: search tool contract initialization failed. No network request made.")]
    reason = provider.unavailable_reason()
    checks = [Check("WARN" if reason else "PASS", "Web Search", reason or "Selected route configured; provider connectivity/authentication not tested."),
            Check("PASS", "Web Search Configuration", f"Enabled={'yes' if provider.enabled else 'no'}; mode={provider.mode}; fallback={'yes' if provider.fallback_enabled else 'no'}; secondary={provider.secondary}; API key present={'yes' if provider.api_key else 'no'}; registered=web.search READ_ONLY; max_results={MAX_RESULTS}."),
            Check("PASS", "Search Provider Endpoint", f"{ENDPOINT}; diagnostics make no provider requests or use API credits.")]
    for name, adapter in (("DDGS", provider.ddgs), ("Tavily", provider.tavily)):
        unavailable = adapter.unavailable_reason()
        checks.append(Check("WARN" if unavailable else "PASS", f"{name} Search", unavailable or "Locally available; no connectivity test performed."))
    import importlib.util
    extraction_available = importlib.util.find_spec("trafilatura") is not None
    checks.append(Check("PASS" if extraction_available else "WARN", "Web Reading",
                        f"Enabled={'yes' if settings.web_reading_enabled and settings.web_search_enabled else 'no'}; "
                        f"registered=web.read READ_ONLY; extraction={'available' if extraction_available else 'unavailable'}; "
                        "selected public HTTPS only; no source request made."))
    checks.append(Check("PASS", "Research Configuration", f"Budget={settings.research_timeout:g}s; timezone={settings.timezone}; "
                        "one search, at most five read attempts and three successful sources; no diagnostic network requests."))
    checks.append(Check("PASS", "Agent Configuration", f"Budget={settings.agent_timeout:g}s; "
                        "4 plan steps, 8 executor calls, 2 model generations; no diagnostic execution."))
    return checks
