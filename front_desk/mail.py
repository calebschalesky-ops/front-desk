"""Reading mail and writing drafts.

Two mailboxes share one small interface:

- ImapMailbox talks to Gmail over IMAP. It can read, label and save drafts.
- FolderMailbox reads .eml files from a folder and writes drafts back out as
  .eml files, so the whole agent runs with no account at all.

Neither one can send mail. There is no SMTP client anywhere in this package,
and tests/test_never_sends.py fails the build if one is ever added.
"""
from __future__ import annotations

import datetime as dt
import email
import email.header
import email.policy
import email.utils
import html
import imaplib
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path


@dataclass
class Message:
    msg_id: str
    sender: str
    subject: str
    body: str
    date: dt.datetime | None = None
    uid: str | None = None          # IMAP UID or file name, used to label it later
    references: str = ""
    labels: list[str] = field(default_factory=list)

    @property
    def sender_address(self) -> str:
        return email.utils.parseaddr(self.sender)[1].lower()


def decode(s: str | None) -> str:
    if not s:
        return ""
    return "".join(
        p.decode(enc or "utf-8", "replace") if isinstance(p, bytes) else p
        for p, enc in email.header.decode_header(s)
    )


def body_text(msg) -> str:
    """Plain text if there is any, otherwise the HTML with tags stripped.

    Hidden HTML (display:none, zero-size or white text) is kept on purpose:
    that is where prompt-injection text hides, and the extract pass needs to
    see it in order to report it.
    """
    plain, htm = "", ""
    for part in msg.walk():
        if part.get_filename() or part.is_multipart():
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:
            continue
        if not payload:
            continue
        txt = payload.decode(part.get_content_charset() or "utf-8", "replace")
        if part.get_content_type() == "text/plain":
            plain += txt
        elif part.get_content_type() == "text/html":
            htm += txt
    if plain.strip():
        return plain.strip()
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", htm))).strip()


def parse(raw: bytes, uid: str | None = None) -> Message:
    msg = email.message_from_bytes(raw)
    date = None
    if msg.get("Date"):
        try:
            date = email.utils.parsedate_to_datetime(msg["Date"])
        except (TypeError, ValueError):
            pass
    return Message(
        msg_id=(msg.get("Message-ID") or f"<uid-{uid}>").strip(),
        sender=decode(msg.get("From")),
        subject=decode(msg.get("Subject")),
        body=body_text(msg),
        date=date,
        uid=uid,
        references=(msg.get("References") or "").strip(),
    )


def build_draft(original: Message, body: str, from_addr: str) -> EmailMessage:
    """A reply that threads under the original in the mail client."""
    d = EmailMessage()
    d["From"] = from_addr
    d["To"] = original.sender
    subj = original.subject
    d["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    d["In-Reply-To"] = original.msg_id
    d["References"] = f"{original.references} {original.msg_id}".strip()
    d["Date"] = email.utils.formatdate(localtime=True)
    d.set_content(body)
    return d


class FolderMailbox:
    """Reads ./samples/*.eml and writes drafts to an output folder."""

    def __init__(self, inbox: Path, out: Path):
        self.inbox, self.out = Path(inbox), Path(out)
        self.labels: dict[str, list[str]] = {}

    def fetch_new(self, seen: set[str]) -> list[Message]:
        msgs = [parse(p.read_bytes(), uid=p.name) for p in sorted(self.inbox.glob("*.eml"))]
        return [m for m in msgs if m.msg_id not in seen]

    def add_label(self, msg: Message, label: str) -> None:
        self.labels.setdefault(msg.uid, []).append(label)

    def save_draft(self, draft: EmailMessage, original: Message) -> str:
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"draft-{Path(original.uid).stem}.eml"
        path.write_bytes(draft.as_bytes(policy=email.policy.SMTP))
        return str(path)

    def close(self) -> None:
        pass


class ImapMailbox:
    """Gmail over IMAP with an app password.

    Read with BODY.PEEK so nothing is marked as read. Labels go on with
    X-GM-LABELS. Drafts are APPENDed to the Drafts folder with the \\Draft flag,
    which is how Gmail stores a draft you started yourself.
    """

    DRAFTS = "[Gmail]/Drafts"

    def __init__(self, user: str, password: str, folder: str = "INBOX",
                 host: str = "imap.gmail.com", days: int = 2, conn=None):
        self.user, self.folder, self.days = user, folder, days
        self.conn = conn or imaplib.IMAP4_SSL(host)
        self.conn.login(user, password)
        typ, _ = self.conn.select(f'"{folder}"', readonly=False)
        if typ != "OK":
            raise RuntimeError(f'mail folder "{folder}" not found')
        self._made: set[str] = set()

    def fetch_new(self, seen: set[str]) -> list[Message]:
        since = (dt.date.today() - dt.timedelta(days=self.days)).strftime("%d-%b-%Y")
        typ, data = self.conn.uid("search", None, f"(SINCE {since})")
        out = []
        for uid in (data[0] or b"").split():
            typ, md = self.conn.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not md or not isinstance(md[0], tuple):
                continue
            m = parse(md[0][1], uid=uid.decode())
            if m.msg_id not in seen:
                out.append(m)
        return out

    def add_label(self, msg: Message, label: str) -> None:
        if label not in self._made:
            self.conn.create(f'"{label}"')   # harmless "already exists" if it does
            self._made.add(label)
        self.conn.uid("store", msg.uid, "+X-GM-LABELS", f'("{label}")')

    def save_draft(self, draft: EmailMessage, original: Message) -> str:
        typ, _ = self.conn.append(f'"{self.DRAFTS}"', r"(\Draft)",
                                  imaplib.Time2Internaldate(dt.datetime.now().astimezone()),
                                  draft.as_bytes(policy=email.policy.SMTP))
        if typ != "OK":
            raise RuntimeError("Gmail refused the draft")
        return f"Gmail Drafts: {draft['Subject']}"

    def close(self) -> None:
        try:
            self.conn.logout()
        except Exception:
            pass
