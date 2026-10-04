"""One `claude -p` process: argv, scrubbed env, streamed events, user lines on stdin, kill on /stop."""
import json
import os
import signal
import subprocess
import threading
import uuid
from pathlib import Path

from .streamjson import Parser

# Never inherited by claude: systemd credential dir, our own knobs, nested-session markers.
DROP = ("CREDENTIALS_DIRECTORY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


def child_env(token: str, extra: dict, connectors: bool = True) -> dict:
    env = dict(os.environ)
    env.update(extra)
    if not connectors:  # claude.ai account connectors (Gmail, Drive...): off = no MCP load, no "not authorized" chatter
        env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    for k in list(env):
        if k in DROP or k.startswith("CLAUDE_TG_") or (token and token in env[k]):
            env.pop(k)
    home = env.setdefault("HOME", str(Path.home()))
    local_bin = os.path.join(home, ".local", "bin")
    path = env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    if local_bin not in path.split(":"):
        env["PATH"] = f"{local_bin}:{path}"
    return env


def build_argv(claude: str, session_id, extra_args) -> list:
    """Prompts go in on stdin as user lines (one process, many turns); --replay-user-messages echoes each
    line with its uuid when claude takes it in -> we know which `result` answered which message."""
    argv = [claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--replay-user-messages", "--dangerously-skip-permissions", *extra_args]
    if session_id:
        argv += ["--resume", session_id]
    return argv


def user_line(text: str, uid: str) -> str:
    return json.dumps({"type": "user", "uuid": uid, "message": {"role": "user", "content": text}},
                      ensure_ascii=False) + "\n"


class Run:
    def __init__(self, argv, cwd, env):
        self.stopped = False
        self.open = True  # stdin accepts user lines; closed -> claude finishes its work (helpers too) and exits
        self.stderr = []
        self.parser = Parser(cwd)
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
        threading.Thread(target=self._drain, daemon=True).start()

    def send(self, text: str):
        """Write one user message; its uuid, or None if the input is closed / the process is gone."""
        if not self.open:
            return None
        uid = str(uuid.uuid4())
        try:
            self.proc.stdin.write(user_line(text, uid))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.open = False
            return None
        return uid

    def close_input(self):
        if self.open:
            self.open = False
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def _drain(self):
        for line in self.proc.stderr:
            self.stderr.append(line)
            del self.stderr[:-50]

    def events(self):
        for line in self.proc.stdout:
            yield from self.parser.feed(line)
        self.proc.wait()

    def stop(self):
        self.stopped, self.open = True, False
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)


def one_shot(claude, prompt, env, cwd, model, timeout=90) -> str:
    """Plain text answer from a throwaway session (topic titles)."""
    # no tools: with them the model may act on the quoted chat (asked for file access instead of titling)
    argv = [claude, "-p", "--model", model, "--no-session-persistence", "--tools", "", "--", prompt]
    r = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""
