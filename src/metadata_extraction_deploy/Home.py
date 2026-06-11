"""
MEP Deploy — home / login page
Run: uv run dev
"""

import datetime

import streamlit as st

from metadata_extraction_deploy._shared import (
    aws_login,
    inject_credentials,
    is_session_valid,
    load_config,
    read_env_file,
    session_expiry,
)

# ── Page setup ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="MEP Deploy", layout="centered", page_icon="🚀")

try:
    load_config()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

_env_creds = read_env_file()
if _env_creds:
    inject_credentials(_env_creds)

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("🚀 MEP Deploy")
st.caption("Metadata Extraction Platform — deployment console")

st.markdown(
    """
    This tool lets you build, push, and deploy MEP services to AWS from a single UI.

    **What you can do:**
    - **Deploy** — select any combination of Lambda, ECS, or BDA engine services and deploy
      them in parallel. Builds Docker images, pushes to ECR, and updates Lambda function code.
    - **Content Testing** — create a content record via the middleware API, copy the source
      media to S3, and trigger the Step Functions orchestration workflow.

    Log in below to get started. Your session credentials are written to `.env` and
    automatically loaded on each page.
    """
)

st.divider()

# ── Session status ─────────────────────────────────────────────────────────────
creds = read_env_file()

if is_session_valid(creds):
    expiry = session_expiry(creds)
    assert expiry is not None
    remaining = expiry - datetime.datetime.now(datetime.timezone.utc)
    hours, rem = divmod(int(remaining.total_seconds()), 3600)
    minutes = rem // 60
    st.success(f"AWS session active — expires in {hours}h {minutes}m")
    st.info("Use the sidebar to navigate to **Deploy** or **Content Testing**.")
elif creds:
    st.warning("Your AWS session has expired — please log in again.")
else:
    st.info("Log in with your AWS profile and MFA token to get started.")

st.divider()

# ── Login form ─────────────────────────────────────────────────────────────────
st.subheader("AWS Login")

with st.form("aws_login_form"):
    col_profile, col_token = st.columns([1, 1])
    with col_profile:
        profile = st.text_input("AWS Profile", value="default", placeholder="default")
    with col_token:
        mfa_token = st.text_input("MFA Token", max_chars=6, placeholder="123456", type="password")
    submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

if submitted:
    if not mfa_token.strip():
        st.error("MFA token is required.")
    else:
        with st.spinner("Authenticating..."):
            ok, msg = aws_login(profile.strip() or "default", mfa_token.strip())
        if ok:
            st.success("Logged in successfully.")
            st.rerun()
        else:
            st.error(msg)
