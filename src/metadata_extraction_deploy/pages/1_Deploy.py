"""
Deploy — build and push services to AWS.
"""

import subprocess
import threading
import time

import streamlit as st

from metadata_extraction_deploy._shared import (
    DEPLOY_DIR,
    inject_credentials,
    is_session_valid,
    lambda_services,
    load_config,
    read_env_file,
    render_sidebar,
)

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
st.set_page_config(page_title="Deploy", layout="wide", page_icon="📦")

try:
    load_config()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

_env_creds = read_env_file()
if _env_creds:
    inject_credentials(_env_creds)

render_sidebar()

st.title("📦 Deploy")
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
session_ok = is_session_valid(read_env_file())

if not session_ok:
    st.warning("Log in on the home page before deploying.")

deploy_disabled = n == 0 or not session_ok
if st.button(btn_label, disabled=deploy_disabled, type="primary", use_container_width=False):
    output: list[str] = []
    lock = threading.Lock()
    failure_count = [0]

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
