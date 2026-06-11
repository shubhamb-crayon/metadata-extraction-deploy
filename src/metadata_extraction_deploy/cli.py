import subprocess
import sys
from pathlib import Path


def run_app() -> None:
    app = Path(__file__).parent / "Home.py"
    result = subprocess.run(["streamlit", "run", str(app), *sys.argv[1:]], check=False)
    sys.exit(result.returncode)


def run_lint() -> None:
    result = subprocess.run(["uvx", "ruff", "check", "src/"], check=False)
    sys.exit(result.returncode)


def run_lint_fix() -> None:
    result = subprocess.run(["uvx", "ruff", "check", "--fix", "src/"], check=False)
    sys.exit(result.returncode)


def run_format() -> None:
    result = subprocess.run(["uvx", "ruff", "format", "src/"], check=False)
    sys.exit(result.returncode)
