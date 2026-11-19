import os
import subprocess
import sys
from pathlib import Path

import pytest

import aika
import src.diagnostics as diagnostics
from src import __version__
from src.config import Settings, load_config
from src.diagnostics import check_python


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "aika", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_import():
    assert callable(aika.main)


@pytest.mark.parametrize("ollama_model", ["qwen2.5:3b", "qwen3:4b"], indirect=True)
def test_startup(ollama_model):
    result = run_cli()
    assert result.returncode == 0, result.stderr
    assert "Core Runtime:    READY" in result.stdout
    assert "Configuration:   LOADED" in result.stdout
    assert "Current Phase:   6B" in result.stdout
    assert f"AI Model:        {ollama_model} (run doctor to check availability)" in result.stdout
    assert result.stdout.count("NOT IMPLEMENTED") == 1


def test_version(monkeypatch):
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"AIKA AI V2 {__version__}"
    monkeypatch.setenv("AIKA_VERSION", "2.10.3")
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "AIKA AI V2 2.10.3"


def test_help_and_unknown_command():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "doctor" in result.stdout and "--version" in result.stdout
    assert run_cli("unknown").returncode == 2


def test_doctor(tmp_path, capsys, mock_ollama, ollama_model):
    mock_ollama()
    assert aika.main(["doctor"]) == 0
    output = capsys.readouterr().out
    for check in ("Python", "Project directory", "Runtime files", "Configuration", "Data directory", "SQLite", "Ollama", "Model"):
        assert f"PASS  {check}:" in output
    assert f"{'PASS' if os.name == 'nt' else 'WARN'}  Environment:" in output
    assert f"PASS  Model: {ollama_model} is installed locally." in output
    assert output.count("NOT IMPLEMENTED") == 1
    assert "PASS  Tool Registry: Initialized" in output
    assert "PASS  Calculator: Available" in output
    assert "PASS  Tools Registered: 7" in output
    assert list(tmp_path.iterdir()) == []


def test_doctor_warns_without_creating_data_directory(tmp_path, monkeypatch, capsys, mock_ollama):
    data_path = tmp_path / "missing" / "data"
    monkeypatch.setenv("AIKA_DATA_DIR", str(data_path))
    mock_ollama()
    assert aika.main(["doctor"]) == 0
    assert "WARN  Data directory:" in capsys.readouterr().out
    assert not data_path.parent.exists()


def test_valid_configuration(tmp_path, monkeypatch, ollama_model):
    monkeypatch.setenv("AIKA_APP_NAME", "AIKA Local")
    monkeypatch.setenv("AIKA_VERSION", "0.2.1")
    monkeypatch.setenv("AIKA_LOG_LEVEL", "debug")
    monkeypatch.setenv("AIKA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AIKA_RUNTIME_URL", "http://[::1]:11435/")
    assert load_config() == Settings(
        "AIKA Local", "0.2.1", "DEBUG", tmp_path, "http://[::1]:11435/", model=ollama_model,
    )
    result = run_cli()
    assert result.returncode == 0
    assert result.stdout.startswith("AIKA Local\n")
    assert "event=runtime_checked correlation_id=" in result.stderr
    assert str(tmp_path) not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AIKA_APP_NAME", " \t "),
        ("AIKA_VERSION", "private-version"),
        ("AIKA_LOG_LEVEL", "private-log-level"),
        ("AIKA_DATA_DIR", "private-relative-dir"),
        ("AIKA_RUNTIME_URL", "http://user:private-password@localhost:11434"),
        ("AIKA_RUNTIME_URL", "http://localhost:99999"),
        ("AIKA_RUNTIME_URL", "https://example.test/"),
        ("AIKA_CONTEXT_TURNS", "-1"),
        ("AIKA_CONTEXT_TURNS", "1.5"),
        ("AIKA_CONTEXT_TURNS", "999999999999999999999999"),
    ],
)
def test_invalid_configuration_is_safe(key, value, monkeypatch):
    monkeypatch.setenv(key, value)
    doctor = run_cli("doctor")
    assert doctor.returncode == 1
    assert f"FAIL  Configuration: {key}" in doctor.stdout
    startup = run_cli()
    assert startup.returncode == 1
    assert f"Configuration error: {key}" in startup.stderr
    output = doctor.stdout + doctor.stderr + startup.stdout + startup.stderr
    assert "Traceback" not in output
    assert "READY" not in output
    assert value not in output
    assert "private-password" not in output


def test_invalid_version_command(monkeypatch):
    monkeypatch.setenv("AIKA_VERSION", "bad-version")
    result = run_cli("--version")
    assert result.returncode == 1
    assert "Configuration error: AIKA_VERSION" in result.stderr
    assert "bad-version" not in result.stderr


def test_doctor_fails_when_data_path_has_file_parent(tmp_path, monkeypatch):
    file_path = tmp_path / "data-file"
    file_path.touch()
    monkeypatch.setenv("AIKA_DATA_DIR", str(file_path / "data"))
    result = run_cli("doctor")
    assert result.returncode == 1
    assert "FAIL  Data directory:" in result.stdout
    assert str(file_path) not in result.stdout


@pytest.mark.skipif(os.name != "nt", reason="Windows path rules")
@pytest.mark.parametrize("name", ["bad?path", "NUL"])
def test_rejects_invalid_windows_data_paths(name, tmp_path, monkeypatch):
    monkeypatch.setenv("AIKA_DATA_DIR", str(tmp_path / name / "data"))
    result = run_cli("doctor")
    assert result.returncode == 1
    assert "FAIL  Configuration: AIKA_DATA_DIR" in result.stdout


def test_doctor_reports_missing_runtime_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(diagnostics, "__file__", str(tmp_path / "src" / "diagnostics.py"))
    assert aika.main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "WARN  Project directory:" in output
    assert "FAIL  Runtime files: Missing aika.py" in output


def test_unsupported_python_detection_and_exit_code(monkeypatch, capsys):
    assert check_python((3, 12, 0)).status == "PASS"
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    assert aika.main(["doctor"]) == 1
    assert "FAIL  Python: Found 3.11.9" in capsys.readouterr().out
    assert aika.main([]) == 1
    assert "Python 3.12 or newer is required" in capsys.readouterr().err
