"""
MEP Deploy UI
Run: uv run dev
"""

import datetime
import os
import subprocess
import threading
import time
from pathlib import Path

import streamlit as st

# ── Config ─────────────────────────────────────────────────────────────────────
# app.py lives at src/metadata_extraction_deploy/app.py; Makefile and config.mk
# are two levels up at the repo root.
DEPLOY_DIR = Path(__file__).resolve().parents[2]
AWS_LOGIN_SCRIPT = DEPLOY_DIR / "aws_login.sh"
ENV_FILE = DEPLOY_DIR / ".env"

# Folders that have dedicated Makefile targets — excluded from generic Lambda list
_EXCLUDED = {
    "automated-speech-recognition",
    "mdm-intelligent-frame-sampling",
    "bda-image-engine",
    "bda-video-engine",
    # scaffold / test folders
    "my-lambda-app",
    "my-ecs-app",
}

FIXED_TARGETS: dict[str, list[tuple[str, str]]] = {
    "ECS": [
        ("deploy-asr", "automated-speech-recognition"),
        ("deploy-intelligent-frame-sampling", "mdm-intelligent-frame-sampling"),
    ],
    "BDA Image Engine": [
        ("deploy-bda-image-engine-invoke", "bda-image-engine-invoke"),
        ("deploy-bda-image-engine-process", "bda-image-engine-process"),
    ],
    "BDA Video Engine": [
        ("deploy-bda-video-engine-invoke", "bda-video-engine-invoke"),
        ("deploy-bda-video-engine-process", "bda-video-engine-process"),
    ],
}


# ── Config helpers ──────────────────────────────────────────────────────────────
def _load_config() -> dict[str, str]:
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
        cfg = _load_config()
    except FileNotFoundError:
        return []
    app_dir = Path(cfg.get("APP_DIR", "")).expanduser()
    d = app_dir / "services"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir() and p.name not in _EXCLUDED)


# ── AWS credential helpers ──────────────────────────────────────────────────────
def _read_env_file() -> dict[str, str]:
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


def _inject_credentials(creds: dict[str, str]) -> None:
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
    ):
        if key in creds:
            os.environ[key] = creds[key]


def _session_expiry(creds: dict[str, str]) -> datetime.datetime | None:
    exp = creds.get("AWS_SESSION_EXPIRATION")
    if not exp:
        return None
    try:
        return datetime.datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_session_valid(creds: dict[str, str]) -> bool:
    expiry = _session_expiry(creds)
    if expiry is None:
        return False
    return expiry > datetime.datetime.now(datetime.timezone.utc)


def _aws_login(profile: str, mfa_token: str) -> tuple[bool, str]:
    """Run aws_login.sh and inject resulting credentials. Returns (success, message)."""
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
    creds = _read_env_file()
    _inject_credentials(creds)
    return True, output


# ── Deploy helpers ──────────────────────────────────────────────────────────────
def make_cmd(target_id: str, env: str) -> list[str]:
    base = ["make", "-C", str(DEPLOY_DIR), f"env={env}"]
    if target_id.startswith("svc:"):
        return base + ["deploy-lambda", f"service={target_id[4:]}"]
    return base + [target_id]


def run_service(
    target_id: str,
    env: str,
    output: list[str],
    lock: threading.Lock,
    failure_count: list[int],
) -> None:
    cmd = make_cmd(target_id, env)
    label = target_id[4:] if target_id.startswith("svc:") else target_id.replace("deploy-", "")
    with lock:
        output.append(f"[{label}] $ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                output.append(f"[{label}] {line.rstrip()}")
        proc.wait()
        if proc.returncode == 0:
            with lock:
                output.append(f"[{label}] ✅ done")
        else:
            with lock:
                output.append(f"[{label}] ❌ failed (exit {proc.returncode})")
                failure_count[0] += 1
    except Exception as e:
        with lock:
            output.append(f"[{label}] ❌ {e}")
            failure_count[0] += 1


# ── Page setup ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="MEP Deploy", layout="wide", page_icon="🚀")

# Validate config before rendering anything else
try:
    _load_config()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

# Auto-load credentials from .env on every render
_env_creds = _read_env_file()
if _env_creds:
    _inject_credentials(_env_creds)

# ── Sidebar: AWS Login ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("AWS Login")

    # Session status
    creds = _read_env_file()
    if _is_session_valid(creds):
        expiry = _session_expiry(creds)
        assert expiry is not None
        remaining = expiry - datetime.datetime.now(datetime.timezone.utc)
        hours, rem = divmod(int(remaining.total_seconds()), 3600)
        minutes = rem // 60
        st.success(f"Session active — expires in {hours}h {minutes}m")
    elif creds:
        st.warning("Session expired — please log in again.")
    else:
        st.info("Not logged in.")

    st.divider()

    with st.form("aws_login_form"):
        profile = st.text_input("AWS Profile", value="default", placeholder="default")
        mfa_token = st.text_input("MFA Token", max_chars=6, placeholder="123456", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

    if submitted:
        if not mfa_token.strip():
            st.sidebar.error("MFA token is required.")
        else:
            with st.sidebar.spinner("Authenticating..."):
                ok, msg = _aws_login(profile.strip() or "default", mfa_token.strip())
            if ok:
                st.sidebar.success("Logged in successfully.")
                st.rerun()
            else:
                st.sidebar.error(msg)

# ── Main page ──────────────────────────────────────────────────────────────────
st.title("🚀 MEP Deploy")
st.caption("Select services and deploy to AWS in parallel")

# ── Top bar ────────────────────────────────────────────────────────────────────
col_env, col_spacer = st.columns([1, 5])
with col_env:
    env = st.selectbox("Environment", ["dev", "prod"], index=0)

st.divider()

# ── Service selection ──────────────────────────────────────────────────────────
selected: list[str] = []

lambdas = lambda_services()


def _on_select_all_lambda() -> None:
    """Propagate the 'select all' toggle to every individual Lambda checkbox."""
    checked = st.session_state["all_lambda"]
    for svc in lambdas:
        st.session_state[f"svc:{svc}"] = checked


with st.expander(f"**Lambda** ({len(lambdas)} services)", expanded=True):
    st.checkbox("Select all Lambda", key="all_lambda", on_change=_on_select_all_lambda)
    cols = st.columns(4)
    for i, svc in enumerate(lambdas):
        if cols[i % 4].checkbox(svc, key=f"svc:{svc}"):
            selected.append(f"svc:{svc}")

for group_name, targets in FIXED_TARGETS.items():
    with st.expander(f"**{group_name}**", expanded=True):
        cols = st.columns(4)
        for i, (tid, svc_label) in enumerate(targets):
            if cols[i % 4].checkbox(svc_label, key=tid):
                selected.append(tid)

st.divider()

# ── Deploy button ──────────────────────────────────────────────────────────────
n = len(selected)
btn_label = f"🚀 Deploy {n} service{'s' if n != 1 else ''}" if n else "Select services to deploy"

# Block deploy if session is not valid
session_ok = _is_session_valid(_read_env_file())

if not session_ok:
    st.warning("Log in via the sidebar before deploying.")

deploy_disabled = n == 0 or not session_ok
if st.button(btn_label, disabled=deploy_disabled, type="primary", use_container_width=False):
    output: list[str] = []
    lock = threading.Lock()
    failure_count = [0]  # single-element list so threads can mutate it

    with st.status(
        f"Deploying {n} service{'s' if n != 1 else ''} in parallel...", expanded=True
    ) as status:
        log_box = st.empty()

        # ECR login once before parallel deploys to avoid keychain race condition
        login_result = subprocess.run(
            ["make", "-C", str(DEPLOY_DIR), f"env={env}", "ecr-login"],
            capture_output=True,
            text=True,
            check=False,
        )
        if login_result.returncode != 0:
            output.append(
                f"[ecr-login] ❌ {login_result.stdout.strip() or login_result.stderr.strip()}"
            )
            log_box.code("\n".join(output), language="bash")
            status.update(label="ECR login failed", state="error")
            st.stop()
        output.append("[ecr-login] ✅ logged in")
        log_box.code("\n".join(output), language="bash")

        threads = [
            threading.Thread(
                target=run_service,
                args=(tid, env, output, lock, failure_count),
                daemon=True,
            )
            for tid in selected
        ]

        for t in threads:
            t.start()

        while any(t.is_alive() for t in threads):
            with lock:
                snapshot = list(output)
            log_box.code("\n".join(snapshot), language="bash")
            time.sleep(0.3)

        for t in threads:
            t.join()

        with lock:
            log_box.code("\n".join(output), language="bash")

        failures = failure_count[0]
        if failures:
            status.update(
                label=f"Done — {failures} deployment{'s' if failures != 1 else ''} failed",
                state="error",
            )
        else:
            status.update(
                label=f"All {n} service{'s' if n != 1 else ''} deployed successfully ✅",
                state="complete",
            )
