"""Parse explicitly selected source files without importing or running them."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tokenize
import tomllib


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    paths = json.loads((root / ".github/source-check.json").read_text(encoding="utf-8"))
    failures = []
    for name in paths:
        path = root / name
        try:
            if path.resolve().is_relative_to(root) is False or not path.is_file():
                raise ValueError("missing or out-of-scope file")
            extension = path.suffix.lower()
            if extension == ".py":
                with tokenize.open(path) as handle:
                    ast.parse(handle.read(), filename=name)
            elif extension == ".json":
                json.loads(path.read_text(encoding="utf-8-sig"))
            elif extension == ".toml":
                tomllib.loads(path.read_text(encoding="utf-8"))
            elif extension in {".yaml", ".yml"}:
                import yaml
                # Compose only: HA !include/!secret tags are syntax, never executed.
                list(yaml.compose_all(path.read_text(encoding="utf-8")))
            elif extension == ".sh":
                bash = r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else "bash"
                result = subprocess.run([bash, "-n"], input=path.read_bytes().replace(b"\r\n", b"\n"), capture_output=True, timeout=20)
                if result.returncode:
                    raise ValueError("bash syntax error")
            elif extension == ".ps1":
                script = "$e=$null; $t=$null; [void][System.Management.Automation.Language.Parser]::ParseInput([Console]::In.ReadToEnd(),[ref]$t,[ref]$e); if($e.Count){exit 1}"
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], input=path.read_text(encoding="utf-8-sig"), text=True, capture_output=True, timeout=20)
                if result.returncode:
                    raise ValueError("PowerShell syntax error")
            elif extension == ".md":
                if len(path.read_text(encoding="utf-8").strip()) < 40:
                    raise ValueError("missing project documentation")
            else:
                raise ValueError("unsupported source type")
        except Exception as error:
            # Do not put potentially sensitive configuration values in CI logs.
            failures.append(f"{name}: {type(error).__name__}")
    for failure in failures:
        print(failure, file=sys.stderr)
    print(f"Source syntax: {len(paths) - len(failures)}/{len(paths)} files passed; no application code executed.")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
