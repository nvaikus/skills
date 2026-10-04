"""Parse `claude -p --output-format stream-json --verbose --include-partial-messages` lines
into a few UI events. Pure: no I/O, fully unit-tested."""
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

ICONS = {
    "Bash": "🔧", "Read": "📖", "Edit": "✏️", "MultiEdit": "✏️", "Write": "📝", "NotebookEdit": "✏️",
    "Grep": "🔎", "Glob": "🔎", "WebFetch": "🌐", "WebSearch": "🌐", "Task": "🤖", "Agent": "🤖",
    "TodoWrite": "📋",
}


DENIED = re.compile(r"permission .{0,40}denied|denied by .{0,60}(classifier|permission)|requested permissions", re.I)

@dataclass
class Event:
    kind: str                 # session | turn | thinking | tool | text | text_end | result | user | bg | denied
    text: str = ""            # tool line / streamed text or thinking so far / final result / session model /
                              # user: uuid of our stdin line claude just took in
    session_id: Optional[str] = None
    is_error: bool = False
    num_turns: int = 0
    api_ms: int = 0
    name: str = ""            # tool events: raw tool name (friendly status maps it to a phase)
    sub: bool = False         # tool events: called inside a subagent
    count: int = 0            # bg: background tasks (helpers, background shells) still running;
                              # result: permission denials in the turn


def _short(s: str, n: int = 60) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_line(name: str, inp: dict, cwd: str = "") -> str:
    inp = inp or {}
    if name == "Bash":
        arg = inp.get("command", "")
    elif name in ("Read", "Edit", "MultiEdit", "Write", "NotebookEdit"):
        arg = inp.get("file_path") or inp.get("notebook_path") or ""
        if cwd and arg.startswith(cwd.rstrip("/") + "/"):
            arg = os.path.relpath(arg, cwd)
    elif name in ("Grep", "Glob"):
        arg = inp.get("pattern", "")
    elif name == "WebFetch":
        arg = inp.get("url", "")
    elif name == "WebSearch":
        arg = inp.get("query", "")
    elif name in ("Task", "Agent"):
        arg = inp.get("description", "")
    else:
        arg = ""
    icon = ICONS.get(name, "⚙️")
    return f"{icon} {name}: {_short(arg)}" if arg else f"{icon} {name}"


class Parser:
    def __init__(self, cwd: str = ""):
        self.cwd = cwd
        self.text = ""   # current top-level text block being streamed
        self.think = ""  # current top-level thinking block (often empty: models may omit thinking text)
        self.block = ""  # type of the open top-level content block
        self.tools = {}  # tool_use_id -> tool name (a denial names only the id)

    def feed(self, line: str) -> list:
        line = line.strip()
        if not line:
            return []
        try:
            d = json.loads(line)
        except ValueError:
            return []
        t = d.get("type")
        sub = d.get("parent_tool_use_id") is not None
        if t == "system" and d.get("subtype") == "init":  # once per turn when prompts come on stdin
            return [Event("session", d.get("model") or "", d.get("session_id"))]
        if t == "system" and d.get("subtype") == "background_tasks_changed":  # full list, top-level tasks only
            return [Event("bg", count=len(d.get("tasks") or []))]
        if t == "user" and d.get("isReplay") and not sub:  # --replay-user-messages: a stdin line was taken in
            return [Event("user", d.get("uuid") or "")]
        if t == "user":  # tool results: a permission-mode denial comes back as an error result, the run goes on
            content = (d.get("message") or {}).get("content")
            out = []
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_result" and c.get("is_error") and DENIED.search(str(c.get("content"))[:400]):
                    out.append(Event("denied", name=self.tools.get(c.get("tool_use_id"), "?"), sub=sub))
            return out
        if t == "stream_event" and not sub:
            ev = d.get("event") or {}
            et = ev.get("type")
            block = (ev.get("content_block") or {}).get("type")
            dt = (ev.get("delta") or {}).get("type")
            if et == "message_start":
                return [Event("turn")]
            if et == "content_block_start":
                self.block = block or ""
            if et == "content_block_start" and block == "text":
                self.text = ""
            elif et == "content_block_start" and block == "thinking":
                self.think = ""
                return [Event("thinking")]
            elif et == "content_block_delta" and dt == "text_delta":
                self.text += ev["delta"].get("text", "")
                return [Event("text", self.text)]
            elif et == "content_block_delta" and dt == "thinking_delta" and ev["delta"].get("thinking"):
                self.think += ev["delta"]["thinking"]
                return [Event("thinking", self.think)]
            elif et == "content_block_stop" and self.block == "text":
                self.block = ""
                return [Event("text_end", self.text)]
            return []
        if t == "assistant":
            out = []
            for block in (d.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use":
                    self.tools[block.get("id")] = block.get("name", "?")
                    line_ = tool_line(block.get("name", "?"), block.get("input"), self.cwd)
                    out.append(Event("tool", ("↳ " if sub else "") + line_, name=block.get("name", ""), sub=sub))
            return out
        if t == "result":
            self.tools = {}
            return [Event("result", d.get("result") or "", d.get("session_id"), bool(d.get("is_error")),
                          d.get("num_turns") or 0, d.get("duration_api_ms") or 0,
                          count=len(d.get("permission_denials") or []))]
        return []
