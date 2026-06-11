"""
Content Testing — create a content record and trigger the Step Functions workflow.
"""

import datetime
import json
import subprocess
import uuid

import streamlit as st

from metadata_extraction_deploy._shared import (
    AWS_REGION,
    inject_credentials,
    is_session_valid,
    load_config,
    read_env_file,
    render_sidebar,
)

# ── Artifact config ────────────────────────────────────────────────────────────
CONTENT_TYPES = ["VIDEO", "IMAGE", "AUDIO", "TEXT"]

_VIDEO_ID = "0ee0fe36-8a54-495f-a96a-9eac02da0f94"
_IMAGE_ID = "1cc59676-cb04-47ca-baf2-d99303dfba18"
_TEXT_ID = "007a2798-58a0-4486-b4a4-7b1b252ecf93"

ARTIFACT_DEFAULTS: dict[str, dict[str, str | int]] = {
    "VIDEO": {
        "source_key": f"{_VIDEO_ID}/{_VIDEO_ID}.mp4",
        "extension": "mp4",
        "mime_type": "video/mp4",
        "file_size": 10_000_000,
    },
    "IMAGE": {
        "source_key": f"{_IMAGE_ID}/{_IMAGE_ID}.jpg",
        "extension": "jpg",
        "mime_type": "image/jpeg",
        "file_size": 1_000_000,
    },
    "AUDIO": {
        "source_key": "audio/audio.mp3",
        "extension": "mp3",
        "mime_type": "audio/mpeg",
        "file_size": 5_000_000,
    },
    "TEXT": {
        "source_key": f"{_TEXT_ID}/{_TEXT_ID}.txt",
        "extension": "txt",
        "mime_type": "text/plain",
        "file_size": 1_000,
    },
}

STATE_MACHINE_ARN_TPL = (
    "arn:aws:states:{region}:{account}:stateMachine:metadata-extraction-orchestrator"
)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _config() -> dict[str, str]:
    try:
        return load_config()
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()


def _create_content(
    api_url: str,
    auth_token: str,
    bucket: str,
    content_type: str,
    mime_type: str,
    extension: str,
    file_size: int,
) -> tuple[bool, str, str]:
    """POST to the content API. Returns (success, content_id, message)."""
    body = {
        "source_bucket": bucket,
        "source_key": "uploaded/sample",
        "original_filename": f"sample.{extension}",
        "file_size_bytes": file_size,
        "mime_type": mime_type,
        "content_type": content_type,
        "checksum_sha256": str(uuid.uuid4()),
        "metadata_hash": str(uuid.uuid4()),
        "media_metadata": {},
        "processing_config": {},
        "status": "PENDING",
        "preprocessing_status": "PENDING",
        "postprocessing_status": "PENDING",
    }
    result = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            api_url,
            "-H",
            f"authorization: {auth_token}",
            "-H",
            "content-type: application/json",
            "-d",
            json.dumps(body),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, "", f"curl failed: {result.stderr.strip()}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "", f"Invalid response: {result.stdout.strip()}"
    content_id = data.get("content_id", "")
    if not content_id:
        return False, "", f"No content_id in response: {result.stdout.strip()}"
    return True, content_id, ""


def _copy_media(bucket: str, source_key: str, content_id: str, extension: str) -> tuple[bool, str]:
    src = f"s3://{bucket}/{source_key}"
    dst = f"s3://{bucket}/{content_id}/{content_id}.{extension}"
    result = subprocess.run(
        ["aws", "s3", "cp", src, dst, "--region", AWS_REGION],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, (result.stdout + result.stderr).strip()
    return True, dst


def _trigger_workflow(
    state_machine_arn: str, content_id: str, content_type: str
) -> tuple[bool, str]:
    payload = json.dumps(
        {
            "content_id": content_id,
            "content_type": content_type,
            "triggered_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "triggered_by": "content-inventory",
        }
    )
    result = subprocess.run(
        [
            "aws",
            "stepfunctions",
            "start-execution",
            "--state-machine-arn",
            state_machine_arn,
            "--input",
            payload,
            "--region",
            AWS_REGION,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, (result.stdout + result.stderr).strip()
    try:
        data = json.loads(result.stdout)
        return True, data.get("executionArn", result.stdout.strip())
    except json.JSONDecodeError:
        return True, result.stdout.strip()


# ── Page ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Content Testing", layout="wide", page_icon="🧪")

cfg = _config()
_env_creds = read_env_file()
if _env_creds:
    inject_credentials(_env_creds)

render_sidebar()

st.title("🧪 Content Testing")
st.caption("Create a content record and trigger the Step Functions workflow")

session_ok = is_session_valid(read_env_file())
if not session_ok:
    st.warning("Log in via the sidebar before running tests.")

st.divider()

# ── Form ───────────────────────────────────────────────────────────────────────
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("Create content")

    content_type = st.selectbox("Content type", CONTENT_TYPES)
    defaults = ARTIFACT_DEFAULTS[content_type]

    with st.expander("Override artifact settings", expanded=False):
        source_key = st.text_input("Source S3 key", value=str(defaults["source_key"]))
        mime_type = st.text_input("MIME type", value=str(defaults["mime_type"]))
        extension = st.text_input("Extension", value=str(defaults["extension"]))
        file_size = st.number_input(
            "File size (bytes)", value=int(defaults["file_size"]), min_value=1
        )

    trigger_after = st.toggle("Trigger workflow after creation", value=True)

    create_btn = st.button(
        "Create content",
        disabled=not session_ok,
        type="primary",
        use_container_width=True,
    )

with col_right:
    st.subheader("Trigger existing content")
    st.caption("Trigger the workflow for a content ID that already exists.")

    existing_id = st.text_input("Content ID", placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    existing_type = st.selectbox("Content type ", CONTENT_TYPES, key="existing_type")

    trigger_btn = st.button(
        "Trigger workflow",
        disabled=not session_ok or not existing_id.strip(),
        type="secondary",
        use_container_width=True,
    )

st.divider()

# ── Results ────────────────────────────────────────────────────────────────────
if create_btn:
    bucket = cfg.get("BUCKET", "")
    api_url = cfg.get("API_URL", "")
    auth_token = cfg.get("AUTH_TOKEN", "")
    account_id = cfg.get("AWS_ACCOUNT_ID", "")
    state_machine_arn = STATE_MACHINE_ARN_TPL.format(region=AWS_REGION, account=account_id)

    log: list[str] = []
    log_box = st.empty()

    with st.status("Running...", expanded=True) as status:
        # Step 1: create content record
        log.append(f"[create] POST {api_url}")
        log_box.code("\n".join(log), language="bash")
        ok, content_id, err = _create_content(
            api_url,
            auth_token,
            bucket,
            content_type,
            mime_type,
            extension,
            int(file_size),
        )
        if not ok:
            log.append(f"[create] ❌ {err}")
            log_box.code("\n".join(log), language="bash")
            status.update(label="Failed to create content", state="error")
            st.stop()
        log.append(f"[create] ✅ content_id: {content_id}")
        log_box.code("\n".join(log), language="bash")

        # Step 2: copy media file
        log.append(f"[s3 cp] s3://{bucket}/{source_key} → {content_id}.{extension}")
        log_box.code("\n".join(log), language="bash")
        ok, msg = _copy_media(bucket, source_key, content_id, extension)
        if not ok:
            log.append(f"[s3 cp] ❌ {msg}")
            log_box.code("\n".join(log), language="bash")
            status.update(label="Media copy failed", state="error")
            st.stop()
        log.append(f"[s3 cp] ✅ {msg}")
        log_box.code("\n".join(log), language="bash")

        # Step 3: optionally trigger workflow
        if trigger_after:
            log.append(f"[sfn] starting execution for {content_id}...")
            log_box.code("\n".join(log), language="bash")
            ok, arn = _trigger_workflow(state_machine_arn, content_id, content_type)
            if not ok:
                log.append(f"[sfn] ❌ {arn}")
                log_box.code("\n".join(log), language="bash")
                status.update(label="Workflow trigger failed", state="error")
                st.stop()
            log.append(f"[sfn] ✅ {arn}")
            log_box.code("\n".join(log), language="bash")

        status.update(label="Done ✅", state="complete")

    st.success(f"Content ID: `{content_id}`")
    # Stash for the trigger panel
    st.session_state["last_content_id"] = content_id
    st.session_state["last_content_type"] = content_type

if trigger_btn:
    account_id = cfg.get("AWS_ACCOUNT_ID", "")
    state_machine_arn = STATE_MACHINE_ARN_TPL.format(region=AWS_REGION, account=account_id)

    with st.status(f"Triggering workflow for {existing_id}...", expanded=True) as status:
        ok, arn = _trigger_workflow(state_machine_arn, existing_id.strip(), existing_type)
        if ok:
            st.code(f"[sfn] ✅ {arn}", language="bash")
            status.update(label="Workflow triggered ✅", state="complete")
        else:
            st.code(f"[sfn] ❌ {arn}", language="bash")
            status.update(label="Workflow trigger failed", state="error")

# Show last created ID as a convenience copy
if "last_content_id" in st.session_state:
    with st.sidebar:
        st.divider()
        st.caption("Last created")
        st.code(st.session_state["last_content_id"], language="text")
