"""Run a tool-free, synthetic OpenCode baseline against AgencyZero's local proxy."""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

VERSION = "1.19.6"
PROXY_URL = "http://127.0.0.1:8989/v1"
MODELS = ("premium", "explorer")
PROMPT = (
    'Summarize this synthetic lab status in one sentence: '
    '"Three demo notes were reviewed; two passed and one needs follow-up." '
    'Use only the supplied text and do not use any tools.'
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default="premium")
    parser.add_argument("--check", action="store_true", help="List the configured models without sending a prompt")
    args = parser.parse_args()
    binary = shutil.which("opencode")
    if binary is None:
        parser.error(f"install OpenCode {VERSION} and put opencode on PATH")
    binary = str(Path(binary).resolve())

    with tempfile.TemporaryDirectory(prefix="agencyzero-opencode-") as temp:
        root = Path(temp)
        work = root / "workspace"
        work.mkdir()
        config = work / "opencode.json"
        config.write_text(json.dumps({
            "autoupdate": False,
            "share": "disabled",
            "permission": {"*": "deny"},
            "enabled_providers": ["agencyzero"],
            "provider": {
                "agencyzero": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "AgencyZero local proxy",
                    "options": {
                        "baseURL": os.environ.get("AGENCYZERO_OPENCODE_PROXY_URL", PROXY_URL),
                        "apiKey": "bob-proxy",
                    },
                    "models": {model: {"name": model} for model in MODELS},
                },
            },
        }), encoding="utf-8")
        env = {
            "PATH": os.defpath,
            "HOME": str(root),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_STATE_HOME": str(root / "state"),
            "OPENCODE_CONFIG": str(config),
            "OPENCODE_PERMISSION": '{"*":"deny"}',
            "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
            "OPENCODE_DISABLE_MODELS_FETCH": "true",
        }
        version = subprocess.run([binary, "--version"], env=env, cwd=work,
                                 text=True, capture_output=True, check=True).stdout.strip()
        if version != VERSION:
            parser.error(f"expected OpenCode {VERSION}; found {version}")
        command = ["models", "agencyzero"] if args.check else [
            "run", "--model", f"agencyzero/{args.model}", "--format", "json", PROMPT,
        ]
        return subprocess.run([binary, *command], env=env, cwd=work).returncode


if __name__ == "__main__":
    raise SystemExit(main())
