# MEP Deploy

Internal UI for deploying and testing Metadata Extraction Platform (MEP) services on AWS.

## What it does

| Page | Purpose |
|---|---|
| **Home** | AWS MFA login — authenticates and writes session credentials to `.env` |
| **Deploy** | Select any combination of Lambda, ECS, or BDA engine services and deploy them in parallel |
| **Content Testing** | Create a content record via the middleware API, copy media to S3, and trigger the Step Functions workflow |

---

## Setup

**Prerequisites:** Python 3.13, [uv](https://docs.astral.sh/uv/), AWS CLI, Docker (with `buildx`), `jq`

**1. Clone and install**

```bash
git clone <repo-url>
cd metadata-extraction-deploy
uv sync
```

**2. Configure**

```bash
cp config.mk.example config.mk
```

Edit `config.mk` and fill in:

| Variable | Description |
|---|---|
| `APP_DIR` | Absolute path to the `metadata-extraction-app` repo on your machine |
| `AWS_ACCOUNT_ID` | 12-digit AWS account ID |
| `API_URL` | Middleware content API endpoint |
| `AUTH_TOKEN` | API auth token |
| `BUCKET` | S3 orchestration bucket name |

---

## Running

```bash
uv run dev
```

Opens the Streamlit app at `http://localhost:8501`.

---

## Usage

1. **Log in** — open the Home page, enter your AWS profile and MFA token, click **Login**. Your session is written to `.env` and lasts up to 4 hours (role) or 10 hours (IAM user).
2. **Deploy** — go to the Deploy page, pick an environment (`dev` / `prod`), check the services you want, and click **Deploy**. All selected services build and push in parallel.
3. **Content Testing** — go to the Content Testing page, select a content type, and click **Create content**. Toggle **Trigger workflow after creation** to also start the Step Functions execution immediately.

---

## Other commands

```bash
uv run lint        # check for linting issues
uv run lint-fix    # auto-fix linting issues
uv run format      # auto-format code
```

Makefile targets are also available directly — run `make help` for the full list.
