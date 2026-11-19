"""Run with <fresh-venv-python> -I scripts/check_installed.py after wheel installation."""

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    if sys.prefix == sys.base_prefix or not sys.flags.isolated:
        raise RuntimeError("Use a fresh virtual environment and Python -I to exclude checkout/user imports.")
    with TemporaryDirectory(prefix="aika-wheel-smoke-") as directory:
        root = Path(directory).resolve()
        cwd = root / "unrelated working directory"
        cwd.mkdir()
        # Strip inherited AIKA settings and redirect the default Windows data root.
        env = {key: value for key, value in os.environ.items()
               if not key.upper().startswith("AIKA_") and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
        env.update(LOCALAPPDATA=str(root / "local app data Profilé 使用者"),
                   USERPROFILE=str(root / "synthetic home Profilé 使用者"), HOME=str(root / "synthetic home Profilé 使用者"),
                   AIKA_WEB_SEARCH_ENABLED="off", AIKA_WEB_READING_ENABLED="off",
                   AIKA_WEB_SEARCH_PROVIDER="ddgs", AIKA_WEB_SEARCH_FALLBACK_ENABLED="off",
                   AIKA_TAVILY_API_KEY="", AIKA_OLLAMA_URL="http://127.0.0.1:1")

        def run(*args, extra_env=None, expected_exit=0, isolated=True):
            result = subprocess.run([sys.executable, *(["-I"] if isolated else []), *args], cwd=cwd, env={**env, **(extra_env or {})},
                                    capture_output=True, text=True, timeout=40)
            if result.returncode != expected_exit:
                raise RuntimeError(f"Isolated command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
            return result.stdout + result.stderr

        info = json.loads(run("-c", "import aika, src.config as c, json; settings=c.load_config(); "
                             "print(json.dumps({'module': aika.__file__, 'data': str(c.load_data_dir()), "
                             "'config_module': c.__file__, 'user_config': str(c.resolve_user_config_path()), "
                             "'mode': settings.configuration_mode, 'context_chars': settings.context_chars, "
                             "'response_tokens': settings.response_tokens, 'desktop_enabled': settings.desktop_context_enabled}))"))
        if info["context_chars"] != 24000 or info["response_tokens"] != 1024:
            raise RuntimeError("The installed model-budget defaults do not match the checkpoint.")
        if info["desktop_enabled"]:
            raise RuntimeError("Desktop context must be disabled by default in the installed wheel.")
        desktop_check = run("-c", "from unittest.mock import patch; from src.capabilities import create_registry; "
                            "from src.capabilities.executor import ToolExecutor; from src.capabilities.contracts import ToolRequest, ToolStatus; "
                            "guard=patch('src.capabilities.desktop_context.open_windows',side_effect=AssertionError('No observation')); guard.start(); "
                            "registry=create_registry(); assert len(registry.list_tools())==7; "
                            "result=ToolExecutor(registry).execute(ToolRequest('desktop.context',{})); "
                            "assert result.status==ToolStatus.DISABLED and not result.verified; print('disabled without collection')")
        if "disabled without collection" not in desktop_check:
            raise RuntimeError("Installed desktop consent boundary failed.")
        module_path = Path(info["module"]).resolve()
        if not module_path.is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError("AIKA was imported from outside the fresh virtual environment.")
        if not Path(info["config_module"]).resolve().is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError("Configuration was imported from outside the installed wheel.")
        expected = (root / "local app data Profilé 使用者" / "AIKA AI V2" / "data" if os.name == "nt"
                    else root / "synthetic home Profilé 使用者" / ".aika-v2" / "data")
        if Path(info["data"]) != expected:
            raise RuntimeError("The isolated default data directory was not used.")
        user_config = Path(info["user_config"])
        if user_config != expected.parent / "config" / ".env" or not user_config.is_relative_to(root):
            raise RuntimeError("Configuration is not independently rooted in the isolated profile.")
        commands = {}
        for args in ((), ("--help",), ("--version",), ("doctor",)):
            output = run("-m", "aika", *args)
            commands[" ".join(args) or "startup"] = "passed"
            if args == ("doctor",) and "WARN  Ollama:" not in output:
                raise RuntimeError("Doctor must work without a running Ollama service.")
        if expected.exists() or user_config.parent.exists():
            raise RuntimeError("Startup/doctor created a data/config directory unexpectedly.")
        key = ("--type", "project", "--subject", "Wheel Synthetic", "--key", "frontend")
        run("-m", "aika", "memory", "set", *key, "--value", "SvelteKit")
        if "SvelteKit" not in run("-m", "aika", "memory", "get", *key):
            raise RuntimeError("Synthetic default-path memory did not survive a new process.")
        if not (expected / "conversations.sqlite3").is_file():
            raise RuntimeError("The synthetic database was not created at the default path.")
        override = root / "explicit data"
        run("-m", "aika", "memory", "set", *key, "--value", "Next.js",
            extra_env={"AIKA_DATA_DIR": str(override)})
        if not (override / "conversations.sqlite3").is_file():
            raise RuntimeError("AIKA_DATA_DIR override was ignored.")
        lifecycle = run("-c", """
import contextlib, io
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from src.cli import handle_chat_command
from src.config import load_config
from src.intelligence.conversation import ConversationSession
from src.capabilities.contracts import ToolRequest, ToolStatus
from src.storage.conversation_store import ConversationStore
with TemporaryDirectory(prefix='aika-installed-consent-') as directory, patch('src.capabilities.desktop_context.open_windows', side_effect=AssertionError('No collection')) as native:
    store=ConversationStore(Path(directory))
    first=ConversationSession('Synthetic',10,Mock(side_effect=AssertionError('No generation')),store)
    other=ConversationSession('Synthetic',10,Mock(),store)
    with contextlib.redirect_stdout(io.StringIO()):
        handle_chat_command('/desktop-context --enable',load_config(),first,store)
        assert first.desktop_context_enabled and not other.desktop_context_enabled
        handle_chat_command('/clear',load_config(),first,store)
        assert first.desktop_context_enabled
        handle_chat_command('/desktop-context --disable',load_config(),first,store)
        assert not first.desktop_context_enabled
    assert first.tools.execute(ToolRequest('desktop.context',{})).status==ToolStatus.DISABLED
    first.reply('/desktop-context --enable')
    assert not first.desktop_context_enabled and store.list_sessions()==[]
    first.close()
    assert not first.desktop_context_enabled
    native.assert_not_called()
print('session consent lifecycle passed')
""")
        if "session consent lifecycle passed" not in lifecycle:
            raise RuntimeError("Installed session consent lifecycle failed.")
        # Neither a cwd marker nor a cwd .env is configuration authority for an installed wheel.
        (cwd / ".env").write_text("AIKA_APP_NAME=Working Directory Synthetic\n", encoding="utf-8")
        (cwd / "pyproject.toml").write_text('[project]\nname="aika-ai-v2"\n', encoding="utf-8")
        observed_name = run("-c", "from src.config import load_config; print(load_config().app_name)").strip()
        if observed_name != "AIKA AI V2":
            raise RuntimeError("Installed runtime trusted a cwd configuration file.")
        user_config.parent.mkdir(parents=True)
        with user_config.open("x", encoding="utf-8-sig") as stream:
            stream.write("AIKA_APP_NAME=User Configuration Synthetic\nAIKA_TAVILY_API_KEY=synthetic-private-key\nAIKA_DESKTOP_CONTEXT_ENABLED=on\n")
        if run("-c", "from src.config import load_config; print(load_config().desktop_context_enabled)").strip() != "True":
            raise RuntimeError("Installed desktop user configuration opt-in failed.")
        if run("-c", "from src.config import load_config; print(load_config().desktop_context_enabled)",
               extra_env={"AIKA_DESKTOP_CONTEXT_ENABLED": "off"}).strip() != "False":
            raise RuntimeError("Installed desktop process configuration precedence failed.")
        configured = run("-m", "aika")
        if not configured.startswith("User Configuration Synthetic\n"):
            raise RuntimeError("Installed wheel did not load per-user configuration.")
        if "SvelteKit" not in run("-m", "aika", "memory", "get", *key):
            raise RuntimeError("User config discovery changed the existing synthetic data location.")
        doctor = run("-m", "aika", "doctor")
        if "User configuration: Present and readable." not in doctor or "Development .env: Not used." not in doctor:
            raise RuntimeError("Doctor did not identify installed configuration sources.")
        if "synthetic-private-key" in doctor or str(user_config.parent) in doctor:
            raise RuntimeError("Public configuration diagnostics exposed private data.")
        overridden = run("-m", "aika", extra_env={"AIKA_APP_NAME": "Process Environment Synthetic"})
        if not overridden.startswith("Process Environment Synthetic\n"):
            raise RuntimeError("Process environment precedence was not preserved.")
        for invalid in ('AIKA_APP_NAME="synthetic-private-unclosed', 'AIKA_MODEL_TIMEOUT=synthetic-private-invalid'):
            user_config.write_text(invalid, encoding="utf-8")
            error = run("-m", "aika", "doctor", expected_exit=1)
            if "FAIL  Configuration:" not in error or "synthetic-private" in error or str(root) in error or "Traceback" in error:
                raise RuntimeError("Malformed configuration did not fail safely.")
        user_config.write_text("AIKA_APP_NAME=Readable synthetic\n", encoding="utf-8")
        unreadable = run("-c", "from pathlib import Path; from unittest.mock import patch; "
                         "import aika; from src.config import resolve_user_config_path; "
                         "target=resolve_user_config_path(); original=Path.open; "
                         "blocked=lambda path,*a,**kw: (_ for _ in ()).throw(PermissionError('synthetic-private-path')) "
                         "if path==target else original(path,*a,**kw); "
                         "guard=patch.object(Path,'open',blocked); guard.start(); raise SystemExit(aika.main(['doctor']))",
                         expected_exit=1)
        if "FAIL  Configuration:" not in unreadable or "synthetic-private" in unreadable or "Traceback" in unreadable:
            raise RuntimeError("Unreadable configuration did not fail safely.")
        user_config.unlink()
        # Exercise the same source-anchored policy used by bare and editable checkout execution.
        source = root / "verified source tree"
        shutil.copytree(Path(info["config_module"]).parent, source / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(module_path, source / "aika.py")
        (source / "pyproject.toml").write_text('[project]\nname="aika-ai-v2"\n', encoding="utf-8")
        (source / ".env").write_text('AIKA_APP_NAME=Development Configuration Synthetic\n', encoding="utf-8")
        development = run(str(source / "aika.py"), isolated=False)
        if not development.startswith("Development Configuration Synthetic\n"):
            raise RuntimeError("Verified development .env compatibility failed outside its cwd.")
        if user_config.exists() or "SvelteKit" not in run("-m", "aika", "memory", "get", *key):
            raise RuntimeError("Missing optional config did not preserve synthetic memory.")
        print(json.dumps({"python": sys.version.split()[0], "module_inside_fresh_venv": True,
                          "commands": commands, "default_data_path": "isolated OS default",
                          "synthetic_database_restart": "passed", "explicit_data_override": "passed",
                          "configuration_mode": info["mode"], "user_configuration_loading": "passed",
                          "source_configuration_compatibility": "passed", "unicode_profile_paths": "passed",
                          "malformed_configuration": "passed", "unreadable_configuration": "passed (mocked denial)",
                          "working_directory_dotenv_loaded": observed_name == "Working Directory Synthetic",
                          "environment_override": "passed", "desktop_disabled_without_observation": "passed",
                          "desktop_configuration_precedence": "passed", "desktop_session_lifecycle": "passed",
                          "gui_or_provider_operations": 0}, indent=2))


if __name__ == "__main__":
    main()
