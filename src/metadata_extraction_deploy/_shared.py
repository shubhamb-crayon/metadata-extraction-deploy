"""Shared config and AWS helpers used across all pages."""

import datetime
import os
import subprocess
from pathlib import Path

import streamlit as st

DEPLOY_DIR = Path(__file__).resolve().parents[2]
AWS_LOGIN_SCRIPT = DEPLOY_DIR / "aws_login.sh"
ENV_FILE = DEPLOY_DIR / ".env"

AWS_REGION = "ap-southeast-1"

_EXCLUDED = {
    "automated-speech-recognition",
    "mdm-intelligent-frame-sampling",
    "bda-image-engine",
    "bda-video-engine",
    "my-lambda-app",
    "my-ecs-app",
}


# ── config.mk ──────────────────────────────────────────────────────────────────
def load_config() -> dict[str, str]:
    f = DEPLOY_DIR / "config.mk"
    if not f.exists():
        raise FileNotFoundError("config.mk not found — copy config.mk.example and fill in values.")
    cfg: dict[str, str] = {}
    for raw in f.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for sep in (":=", "?=", "="):
            if sep in line:
                k, _, v = line.partition(sep)
                cfg[k.strip()] = v.strip()
                break
    return cfg


@st.cache_data
def lambda_services() -> list[str]:
    try:
        cfg = load_config()
    except FileNotFoundError:
        return []
    app_dir = Path(cfg.get("APP_DIR", "")).expanduser()
    d = app_dir / "services"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir() and p.name not in _EXCLUDED)


# ── AWS credentials ────────────────────────────────────────────────────────────
def read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    creds: dict[str, str] = {}
    for raw in ENV_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        creds[k.strip()] = v.strip()
    return creds


def inject_credentials(creds: dict[str, str]) -> None:
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ):
        if key in creds:
            os.environ[key] = creds[key]


def session_expiry(creds: dict[str, str]) -> datetime.datetime | None:
    exp = creds.get("AWS_SESSION_EXPIRATION")
    if not exp:
        return None
    try:
        return datetime.datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_session_valid(creds: dict[str, str]) -> bool:
    expiry = session_expiry(creds)
    if expiry is None:
        return False
    return expiry > datetime.datetime.now(datetime.timezone.utc)


def aws_login(profile: str, mfa_token: str) -> tuple[bool, str]:
    if not AWS_LOGIN_SCRIPT.exists():
        return False, "aws_login.sh not found in repo root."
    result = subprocess.run(
        ["bash", str(AWS_LOGIN_SCRIPT), profile, mfa_token],
        capture_output=True,
        text=True,
        cwd=str(DEPLOY_DIR),
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        return False, output or "Login failed — check profile and MFA token."
    creds = read_env_file()
    inject_credentials(creds)
    return True, output


# ── Sidebar rendered on every page ────────────────────────────────────────────
def render_sidebar() -> None:
    with st.sidebar:
        st.caption("AWS Session")
        creds = read_env_file()
        if is_session_valid(creds):
            expiry = session_expiry(creds)
            assert expiry is not None
            remaining = expiry - datetime.datetime.now(datetime.timezone.utc)
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            st.success(f"Active — expires in {hours}h {minutes}m")
        elif creds:
            st.warning("Session expired.")
            st.page_link("Home.py", label="Log in again", icon="🔑")
        else:
            st.info("Not logged in.")
            st.page_link("Home.py", label="Go to login", icon="🔑")
