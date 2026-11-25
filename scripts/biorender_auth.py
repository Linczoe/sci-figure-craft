#!/usr/bin/env python3
"""Load BioRender credentials without printing the password.

Any harness may import load_credentials().  Resolution order:
1. BIORENDER_EMAIL / BIORENDER_PASSWORD environment variables;
2. BIORENDER_CREDENTIALS_FILE (JSON or simple YAML key-value);
3. ~/.config/sci-figure-craft/biorender.json.

The CLI is a masked presence check only.  It never emits the password.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


class CredentialError(RuntimeError):
    pass


def default_credential_file() -> Path:
    return Path.home() / ".config" / "sci-figure-craft" / "biorender.json"


def read_credential_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_credentials() -> tuple[str, str, str]:
    email = os.environ.get("BIORENDER_EMAIL")
    password = os.environ.get("BIORENDER_PASSWORD")
    if email and password:
        return email, password, "environment"
    path = Path(os.environ.get("BIORENDER_CREDENTIALS_FILE", str(default_credential_file()))).expanduser()
    if not path.is_file():
        raise CredentialError(
            "BioRender credentials not found; set BIORENDER_EMAIL/BIORENDER_PASSWORD, "
            "BIORENDER_CREDENTIALS_FILE, or install the local credential file"
        )
    data = read_credential_file(path)
    email = data.get("BIORENDER_EMAIL") or data.get("email")
    password = data.get("BIORENDER_PASSWORD") or data.get("password")
    if not email or not password:
        raise CredentialError(f"credential file lacks email/password: {path}")
    return str(email), str(password), str(path)


def masked_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return (local[:2] + "***@" + domain) if local else "***@" + domain


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require", action="store_true", help="return 1 instead of 0 when credentials are absent")
    args = parser.parse_args()
    try:
        email, _password, source = load_credentials()
        result = {"ok": True, "email": masked_email(email), "source": source,
                  "password": "available (not printed)"}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1 if args.require else 0


if __name__ == "__main__":
    raise SystemExit(main())
