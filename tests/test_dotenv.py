import os

import pytest

from src import config


def test_dotenv_loads_key_and_settings_without_mutating_environment(monkeypatch):
    for key in ("AIKA_TAVILY_API_KEY", "AIKA_WEB_SEARCH_ENABLED", "AIKA_WEB_SEARCH_PROVIDER"):
        monkeypatch.delenv(key)
    config.DOTENV_PATH.write_text(
        '# Local settings\nAIKA_TAVILY_API_KEY="tvly-test-only"\n'
        'AIKA_WEB_SEARCH_ENABLED=on # intentional\nAIKA_WEB_SEARCH_PROVIDER=tavily\n',
        encoding="utf-8-sig",
    )
    settings = config.load_config()
    assert settings.tavily_api_key == "tvly-test-only"
    assert settings.web_search_enabled
    assert settings.web_search_provider == "tavily"
    assert "AIKA_TAVILY_API_KEY" not in os.environ
    assert "tvly-test-only" not in repr(settings)


def test_process_environment_overrides_dotenv_even_when_blank():
    config.DOTENV_PATH.write_text(
        "AIKA_TAVILY_API_KEY=tvly-file-secret\nAIKA_WEB_SEARCH_ENABLED=on\n",
        encoding="utf-8",
    )
    settings = config.load_config()
    assert settings.tavily_api_key == ""
    assert not settings.web_search_enabled


def test_dotenv_reloads_and_does_not_interpolate(monkeypatch):
    monkeypatch.delenv("AIKA_TAVILY_API_KEY")
    monkeypatch.setenv("OTHER_SECRET", "private-value")
    config.DOTENV_PATH.write_text("AIKA_TAVILY_API_KEY=${OTHER_SECRET}\n", encoding="utf-8")
    assert config.load_config().tavily_api_key == "${OTHER_SECRET}"
    config.DOTENV_PATH.write_text("AIKA_TAVILY_API_KEY=updated-token\n", encoding="utf-8")
    assert config.load_config().tavily_api_key == "updated-token"


def test_dotenv_helpers_share_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("AIKA_DATA_DIR")
    config.DOTENV_PATH.write_text(
        f'AIKA_VERSION=1.2.3\nAIKA_DATA_DIR="{tmp_path.as_posix()}"\n', encoding="utf-8"
    )
    assert config.load_version() == "1.2.3"
    assert config.load_data_dir() == tmp_path
    settings = config.load_config()
    assert settings.version == "1.2.3"
    assert settings.data_dir == tmp_path


def test_unreadable_dotenv_reports_safe_error():
    config.DOTENV_PATH.write_bytes(b"secret-token-\xff")
    with pytest.raises(config.ConfigError, match="could not be read as UTF-8") as error:
        config.load_config()
    assert "secret-token" not in str(error.value)


def test_invalid_dotenv_setting_does_not_echo_secret(monkeypatch):
    monkeypatch.delenv("AIKA_TAVILY_API_KEY")
    config.DOTENV_PATH.write_text('AIKA_TAVILY_API_KEY="private invalid token"\n', encoding="utf-8")
    with pytest.raises(config.ConfigError) as error:
        config.load_config()
    assert "private invalid token" not in str(error.value)
