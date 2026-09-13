"""
One-time Garmin Connect login.

Reads GARMIN_EMAIL and GARMIN_PASSWORD from environment variables (never
from the command line, so they don't end up in shell history), logs in,
and saves a session token to .garmintokens/ so garmin_sync.py never needs
your password again.

If Garmin asks for a 2FA/MFA code, this script prints "MFA_REQUIRED" and
then waits (polling) for a file called .garmintokens/_mfa_code.txt to show
up containing just the code. Whatever creates that file (a human, a script)
can hand off the code without this process needing an interactive terminal.
"""

import os
import sys
import time
from pathlib import Path

from garminconnect import Garmin

BASE_DIR = Path(__file__).resolve().parent
TOKEN_DIR = BASE_DIR / ".garmintokens"
MFA_CODE_FILE = TOKEN_DIR / "_mfa_code.txt"
MFA_TIMEOUT_SECONDS = 600


def wait_for_mfa_code():
    print("MFA_REQUIRED", flush=True)
    waited = 0
    while not MFA_CODE_FILE.exists():
        time.sleep(2)
        waited += 2
        if waited >= MFA_TIMEOUT_SECONDS:
            print("MFA_TIMEOUT", flush=True)
            sys.exit(1)
    code = MFA_CODE_FILE.read_text(encoding="utf-8").strip()
    MFA_CODE_FILE.unlink()
    return code


def main():
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        print("MISSING_CREDENTIALS", flush=True)
        sys.exit(1)

    TOKEN_DIR.mkdir(exist_ok=True)
    if MFA_CODE_FILE.exists():
        MFA_CODE_FILE.unlink()

    client = Garmin(email=email, password=password, prompt_mfa=wait_for_mfa_code)
    try:
        client.login(str(TOKEN_DIR))
    except Exception as exc:
        print(f"LOGIN_FAILED: {exc}", flush=True)
        sys.exit(1)

    print("LOGIN_OK", flush=True)


if __name__ == "__main__":
    main()
