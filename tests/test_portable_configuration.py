import hashlib
import os
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

import aika
from src import config
from src.memory.store import MemoryStore
from src.storage.conversation_store import ConversationStore


@pytest.fixture
def sources(tmp_path, monkeypatch):
    user = config.resolve_user_config_path()
    user.parent.mkdir(parents=True)
    return config.DOTENV_PATH, user


def test_precedence_environment_user_development_defaults(sources, monkeypatch):
    dev, user = sources
    for key in ("AIKA_APP_NAME", "AIKA_MODEL_TIMEOUT", "AIKA_CONTEXT_TURNS", "AIKA_RESPONSE_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    dev.write_text('AIKA_APP_NAME=Development\nAIKA_MODEL_TIMEOUT=55\nAIKA_CONTEXT_TURNS=3\n', encoding="utf-8")
    user.write_text('AIKA_APP_NAME=User\nAIKA_MODEL_TIMEOUT=42\n', encoding="utf-8")
    settings = config.load_config()
    assert (settings.app_name, settings.model_timeout, settings.context_turns, settings.response_tokens) == ("User", 42, 3, 1024)
    monkeypatch.setenv("AIKA_APP_NAME", "Process")
    assert config.load_config().app_name == "Process"
    assert settings.configuration_sources[:2] == ("development .env", "user")


def test_empty_environment_value_remains_authoritative(sources, monkeypatch):
    dev, user = sources
    dev.write_text('AIKA_TAVILY_API_KEY=development-key\n', encoding="utf-8")
    user.write_text('AIKA_TAVILY_API_KEY=user-key\nAIKA_WEB_SEARCH_ENABLED=on\nAIKA_WEB_SEARCH_FALLBACK_ENABLED=on\n', encoding="utf-8")
    settings = config.load_config()
    assert settings.tavily_api_key == "" and not settings.web_search_enabled and not settings.web_search_fallback_enabled
    monkeypatch.delenv("AIKA_TAVILY_API_KEY")
    assert config.load_config().tavily_api_key == "user-key"


def test_missing_configuration_creates_nothing(tmp_path):
    settings = config.load_config()
    assert "user" not in settings.configuration_sources and "development .env" not in settings.configuration_sources
    assert list(tmp_path.iterdir()) == []


def test_working_directory_never_becomes_configuration_authority(tmp_path, monkeypatch):
    unrelated = tmp_path / "unrelated working directory"
    unrelated.mkdir()
    (unrelated / "pyproject.toml").write_text('[project]\nname="aika-ai-v2"\n', encoding="utf-8")
    (unrelated / ".env").write_text('AIKA_APP_NAME=Untrusted cwd\n', encoding="utf-8")
    monkeypatch.chdir(unrelated)
    assert config.load_config().app_name == "AIKA AI V2"


def test_wheel_record_ownership_disables_adjacent_development_config(monkeypatch):
    module = Path(config.__file__).resolve()
    package = NS(read_text=lambda name: "record", files=[Path("src/config.py")], locate_file=lambda _: module)
    monkeypatch.setattr(config, "distribution", lambda _: package)
    config.DOTENV_PATH.write_text('AIKA_APP_NAME=Must not be used\n', encoding="utf-8")
    settings = config.load_config()
    assert config.resolve_development_config_path() is None
    assert settings.app_name == "AIKA AI V2" and settings.configuration_mode == "Installed / non-checkout runtime"


def test_source_execution_does_not_require_an_editable_install(monkeypatch):
    def missing(_):
        raise config.PackageNotFoundError()
    monkeypatch.setattr(config, "distribution", missing)
    config.DOTENV_PATH.write_text('AIKA_APP_NAME=Source runtime\n', encoding="utf-8")
    assert config.load_config().app_name == "Source runtime"
    assert config.load_config().configuration_mode == "Source checkout"


def test_egg_info_is_not_mistaken_for_wheel_ownership(monkeypatch):
    module = Path(config.__file__).resolve()
    monkeypatch.setattr(config, "distribution", lambda _: NS(read_text=lambda _: None, files=[Path("src/config.py")], locate_file=lambda _: module))
    assert config.resolve_development_config_path() == config.DOTENV_PATH


@pytest.mark.parametrize("project_name", ["unrelated-project", None])
def test_unverified_module_tree_does_not_load_adjacent_config(tmp_path, monkeypatch, project_name):
    root = tmp_path / "unknown module tree"
    (root / "src").mkdir(parents=True)
    (root / "aika.py").write_text("", encoding="utf-8")
    if project_name:
        (root / "pyproject.toml").write_text(f'[project]\nname="{project_name}"\n', encoding="utf-8")
    monkeypatch.setattr(config, "__file__", str(root / "src/config.py"))
    monkeypatch.setattr(config, "DOTENV_PATH", root / ".env")
    config.DOTENV_PATH.write_text('AIKA_APP_NAME=Must not be used\n', encoding="utf-8")
    assert config.resolve_development_config_path() is None and config.load_config().app_name == "AIKA AI V2"


@pytest.mark.parametrize("payload", [b'AIKA_TAVILY_API_KEY="private-unclosed', b'private secret invalid syntax', b'private-\xff'])
def test_malformed_user_config_fails_without_fallback_or_secret_echo(sources, payload):
    dev, user = sources
    dev.write_text('AIKA_APP_NAME=Fallback forbidden\n', encoding="utf-8")
    user.write_bytes(payload)
    with pytest.raises(config.ConfigError) as error:
        config.load_config()
    assert "private" not in str(error.value) and str(user) not in str(error.value)


def test_unreadable_user_config_does_not_fall_back(sources, monkeypatch):
    _, user = sources
    user.write_text("AIKA_APP_NAME=Secret\n", encoding="utf-8")
    original = Path.open
    def blocked(path, *args, **kwargs):
        if path == user:
            raise PermissionError("private profile and credential")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", blocked)
    with pytest.raises(config.ConfigError) as error:
        config.load_config()
    assert "private" not in str(error.value) and str(user) not in str(error.value)


@pytest.mark.parametrize("kind", ["directory", "oversized"])
def test_invalid_config_file_type_and_size_fail_closed(sources, kind):
    _, user = sources
    if kind == "directory":
        user.mkdir()
    else:
        user.write_bytes(b"x" * (config.MAX_CONFIG_BYTES + 1))
    with pytest.raises(config.ConfigError, match="regular file"):
        config.load_config()


@pytest.mark.parametrize("ancestor", [False, True])
def test_config_indirections_are_rejected_before_read(sources, monkeypatch, ancestor):
    _, user = sources
    user.write_text("AIKA_APP_NAME=Secret\n", encoding="utf-8")
    target = user.parent if ancestor else user
    original = Path.lstat
    def linked(path):
        info = original(path)
        if path == target:
            return NS(st_mode=info.st_mode, st_size=info.st_size, st_file_attributes=config.stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info
    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(config.ConfigError, match="indirections"):
        config.load_config()


def test_config_cannot_change_identity_between_check_and_open(sources, monkeypatch):
    _, user = sources
    user.write_text("AIKA_APP_NAME=Secret\n", encoding="utf-8")
    original = os.fstat
    def swapped(fd):
        info = original(fd)
        return NS(st_dev=info.st_dev, st_ino=info.st_ino + 1)
    with monkeypatch.context() as guard:
        guard.setattr(os, "fstat", swapped)
        with pytest.raises(config.ConfigError, match="changed while opening"):
            config.load_config()


def test_loading_user_config_does_not_create_or_redirect_database(sources, tmp_path, monkeypatch):
    dev, user = sources
    original_data = tmp_path / "existing data"
    monkeypatch.delenv("AIKA_DATA_DIR")
    dev.write_text(f'AIKA_DATA_DIR="{original_data.as_posix()}"\n', encoding="utf-8")
    user.write_text('AIKA_APP_NAME=User label\n', encoding="utf-8")
    assert config.load_config().data_dir == original_data
    assert not original_data.exists()
    alternate = tmp_path / "deliberate override"
    user.write_text(f'AIKA_DATA_DIR="{alternate.as_posix()}"\n', encoding="utf-8")
    assert config.load_config().data_dir == alternate
    monkeypatch.setenv("AIKA_DATA_DIR", str(original_data))
    assert config.load_config().data_dir == original_data
    assert config.resolve_user_config_path() == user


def test_configuration_loading_leaves_synthetic_history_memory_schema_unchanged(sources, tmp_path, monkeypatch):
    _, user = sources
    directory = tmp_path / "synthetic data"
    memory, conversations = MemoryStore(directory), ConversationStore(directory)
    memory.set_fact("project", "Synthetic", "frontend", "SvelteKit")
    conversations.save_exchange("a" * 32, 0, "Synthetic question", "Synthetic answer")
    before = hashlib.sha256(memory.path.read_bytes()).hexdigest()
    user.write_text('AIKA_CONTEXT_CHARS=8192\n', encoding="utf-8")
    monkeypatch.setenv("AIKA_DATA_DIR", str(directory))
    assert config.load_config().data_dir == directory
    assert hashlib.sha256(memory.path.read_bytes()).hexdigest() == before


def test_unicode_profile_config_and_data_defaults_are_independent(tmp_path, monkeypatch):
    profile = tmp_path / "Profilé 使用者 with spaces"
    monkeypatch.setenv("LOCALAPPDATA", str(profile))
    monkeypatch.delenv("AIKA_DATA_DIR")
    user = config.resolve_user_config_path()
    user.parent.mkdir(parents=True)
    user.write_text('AIKA_APP_NAME=Unicode profile\n', encoding="utf-8-sig")
    assert user == profile / "AIKA AI V2/config/.env"
    assert config.load_config().data_dir == profile / "AIKA AI V2/data"


@pytest.mark.skipif(os.name != "nt", reason="Windows drive semantics")
def test_user_root_does_not_assume_c_drive(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "Z:\\Synthetic Profile\\Local")
    monkeypatch.delenv("AIKA_DATA_DIR")
    assert config.resolve_user_config_path().drive == "Z:"
    assert config.load_config().data_dir.drive == "Z:"


def test_config_diagnostics_use_labels_without_secret_or_profile_paths(sources, mock_ollama, capsys):
    _, user = sources
    user.write_text('AIKA_TAVILY_API_KEY=private-key-never-print\n', encoding="utf-8")
    mock_ollama()
    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr()
    assert "User configuration: Present and readable." in output.out
    assert "Configuration sources:" in output.out and "process environment" in output.out
    assert "private-key-never-print" not in output.out + output.err
    assert str(user.parent) not in output.out + output.err


def test_invalid_user_config_doctor_does_not_probe_storage_or_leak(sources, monkeypatch, capsys):
    _, user = sources
    user.write_text('AIKA_APP_NAME="private-unclosed\n', encoding="utf-8")
    storage = Mock(side_effect=AssertionError("Invalid config must stop before storage"))
    monkeypatch.setattr("src.cli.inspect_storage", storage)
    assert aika.main(["doctor"]) == 1
    output = capsys.readouterr()
    assert "FAIL  Configuration:" in output.out and "private-unclosed" not in output.out + output.err
    storage.assert_not_called()


def test_user_file_is_not_interpolated_and_helpers_share_precedence(sources, monkeypatch):
    _, user = sources
    for key in ("AIKA_TAVILY_API_KEY", "AIKA_VERSION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRIVATE_SECRET", "do-not-expand")
    user.write_text('AIKA_TAVILY_API_KEY=${PRIVATE_SECRET}\nAIKA_VERSION=1.2.3\n', encoding="utf-8")
    assert config.load_config().tavily_api_key == "${PRIVATE_SECRET}"
    assert config.load_version() == "1.2.3" and config.load_data_dir() == config.load_config().data_dir
