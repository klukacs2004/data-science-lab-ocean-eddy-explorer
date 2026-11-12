#!/usr/bin/env python3
"""Install, prepare, check, or serve a movable Ocean Eddy Explorer checkout."""

import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import venv

BASE_DIR = Path(__file__).resolve().parent


def environment_python():
    candidate = BASE_DIR / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else Path(sys.executable).absolute()


def ensure_environment_file():
    """Preserve existing configuration and generate only a missing secret."""
    path = BASE_DIR / ".env"
    text = (
        path.read_text() if path.exists() else (BASE_DIR / ".env.example").read_text()
    )
    match = re.search(
        r"^[ \t]*(?:export[ \t]+)?DJANGO_SECRET_KEY[ \t]*=[ \t]*(.*)$",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        text += f"\nDJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n"
    elif not match.group(1).strip().strip("'\"") or match.group(1).lstrip().startswith(
        "#"
    ):
        text = (
            text[: match.start()]
            + f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}"
            + text[match.end() :]
        )
    if not path.exists() or text != path.read_text():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
        path.chmod(0o600)


def manage(python, *arguments):
    subprocess.run(
        [str(python), str(BASE_DIR / "manage.py"), *arguments],
        cwd=BASE_DIR,
        check=True,
    )


def prepare(python):
    ensure_environment_file()
    manage(python, "migrate", "--noinput")
    manage(python, "collectstatic", "--noinput")
    manage(python, "check")
    manage(python, "checkdata", "--allow-empty")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--setup",
        action="store_true",
        help="Create .venv, install dependencies, and prepare; then exit.",
    )
    action.add_argument(
        "--prepare",
        action="store_true",
        help="Prepare the database and static files using installed dependencies; then exit.",
    )
    action.add_argument(
        "--check",
        action="store_true",
        help="Check application settings and input data; then exit.",
    )
    parser.add_argument(
        "--production", action="store_true", help="Disable Django debug pages."
    )
    parser.add_argument(
        "--host", help="Bind address; defaults to BIND_HOST or 127.0.0.1."
    )
    parser.add_argument(
        "--port", type=int, help="Listening port; defaults to PORT or 8000."
    )
    parser.add_argument(
        "--prefix", help="Published URL path stripped by the upstream proxy."
    )
    args = parser.parse_args()
    if os.name != "posix":
        parser.error("Use Linux, macOS, or Windows Subsystem for Linux (WSL).")
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12 for the pinned numerical environment.")

    if args.production:
        os.environ["DJANGO_DEBUG"] = "false"
    if args.prefix is not None:
        os.environ["DJANGO_FORCE_SCRIPT_NAME"] = args.prefix

    if args.setup:
        target = BASE_DIR / ".venv"
        if not (target / "bin" / "python").exists():
            venv.create(target, with_pip=True)
        python = target / "bin" / "python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(BASE_DIR / "requirements.txt"),
            ],
            cwd=BASE_DIR,
            check=True,
        )
        prepare(python)
        print("\nReady. Start with: python3.12 method_website/run.py", flush=True)
        return

    python = environment_python()
    if python.absolute() != Path(sys.executable).absolute():
        os.execv(
            str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]]
        )

    try:
        from dotenv import load_dotenv
        import gunicorn
        import whitenoise
    except ImportError:
        parser.error(
            "Dependencies are missing. Run: python3.12 method_website/run.py --setup"
        )

    ensure_environment_file()
    load_dotenv(BASE_DIR / ".env", override=False)
    if args.check:
        manage(python, "check")
        manage(python, "checkdata", "--allow-empty")
        return
    prepare(python)
    if args.prepare:
        return

    host = args.host or os.environ.get("BIND_HOST", "127.0.0.1")
    try:
        port = (
            args.port if args.port is not None else int(os.environ.get("PORT", "8000"))
        )
        timeout = int(os.environ.get("WEB_TIMEOUT", "1200"))
    except ValueError:
        parser.error("PORT and WEB_TIMEOUT must be integers.")
    if not 1 <= port <= 65535 or timeout < 1:
        parser.error("PORT must be 1–65535 and WEB_TIMEOUT must be positive.")
    print(f"\nServing on {host}:{port}. Stop with Ctrl+C.", flush=True)
    if os.environ.get("DJANGO_FORCE_SCRIPT_NAME"):
        print(
            "Open the published proxy URL, including its configured path prefix.",
            flush=True,
        )
    else:
        print(f"Local URL: http://127.0.0.1:{port}/", flush=True)
    os.execv(
        str(python),
        [
            str(python),
            "-m",
            "gunicorn",
            "--chdir",
            str(BASE_DIR),
            "--bind",
            f"{host}:{port}",
            "--worker-class",
            "sync",
            "--workers",
            "1",
            "--threads",
            "1",
            "--timeout",
            str(timeout),
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            "config.wsgi:application",
        ],
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
    except KeyboardInterrupt:
        raise SystemExit(130)
