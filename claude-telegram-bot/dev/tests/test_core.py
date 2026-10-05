"""Offline tests: stream-json parser, markdown->HTML, splitter, env scrub, store, config."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src import bridge, config, fmt, runner, service, streamjson, ui  # noqa: E402
from src import botapi  # noqa: E402
from src.botapi import TgError  # noqa: E402
from src.store import Store  # noqa: E402

SID = "8e5b94ae-ad9e-466e-9d4b-070cef431048"


def j(**d):
    return json.dumps(d)


def delta(text, sub=None):
    return j(type="stream_event", parent_tool_use_id=sub,
             event={"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text}})


class StreamJson(unittest.TestCase):
    def feed(self, lines, cwd="/w"):
        p = streamjson.Parser(cwd)
        return [e for line in lines for e in p.feed(line)]

    def test_full_run(self):
        lines = [
            j(type="system", subtype="hook_started", session_id=SID),
            j(type="system", subtype="init", cwd="/w", session_id=SID, tools=["Bash"]),
            j(type="stream_event", event={"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
            delta("Гот"), delta("ово"),
            j(type="assistant", parent_tool_use_id=None, message={"content": [
                {"type": "thinking", "thinking": ""},
                {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q\n  --maxfail=1"}},
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/w/src/app.py"}}]}),
            j(type="assistant", parent_tool_use_id="toolu_1", message={"content": [
                {"type": "tool_use", "name": "Grep", "input": {"pattern": "TODO"}}]}),
            "not json", "",
            j(type="result", subtype="success", is_error=False, num_turns=3, result="Done.", session_id=SID),
        ]
        ev = self.feed(lines)
        self.assertEqual([e.kind for e in ev], ["session", "text", "text", "tool", "tool", "tool", "result"])
        self.assertEqual(ev[0].session_id, SID)
        self.assertEqual(ev[2].text, "Готово")
        self.assertEqual(ev[3].text, "🔧 Bash: pytest -q --maxfail=1")
        self.assertEqual(ev[4].text, "📖 Read: src/app.py")
        self.assertEqual(ev[5].text, "↳ 🔎 Grep: TODO")
        self.assertEqual((ev[6].text, ev[6].is_error, ev[6].num_turns), ("Done.", False, 3))

    def test_permission_denial_is_an_event_and_counted_in_result(self):
        deny = ("Permission for this action was denied by the Claude Code auto mode classifier. Reason: x")
        ev = self.feed([
            j(type="assistant", parent_tool_use_id=None, message={"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "rm -rf /"}}]}),
            j(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": deny}]}),
            j(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "exit code 1"}]}),
            j(type="result", subtype="success", is_error=False, num_turns=2, result="Could not.", session_id=SID,
              permission_denials=[{"tool_name": "Bash", "tool_use_id": "t1"}]),
        ])
        self.assertEqual([(e.kind, e.name) for e in ev], [("tool", "Bash"), ("denied", "Bash"), ("result", "")])
        self.assertEqual(ev[-1].count, 1)

    def test_new_text_block_resets_and_subagent_text_ignored(self):
        start = j(type="stream_event", event={"type": "content_block_start", "content_block": {"type": "text"}})
        ev = self.feed([start, delta("a"), delta("x", sub="toolu_9"), start, delta("b")])
        self.assertEqual([e.text for e in ev], ["a", "b"])

    def test_text_end_carries_full_block_and_skips_other_blocks(self):
        start = lambda t: j(type="stream_event", event={"type": "content_block_start", "content_block": {"type": t}})
        stop = j(type="stream_event", event={"type": "content_block_stop", "index": 1})
        ev = self.feed([start("text"), delta("Гот"), delta("овлю"), stop, start("tool_use"), stop])
        self.assertEqual([(e.kind, e.text) for e in ev], [("text", "Гот"), ("text", "Готовлю"), ("text_end", "Готовлю")])

    def test_bad_resume_result(self):
        ev = self.feed([j(type="result", subtype="error_during_execution", is_error=True, num_turns=0, session_id=SID)])
        self.assertTrue(ev[0].is_error)
        self.assertEqual((ev[0].text, ev[0].num_turns), ("", 0))

    def test_thinking_turn_model_and_api_time(self):
        def se(**ev):
            return j(type="stream_event", parent_tool_use_id=None, event=ev)
        ev = self.feed([
            j(type="system", subtype="init", session_id=SID, model="claude-opus-5-5"),
            se(type="message_start", message={}),
            se(type="content_block_start", index=0, content_block={"type": "thinking", "thinking": ""}),
            se(type="content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": ""}),  # omitted text
            se(type="content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": "Let me "}),
            se(type="content_block_delta", index=0, delta={"type": "thinking_delta", "thinking": "count"}),
            se(type="content_block_delta", index=0, delta={"type": "signature_delta", "signature": "x"}),
            j(type="stream_event", parent_tool_use_id="toolu_1", event={"type": "content_block_start",
                                                                        "content_block": {"type": "thinking"}}),
            j(type="result", is_error=False, num_turns=1, result="17", session_id=SID, duration_api_ms=2500),
        ])
        self.assertEqual([e.kind for e in ev], ["session", "turn", "thinking", "thinking", "thinking", "result"])
        self.assertEqual(ev[0].text, "claude-opus-5-5")
        self.assertEqual(ev[4].text, "Let me count")
        self.assertEqual(ev[5].api_ms, 2500)

    def test_turns_background_tasks_and_replayed_input(self):
        ev = self.feed([
            j(type="system", subtype="init", session_id=SID, model="m"),
            j(type="user", isReplay=True, uuid="u1", parent_tool_use_id=None, message={"content": "hi"}),
            j(type="system", subtype="background_tasks_changed", tasks=[{"task_id": "a", "task_type": "local_agent"}]),
            j(type="system", subtype="task_started", task_id="b", owned_by_subagent=True),  # not top-level: ignored
            j(type="user", parent_tool_use_id=None, message={"content": [{"type": "tool_result"}]}),  # not a replay
            j(type="result", is_error=False, num_turns=1, result="waiting", session_id=SID),
            j(type="system", subtype="init", session_id=SID, model="m"),  # next turn, same process
            j(type="system", subtype="background_tasks_changed", tasks=[]),
            j(type="result", is_error=False, num_turns=1, result="helper finished", session_id=SID),
        ])
        self.assertEqual([(e.kind, e.text if e.kind != "bg" else e.count) for e in ev], [
            ("session", "m"), ("user", "u1"), ("bg", 1), ("result", "waiting"), ("session", "m"), ("bg", 0),
            ("result", "helper finished")])

    def test_tool_line_truncates_and_unknown(self):
        self.assertTrue(streamjson.tool_line("Bash", {"command": "x" * 200}).endswith("…"))
        self.assertEqual(streamjson.tool_line("Mystery", {}), "⚙️ Mystery")
        self.assertEqual(streamjson.tool_line("Read", {"file_path": "/etc/hosts"}, "/w"), "📖 Read: /etc/hosts")


class Html(unittest.TestCase):
    def test_escape_and_inline(self):
        self.assertEqual(fmt.md_to_html("a < b & **c** `x<y>` [t](https://e.x/?a=1&b=2)"),
                         'a &lt; b &amp; <b>c</b> <code>x&lt;y&gt;</code> <a href="https://e.x/?a=1&amp;b=2">t</a>')

    def test_snake_case_is_not_italic(self):
        self.assertEqual(fmt.md_to_html("my_var_name and _it_ and *em*"), "my_var_name and <i>it</i> and <i>em</i>")

    def test_code_fence_is_verbatim(self):
        out = fmt.md_to_html("# Title\n```python\nif a < b and **x**:\n    pass\n```\n- item")
        self.assertEqual(out, '<b>Title</b>\n<pre><code class="language-python">if a &lt; b and **x**:\n    pass'
                              "</code></pre>\n• item")

    def test_table_and_quote(self):
        out = fmt.md_to_html("| a | b |\n|---|---|\n| 1 | 2 |\n> q1\n> q2")
        self.assertEqual(out, "<pre>a  b\n─  ─\n1  2</pre>\n<blockquote>q1\nq2</blockquote>")

    def test_wide_table_becomes_cards(self):
        md = ("| Где | Сейчас | Что не так |\n|---|---|---|\n"
              "| Горчица | 10 г | Это скорее **2 ч. л.** и вообще длинный текст |\n| Масштаб | — | 3 желтка |")
        self.assertEqual(fmt.md_to_html(md),
                         "<b>Горчица</b>\nСейчас: 10 г\nЧто не так: Это скорее <b>2 ч. л.</b> и вообще длинный текст"
                         "\n\n<b>Масштаб</b>\nСейчас: —\nЧто не так: 3 желтка")


class Split(unittest.TestCase):
    def test_short_is_one_chunk(self):
        self.assertEqual(fmt.split_md("hello"), ["hello"])

    def test_chunks_fit_and_cover_text(self):
        md = "\n".join(f"line {i} " + "w" * 50 for i in range(300))
        chunks = fmt.split_md(md, 1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual("\n".join(chunks), md)

    def test_fence_reopened_across_split(self):
        md = "intro\n```py\n" + "\n".join(f"x = {i}" for i in range(400)) + "\n```\nafter"
        chunks = fmt.split_md(md, 500)
        self.assertGreater(len(chunks), 2)
        for c in chunks:
            self.assertLessEqual(len(c), 500)
            self.assertEqual(c.count("```") % 2, 0, c[:80])
        self.assertTrue(chunks[1].startswith("```py\n"))
        for c in chunks:
            self.assertLessEqual(len(fmt.md_to_html(c)), fmt.LIMIT)

    def test_giant_line_is_cut(self):
        chunks = fmt.split_md("y" * 9000, 1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual("".join(chunks), "y" * 9000)


class Env(unittest.TestCase):
    def test_token_and_credentials_never_reach_claude(self):
        tok = "123456:SECRET"
        with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": "/run/credentials/x", "LEAK": f"x{tok}x",
                                          "CLAUDE_TG_TOKEN": "t", "CLAUDECODE": "1", "HOME": "/h", "PATH": "/usr/bin"},
                             clear=True):
            env = runner.child_env(tok, {"HF_TOKEN": "hf"})
        self.assertNotIn(tok, "".join(env.values()))
        for k in ("CREDENTIALS_DIRECTORY", "LEAK", "CLAUDE_TG_TOKEN", "CLAUDECODE"):
            self.assertNotIn(k, env)
        self.assertEqual(env["HF_TOKEN"], "hf")
        self.assertEqual(env["PATH"], "/h/.local/bin:/usr/bin")

    def test_claudeai_connectors_switch(self):
        with mock.patch.dict(os.environ, {"HOME": "/h", "PATH": "/usr/bin"}, clear=True):
            self.assertNotIn("ENABLE_CLAUDEAI_MCP_SERVERS", runner.child_env("t", {}))
            self.assertEqual(runner.child_env("t", {}, connectors=False)["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertIs(config.DEFAULTS["claudeai_connectors"], True)

    def test_argv(self):
        a = runner.build_argv("claude", "sid", ["--model", "opus"])
        self.assertEqual(a[-2:], ["--resume", "sid"])  # the prompt goes on stdin, never into argv
        for flag in ("--dangerously-skip-permissions", "--replay-user-messages", "--input-format"):
            self.assertIn(flag, a)
        self.assertNotIn("--resume", runner.build_argv("claude", None, []))
        a = runner.build_argv("claude", None, ["--model", "opus"], "auto")
        self.assertNotIn("--dangerously-skip-permissions", a)
        self.assertEqual(a[-4:], ["--permission-mode", "auto", "--model", "opus"])
        self.assertIn("--dangerously-skip-permissions", runner.build_argv("claude", None, [], config.DEFAULTS["permission_mode"]))
        line = json.loads(runner.user_line("-привет", "u1"))
        self.assertEqual(line, {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "-привет"}})


class StoreAndConfig(unittest.TestCase):
    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "s.json", "/tmp")
            self.assertEqual(s.topic(5)["cwd"], "/tmp")
            s.update(5, session_id="abc", implicit=True)
            s.set_owner(42)
            s2 = Store(Path(d) / "s.json", "/tmp")
            self.assertEqual((s2.owner_id, s2.topic(5)["session_id"], s2.topic(5)["implicit"]), (42, "abc", True))

    def test_store_drop_blocks_late_writes(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "s.json", "/tmp")
            s.update(7, session_id="abc")
            s.update(8, session_id="keep")
            s.drop(7)
            s.update(7, session_id="late")  # a finishing run must not resurrect a deleted topic
            s2 = Store(Path(d) / "s.json", "/tmp")
            self.assertEqual(list(s2.data["topics"]), ["8"])
            self.assertIsNone(s2.topic(7)["session_id"])

    def test_env_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# c\nexport A=1\nB='two words'\nnoeq\n")
        try:
            self.assertEqual(config.read_env_file(f.name), {"A": "1", "B": "two words"})
        finally:
            os.unlink(f.name)


class FakeBot:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def call(self, method, _timeout=35, _retries=3, **p):
        self.calls.append((method, p))
        if method in self.fail:
            raise TgError(method, 400, self.fail[method])
        return {"message_id": 1}


class TopicCommands(unittest.TestCase):
    def bridge(self, d, fail=None):
        with mock.patch.object(config, "STATE_DIR", Path(d)):
            b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1), "tok")
        b.bot = FakeBot(fail)
        b.store.update(50, session_id="s50", implicit=True)
        (Path(d) / "files" / "50").mkdir(parents=True)
        return b

    def cmd(self, b, text, thread=50):
        b.handle({"message": {"message_id": 9, "chat": {"id": 1, "type": "private"}, "from": {"id": 1},
                              "message_thread_id": thread, "text": text, "date": 0}})

    def test_rename_pins_title(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            self.cmd(b, "/rename  My topic ")
            self.assertEqual(b.bot.calls[-1], ("editForumTopic", {"chat_id": 1, "message_thread_id": 50, "name": "My topic"}))
            self.assertEqual((b.store.topic(50)["title"], b.store.topic(50)["implicit"]), ("My topic", False))

    def test_delete_drops_mapping_and_files(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            self.cmd(b, "/delete")
            self.assertEqual(b.bot.calls[-1][0], "deleteForumTopic")
            self.assertNotIn("50", b.store.data["topics"])
            self.assertFalse((Path(d) / "files" / "50").exists())

    def test_topic_deleted_in_client_is_forgotten_on_send(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d, fail={"sendMessage": "Bad Request: message thread not found"})
            with self.assertRaises(TgError):
                b.say(1, 50, "hi")
            self.assertNotIn("50", b.store.data["topics"])
            b.store.update(50, session_id="late")
            self.assertNotIn("50", b.store.data["topics"])

    def test_command_in_all_messages_never_keeps_a_topic(self):
        # the client wraps a message typed in All messages into a new implicit topic
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.handle({"message": {"message_id": 61, "chat": {"id": 1, "type": "private"}, "from": {"id": 1},
                                  "message_thread_id": 60, "text": "/help", "date": 0,
                                  "reply_to_message": {"message_id": 60, "forum_topic_created":
                                                       {"name": "/help", "is_name_implicit": True}}}})
            self.assertEqual(b.bot.calls[0], ("deleteForumTopic", {"chat_id": 1, "message_thread_id": 60}))
            self.assertEqual(b.bot.calls[-1][1]["message_thread_id"], None)  # help answered in All messages
            self.assertNotIn("60", b.store.data["topics"])


class FriendlyUi(unittest.TestCase):
    def test_string_tables_have_same_keys_and_placeholders(self):
        import string
        for k, v in ui.S["en"].items():
            ru = ui.S["ru"][k]
            fields = lambda x: sorted(f for _, f, _, _ in string.Formatter().parse(x) if f)  # noqa: E731
            self.assertEqual(fields(v), fields(ru), k)
        self.assertEqual(set(ui.S["en"]), set(ui.S["ru"]))
        for c in bridge.COMMANDS:
            self.assertIn("cmd." + c, ui.S["en"])

    def test_tool_to_phrase(self):
        cases = {"Read": "📖 Изучаю файлы…", "Grep": "🔎 Ищу…", "Glob": "🔎 Ищу…", "Bash": "⚙️ Работаю…",
                 "Edit": "✏️ Вношу правки…", "Write": "✏️ Вношу правки…", "WebFetch": "🌐 Ищу в интернете…",
                 "Task": "👥 Подключаю помощника…", "TodoWrite": "📝 Составляю план…",
                 "mcp__gmail__search": "⚙️ Работаю…", "": "⚙️ Работаю…"}
        for name, want in cases.items():
            self.assertEqual(ui.status_line("ru", ui.tool_phase(name), 1), want, name)
        self.assertEqual(ui.status_line("en", "think", 0), "🧠 Thinking…")

    def test_elapsed_and_lang_fallback(self):
        self.assertEqual(ui.status_line("ru", "work", 9.9), "⚙️ Работаю…")
        self.assertEqual(ui.status_line("ru", "work", 17), "⚙️ Работаю… · 15 с")
        self.assertEqual(ui.status_line("en", "work", 83), "⚙️ Working… · 1 min 20 s")
        self.assertEqual(ui.lang({"ui_lang": "de"}), "en")
        self.assertEqual(ui.reason("\nAPI Error: 529 overloaded\ntrace…"), "API Error: 529 overloaded")

    def status(self, detailed=False):
        clock = [0.0]
        w = mock.Mock(chat=1, thread=50)
        w.b.guard = None
        w.b.quiet.side_effect = lambda m, **p: {"message_id": 77} if m == "sendMessage" else None
        st = bridge.Status(w, detailed, "ru", clock=lambda: clock[0], ticker=False)
        return st, clock, w.b.quiet.call_args_list

    def test_status_stop_button_and_callback(self):
        st, clock, calls = self.status()
        st.tool(streamjson.Event("tool", "🔧 Bash: ls", name="Bash"))
        clock[0] = 3.0
        st.tick()
        kb = calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual((kb["text"], kb["callback_data"]), ("⏹ Стоп", "stop"))
        b = bridge.Bridge.__new__(bridge.Bridge)
        b.owner, b.lang, b.quiet = 5, "ru", mock.Mock()
        st.w.st, st.w.run = st, object()
        b.workers = {50: st.w}
        b.button({"id": "q", "from": {"id": 6}, "data": "stop", "message": {"message_id": 77}})
        st.w.stop.assert_not_called()  # not the owner
        b.button({"id": "q", "from": {"id": 5}, "data": "stop", "message": {"message_id": 77}})
        st.w.stop.assert_called_once_with(drop_queue=False)
        self.assertEqual(b.quiet.call_args[1]["text"], "⏹ Остановлено.")

    def test_status_no_flash_single_line_and_cleanup(self):
        st, clock, calls = self.status()
        st.set("write")
        clock[0] = 1.0
        st.tick()
        self.assertEqual(calls, [])  # answer started fast: no status at all
        clock[0] = 3.0
        st.tick()
        self.assertEqual(calls, [])  # still streaming the draft: nothing to show
        st.tool(streamjson.Event("tool", "🔧 Bash: rm -rf /tmp/x", name="Bash"))
        st.tick()
        self.assertEqual(calls[-1][0][0], "sendMessage")
        self.assertEqual(calls[-1][1]["text"], "⚙️ Работаю…")  # no command, no tool name
        st.tool(streamjson.Event("tool", "↳ 📖 Read: /etc/x", name="Read", sub=True))
        st.set("write")
        clock[0] = 3.5
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "✍️ Пишу ответ…")  # visible status is edited, not deleted
        clock[0] = 12.0
        st.set("work")
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "⚙️ Работаю… · 10 с")
        n = len(calls)
        clock[0] = 12.5
        st.tick()
        self.assertEqual(len(calls), n)  # unchanged text: no edit
        st.close()
        self.assertEqual(calls[-1][0], ("deleteMessage",))
        st.tick()
        self.assertEqual(calls[-1][0], ("deleteMessage",))

    def test_writing_does_not_hang_after_text_ends(self):
        st, clock, calls = self.status()
        st.tool(streamjson.Event("tool", "👥 Agent: code", name="Agent"))
        clock[0] = 3.0
        st.tick()
        st.set("write")
        st.text_end()
        clock[0] = 4.0
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "✍️ Пишу ответ…")  # a final answer ends the run within IDLE
        clock[0] = 6.5
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "👥 Подключаю помощника…")  # silence after Agent = waiting for it
        st.w.post_interim.assert_called_once()  # the ended block becomes a real message
        st2, clock2, calls2 = self.status()
        st2.set("write")
        st2.text_end()
        clock2[0] = 2.5
        st2.tick()
        self.assertEqual(calls2, [])  # the final answer usually ends the run here: no status over the draft
        st2.w.post_interim.assert_not_called()

    def test_interim_text_is_posted_once_and_status_moves_below(self):
        w = object.__new__(bridge.Worker)
        w.b, w.chat, w.thread = mock.Mock(guard=None), 1, 50
        w.noticed = w.tripped = False
        w.ilock, w.interim, w.posted, w.stream_id = threading.Lock(), "Отдаю тиммейту.", "", 88
        w.st = mock.Mock()
        w.post_interim()
        w.post_interim()  # nothing pending: no second post
        w.b.send_answer.assert_called_once_with(1, 50, "Отдаю тиммейту.")
        w.b.quiet.assert_called_once_with("deleteMessage", chat_id=1, message_id=88)  # edit-mode draft replaced
        self.assertEqual((w.posted, w.stream_id), ("Отдаю тиммейту.", None))
        w.st.below.assert_called()

    def test_detailed_lists_tool_calls(self):
        st, clock, calls = self.status(detailed=True)
        st.tool(streamjson.Event("tool", "🔧 Bash: pytest", name="Bash"))
        clock[0] = 2.5
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "🔧 Bash: pytest")


class Verbose(TopicCommands):
    def test_verbose_toggle_and_friendly_error(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            self.assertFalse(b.detailed(50))
            self.cmd(b, "/verbose")
            self.assertTrue(b.detailed(50))
            b.fail(1, 50, "boom.", "claude error: Traceback …")
            self.assertIn("Traceback", b.bot.calls[-1][1]["text"])
            self.cmd(b, "/verbose off")
            self.assertFalse(b.detailed(50))
            b.fail(1, 50, "boom.", "claude error: Traceback …")
            self.assertEqual(b.bot.calls[-1][1]["text"], "😕 Something went wrong: boom.")


class Reactions(TopicCommands):
    def test_reactions_off_sends_none_but_stop_button_gets_text(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.react(1, 9, "👀")
            self.assertEqual(b.bot.calls[-1][0], "setMessageReaction")
            b.cfg["reactions"], b.bot.calls = False, []
            for e in ("👀", "💔", None):
                b.react(1, 9, e)
            self.assertEqual(b.bot.calls, [])
            w = mock.Mock(draft_id=5, chat=1, thread=50)
            b.workers[50] = w
            b.handle({"stopped_message_generation": {"draft_id": 5}})
            w.stop.assert_called_once_with(drop_queue=False)
            self.assertEqual([(m, p["text"]) for m, p in b.bot.calls], [("sendMessage", b.s("stopped"))])


class Burst(TopicCommands):
    def send(self, b, mid, thread=None, **kw):
        m = {"message_id": mid, "chat": {"id": 1, "type": "private"}, "from": {"id": 1}, "date": 0, **kw}
        if thread:
            m["message_thread_id"] = thread
        b.handle({"message": m})

    def run_burst(self, d, thread):
        b, put = self.bridge(d), []
        b.worker = lambda chat, th: mock.Mock(put=lambda msgs: put.append((th, [m["message_id"] for m in msgs])))
        b.created, call = [], b.bot.call
        b.bot.call = lambda method, **p: (b.created.append(p["name"]) or {"message_thread_id": 77}
                                          if method == "createForumTopic" else call(method, **p))
        with mock.patch.object(bridge, "BURST", 0.2), mock.patch.object(bridge, "FORWARD", 0.3):
            self.send(b, 1, thread, text="What is on the photo?")
            __import__("time").sleep(0.1)
            self.send(b, 2, thread, photo=[{"file_id": "x"}], forward_origin={"type": "user"})
            self.send(b, 3, thread, photo=[{"file_id": "y"}], forward_origin={"type": "user"})
            __import__("time").sleep(0.5)
        return b, put

    def test_forward_with_comment_is_one_run(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            _, put = self.run_burst(d, 50)
            self.assertEqual(put, [(50, [1, 2, 3])])

    def test_burst_in_all_messages_makes_one_topic(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b, put = self.run_burst(d, None)
            self.assertEqual(put, [(77, [1, 2, 3])])
            self.assertEqual(b.created, ["What is on the photo?"])  # one topic, named from the comment

    def test_late_forwarded_photo_joins_the_forwarded_text(self):
        # seen live: forwarded text, then its forwarded photo 5 s later -> was two runs
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b, put = self.bridge(d), []
            b.worker = lambda chat, th: mock.Mock(put=lambda msgs: put.append([m["message_id"] for m in msgs]))
            with mock.patch.object(bridge, "BURST", 0.1), mock.patch.object(bridge, "FORWARD", 0.5):
                self.send(b, 1, 50, text="look", forward_origin={"type": "user"})
                __import__("time").sleep(0.3)  # > BURST, < FORWARD
                self.send(b, 2, 50, photo=[{"file_id": "x"}], forward_origin={"type": "user"})
                __import__("time").sleep(0.8)
            self.assertEqual(put, [[1, 2]])


class RestartSafety(unittest.TestCase):
    def test_pending_survives_and_is_restored(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            s = Store(Path(d) / "state.json", "/tmp")
            now = __import__("time").time()
            s.pend(11, thread=5, chat=1, msgs=[{"message_id": 11, "date": now, "text": "a"}], started=True)
            s.pend(12, thread=5, chat=1, msgs=[{"message_id": 12, "date": now, "text": "b"}], started=False)
            s.pend(9, thread=6, chat=1, msgs=[{"message_id": 9, "date": now - 7200, "text": "old"}], started=True)
            b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1), "tok")
            b.bot, put = FakeBot(), []
            b.worker = lambda chat, thread: mock.Mock(put=lambda msgs: put.append((thread, msgs)))
            b.restore()
            self.assertEqual([(t, m[-1]["message_id"], bool(m[-1].get("_restarted"))) for t, m in put],
                             [(5, 11, True), (5, 12, False)])
            self.assertNotIn("9", b.store.pending())  # too old: user told to resend
            texts = [p.get("text", "") for m, p in b.bot.calls if m == "sendMessage"]
            self.assertTrue(any("resend" in t for t in texts) and any("restarted mid-run" in t for t in texts))

    def test_drop_clears_pending_of_topic(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "s.json", "/tmp")
            s.pend(1, thread=5, chat=1, msgs=[], started=False)
            s.pend(2, thread=6, chat=1, msgs=[], started=False)
            s.drop(5)
            self.assertEqual(list(Store(Path(d) / "s.json", "/tmp").pending()), ["2"])


class FakeRun:
    """Scripted claude process: the test feeds events, sees stdin lines."""
    runs = []

    def __init__(self, argv, cwd, env):
        import queue
        self.argv, self.ev, self.lines = argv, queue.Queue(), []
        self.open, self.stopped, self.stderr = True, False, []
        FakeRun.runs.append(self)

    def send(self, text):
        if not self.open:
            return None
        self.lines.append(text)
        return f"u{len(self.lines)}"

    def close_input(self):
        if self.open:
            self.open = False
            self.ev.put(None) if self.exit_on_close else None

    exit_on_close = False

    def stop(self):
        self.stopped, self.open = True, False
        self.ev.put(None)

    def events(self):
        while True:
            e = self.ev.get()
            if e is None:
                return
            yield e


def until(cond, timeout=3.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError("condition not reached")


class Inject(TopicCommands):
    E = streamjson.Event

    def msg(self, mid, text):
        return [{"message_id": mid, "chat": {"id": 1, "type": "private"}, "date": 0, "text": text}]

    def answers(self, b):
        return [p["text"] for m, p in b.bot.calls if m == "sendMessage" and p.get("parse_mode")]

    def reacts(self, b, mid):
        return [p["reaction"][0]["emoji"] if p["reaction"] else None
                for m, p in b.bot.calls if m == "setMessageReaction" and p["message_id"] == mid]

    def test_message_goes_into_the_running_process_while_a_helper_runs(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            b = self.bridge(d)
            w = b.worker(1, 50)
            w.put(self.msg(1, "launch a helper"))
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]
            self.assertEqual(r.lines, ["launch a helper"])
            for e in (self.E("session", "m", "s50"), self.E("user", "u1"), self.E("bg", count=1),
                      self.E("result", "waiting", "s50", num_turns=1)):
                r.ev.put(e)
            until(lambda: "👍" in self.reacts(b, 1))
            self.assertTrue(r.open)  # a helper still runs: stdin stays open
            self.assertNotIn("1", b.store.pending())
            w.put(self.msg(2, "what is taking so long?"))  # goes in at once, not queued
            until(lambda: len(r.lines) == 2)
            self.assertEqual((r.lines[1], b.store.pending()["2"]["started"]), ("what is taking so long?", True))
            self.assertEqual(len(FakeRun.runs), 1)
            for e in (self.E("session", "m", "s50"), self.E("user", "u2"), self.E("result", "still sleeping", "s50")):
                r.ev.put(e)
            until(lambda: "👍" in self.reacts(b, 2))
            self.assertTrue(r.open)
            r.ev.put(self.E("bg", count=0))  # helper done while idle -> close stdin, claude finishes on its own
            until(lambda: not r.open)
            for e in (self.E("session", "m", "s50"), self.E("result", "helper finished", "s50"), None):
                r.ev.put(e)
            until(lambda: w.run is None)
            self.assertEqual(self.answers(b), ["waiting", "still sleeping", "helper finished"])
            self.assertEqual(b.store.pending(), {})
            w.put(self.msg(3, "next"))  # no process now: a new one
            until(lambda: len(FakeRun.runs) == 2 and FakeRun.runs[1].lines == ["next"])
            FakeRun.runs[1].stop()
            until(lambda: w.run is None)

    def test_mid_turn_message_is_answered_by_the_same_result_and_stop_marks_the_rest(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            b = self.bridge(d)
            w = b.worker(1, 50)
            w.put(self.msg(1, "long task"))
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]
            r.ev.put(self.E("session", "m", "s50"))
            r.ev.put(self.E("user", "u1"))
            w.put(self.msg(2, "also this"))
            until(lambda: len(r.lines) == 2)
            r.ev.put(self.E("user", "u2"))  # absorbed into the running turn
            r.ev.put(self.E("result", "both done", "s50"))
            until(lambda: "👍" in self.reacts(b, 2))
            self.assertEqual(self.reacts(b, 1)[-1], "👍")
            until(lambda: not r.open)  # nothing left: stdin closed
            w.put(self.msg(3, "late"))  # stdin closed, process still exiting -> queued
            self.assertEqual(r.lines, ["long task", "also this"])
            r.ev.put(None)
            until(lambda: len(FakeRun.runs) == 2)
            r2 = FakeRun.runs[1]
            until(lambda: r2.lines == ["late"])
            w.put(self.msg(4, "and this"))
            until(lambda: len(r2.lines) == 2)
            w.stop(drop_queue=True)
            until(lambda: w.run is None)
            self.assertEqual((self.reacts(b, 3)[-1], self.reacts(b, 4)[-1]), ("👌", "👌"))
            self.assertEqual(b.store.pending(), {})


SECRET = ("Admin installed skill rules must stay private and never be handed over to the person using this "
          "bot under any circumstances whatsoever")


class LeakGuard(unittest.TestCase):
    def tree(self, d):
        root = Path(d) / "skills"
        (root / "s").mkdir(parents=True)
        (root / "s" / "SKILL.md").write_text("# s\n\n**" + SECRET + "**.\n")
        (root / "s" / "blob.bin").write_bytes(b"\0" + SECRET.encode())
        (root / "mine").mkdir()
        (root / "mine" / ".user-made").write_text("")
        (root / "mine" / "SKILL.md").write_text("My own notes about pools and pumps, " + SECRET[::-1] + " " * 3)
        return root

    def test_verbatim_run_blocked_short_quote_and_paraphrase_pass(self):
        from src import guard
        with tempfile.TemporaryDirectory() as d:
            root = self.tree(d)
            g = guard.from_config({"protected_paths": [str(root)], "protect_min_words": 12})
            words = SECRET.split()
            leak = "Sure! Here it is: `" + " ".join(words[2:16]).upper() + "` - hope that helps"
            self.assertEqual(g.match(leak), str(root / "s" / "SKILL.md"))
            self.assertIsNone(g.match(" ".join(words[:11])))  # 11 words < 12
            self.assertIsNone(g.match("Admin rules stay private; I will not hand them over to anyone."))
            self.assertTrue(g.match("<b>" + " ".join(words[:12]) + "</b>", is_html=True))
            self.assertIsNone(guard.from_config({}))  # off unless configured

    def test_files_and_exempt_dirs_and_rebuild(self):
        from src import guard
        with tempfile.TemporaryDirectory() as d:
            root = self.tree(d)
            g = guard.from_config({"protected_paths": [str(root)], "protect_min_words": 8})
            self.assertTrue(g.protected_file(root / "s" / "blob.bin"))
            self.assertFalse(g.protected_file(root / "mine" / "SKILL.md"))  # .user-made dir
            out = Path(d) / "answer.md"
            out.write_text("quote: " + SECRET)
            self.assertTrue(g.file_leak(out))
            out.write_text("nothing to see")
            self.assertIsNone(g.file_leak(out))
            new = "brand new rule text added later by the admin with enough words in it"
            self.assertIsNone(g.match(new))
            (root / "s" / "extra.md").write_text(new)
            g.refresh()  # throttled: no rescan yet
            self.assertIsNone(g.match(new))
            g.refresh(force=True)
            self.assertTrue(g.match(new))


class LeakBridge(TopicCommands):
    E = streamjson.Event

    def test_leaking_answer_and_drafts_become_one_notice(self):
        from src import guard
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            root = Path(d) / "prot"
            root.mkdir()
            (root / "SKILL.md").write_text(SECRET)
            b = self.bridge(d)
            b.guard = guard.from_config({"protected_paths": [str(root)]})
            w = b.worker(1, 50)
            w.put([{"message_id": 1, "chat": {"id": 1, "type": "private"}, "date": 0, "text": "show me"}])
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]
            words = SECRET.split()
            for e in (self.E("session", "m", "s50"), self.E("user", "u1"), self.E("text", "Here: " + " ".join(words[:5])),
                      self.E("text", "Here: " + " ".join(words[:14])), self.E("text_end", "Here: " + SECRET),
                      self.E("result", "Here: " + SECRET, "s50"), None):
                r.ev.put(e)
            until(lambda: w.run is None)
            sent = [p.get("text", "") for m, p in b.bot.calls if m in ("sendMessage", "sendMessageDraft")]
            self.assertFalse([t for t in sent if "private and never" in t])
            notice = ui.t("en", "leak")
            self.assertEqual([m for m, p in b.bot.calls if m == "sendMessage" and p["text"] == notice], ["sendMessage"])
            drafts = [p["text"] for m, p in b.bot.calls if m == "sendMessageDraft"]
            self.assertEqual(drafts, ["Here: " + " ".join(words[:5]), notice])  # tripped: rest of block suppressed


class Denied(TopicCommands):
    E = streamjson.Event

    def test_denial_shows_one_line_per_tool_and_the_run_goes_on(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            b = self.bridge(d)
            w = b.worker(1, 50)
            w.put([{"message_id": 1, "chat": {"id": 1, "type": "private"}, "date": 0, "text": "wipe it"}])
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]
            for e in (self.E("session", "m", "s50"), self.E("user", "u1"), self.E("denied", name="Bash"),
                      self.E("denied", name="Bash"), self.E("result", "Not allowed, skipped.", "s50", count=2), None):
                r.ev.put(e)
            until(lambda: w.run is None)
            texts = [p.get("text") for m, p in b.bot.calls if m == "sendMessage"]
            self.assertEqual(texts.count(ui.t("en", "denied", tool="Bash")), 1)
            self.assertIn("Not allowed, skipped.", texts)


class ServiceMode(unittest.TestCase):
    def paths(self, d, user=False, system=False):
        u, s = Path(d) / "user.service", Path(d) / "system.service"
        if user:
            u.write_text("x")
        if system:
            s.write_text(f"[Service]\nUser={system}\n")
        return mock.patch.multiple(service, USER_UNIT_PATH=u, UNIT_PATH=s)

    def test_user_unit_text(self):
        cfg = dict(config.DEFAULTS, token_file="/home/u/100%/token")
        t = service.unit_text(cfg, "user")
        self.assertIn("LoadCredential=token:/home/u/100%%/token", t)  # % escaped for systemd
        self.assertIn("WantedBy=default.target", t)
        self.assertNotIn("User=", t)
        self.assertNotIn(str(config.SYSTEM_TOKEN), t)
        self.assertIn(f"LoadCredential=token:{config.SYSTEM_TOKEN}", service.unit_text(cfg))

    def test_mode_detection(self):
        with tempfile.TemporaryDirectory() as d:
            with self.paths(d):
                self.assertIsNone(service.installed_mode())
                with mock.patch.object(service, "can_sudo", return_value=True):
                    self.assertEqual(service.pick_mode(), "system")
                with mock.patch.object(service, "can_sudo", return_value=False):
                    self.assertEqual(service.pick_mode(), "user")
                    self.assertEqual(service.pick_mode("system"), "system")
            with self.paths(d, user=True), mock.patch.object(service, "can_sudo", return_value=True):
                self.assertEqual(service.installed_mode(), "user")
                self.assertEqual(service.pick_mode(), "user")  # reinstall keeps the existing mode
                with self.assertRaises(service.Fail):
                    service.pick_mode("system")  # never two pollers on one token
        me = __import__("getpass").getuser()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(service, "can_sudo", return_value=False):
            with self.paths(d, system=me):
                self.assertEqual(service.installed_mode(), "system")
            with self.paths(d, system="someone-else"):  # another user's system bot on the same host
                self.assertIsNone(service.installed_mode())
                self.assertEqual(service.pick_mode(), "user")


class FastConnect(unittest.TestCase):
    def test_blackholed_address_falls_through_fast_and_family_sticks(self):
        tried = []

        class Sock:
            def __init__(self, fam, *a):
                self.fam = fam

            def settimeout(self, t):
                tried.append(("timeout", self.fam, t))

            def connect(self, addr):
                tried.append(("connect", self.fam))
                if self.fam == 10:
                    raise TimeoutError()

            def close(self):
                pass

        infos = [(10, 1, 6, "", ("::1", 443)), (2, 1, 6, "", ("1.2.3.4", 443))]
        with mock.patch.object(botapi.socket, "getaddrinfo", return_value=infos), \
                mock.patch.object(botapi.socket, "socket", Sock), mock.patch.object(botapi._Net, "family", None):
            self.assertEqual(botapi.fast_connect(("h", 443), 65).fam, 2)
            self.assertIn(("timeout", 10, botapi.CONNECT_TIMEOUT), tried)  # not the 65 s read timeout
            tried.clear()
            botapi.fast_connect(("h", 443), 65)
            self.assertEqual([t for t in tried if t[0] == "connect"], [("connect", 2)])  # IPv4 first now


if __name__ == "__main__":
    unittest.main()


class Notify(unittest.TestCase):
    from src import notify as n

    def run_send(self, d, bot, **kw):
        with mock.patch.object(config, "STATE_DIR", Path(d)):
            return self.n.send(bot, dict(config.DEFAULTS, owner_id=7), **kw)

    def test_creates_topic_once_and_reuses_it(self):
        class Bot(FakeBot):
            def call(self, method, _timeout=35, _retries=3, **p):
                super().call(method, **p)
                return {"message_thread_id": 300} if method == "createForumTopic" else {"message_id": 5}
        with tempfile.TemporaryDirectory() as d:
            bot = Bot()
            r = self.run_send(d, bot, text="hi", silent=True)
            self.run_send(d, bot, text="again")
            self.assertEqual([c[0] for c in bot.calls], ["createForumTopic", "sendMessage", "sendMessage"])
            self.assertEqual(bot.calls[1][1]["message_thread_id"], 300)
            self.assertTrue(bot.calls[1][1]["disable_notification"])
            self.assertEqual(r, {"chat": 7, "thread": 300, "message_ids": [5]})
            self.assertEqual(json.loads((Path(d) / "notify.json").read_text()),
                             {"topics": {"Notifications": 300}, "meta": {"Notifications": {"name": "Notifications",
                                                                                           "icon": None}}})

    def test_deleted_topic_is_recreated(self):
        class Bot(FakeBot):
            n = 0

            def call(self, method, _timeout=35, _retries=3, **p):
                self.calls.append((method, p))
                if method == "createForumTopic":
                    return {"message_thread_id": 301}
                if p.get("message_thread_id") == 300:
                    raise TgError(method, 400, "Bad Request: message thread not found")
                return {"message_id": 6}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "notify.json").write_text('{"topics": {"Notifications": 300}}')
            r = self.run_send(d, Bot(), text="x")
            self.assertEqual(r["thread"], 301)

    def test_registry_key_creates_named_topic_with_icon(self):
        class Bot(FakeBot):
            def call(self, method, _timeout=35, _retries=3, **p):
                super().call(method, **p)
                if method == "getForumTopicIconStickers":
                    return [{"emoji": "\U0001f4ac", "custom_emoji_id": "111"}, {"emoji": "\u2b50\ufe0f", "custom_emoji_id": "222"}]
                return {"message_thread_id": 400} if method == "createForumTopic" else {"message_id": 5}
        cfg = dict(config.DEFAULTS, owner_id=7, notify_topics={"mail": {"name": "Mail box", "icon": "\u2b50"},
                                                                 "plain": "Plain name"})
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            bot = Bot()
            self.n.send(bot, cfg, "x", topic="mail")
            self.assertEqual(bot.calls[1], ("createForumTopic", {"chat_id": 7, "name": "Mail box",
                                                                 "icon_custom_emoji_id": "222"}))
            self.n.send(bot, cfg, "x", topic="plain")
            self.assertEqual(bot.calls[3], ("createForumTopic", {"chat_id": 7, "name": "Plain name"}))
            self.n.send(bot, cfg, "x", topic="Literal")
            self.assertEqual(bot.calls[5], ("createForumTopic", {"chat_id": 7, "name": "Literal"}))
            self.assertEqual(sorted(json.loads((Path(d) / "notify.json").read_text())["topics"]),
                             ["Literal", "mail", "plain"])

    def test_renamed_registry_entry_edits_cached_topic(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            (Path(d) / "notify.json").write_text('{"topics": {"Notifications": 300}}')  # pre-registry cache
            cfg = dict(config.DEFAULTS, owner_id=7, notify_topics={"Notifications": "Other", "x": "X"})
            bot = FakeBot()
            r = self.n.send(bot, cfg, "a")
            self.n.send(bot, cfg, "b")
            self.assertEqual([c[0] for c in bot.calls], ["editForumTopic", "sendMessage", "sendMessage"])
            self.assertEqual(bot.calls[0][1], {"chat_id": 7, "message_thread_id": 300, "name": "Other"})
            self.assertEqual(r["thread"], 300)
            bot = FakeBot(fail={"editForumTopic": "Bad Request: TOPIC_NOT_MODIFIED"})
            cfg["notify_topics"]["Notifications"] = "Third"
            self.assertEqual(self.n.send(bot, cfg, "c")["thread"], 300)  # rename failure never blocks the send

    def test_main_chat_and_owner_from_state(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text('{"owner_id": 42}')
            bot = FakeBot()
            with mock.patch.object(config, "STATE_DIR", Path(d)):
                self.n.send(bot, dict(config.DEFAULTS), "<b>x</b>", mode="html", topic=None)
            self.assertEqual(bot.calls, [("sendMessage", {"chat_id": 42, "text": "<b>x</b>", "parse_mode": "HTML",
                                          "disable_notification": None, "message_thread_id": None,
                                          "link_preview_options": {"is_disabled": True}})])

    def test_buttons_go_on_the_last_chunk(self):
        with tempfile.TemporaryDirectory() as d:
            bot = FakeBot()
            self.run_send(d, bot, text="x" * 5000, topic=None, buttons=["Open = https://a.b/c?x=1"])
            self.assertNotIn("reply_markup", bot.calls[0][1])
            self.assertEqual(bot.calls[1][1]["reply_markup"],
                             {"inline_keyboard": [[{"text": "Open", "url": "https://a.b/c?x=1"}]]})
        with self.assertRaises(self.n.NotifyError):
            self.n.keyboard(["no url"])

    def test_markdown_and_long_plain_are_chunked(self):
        self.assertEqual(self.n.chunks("**a**", "md"), [("<b>a</b>", "HTML")])
        self.assertEqual(len(self.n.chunks("x" * 5000, "plain")), 2)
        with self.assertRaises(self.n.NotifyError):
            self.n.chunks("x" * 5000, "html")

    def parse(self, *argv, env=None):
        from src import main as m
        with mock.patch.object(self.n, "main", lambda cfg, a: setattr(self, "args", a) or 0):
            m.main(["notify", *argv])
        return self.n.target(self.args, env or {})

    def test_target_resolution(self):
        run = {config.RUN_TOPIC_ENV: "555"}
        self.assertEqual(self.parse("x"), ("Notifications", None))
        self.assertEqual(self.parse("x", env=run), (None, 555))  # inside a bot run: its own topic
        self.assertEqual(self.parse("--topic", "mail", "x", env=run), ("mail", None))
        self.assertEqual(self.parse("--main-chat", "x", env=run), (None, None))
        self.assertEqual(self.parse("--thread", "77", "--file", "a.mp4", "--file", "b.png", env=run), (None, 77))
        self.assertEqual(self.args.file, ["a.mp4", "b.png"])
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.parse("--thread", "1", "--topic", "k")

    class UpBot(FakeBot):
        def __init__(self, fail=None):
            super().__init__(fail)
            self.uploads = []

        def upload(self, method, field, path, _timeout=120, **p):
            self.uploads.append((method, field, path.name, p))
            if method in self.fail:
                raise TgError(method, 400, self.fail[method])
            return {"message_id": len(self.uploads) + 10}

    def test_files_by_type_caption_and_fallback(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            for n in ("v.MP4", "p.png", "r.html"):
                (Path(d) / n).write_bytes(b"x")
            cfg = dict(config.DEFAULTS, owner_id=7)
            bot = self.UpBot(fail={"sendPhoto": "Bad Request: IMAGE_PROCESS_FAILED"})
            r = self.n.send_files(bot, cfg, [f"{d}/v.MP4", f"{d}/p.png", f"{d}/r.html"], "**done**", "md", thread=9)
            self.assertEqual([u[:2] for u in bot.uploads], [("sendVideo", "video"), ("sendPhoto", "photo"),
                                                            ("sendDocument", "document"), ("sendDocument", "document")])
            v = bot.uploads[0][3]
            self.assertEqual((v["supports_streaming"], v["caption"], v["parse_mode"], v["message_thread_id"]),
                             (True, "<b>done</b>", "HTML", 9))
            self.assertNotIn("caption", bot.uploads[3][3])
            self.assertEqual(bot.calls, [])  # short text = caption, no message
            self.assertEqual(r["message_ids"], [11, 13, 14])
            bot = self.UpBot()
            self.n.send_files(bot, cfg, [f"{d}/r.html"], "y" * 2000, topic=None)
            self.assertEqual([c[0] for c in bot.calls], ["sendMessage"])  # long text goes before the file
            self.assertNotIn("caption", bot.uploads[0][3])

    def test_file_limits_and_leak_guard(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            big = Path(d) / "big.mp4"
            with open(big, "wb") as f:
                f.truncate(self.n.MAX_FILE + 1)
            bot = self.UpBot()
            cfg = dict(config.DEFAULTS, owner_id=7)
            with self.assertRaisesRegex(self.n.NotifyError, "50 MB"):
                self.n.send_files(bot, cfg, [str(big)], topic=None)
            with self.assertRaisesRegex(self.n.NotifyError, "no such file"):
                self.n.send_files(bot, cfg, [f"{d}/missing"], topic=None)
            self.assertEqual((bot.calls, bot.uploads), ([], []))
            (Path(d) / "s.txt").write_text("secret")
            g = mock.Mock(file_leak=lambda p: "/protected/x" if p.name == "s.txt" else None)
            with mock.patch("sys.stderr"):
                r = self.n.send_files(bot, cfg, [f"{d}/s.txt"], topic=None, guard=g)
            self.assertEqual((bot.uploads, r["blocked"]), ([], [f"{d}/s.txt"]))
            self.assertEqual(bot.calls[0][1]["text"], ui.t("en", "leak_file"))

    def test_reply_to_bot_message_is_quoted(self):
        bot_msg = {"message_id": 10, "from": {"is_bot": True}, "text": "Bill due 5 Oct"}
        self.assertIn("Bill due 5 Oct", bridge.reply_context({"reply_to_message": bot_msg}, 300))
        root = dict(bot_msg, message_id=300)
        self.assertIsNone(bridge.reply_context({"reply_to_message": root}, 300))
        own = dict(bot_msg, **{"from": {"is_bot": False}})
        self.assertIsNone(bridge.reply_context({"reply_to_message": own}, 300))


class Profile(unittest.TestCase):
    from src import botprofile as bp

    def args(self, *argv):
        from src import main as m
        with mock.patch.object(self.bp, "main", lambda cfg, a: setattr(self, "a", a) or 0):
            m.main(["profile", *argv])
        return self.a

    class Bot(FakeBot):
        def __init__(self, fail=None):
            super().__init__(fail)
            self.uploads = []

        def call(self, method, _timeout=35, _retries=3, **p):
            super().call(method, **p)
            return {"name": "Bot", "description": "a\nb", "short_description": "s"}

        def upload(self, method, field, path, _timeout=120, **p):
            self.uploads.append((method, field, path.suffix, path.read_bytes()[:2], p))
            return True

    def test_validation(self):
        self.assertEqual(self.bp.validate(self.args("--name", "x" * 64, "--short", "")), [])
        errs = self.bp.validate(self.args("--name", "x" * 65, "--description", "d" * 513, "--short", "s" * 121,
                                          "--photo", "/nope.jpg", "--photo-remove"))
        self.assertEqual(len(errs), 5)
        self.assertFalse(self.bp.wants_change(self.args()))
        self.assertTrue(self.bp.wants_change(self.args("--short", "")))  # empty = clear the field

    def test_show_uses_getters(self):
        bot = self.Bot()
        rows = self.bp.show(bot, "ru")
        self.assertEqual(rows, [("name", "Bot"), ("description", "a\\nb"), ("short", "s")])
        self.assertEqual([c for c in bot.calls], [("getMyName", {"language_code": "ru"}),
                                                  ("getMyDescription", {"language_code": "ru"}),
                                                  ("getMyShortDescription", {"language_code": "ru"})])

    def test_setters_and_photo_payload(self):
        with tempfile.TemporaryDirectory() as d:
            jpg = Path(d) / "a.JPG"
            jpg.write_bytes(b"\xff\xd8jpeg")
            bot = self.Bot(fail={"setMyDescription": "Bad Request: too long"})
            rows = self.bp.apply(bot, self.args("--name", "N", "--description", "D", "--short", "S",
                                                "--lang", "en", "--photo", str(jpg)))
        self.assertEqual(rows, [("name", "ok"), ("description", "error: Bad Request: too long"),
                                ("short", "ok"), ("photo", "ok")])
        self.assertEqual(bot.calls[0], ("setMyName", {"language_code": "en", "name": "N"}))
        self.assertEqual(bot.calls[2], ("setMyShortDescription", {"language_code": "en", "short_description": "S"}))
        self.assertEqual(bot.uploads, [("setMyProfilePhoto", "p", ".JPG", b"\xff\xd8",
                                        {"photo": {"type": "static", "photo": "attach://p"}})])
        bot = self.Bot()
        self.assertEqual(self.bp.apply(bot, self.args("--photo-remove")), [("photo", "removed")])
        self.assertEqual(bot.calls, [("removeMyProfilePhoto", {})])

    def test_non_jpg_needs_ffmpeg(self):
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "a.png"
            png.write_bytes(b"x")
            with mock.patch("shutil.which", return_value=None):
                rows = self.bp.apply(self.Bot(), self.args("--photo", str(png)))
            self.assertEqual(rows[0][0], "photo")
            self.assertIn("install ffmpeg", rows[0][1])

    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "no ffmpeg")
    def test_png_converted_to_jpg(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            png = Path(d) / "a.png"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1",
                            str(png)], check=True)
            bot = self.Bot()
            self.assertEqual(self.bp.apply(bot, self.args("--photo", str(png))), [("photo", "ok")])
        self.assertEqual(bot.uploads[0][1:4], ("p", ".jpg", b"\xff\xd8"))
