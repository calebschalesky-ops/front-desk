"""The three ways Front Desk can reach a model.

All of them have one method, complete(system, prompt) -> str.

- ApiClient uses the Anthropic API. Needs ANTHROPIC_API_KEY.
- CliClient runs the Claude Code command line (`claude -p`) headless, so a
  machine that is signed in to Claude Code needs no API key at all. Tools,
  settings files and MCP servers are all switched off for the call: the model
  gets the prompt and nothing else.
- None means offline: no model, the drafts are built from the info file by
  templates. The demo and the tests run this way.

Whichever is used, the reply is checked by guard.py before it is saved.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile


class ApiClient:
    name = "Anthropic API"

    def __init__(self, model: str):
        import anthropic
        self.model = model
        self.client = anthropic.Anthropic()

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        resp = self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                           messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


class CliClient:
    name = "Claude Code CLI"

    def __init__(self, model: str = "sonnet", exe: str | None = None, timeout: int = 180):
        self.exe = exe or shutil.which("claude")
        if not self.exe:
            raise RuntimeError("the claude command was not found on PATH")
        self.model, self.timeout = model, timeout

    def command(self, system_file: str) -> list[str]:
        # The system prompt goes in a file: on Windows `claude` is a .cmd batch
        # file, and batch files cut a multi-line argument off at the first newline.
        return [self.exe, "-p", "--output-format", "text", "--model", self.model,
                "--system-prompt-file", system_file, "--tools", "", "--setting-sources", "",
                "--strict-mcp-config", "--no-session-persistence"]

    def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        # Run from an empty folder so no project instructions get picked up.
        # ignore_cleanup_errors: on Windows a claude child process can hold the folder a moment longer.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
            sys_file = os.path.join(empty, "system.txt")
            with open(sys_file, "w", encoding="utf-8") as f:
                f.write(system)
            r = subprocess.run(self.command(sys_file), input=prompt, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout, cwd=empty)
        if r.returncode != 0:
            raise RuntimeError(f"claude -p failed: {(r.stderr or r.stdout).strip()[:300]}")
        return r.stdout.strip()


def pick(mode: str, model: str):
    """mode is auto, api, cli or offline. Returns a client, or None for offline."""
    if mode == "offline":
        return None
    if mode == "api" or (mode == "auto" and os.environ.get("ANTHROPIC_API_KEY")):
        return ApiClient(model)
    if mode == "cli" or (mode == "auto" and shutil.which("claude")):
        return CliClient()
    return None


def parse_json(text: str) -> dict:
    """The first JSON object in a model reply, with or without a code fence around it."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in the model reply")
    return json.loads(m.group(0))
