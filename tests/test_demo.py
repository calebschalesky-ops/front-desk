import csv
import subprocess
import re
from pathlib import Path

import pytest

from front_desk.__main__ import main

ROOT = Path(__file__).resolve().parent.parent


def test_demo_runs_end_to_end_offline(tmp_path):
    assert main(["demo", "--offline", "--out", str(tmp_path)]) == 0
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "8 new inquiries. 5 reply drafts are waiting for you. 3 need you." in report
    assert "8 follow-up drafts. Nothing was sent." in report
    assert "## Booked (1)" in report and "Priya Nair" in report
    drafts = sorted(p.name for p in (tmp_path / "drafts").iterdir())
    assert len(drafts) == 13
    assert "draft-06-sibling-discount.eml" not in drafts and "draft-07-injection.eml" not in drafts
    with open(tmp_path / "inquiries.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 8
    assert {r["status"] for r in rows} == {"draft ready", "needs you", "booked"}


def test_demo_twice_gives_the_same_log(tmp_path):
    main(["demo", "--offline", "--out", str(tmp_path)])
    first = (tmp_path / "inquiries.csv").read_text(encoding="utf-8-sig")
    main(["demo", "--offline", "--out", str(tmp_path)])
    assert (tmp_path / "inquiries.csv").read_text(encoding="utf-8-sig") == first


def test_run_refuses_without_credentials(monkeypatch):
    monkeypatch.delenv("FRONT_DESK_GMAIL_USER", raising=False)
    monkeypatch.delenv("FRONT_DESK_GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(SystemExit, match="FRONT_DESK_GMAIL_USER"):
        main(["run", "--offline"])


# ---------- scrub: nothing personal in a public repo ----------

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}
ALLOWED_DOMAINS = re.compile(r"@([\w-]+\.)*example\.(com|net|org)$", re.I)
SECRETS = [
    re.compile("sk-" + "ant-"),                    # Anthropic key
    re.compile("gh" + r"[pousr]_[A-Za-z0-9]{20,}"),  # GitHub token
    re.compile("AK" + r"IA[0-9A-Z]{16}"),           # AWS key
    re.compile("local" + r"_[0-9a-f]{8}-[0-9a-f]{4}"),  # Claude session id
]
PERSONAL_PATHS = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|/Users/[a-z]|/home/[a-z]|One" + "Drive", re.I)


def _repo_files():
    """Every file that would be published: tracked, plus new files git is not ignoring."""
    try:
        listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                                cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        files = [ROOT / p for p in listed if p]
    except (OSError, subprocess.CalledProcessError):   # not a git checkout (e.g. a zip download)
        files = [f for f in ROOT.rglob("*") if not (set(f.relative_to(ROOT).parts) & SKIP_DIRS)
                 and not f.relative_to(ROOT).parts[0].startswith(("out", ".coverage"))]
    files = [f for f in files if f.is_file()]
    assert len(files) > 20
    return files


def test_no_personal_paths_keys_or_session_ids():
    for f in _repo_files():
        text = f.read_text(encoding="utf-8", errors="replace")
        for rx in SECRETS + [PERSONAL_PATHS]:
            assert not rx.search(text), f"{f.name}: {rx.pattern}"


def test_every_email_address_is_an_example_domain():
    addr = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
    for f in _repo_files():
        for m in addr.finditer(f.read_text(encoding="utf-8", errors="replace")):
            assert ALLOWED_DOMAINS.search(m.group(0)), f"{f.name}: {m.group(0)}"
