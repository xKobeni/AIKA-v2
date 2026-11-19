import json
import math
import os
import re
import io
import stat
import tomllib
from importlib.metadata import distribution, PackageNotFoundError
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv.parser import parse_stream

from src import __version__


DOTENV_PATH = Path(__file__).resolve().parents[1] / ".env"
MAX_CONFIG_BYTES = 65536

DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_MODEL_TIMEOUT = 180.0
DEFAULT_CONTEXT_TURNS = 10
MAX_CONTEXT_TURNS = 50
DEFAULT_CONTEXT_CHARS = 24000
MIN_CONTEXT_CHARS = 4096
MAX_CONTEXT_CHARS = 64000
DEFAULT_RESPONSE_TOKENS = 1024
MAX_RESPONSE_TOKENS = 4096


class ConfigError(ValueError):
    """A configuration error safe to display without the input value."""


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    log_level: str
    data_dir: Path
    runtime_url: str
    model: str = DEFAULT_MODEL
    model_timeout: float = DEFAULT_MODEL_TIMEOUT
    context_turns: int = DEFAULT_CONTEXT_TURNS
    ollama_think: str = "off"
    context_debug: str = "off"
    context_debug_public: tuple[str, ...] = ()
    disabled_apps: tuple[str, ...] = ()
    web_search_enabled: bool = False
    tavily_api_key: str = field(default="", repr=False)
    web_search_provider: str = "auto"
    web_search_fallback_enabled: bool = False
    web_search_fallback_provider: str = "tavily"
    web_reading_enabled: bool = False
    web_debug: bool = False
    research_timeout: float = 180.0
    timezone: str = "local"
    agent_timeout: float = 180.0
    context_chars: int = DEFAULT_CONTEXT_CHARS
    response_tokens: int = DEFAULT_RESPONSE_TOKENS
    configuration_mode: str = field(default="Not inspected", compare=False, repr=False)
    configuration_sources: tuple[str, ...] = field(default=(), compare=False, repr=False)


def resolve_development_config_path() -> Path | None:
    """Trust the executing source tree, never the working directory or a wheel's neighbors."""
    module = Path(__file__).resolve()
    root = module.parents[1]
    try:
        package = distribution("aika-ai-v2")
        if package.read_text("RECORD") is not None and any(
            str(item).replace("\\", "/") == "src/config.py" and package.locate_file(item).resolve() == module
            for item in (package.files or ())
        ):
            return None
    except PackageNotFoundError:
        pass
    except (OSError, UnicodeError, ValueError):
        raise ConfigError("Cannot verify the installed configuration source.") from None
    try:
        with (root / "pyproject.toml").open("rb") as stream:
            metadata = tomllib.load(stream)
        if (metadata.get("project", {}).get("name") == "aika-ai-v2"
                and (root / "aika.py").is_file() and module == root / "src" / "config.py"):
            return DOTENV_PATH
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        raise ConfigError("Cannot verify the development configuration source.") from None
    return None


def resolve_user_config_path() -> Path:
    # Configuration discovery must never inherit AIKA_DATA_DIR from any source.
    try:
        profile = {key: value for key, value in os.environ.items() if key == "LOCALAPPDATA"}
        return load_data_dir(profile).parent / "config" / ".env"
    except ConfigError:
        raise ConfigError("The user configuration location is invalid.") from None


def _read_configuration_file(path: Path, label: str) -> dict[str, str] | None:
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise ConfigError(f"The {label} configuration path is invalid.")
        try:
            original = path.lstat()
        except FileNotFoundError:
            return None
        for candidate in (path, *path.parents):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ConfigError(f"The {label} configuration cannot use file or directory indirections.")
        if not stat.S_ISREG(original.st_mode) or original.st_size > MAX_CONFIG_BYTES:
            raise ConfigError(f"The {label} configuration must be a regular file of at most 64 KiB.")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino):
                raise ConfigError(f"The {label} configuration changed while opening; retry explicitly.")
            raw = stream.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            raise ConfigError(f"The {label} configuration exceeds 64 KiB.")
        values = {}
        for binding in parse_stream(io.StringIO(raw.decode("utf-8-sig"))):
            if binding.error:
                raise ConfigError(f"The {label} configuration contains malformed .env syntax.")
            if binding.key is not None and binding.value is not None:
                values[binding.key] = binding.value
        return values
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"The {label} configuration could not be read as UTF-8.") from None


def _configuration_values():
    development = resolve_development_config_path()
    values = {}
    sources = []
    for path, label in ((development, "development .env"), (resolve_user_config_path(), "user")):
        if path is not None:
            selected = _read_configuration_file(path, label)
            if selected is not None:
                values.update(selected)
                sources.append(label)
    if any(key.startswith("AIKA_") for key in os.environ):
        sources.append("process environment")
    return {**values, **os.environ}, tuple(sources), "Source checkout" if development is not None else "Installed / non-checkout runtime"


def load_version(environment: Mapping[str, str] | None = None) -> str:
    environment = _configuration_values()[0] if environment is None else environment
    version = environment.get("AIKA_VERSION", __version__)
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        raise ConfigError("AIKA_VERSION must use a numeric X.Y.Z version, such as 0.1.0.")
    return version


def _bounded_integer(environment, key, default, minimum, maximum):
    error = f"{key} must be a whole number from {minimum} to {maximum}."
    try:
        value = int(environment.get(key, default))
    except ValueError:
        raise ConfigError(error) from None
    if not minimum <= value <= maximum:
        raise ConfigError(error)
    return value


def load_config() -> Settings:
    environment, sources, mode = _configuration_values()
    name = environment.get("AIKA_APP_NAME", "AIKA AI V2").strip()
    if not name or len(name) > 80 or not name.isprintable():
        raise ConfigError("AIKA_APP_NAME must contain 1 to 80 printable characters.")

    log_level = environment.get("AIKA_LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("AIKA_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL.")

    url_key = "AIKA_OLLAMA_URL" if "AIKA_OLLAMA_URL" in environment else "AIKA_RUNTIME_URL"
    runtime_url = environment.get(url_key, "http://127.0.0.1:11434")
    validate_runtime_url(runtime_url, url_key)

    model = environment.get("AIKA_OLLAMA_MODEL", DEFAULT_MODEL)
    if not re.fullmatch(r"(?:[\w.-]+/)*[a-zA-Z0-9_][\w.-]*(?::[a-zA-Z0-9_][\w.-]*)?", model, re.ASCII):
        raise ConfigError(f"AIKA_OLLAMA_MODEL must be an Ollama model name, such as {DEFAULT_MODEL}.")
    if model.lower().endswith((":cloud", "-cloud")):
        raise ConfigError("AIKA_OLLAMA_MODEL must select a local model. Cloud models are unavailable.")

    timeout_error = "AIKA_MODEL_TIMEOUT must be a finite positive number of seconds."
    try:
        timeout = float(environment.get("AIKA_MODEL_TIMEOUT", DEFAULT_MODEL_TIMEOUT))
    except ValueError:
        raise ConfigError(timeout_error) from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ConfigError(timeout_error)

    context_turns = _bounded_integer(environment, "AIKA_CONTEXT_TURNS", DEFAULT_CONTEXT_TURNS, 0, MAX_CONTEXT_TURNS)
    context_chars = _bounded_integer(environment, "AIKA_CONTEXT_CHARS", DEFAULT_CONTEXT_CHARS, MIN_CONTEXT_CHARS, MAX_CONTEXT_CHARS)
    response_tokens = _bounded_integer(environment, "AIKA_RESPONSE_TOKENS", DEFAULT_RESPONSE_TOKENS, 64, MAX_RESPONSE_TOKENS)

    ollama_think = environment.get("AIKA_OLLAMA_THINK", "off").strip().lower()
    if ollama_think not in {"off", "on", "default"}:
        raise ConfigError("AIKA_OLLAMA_THINK must be off, on, or default.")
    context_debug = environment.get("AIKA_CONTEXT_DEBUG", "off").strip().lower()
    if context_debug not in {"off", "roles", "content"}:
        raise ConfigError("AIKA_CONTEXT_DEBUG must be off, roles, or content.")
    public_messages = []
    if context_debug == "content":
        public_error = "AIKA_CONTEXT_DEBUG_PUBLIC must be a JSON array of public message strings."
        try:
            public_messages = json.loads(environment.get("AIKA_CONTEXT_DEBUG_PUBLIC", "[]"))
        except (ValueError, RecursionError):
            raise ConfigError(public_error) from None
        if not isinstance(public_messages, list) or not all(isinstance(message, str) for message in public_messages):
            raise ConfigError(public_error)

    apps_error = "AIKA_DISABLED_APPS must be a JSON array containing only notepad, calculator, or spotify IDs."
    try:
        disabled_apps = json.loads(environment.get("AIKA_DISABLED_APPS", "[]"))
    except (ValueError, RecursionError):
        raise ConfigError(apps_error) from None
    if (not isinstance(disabled_apps, list)
            or any(not isinstance(item, str) or item not in {"notepad", "calculator", "spotify"} for item in disabled_apps)
            or len(set(disabled_apps)) != len(disabled_apps)):
        raise ConfigError(apps_error)

    web_enabled = environment.get("AIKA_WEB_SEARCH_ENABLED", "off").strip().casefold()
    if web_enabled not in {"off", "on", "false", "true", "0", "1"}:
        raise ConfigError("AIKA_WEB_SEARCH_ENABLED must be off/on, false/true, or 0/1.")
    api_key = environment.get("AIKA_TAVILY_API_KEY", "")
    try:
        agent_timeout = float(environment.get("AIKA_AGENT_TIMEOUT", "180"))
    except ValueError:
        raise ConfigError("AIKA_AGENT_TIMEOUT must be 30 to 300 seconds.") from None
    if not math.isfinite(agent_timeout) or not 30 <= agent_timeout <= 300:
        raise ConfigError("AIKA_AGENT_TIMEOUT must be 30 to 300 seconds.")
    try:
        research_timeout = float(environment.get("AIKA_RESEARCH_TIMEOUT", "180"))
    except ValueError:
        raise ConfigError("AIKA_RESEARCH_TIMEOUT must be 30 to 300 seconds.") from None
    if not math.isfinite(research_timeout) or not 30 <= research_timeout <= 300:
        raise ConfigError("AIKA_RESEARCH_TIMEOUT must be 30 to 300 seconds.")
    timezone = environment.get("AIKA_TIMEZONE", "local")
    if timezone != "local":
        if len(timezone) > 100 or not timezone.isprintable():
            raise ConfigError("AIKA_TIMEZONE must be local or an available IANA timezone, such as Asia/Manila.")
        try:
            ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ConfigError("AIKA_TIMEZONE must be local or an available IANA timezone, such as Asia/Manila.") from None
    reading = environment.get("AIKA_WEB_READING_ENABLED", "off").strip().casefold()
    web_debug = environment.get("AIKA_WEB_DEBUG", "off").strip().casefold()
    if web_debug not in {"off", "on", "false", "true", "0", "1"}:
        raise ConfigError("AIKA_WEB_DEBUG must be off/on, false/true, or 0/1.")
    if reading not in {"off", "on", "false", "true", "0", "1"}:
        raise ConfigError("AIKA_WEB_READING_ENABLED must be off/on, false/true, or 0/1.")
    if not valid_tavily_key(api_key):
        raise ConfigError("AIKA_TAVILY_API_KEY must be empty or a printable ASCII token of at most 512 characters without whitespace.")
    provider = environment.get("AIKA_WEB_SEARCH_PROVIDER", "auto").strip().casefold()
    secondary = environment.get("AIKA_WEB_SEARCH_FALLBACK_PROVIDER", "tavily").strip().casefold()
    fallback = environment.get("AIKA_WEB_SEARCH_FALLBACK_ENABLED", "off").strip().casefold()
    if provider not in {"auto", "ddgs", "tavily"}:
        raise ConfigError("AIKA_WEB_SEARCH_PROVIDER must be auto, ddgs, or tavily.")
    if secondary not in {"ddgs", "tavily"}:
        raise ConfigError("AIKA_WEB_SEARCH_FALLBACK_PROVIDER must be ddgs or tavily.")
    if fallback not in {"off", "on", "false", "true", "0", "1"}:
        raise ConfigError("AIKA_WEB_SEARCH_FALLBACK_ENABLED must be off/on, false/true, or 0/1.")

    return Settings(
        name, load_version(environment), log_level, load_data_dir(environment), runtime_url,
        model, timeout, context_turns, ollama_think, context_debug, tuple(public_messages), tuple(disabled_apps),
        web_enabled in {"on", "true", "1"}, api_key,
        provider, fallback in {"on", "true", "1"}, secondary, reading in {"on", "true", "1"}, web_debug in {"on", "true", "1"},
        research_timeout, timezone, agent_timeout,
        context_chars, response_tokens,
        configuration_mode=mode, configuration_sources=sources,
    )


def valid_tavily_key(value: str) -> bool:
    return isinstance(value, str) and (value == "" or (
        len(value) <= 512 and value.isascii() and value.isprintable() and not any(char.isspace() for char in value)
    ))


def load_data_dir(environment: Mapping[str, str] | None = None) -> Path:
    environment = _configuration_values()[0] if environment is None else environment
    path = environment.get("AIKA_DATA_DIR")
    try:
        if path is None:
            local_app_data = environment.get("LOCALAPPDATA") if os.name == "nt" else None
            root = Path(local_app_data) if local_app_data else Path.home()
            path = str(root / ("AIKA AI V2" if local_app_data else ".aika-v2") / "data")
        directory = Path(path).expanduser()
    except (OSError, RuntimeError, ValueError):
        raise ConfigError("AIKA_DATA_DIR could not be resolved to a local directory path.") from None

    if not directory.is_absolute() or not path.isprintable() or directory.drive.startswith("\\\\"):
        raise ConfigError("AIKA_DATA_DIR must be an absolute local directory path.")
    if os.name == "nt" and has_invalid_windows_name(directory):
        raise ConfigError("AIKA_DATA_DIR contains a name that Windows reserves or does not allow.")
    return directory


def has_invalid_windows_name(directory: Path) -> bool:
    is_reserved = getattr(os.path, "isreserved", None)
    if is_reserved is not None:
        return is_reserved(directory)
    # Python 3.12's pathlib check covers device names. Check invalid characters and suffixes here.
    return any(
        part.is_reserved() or re.search(r'[<>:"/\\|?*]|[ .]$', part.name)
        for part in (directory, *directory.parents)
        if part.name and part.name != ".."
    )


def validate_runtime_url(value: str, key: str = "AIKA_RUNTIME_URL") -> None:
    error = f"{key} must be a loopback HTTP(S) origin without credentials, a query, or a fragment."
    if not value.isprintable() or any(char.isspace() for char in value):
        raise ConfigError(error)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ConfigError(error) from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.path not in {"", "/"}
        or "?" in value
        or "#" in value
        or port == 0
        or parsed.netloc.endswith(":")
    ):
        raise ConfigError(error)
