"""Run with <fresh-venv-python> -I scripts/check_installed.py after wheel installation."""

import json
import os
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
        env.update(LOCALAPPDATA=str(root / "local app data"),
                   USERPROFILE=str(root / "synthetic home"), HOME=str(root / "synthetic home"),
                   AIKA_WEB_SEARCH_ENABLED="off", AIKA_WEB_READING_ENABLED="off",
                   AIKA_WEB_SEARCH_PROVIDER="ddgs", AIKA_WEB_SEARCH_FALLBACK_ENABLED="off",
                   AIKA_TAVILY_API_KEY="", AIKA_OLLAMA_URL="http://127.0.0.1:1")

        def run(*args, extra_env=None):
            result = subprocess.run([sys.executable, "-I", *args], cwd=cwd, env={**env, **(extra_env or {})},
                                    capture_output=True, text=True, timeout=40)
            if result.returncode:
                raise RuntimeError(f"Isolated command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        info = json.loads(run("-c", "import aika, src.config as c, json; settings=c.load_config(); "
                             "print(json.dumps({'module': aika.__file__, 'data': str(c.load_data_dir()), "
                             "'dotenv': str(c.DOTENV_PATH), 'context_chars': settings.context_chars, "
                             "'response_tokens': settings.response_tokens}))"))
        if info["context_chars"] != 24000 or info["response_tokens"] != 1024:
            raise RuntimeError("The installed model-budget defaults do not match the checkpoint.")
        module_path = Path(info["module"]).resolve()
        if not module_path.is_relative_to(Path(sys.prefix).resolve()):
            raise RuntimeError("AIKA was imported from outside the fresh virtual environment.")
        expected = (root / "local app data" / "AIKA AI V2" / "data" if os.name == "nt"
                    else root / "synthetic home" / ".aika-v2" / "data")
        if Path(info["data"]) != expected:
            raise RuntimeError("The isolated default data directory was not used.")
        commands = {}
        for args in ((), ("--help",), ("--version",), ("doctor",)):
            output = run("-m", "aika", *args)
            commands[" ".join(args) or "startup"] = "passed"
            if args == ("doctor",) and "WARN  Ollama:" not in output:
                raise RuntimeError("Doctor must work without a running Ollama service.")
        if expected.exists():
            raise RuntimeError("Startup/doctor created the default data directory unexpectedly.")
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
        # Observe the existing config-file coupling, without installing a user-config feature.
        (cwd / ".env").write_text("AIKA_APP_NAME=Working Directory Synthetic\n", encoding="utf-8")
        observed_name = run("-c", "from src.config import load_config; print(load_config().app_name)").strip()
        overridden = run("-m", "aika", extra_env={"AIKA_APP_NAME": "Process Environment Synthetic"})
        if not overridden.startswith("Process Environment Synthetic\n"):
            raise RuntimeError("Process environment precedence was not preserved.")
        print(json.dumps({"python": sys.version.split()[0], "module_inside_fresh_venv": True,
                          "commands": commands, "default_data_path": "isolated OS default",
                          "synthetic_database_restart": "passed", "explicit_data_override": "passed",
                          "dotenv_beside_installed_package": Path(info["dotenv"]).parent == module_path.parent,
                          "working_directory_dotenv_loaded": observed_name == "Working Directory Synthetic",
                          "environment_override": "passed", "gui_or_provider_operations": 0}, indent=2))


if __name__ == "__main__":
    main()
