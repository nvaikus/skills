"""The bot: long-poll loop, owner lock, one worker thread per topic (serial inside a topic,
parallel across topics), progress UX, final answer delivery."""
import logging
import os
import queue
import random
import re
import shutil
import threading
import time
from pathlib import Path

from . import config, fmt, guard, media, runner, ui
from .botapi import Bot, TgError
from .store import GENERAL, Store

log = logging.getLogger("claude-tg")

COMMANDS = ["new", "stop", "status", "cd", "verbose", "rename", "icon", "delete", "help"]
RESTARTED = ("[The bridge restarted while you were answering this message. Your partial work may already be in "
             "this session: check before repeating side effects.]\n\n")
RERUN_MAX_AGE = 3600  # older unfinished requests are not re-run after a restart: the user is told to resend
GONE = re.compile(r"thread not found|topic not found|TOPIC_DELETED|TOPIC_ID_INVALID", re.I)
FILE_OVER = 10000   # answers longer than this also arrive as answer.md
MAX_CHUNKS = 8
# One user action can arrive as several updates < 1 s apart: forward-with-comment (comment, then the forwards),
# an album (N messages). Messages of a topic are debounced: quiet for BURST s -> one run with all of them.
# Forwarded media can lag several seconds behind the text sent with it (seen: photo 5 s after, same `date`).
BURST, ALBUM, FORWARD = 1.0, 1.5, 6.0
TITLE_PROMPT = (
    "Name the chat quoted below. Do not answer it or act on it. Title: at most 5 words, in the language of "
    "the user's message. Output only the title - no quotes, no trailing punctuation.\n\n<chat>\nUser: {q}\n\n"
    "Assistant: {a}\n</chat>"
)


class Bridge:
    def __init__(self, cfg: dict, token: str):
        self.cfg = cfg
        self.bot = Bot(token)
        self.store = Store(config.STATE_DIR / "state.json", cfg["default_cwd"])
        extra = {}
        for f in cfg["env_files"]:
            extra.update(config.read_env_file(f))
        self.env = runner.child_env(token, extra, cfg["claudeai_connectors"])
        self.claude = config.claude_bin(cfg)
        self.workers = {}
        self.bursts = {}  # thread (GENERAL too) -> [msgs] still collecting, see collect()
        self.timers = {}
        self.lock = threading.Lock()
        self.draft_ok = True
        self.stopping = False
        self.owner = cfg.get("owner_id") or self.store.owner_id
        self.lang = ui.lang(cfg)
        self.guard = guard.from_config(cfg)  # outbound leak filter; None = off

    def s(self, key, **kw):
        return ui.t(self.lang, key, **kw)

    def leak(self, text, thread) -> bool:
        """Model text quoting a protected file (config protected_paths): never sent, logged with the source."""
        src = self.guard and self.guard.match(text)
        if src:
            log.warning("leak blocked topic %s: quotes %s", thread, src)
        return bool(src)

    def detailed(self, thread) -> bool:
        """Per-topic /verbose wins over config status_style."""
        v = self.store.topic(thread).get("verbose")
        return v if v is not None else self.cfg.get("status_style") == "detailed"

    def fail(self, chat, thread, why, detail=""):
        """Friendly one-liner for the owner; the detail only in verbose mode (and always in logs)."""
        if detail:
            log.warning("topic %s: %s", thread, detail)
        text = self.s("err", why=why)
        if detail and self.detailed(thread):
            text += "\n\n" + detail
        if self.leak(text, thread):
            text = self.s("leak")
        self.quiet("sendMessage", chat_id=chat, message_thread_id=thread or None, text=text[:fmt.LIMIT],
                   link_preview_options={"is_disabled": True})

    # ---------- telegram helpers (cosmetic calls never retry, never raise) ----------
    def quiet(self, method, **p):
        try:
            return self.bot.call(method, _retries=0, **p)
        except TgError as e:
            if not self.gone(e, p.get("message_thread_id")) and "not modified" not in e.description:
                log.info("%s", e)
            return None

    def gone(self, e: TgError, thread) -> bool:
        """Topic deleted in the client (no update is sent for that): forget it on the first failed send."""
        if thread and GONE.search(e.description or ""):
            self.forget(thread, f"topic gone ({e.description})")
            return True
        return False

    def forget(self, thread, why):
        with self.lock:
            w = self.workers.pop(thread, None)
        if w:
            w.close()
        self.store.drop(thread)
        shutil.rmtree(config.STATE_DIR / "files" / str(thread), ignore_errors=True)
        log.info("topic %s forgotten: %s", thread, why)

    def react(self, chat, mid, emoji):
        if not self.cfg.get("reactions", True):
            return
        self.quiet("setMessageReaction", chat_id=chat, message_id=mid,
                   reaction=[{"type": "emoji", "emoji": emoji}] if emoji else [])

    def say(self, chat, thread, text, html=False):
        p = {"chat_id": chat, "message_thread_id": thread or None, "text": text,
             "link_preview_options": {"is_disabled": True}}
        if html:
            p["parse_mode"] = "HTML"
        try:
            return self.bot.call("sendMessage", **p)
        except TgError as e:
            self.gone(e, thread)
            raise

    def send_answer(self, chat, thread, md: str):
        md = md.strip() or self.s("empty")
        chunks = fmt.split_md(md)
        for i, chunk in enumerate(chunks[:MAX_CHUNKS]):
            html = fmt.md_to_html(chunk)
            try:
                if len(html) > fmt.LIMIT:
                    raise TgError("local", 400, "too long for html")
                self.say(chat, thread, html, html=True)
            except TgError as e:
                if e.code != 400:
                    raise
                log.info("html rejected (%s), sending plain", e.description)
                self.say(chat, thread, chunk[: fmt.LIMIT])
        if len(chunks) > MAX_CHUNKS:
            self.say(chat, thread, self.s("more_parts", n=len(chunks) - MAX_CHUNKS))
        if len(md) > FILE_OVER or len(chunks) > MAX_CHUNKS:
            path = config.STATE_DIR / "files" / str(thread) / "answer.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(md)
            self.send_file(chat, thread, path)

    def send_file(self, chat, thread, path):
        why = self.guard and self.guard.file_leak(path)
        if why:
            log.warning("leak blocked topic %s: file %s (%s)", thread, path, why)
            return self.quiet("sendMessage", chat_id=chat, message_thread_id=thread or None, text=self.s("leak_file"))
        try:
            self.bot.upload("sendDocument", "document", path, chat_id=chat, message_thread_id=thread or None)
        except TgError as e:
            log.warning("%s upload: %s", path.name, e)

    # ---------- update routing ----------
    def handle(self, upd: dict):
        if "stopped_message_generation" in upd:
            draft = upd["stopped_message_generation"].get("draft_id")
            for w in list(self.workers.values()):
                if w.draft_id == draft:
                    w.stop(drop_queue=False)
                    if not self.cfg.get("reactions", True):  # no 👌 then: confirm the stop button in text
                        self.quiet("sendMessage", chat_id=w.chat, message_thread_id=w.thread or None,
                                   text=self.s("stopped"))
            return
        msg = upd.get("message")
        if not msg or msg["chat"]["type"] != "private" or "from" not in msg:
            return
        uid = msg["from"]["id"]
        if self.owner is None:
            self.owner = uid
            self.store.set_owner(uid)
            log.info("owner set: user id %s", uid)
        if uid != self.owner:
            return
        chat = msg["chat"]["id"]
        thread = msg.get("message_thread_id") or GENERAL
        msg["_rx"] = time.time()  # timing: Telegram date -> received -> claude spawned
        self.note_topic(thread, msg)
        if msg.get("forum_topic_created") or msg.get("forum_topic_edited"):
            return
        text = msg.get("text") or ""
        if text.startswith("/"):
            rt = msg.get("reply_to_message") or {}
            if (thread != GENERAL and rt.get("message_id") == thread
                    and (rt.get("forum_topic_created") or {}).get("is_name_implicit")):
                # a command typed in All messages: the client wrapped it in a new topic - undo that
                self.quiet("deleteForumTopic", chat_id=chat, message_thread_id=thread)
                self.forget(thread, "command sent in All messages")
                thread = GENERAL
            return self.command(chat, thread, msg, text)
        self.react(chat, msg["message_id"], "👀")
        self.collect(chat, thread, msg)

    def collect(self, chat, thread, msg):
        """Debounce per topic: every new message restarts the timer; the burst runs once, as one prompt."""
        with self.lock:
            msgs = self.bursts.setdefault(thread, [])
            msgs.append(msg)
            old = self.timers.pop(thread, None)
            if old:
                old.cancel()
            wait = (FORWARD if any(m.get("forward_origin") for m in msgs)
                    else ALBUM if any(m.get("media_group_id") for m in msgs) else BURST)
            t = self.timers[thread] = threading.Timer(wait, lambda: self.flush(chat, thread, t))
            t.daemon = True
            t.start()

    def flush(self, chat, thread, timer):
        with self.lock:
            if self.timers.get(thread) is not timer:  # superseded: fired while a newer message restarted it
                return
            del self.timers[thread]
            msgs = self.bursts.pop(thread, None)
        if not msgs:
            return
        if thread == GENERAL:  # a burst sent in All messages -> one new topic for all of it
            thread = self.new_topic(chat, msgs[0])
            if thread is None:
                return
        self.worker(chat, thread).put(msgs)

    def note_topic(self, thread, msg):
        """Remember topic name and whether Telegram says it is implicit (auto-named)."""
        if thread == GENERAL:
            return
        created = msg.get("forum_topic_created") or (msg.get("reply_to_message") or {}).get("forum_topic_created")
        edited = msg.get("forum_topic_edited")
        t = self.store.topic(thread)
        if created and t["implicit"] is None:
            log.info("topic %s created: %r implicit=%s", thread, created.get("name"), bool(created.get("is_name_implicit")))
            self.store.update(thread, title=created.get("name"), implicit=bool(created.get("is_name_implicit")))
        if edited and edited.get("name"):
            self.store.update(thread, title=edited["name"], implicit=False)

    def new_topic(self, chat, msg):
        seed = " ".join((msg.get("text") or msg.get("caption") or "New chat").split()[:5])[:40]
        try:
            topic = self.bot.call("createForumTopic", chat_id=chat, name=seed)
        except TgError as e:
            log.warning("createForumTopic: %s", e)
            self.say(chat, None, self.s("write_in_topic"))
            return None
        thread = topic["message_thread_id"]
        self.store.update(thread, title=seed, implicit=True)
        log.info("topic %s auto-created from All messages", thread)
        return thread

    def worker(self, chat, thread):
        with self.lock:
            w = self.workers.get(thread)
            if w is None:
                w = self.workers[thread] = Worker(self, chat, thread)
            return w

    def command(self, chat, thread, msg, text):
        cmd, _, arg = text.partition(" ")
        cmd = cmd[1:].split("@")[0].lower()
        arg = arg.strip()
        if cmd in ("start", "help"):
            return self.say(chat, thread, self.s("help"))
        if thread == GENERAL:
            return self.say(chat, None, self.s("in_topic", cmd=cmd))
        w = self.workers.get(thread)
        t = self.store.topic(thread)
        if cmd == "rename":
            if not arg:
                return self.say(chat, thread, self.s("rename_usage"))
            try:
                self.bot.call("editForumTopic", chat_id=chat, message_thread_id=thread, name=arg[:128])
            except TgError as e:
                return self.say(chat, thread, self.s("rename_fail", e=e.description))
            self.store.update(thread, title=arg[:128], implicit=False)  # auto-title never overrides it
        elif cmd == "icon":
            self.set_icon(chat, thread, msg["message_id"], arg)
        elif cmd == "delete":
            try:
                self.bot.call("deleteForumTopic", chat_id=chat, message_thread_id=thread)
            except TgError as e:
                if not GONE.search(e.description or ""):
                    return self.say(chat, thread, self.s("delete_fail", e=e.description))
            self.forget(thread, "/delete")
        elif cmd == "new":
            self.store.update(thread, session_id=None)
            self.say(chat, thread, self.s("new", cwd=t["cwd"]))
        elif cmd == "stop":
            running = bool(w and w.run)
            dropped = w.stop(drop_queue=True) if running else 0
            self.say(chat, thread, self.s("stopped_n", n=dropped) if dropped else
                     self.s("stopped") if running else self.s("idle"))
        elif cmd == "status":
            run = (self.s("yes" if w and w.run else "no") + (self.s("bg", n=w.bg) if w and w.run and w.bg else "")
                   + (self.s("queued", n=w.q.qsize()) if w and w.q.qsize() else ""))
            self.say(chat, thread, self.s("status", sid=t["session_id"] or self.s("new_next"), cwd=t["cwd"], run=run,
                                          title=t["title"] or "?", verbose=self.s("yes" if self.detailed(thread) else "no")))
        elif cmd == "verbose":
            on = {"on": True, "off": False}.get(arg.lower(), not self.detailed(thread))
            self.store.update(thread, verbose=on)
            self.say(chat, thread, self.s("verbose_on" if on else "verbose_off"))
        elif cmd == "cd":
            if not arg:
                return self.say(chat, thread, self.s("cd_show", cwd=t["cwd"]))
            path = Path(os.path.expanduser(arg))
            if not path.is_absolute():
                path = Path(t["cwd"]) / path
            path = path.resolve()
            if not path.is_dir():
                return self.say(chat, thread, self.s("cd_bad", path=path))
            self.store.update(thread, cwd=str(path), session_id=None)
            self.say(chat, thread, self.s("cd_ok", path=path))
        else:
            self.worker(chat, thread).put([msg])  # unknown /command: let Claude see it

    def set_icon(self, chat, thread, mid, arg):
        """/icon <emoji> | off. Only getForumTopicIconStickers emojis are allowed; no arg = list them."""
        try:
            icons = {x["emoji"].rstrip("\ufe0f"): x["custom_emoji_id"] for x in self.bot.call("getForumTopicIconStickers")}
        except TgError as e:
            return self.say(chat, thread, self.s("icon_fail", e=e.description))
        if not arg:
            return self.say(chat, thread, self.s("icon_usage", icons=" ".join(icons)))
        cid = "" if arg.lower() in ("off", "none", "-") else icons.get(arg.rstrip("\ufe0f"))
        if cid is None:
            return self.say(chat, thread, self.s("icon_bad", icons=" ".join(icons)))
        try:
            self.bot.call("editForumTopic", chat_id=chat, message_thread_id=thread, icon_custom_emoji_id=cid)
        except TgError as e:
            if "not modified" not in e.description:
                return self.say(chat, thread, self.s("icon_fail", e=e.description))
        self.react(chat, mid, "👌")

    # ---------- restart safety ----------
    def restore(self):
        """Re-run requests a previous process accepted but did not finish (restart, crash)."""
        for key, e in sorted(self.store.pending().items(), key=lambda kv: int(kv[0])):
            msgs, chat, thread = e["msgs"], e["chat"], e["thread"]
            mid = msgs[-1]["message_id"]
            if time.time() - msgs[-1].get("date", 0) > RERUN_MAX_AGE:
                self.store.unpend(key)
                self.react(chat, mid, "💔")
                self.quiet("sendMessage", chat_id=chat, message_thread_id=thread, reply_parameters={"message_id": mid},
                           text=self.s("restart_resend"))
                continue
            if e.get("started"):
                msgs[-1]["_restarted"] = True
                self.quiet("sendMessage", chat_id=chat, message_thread_id=thread, reply_parameters={"message_id": mid},
                           text=self.s("restart_rerun"))
            log.info("restoring unfinished request %s in topic %s (started: %s)", key, thread, bool(e.get("started")))
            self.worker(chat, thread).put(msgs)

    def shutdown(self, grace=8.0):
        """SIGTERM: stop claude runs, keep their requests pending for the next start."""
        self.stopping = True
        busy = [w for w in list(self.workers.values()) if w.run]
        for w in busy:
            w.run.stop()
        end = time.monotonic() + grace
        while time.monotonic() < end and any(w.run for w in busy):
            time.sleep(0.2)
        log.info("shutdown: %d run(s) interrupted, will re-run on start", len(busy))

    # ---------- main loop ----------
    def serve(self):
        me = self.bot.call("getMe")
        log.info("bot @%s up; topics enabled: %s; owner: %s", me.get("username"), me.get("has_topics_enabled"),
                 self.owner or "first private-chat user")
        if not me.get("has_topics_enabled"):
            log.warning("Threaded Mode is off: enable it in @BotFather (Bot Settings -> Threads)")
        self.quiet("setMyCommands", commands=[{"command": c, "description": self.s("cmd." + c)} for c in COMMANDS])
        self.restore()
        offset = None
        while True:
            try:
                ups = self.bot.call("getUpdates", _timeout=65, offset=offset, timeout=50,
                                    allowed_updates=["message", "stopped_message_generation"])
            except TgError as e:
                if e.code == 409:
                    log.error("another poller uses this token (409); retrying in 30 s")
                    time.sleep(30)
                else:
                    log.warning("getUpdates: %s", e)
                    time.sleep(3)
                continue
            for u in ups:
                offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception:
                    log.exception("update %s failed", u.get("update_id"))


def reply_context(msg, thread):
    """The bot message the owner replies to (e.g. a `claude-tg notify` notification), quoted for claude.
    Replies to the topic root (the client's default) and to the owner's own messages add nothing."""
    rt = msg.get("reply_to_message") or {}
    text = rt.get("text") or rt.get("caption")
    if not text or rt.get("message_id") == thread or not (rt.get("from") or {}).get("is_bot"):
        return None
    quote = (msg.get("quote") or {}).get("text")  # the owner quoted only a part of it
    return "[Replying to this bot message:]\n" + (quote or text)[:4000] + "\n[Reply:]"


class Batch:
    """Messages that became one prompt (a debounced burst)."""

    def __init__(self, msgs, prompt):
        self.msgs, self.prompt, self.key = msgs, prompt, msgs[-1]["message_id"]


class Worker:
    """One topic, one `claude -p` process at a time. A message sent while that process takes input goes into
    it at once (stdin user line): claude answers it in its own turn, or inside the running one. Otherwise it
    queues for the next process. One process = many `result`s; each one answers the messages claude took in
    since the previous one."""

    def __init__(self, bridge: Bridge, chat: int, thread: int):
        self.b, self.chat, self.thread = bridge, chat, thread
        self.q = queue.Queue()
        self.run = None
        self.draft_id = None
        self.closed = self.stopped = self.renamed = False
        self.keys = []  # pending keys handled by the current process
        self.lock = threading.Lock()  # run input state below + the decision to close stdin
        self.inj = threading.Lock()   # injected prompts are built one at a time: message order holds
        self.sent, self.seen = {}, []  # uuid -> Batch written to stdin / batches claude took in since the last result
        self.preparing = self.bg = 0  # injected batches still being built / background tasks running
        self.idle = False  # a turn ended (result) and no new one started
        self.ilock = threading.Lock()  # post_interim runs from the event loop and the status ticker
        self.interim = self.posted = ""  # ended text block not yet posted / last posted one
        self.stream_id = self.st = self.typing = None
        self.last_draft = 0.0
        self.denials = set()  # tools denied by the permission mode this turn (one status line each)
        self.tripped = self.noticed = False  # leak filter: block's drafts suppressed / notice posted this turn
        threading.Thread(target=self._loop, daemon=True, name=f"topic-{thread}").start()

    def close(self):
        """Topic deleted: stop the run, drop the queue, end the thread."""
        self.closed = True
        self.stop(drop_queue=True)
        self.q.put(None)

    def put(self, msgs):
        self.b.store.pend(msgs[-1]["message_id"], thread=self.thread, chat=self.chat, msgs=msgs, started=False)
        with self.lock:
            live = bool(self.run and self.run.open) and not self.closed
            if live:
                self.preparing += 1  # holds stdin open until the prompt is built (voice, downloads)
        if live:
            threading.Thread(target=self.inject, args=(msgs,), daemon=True, name=f"inject-{self.thread}").start()
        else:
            self.q.put(msgs)

    def stop(self, drop_queue: bool) -> int:
        dropped = 0
        while drop_queue:
            try:
                msgs = self.q.get_nowait()
                if msgs is None:
                    continue
                for m in msgs:
                    self.b.react(self.chat, m["message_id"], None)
                self.b.store.unpend(msgs[-1]["message_id"])
                dropped += 1
            except queue.Empty:
                break
        if self.run:
            self.run.stop()
        return dropped

    def _loop(self):
        while True:
            msgs = self.q.get()
            if msgs is None or self.closed:
                return
            with self.lock:
                self.keys = [msgs[-1]["message_id"]]
            self.b.store.pend(self.keys[0], started=True)
            try:
                self.process(msgs)
            except Exception as e:
                if self.closed or self.b.stopping:
                    continue
                log.exception("topic %s failed", self.thread)
                self.b.react(self.chat, msgs[-1]["message_id"], "💔")
                self.b.fail(self.chat, self.thread, self.b.s("why.bridge"),
                            f"{type(e).__name__}: {self.b.bot.redact(str(e))[:300]}")
            finally:
                with self.lock:
                    self.run, keys = None, self.keys
                self.draft_id = None
                if not self.b.stopping:  # answered ones are gone already; a cut run keeps the rest for restore()
                    for k in keys:
                        self.b.store.unpend(k)

    # ---------- prompts ----------
    def prompt(self, msgs):
        b, parts, files = self.b, [], []
        folder = config.STATE_DIR / "files" / str(self.thread)
        for m in msgs:
            got, audio = media.fetch(b.bot, m, folder)
            files += got
            if audio:
                b.quiet("sendChatAction", chat_id=self.chat, message_thread_id=self.thread, action="typing")
                text = media.transcribe(audio, b.cfg, b.env)
                short = text if len(text) <= 300 else text[:300] + "…"
                b.say(self.chat, self.thread, f"🎙 {short}")
                parts.append(text)
            quoted = reply_context(m, self.thread)
            if quoted:
                parts.append(quoted)
            if m.get("text") or m.get("caption"):
                parts.append(m.get("text") or m.get("caption"))
        prompt = "\n\n".join(parts)
        if msgs[-1].get("_restarted") and self.b.store.topic(self.thread)["session_id"]:
            prompt = RESTARTED + prompt
        if files:
            prompt += "\n\nUser attached:\n" + "\n".join(str(Path(f).resolve()) for f in files)
        return prompt.strip()

    def build(self, msgs):
        """Prompt of a batch, or None: nothing to run (failure already shown, or an empty message)."""
        b, mid = self.b, msgs[-1]["message_id"]
        if msgs[-1].get("_prompt"):  # built for an injection that missed the process: don't transcribe twice
            return msgs[-1].pop("_prompt")
        try:
            prompt = self.prompt(msgs)
        except media.NoStt as e:
            b.react(self.chat, mid, "💔")
            return b.fail(self.chat, self.thread, b.s("why." + e.key), f"voice: {e}")
        except TgError as e:
            b.react(self.chat, mid, "💔")
            return b.fail(self.chat, self.thread, b.s("why.download"), f"attachment: {e.description}")
        if not prompt:
            return b.react(self.chat, mid, None)
        return prompt

    def inject(self, msgs):
        """put() while a process takes input: build the prompt off the poller/timer thread, write it to stdin."""
        b, mid = self.b, msgs[-1]["message_id"]
        try:
            with self.inj:
                prompt = self.build(msgs)
                if prompt is None:
                    return b.store.unpend(mid)
                with self.lock:
                    run, uid = self.run, None
                    if run and run.open and not self.closed:
                        b.store.pend(mid, started=True)  # before send: a fast answer unpends it
                        uid = run.send(prompt)
                        if uid:
                            self.sent[uid] = Batch(msgs, prompt)
                            self.keys.append(mid)
                        else:
                            b.store.pend(mid, started=False)
                if uid:
                    b.react(self.chat, mid, "✍")
                    return log.info("topic %s: message %s went into the running claude", self.thread, mid)
                msgs[-1]["_prompt"] = prompt  # the process ended meanwhile: next one
                self.q.put(msgs)
        except Exception:
            log.exception("topic %s: injecting message %s failed", self.thread, mid)
            b.react(self.chat, mid, "💔")
            b.store.unpend(mid)
        finally:
            with self.lock:
                self.preparing -= 1
            self.maybe_close()

    def maybe_close(self):
        """Close stdin once nothing is left to answer: the turn ended, no background task runs, no message is on
        its way in. claude then exits (it would still finish helpers first); later messages start a new process."""
        with self.lock:
            run = self.run
            if run and run.open and self.idle and not self.bg and not self.sent and not self.preparing:
                run.close_input()

    # ---------- one process ----------
    def process(self, msgs):
        b, chat, thread, mid = self.b, self.chat, self.thread, msgs[-1]["message_id"]
        prompt = self.build(msgs)
        if prompt is None:
            return
        b.react(chat, mid, "✍")  # 👀 accepted -> ✍ working -> 👍 done
        rx = msgs[-1].get("_rx") or time.time()
        lag, wait = rx - msgs[-1].get("date", rx), time.time() - rx
        self.renamed = False
        left, lost = self.execute([Batch(msgs, prompt)])
        if lost and "No conversation found" in "".join(self.last_stderr) and not (self.closed or b.stopping):
            b.store.update(thread, session_id=None)  # session file gone (other machine, cleaned up): start over
            b.say(chat, thread, b.s("session_lost"))
            left, lost = self.execute(left)
        tm = self.timing
        log.info("run topic %s: tg-lag %.0fs queue %.1fs | %s | results %s model %s%s", thread, lag, wait,
                 " ".join(f"{k} {v:.1f}" for k, v in tm["marks"].items()), tm["results"], tm["model"] or "?",
                 " resume" if tm["resume"] else "")
        if self.closed or b.stopping or not left:
            return
        for bt in left:
            b.react(chat, bt.key, "👌" if self.stopped else "💔")
            b.store.unpend(bt.key)
        if self.stopped:
            return
        if lost:
            b.fail(chat, thread, ui.reason(lost.text) or b.s("why.claude"), f"claude error: {lost.text}")
        else:
            tail = "".join(self.last_stderr[-5:]).strip()[-800:] or "no output"
            b.fail(chat, thread, b.s("why.no_result"), f"claude exited without a result: {tail}")

    def execute(self, batches):
        """Run one process with these batches as its first input; returns (batches left unanswered, the
        deferred error result of a failed --resume or None)."""
        if not batches:  # a process without input would wait on stdin forever
            return [], None
        b, chat, thread = self.b, self.chat, self.thread
        if b.guard:
            b.guard.refresh()  # protected files changed (skill update) -> rebuild the index
        t = b.store.topic(thread)
        cwd = t["cwd"] if os.path.isdir(t["cwd"]) else os.path.expanduser("~")
        argv = runner.build_argv(b.claude, t["session_id"], b.cfg["claude_args"], b.cfg.get("permission_mode"))
        run = runner.Run(argv, cwd, dict(b.env, **{config.RUN_TOPIC_ENV: str(thread)}))
        self.stopped, self.last_stderr = False, run.stderr
        unsent = []
        with self.lock:
            self.run, self.sent, self.seen, self.bg, self.idle = run, {}, [], 0, False
            for bt in batches:
                uid = run.send(bt.prompt)
                if uid:
                    self.sent[uid] = bt
                else:
                    unsent.append(bt)
        t0 = time.monotonic()
        marks = {}  # seconds since spawn of the first event of each kind -> one log line per process
        self.timing = {"marks": marks, "model": "", "resume": bool(t["session_id"]), "results": 0}
        lost = None
        try:
            for ev in run.events():
                now = time.monotonic()
                marks.setdefault(ev.kind, now - t0)
                if ev.kind in ("session", "turn", "thinking", "tool", "text", "text_end") and self.st is None:
                    self.turn_begin()
                if ev.kind in ("turn", "thinking", "tool", "text"):
                    self.post_interim()  # the run went on: the ended block was a message, not the answer
                if ev.kind == "session":  # once per turn
                    self.timing["model"] = ev.text
                    with self.lock:
                        self.idle = False
                    if ev.session_id and ev.session_id != b.store.topic(thread)["session_id"]:
                        b.store.update(thread, session_id=ev.session_id)
                elif ev.kind == "user":
                    with self.lock:
                        bt = self.sent.pop(ev.text, None)
                        if bt:
                            self.seen.append(bt)
                        self.idle = False
                elif ev.kind == "bg":
                    with self.lock:
                        self.bg = ev.count
                    self.maybe_close()
                elif ev.kind == "thinking":
                    self.st.thinking(ev.text)
                elif ev.kind == "tool":
                    self.st.tool(ev)
                elif ev.kind == "denied":
                    self.denied(ev)
                elif ev.kind == "text":
                    self.st.set("write")
                    if now - self.last_draft >= 1.0 and ev.text.strip():
                        self.last_draft = now
                        self.stream_id = self._stream(ev.text, self.stream_id)
                elif ev.kind == "text_end":
                    with self.ilock:
                        self.interim = ev.text
                    self.st.text_end()
                    if ev.text.strip():  # the throttle may have dropped the tail: flush the full block
                        self.last_draft = now
                        self.stream_id = self._stream(ev.text, self.stream_id)
                elif ev.kind == "result":
                    self.turn_end()
                    with self.lock:
                        answered, self.seen, self.idle = self.seen, [], True
                    if ev.session_id:
                        b.store.update(thread, session_id=ev.session_id)
                    if ev.count:
                        log.info("topic %s: %d permission denial(s) this turn", thread, ev.count)
                    if not self.timing["results"] and t["session_id"] and ev.is_error and ev.num_turns == 0:
                        lost = ev  # likely a failed --resume: decided after exit, once stderr is in
                        unsent += answered
                        run.close_input()
                        continue
                    self.timing["results"] += 1
                    try:
                        self.deliver(ev, answered)
                    except Exception:  # never leave the process running unread
                        log.exception("topic %s: delivering an answer failed", thread)
                        for bt in answered:
                            b.react(chat, bt.key, "💔")
                    self.maybe_close()
            marks["exit"] = time.monotonic() - t0
        finally:
            self.turn_end()
            with self.lock:
                run.close_input()
                left = unsent + self.seen + list(self.sent.values())
                self.sent, self.seen = {}, []
            self.stopped = run.stopped
        return left, lost

    def deliver(self, ev, answered):
        """One `result`: the answer to every batch claude took in since the previous one (none for a turn
        started by a finished background task)."""
        b, chat, thread = self.b, self.chat, self.thread
        log.info("result topic %s: answers %s turns %s api %.1fs%s", thread, [bt.key for bt in answered] or "-",
                 ev.num_turns, ev.api_ms / 1000, " error" if ev.is_error else "")
        if self.closed:
            return
        if ev.is_error:
            for bt in answered:
                b.react(chat, bt.key, "💔")
            b.fail(chat, thread, ui.reason(ev.text) or b.s("why.claude"), f"claude error: {ev.text}")
        else:
            if (answered or ev.text.strip()) and ev.text.strip() != self.posted.strip():
                self.answer(ev.text)  # skipped if the idle ticker posted it already
            for bt in answered:
                b.react(chat, bt.key, "👍")
            if answered and not self.renamed and b.store.topic(thread).get("implicit"):
                self.renamed = True
                threading.Thread(target=self.rename, args=(answered[0].prompt, ev.text), daemon=True).start()
        for bt in answered:
            b.store.unpend(bt.key)

    def turn_begin(self):
        """A turn started: fresh status message, typing, draft."""
        self.draft_id = random.randint(1, 2**31 - 1)
        with self.ilock:
            self.interim = self.posted = ""
        self.stream_id, self.last_draft = None, 0.0
        self.tripped = self.noticed = False
        self.denials = set()
        self.typing = threading.Event()
        threading.Thread(target=self._typing, args=(self.typing,), daemon=True).start()
        self.st = Status(self, self.b.detailed(self.thread), self.b.lang)

    def turn_end(self):
        if self.typing:
            self.typing.set()
            self.typing = None
        if self.st:
            self.st.close()
            self.st = None
        with self.ilock:
            self.interim = ""
        if self.stream_id:
            self.b.quiet("deleteMessage", chat_id=self.chat, message_id=self.stream_id)
            self.stream_id = None

    def post_interim(self):
        """A text block between tool calls (or before a wait for background helpers) is a real message:
        the draft preview dies in 30 s and `result` carries only the last block, so it would be lost."""
        with self.ilock:
            text, self.interim = self.interim, ""
            if not text.strip():
                return
            if self.stream_id:
                self.b.quiet("deleteMessage", chat_id=self.chat, message_id=self.stream_id)
                self.stream_id = None
            try:
                self.answer(text)
                self.posted = text
            except TgError as e:
                log.warning("interim message: %s", e.description)
            self.tripped = False  # the next block streams again
        if self.st:
            self.st.below()

    def denied(self, ev):
        """A tool call refused by the permission mode (auto classifier): one short line per tool per turn."""
        log.info("topic %s: permission denied: %s%s", self.thread, ev.name, " (subagent)" if ev.sub else "")
        if ev.name in self.denials:
            return
        self.denials.add(ev.name)
        self.b.quiet("sendMessage", chat_id=self.chat, message_thread_id=self.thread,
                     text=self.b.s("denied", tool=ev.name))
        if self.st:
            self.st.below()

    def answer(self, text):
        """A real answer message; one quoting a protected file becomes one notice per turn."""
        b = self.b
        if not (b.guard and b.leak(text, self.thread)):
            return b.send_answer(self.chat, self.thread, text)
        if not self.noticed:
            self.noticed = True
            b.say(self.chat, self.thread, b.s("leak"))

    def _stream(self, text, stream_id):
        """Partial answer: sendMessageDraft (Bot API 9.3+); if the API refuses it, one edited message.
        A draft quoting a protected file shows the notice once; the rest of that block is not streamed."""
        b = self.b
        if self.tripped:
            return stream_id
        if b.guard and b.leak(text, self.thread):
            self.tripped, text = True, b.s("leak")
        tail = text[-fmt.LIMIT:]
        if b.draft_ok:
            try:
                b.bot.call("sendMessageDraft", _retries=0, chat_id=self.chat, message_thread_id=self.thread,
                           draft_id=self.draft_id, text=tail, can_stop=True)
                return stream_id
            except TgError as e:
                if e.code == 429:
                    return stream_id
                b.draft_ok = False
                log.warning("sendMessageDraft unavailable (%s); falling back to message edits", e.description)
        if stream_id:
            b.quiet("editMessageText", chat_id=self.chat, message_id=stream_id, text=tail)
            return stream_id
        sent = b.quiet("sendMessage", chat_id=self.chat, message_thread_id=self.thread, text=tail)
        return sent and sent["message_id"]

    def _typing(self, done: threading.Event):
        while not done.is_set():
            self.b.quiet("sendChatAction", chat_id=self.chat, message_thread_id=self.thread, action="typing")
            done.wait(4)

    def rename(self, question, answer):
        b = self.b
        try:
            raw = runner.one_shot(b.claude, TITLE_PROMPT.format(q=question[:1500], a=answer[:1500]), b.env,
                                  str(config.STATE_DIR), b.cfg["title_model"])
        except Exception as e:
            return log.warning("title: %s", e)
        title = re.sub(r"[\"'«»*_`#]", "", (raw.splitlines() or [""])[0]).strip().rstrip(".!")[:60]
        if not title:
            return
        try:
            b.bot.call("editForumTopic", chat_id=self.chat, message_thread_id=self.thread, name=title)
            b.store.update(self.thread, title=title, implicit=False)
            log.info("topic %s renamed: %r", self.thread, title)
        except TgError as e:
            log.warning("editForumTopic: %s", e)


class Status:
    """The run's one in-place status message, rendered by a ticker thread (so elapsed time moves while a
    tool runs silently). friendly: one short phase line; detailed (/verbose): tool calls + thinking.
    Nothing is sent if the answer starts within DELAY; edits are throttled to MIN_EDIT except phase changes."""
    DELAY, MIN_EDIT, TICK, IDLE = 2.0, 3.0, 0.5, 3.0

    def __init__(self, worker, detailed: bool, lang: str, clock=time.monotonic, ticker=True):
        self.w, self.detailed, self.lang, self.clock = worker, detailed, lang, clock
        self.t0 = clock()
        self.phase, self.tools, self.snippet = "think", [], ""
        self.agents = False  # a helper was launched: silence after text = waiting for it
        self.text_done = None  # clock when a text block ended with nothing after it yet
        self.id = self.shown = self.shown_phase = None
        self.at = 0.0
        self.lock, self.done = threading.Lock(), threading.Event()
        if ticker:
            threading.Thread(target=self._loop, daemon=True).start()

    # event side: plain attribute writes, never blocks the stdout reader
    def set(self, phase):
        self.phase, self.text_done = phase, None

    def thinking(self, text):
        # thinking text is often omitted by the model: the indicator alone still beats silence
        self.snippet = " ".join(text.split())[-300:]
        self.phase, self.text_done = "think", None

    def tool(self, ev):
        self.tools.append(ev.text)
        self.text_done = None
        if ev.sub:  # a subagent's tools stay under "bringing in a helper"
            self.phase = "agent"
            return
        self.phase = ui.tool_phase(ev.name)
        self.agents = self.agents or self.phase == "agent"

    def text_end(self):
        self.text_done = self.clock()

    def below(self):
        """A message was posted under the status: drop it so the next tick re-sends it at the bottom."""
        with self.lock:
            if self.id:
                self.w.b.quiet("deleteMessage", chat_id=self.w.chat, message_id=self.id)
            self.id = self.shown = None

    def render(self, now) -> str:
        if self.detailed:
            tools = self.tools
            body = "\n".join(tools[-8:])
            if len(tools) > 8:
                body = f"… {len(tools) - 8}\n" + body
            if self.phase == "think":
                body += ("\n" if body else "") + ui.t(self.lang, "ph.think") + (f"\n{self.snippet}" if self.snippet else "")
            return body
        if self.phase == "write" and self.id is None:
            return ""  # the streamed draft already shows progress
        return ui.status_line(self.lang, self.phase, now - self.t0)

    def tick(self):
        done = self.text_done
        if done is not None and not self.done.is_set() and self.clock() - done >= self.IDLE:
            # text ended, run goes on silently (a long tool input, or background helpers after Agent):
            # post the block as a message and leave "writing" - a final answer ends the run within IDLE
            self.phase, self.text_done = "agent" if self.agents else "think", None
            self.w.post_interim()
        with self.lock:
            now = self.clock()
            if self.done.is_set() or now - self.t0 < self.DELAY:
                return
            phase, body = self.phase, self.render(now)
            if body == self.shown or not (phase != self.shown_phase or now - self.at >= self.MIN_EDIT):
                return
            b, chat = self.w.b, self.w.chat
            raw = body
            if self.detailed and b.guard and b.leak(body, self.w.thread):  # thinking snippets are model text
                body = b.s("leak")
            if not body:
                if self.id:
                    b.quiet("deleteMessage", chat_id=chat, message_id=self.id)
                self.id = None
            elif self.id:
                b.quiet("editMessageText", chat_id=chat, message_id=self.id, text=body)
            else:
                sent = b.quiet("sendMessage", chat_id=chat, message_thread_id=self.w.thread, text=body)
                self.id = sent and sent["message_id"]
            self.shown, self.shown_phase, self.at = raw, phase, now

    def _loop(self):
        while not self.done.wait(self.TICK):
            self.tick()

    def close(self):
        with self.lock:
            self.done.set()
            if self.id:
                self.w.b.quiet("deleteMessage", chat_id=self.w.chat, message_id=self.id)
                self.id = None
