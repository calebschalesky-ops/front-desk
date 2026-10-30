"""The promise that matters most: Front Desk cannot send mail, take payment or
touch a booking system.

These tests fail the build if anyone adds a way to do any of that, so the
promise holds because of the code, not because of a sentence in a prompt.
"""
import ast
import re
from pathlib import Path
from types import SimpleNamespace

from front_desk import llm
from front_desk.mail import ImapMailbox, build_draft

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "front_desk"
BANNED = re.compile(r"\bsmtplib\b|\bSMTP\(|\bSMTP_SSL\b|send_message|sendmail|\.send\(|"
                    r"gmail\.users\(\)\.messages\(\)\.send")
# Everything the package may import. No HTTP client, no payment SDK, no booking
# system SDK. The only network code is imaplib (read mail, save drafts) and the
# anthropic SDK (write the draft text).
ALLOWED_IMPORTS = {"__future__", "argparse", "ast", "csv", "datetime", "email", "html", "imaplib",
                   "json", "os", "re", "shutil", "subprocess", "sys", "tempfile", "tomllib",
                   "dataclasses", "pathlib", "anthropic"}


def test_no_sending_code_in_package():
    hits = []
    for f in PKG.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if BANNED.search(line):
                hits.append(f"{f.name}:{n}: {line.strip()}")
    assert hits == [], "sending code found:\n" + "\n".join(hits)


def test_package_imports_nothing_that_could_pay_book_or_post():
    found = {}
    for f in PKG.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                found.setdefault(name.split(".")[0], set()).add(f.name)
    extra = set(found) - ALLOWED_IMPORTS
    assert not extra, f"unexpected imports: { {k: found[k] for k in extra} }"
    assert found["subprocess"] == {"llm.py"}   # only to run `claude -p`, see below


def test_cli_model_runs_with_every_tool_switched_off(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        with open(cmd[cmd.index("--system-prompt-file") + 1], encoding="utf-8") as f:
            seen["system"] = f.read()
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    out = llm.CliClient(exe="claude").complete("line one\nline two", "the prompt")
    cmd = seen["cmd"]
    assert out == '{"ok": true}'
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""             # no Bash, no file edits, no web
    assert cmd[cmd.index("--setting-sources") + 1] == ""   # no user hooks or settings
    assert "--strict-mcp-config" in cmd                    # no MCP connectors (no Gmail send)
    assert seen["kw"]["input"] == "the prompt"             # email text goes in on stdin
    assert seen["system"] == "line one\nline two"          # whole prompt survives the .cmd wrapper


class RecordingImap:
    """Fake IMAP server. Records every command so the test can check them."""

    def __init__(self, raw_messages):
        self.raw = raw_messages
        self.commands = []

    def login(self, *a):
        self.commands.append("login")
        return "OK", [b""]

    def select(self, folder, readonly=False):
        self.commands.append("select")
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        self.commands.append(f"uid {cmd} {' '.join(str(a) for a in args if a)}")
        if cmd == "search":
            return "OK", [b" ".join(str(i).encode() for i in range(1, len(self.raw) + 1))]
        if cmd == "fetch":
            return "OK", [(b"x", self.raw[int(args[0]) - 1])]
        return "OK", [b""]

    def create(self, name):
        self.commands.append(f"create {name}")
        return "OK", [b""]

    def append(self, folder, flags, when, data):
        self.commands.append(f"append {folder} {flags}")
        return "OK", [b""]

    def logout(self):
        self.commands.append("logout")


def test_full_gmail_run_only_reads_labels_and_saves_drafts(biz, monkeypatch, tmp_path):
    """Run the real `run` command against a fake Gmail holding every sample."""
    from front_desk import __main__ as cli
    raws = [p.read_bytes() for p in sorted((ROOT / "samples").glob("*.eml"))]
    conn = RecordingImap(raws)
    monkeypatch.setattr(cli, "ImapMailbox", lambda *a, **kw: ImapMailbox(*a, conn=conn, **{
        k: v for k, v in kw.items() if k != "conn"}))
    monkeypatch.setenv("FRONT_DESK_GMAIL_USER", "owner@example.com")
    monkeypatch.setenv("FRONT_DESK_GMAIL_APP_PASSWORD", "test")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run", "--offline"]) == 0
    assert (tmp_path / "inquiries.csv").exists()

    verbs = {" ".join(c.split()[:2]) if c.startswith("uid") else c.split()[0] for c in conn.commands}
    assert verbs <= {"login", "select", "uid search", "uid fetch", "uid store", "create", "append", "logout"}
    assert all("BODY.PEEK[]" in c for c in conn.commands if c.startswith("uid fetch"))  # stays unread
    appends = {c for c in conn.commands if c.startswith("append")}
    assert appends == {'append "[Gmail]/Drafts" (\\Draft)'}                            # drafts only
    assert not any("-X-GM-LABELS" in c or "\\Deleted" in c for c in conn.commands)


def test_draft_is_a_reply_in_the_same_thread(sample):
    msg = sample("01-saturday-kids")
    d = build_draft(msg, "Hi", "owner@example.com")
    assert d["Subject"] == "Re: Kids class on Saturdays?"
    assert d["In-Reply-To"] == "<sample-01-saturday-kids@example.com>"
    assert d["To"].endswith("<dana.whitfield@example.org>")
