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
            j(type="system", subtype="task_notification", task_id="a", status="completed"),
            j(type="system", subtype="task_notification", task_id="b", status="completed", owned_by_subagent=True),
            j(type="result", is_error=False, num_turns=1, result="helper finished", session_id=SID),
        ])
        self.assertEqual([(e.kind, e.text if e.kind != "bg" else e.count) for e in ev], [
            ("session", "m"), ("user", "u1"), ("bg", 1), ("result", "waiting"), ("session", "m"), ("bg", 0),
            ("done", "completed"), ("result", "helper finished")])

    def test_tool_line_truncates_and_unknown(self):
        self.assertTrue(streamjson.tool_line("Bash", {"command": "x" * 200}).endswith("…"))
        self.assertEqual(streamjson.tool_line("Mystery", {}), "⚙️ Mystery")
        self.assertEqual(streamjson.tool_line("Read", {"file_path": "/etc/hosts"}, "/w"), "📖 Read: /etc/hosts")

    def test_user_prompt_submit_block_gives_the_reason_and_the_line_uuid(self):
        blocked = "UserPromptSubmit operation blocked by hook:\nЛимит исчерпан\nещё строка\n\nOriginal prompt: hi"
        lines = [j(type="command_lifecycle", command_uuid="u1", state="started"),
                 j(type="system", subtype="init", session_id=SID),
                 j(type="system", subtype="informational", content=blocked, level="warning", prevent_continuation=True)]
        ev = self.feed(lines + [j(type="result", subtype="success", is_error=False, num_turns=0, result=blocked,
                                  session_id=SID, user_message_uuids=["u1"])])
        self.assertEqual((ev[-1].text, ev[-1].uuids, ev[-1].hook), ("Лимит исчерпан\nещё строка", ("u1",), True))
        # older shape: empty result, no uuids -> the informational text, the line claude started last
        ev = self.feed(lines + [j(type="result", subtype="success", is_error=False, num_turns=0, result="",
                                  session_id=SID)])
        self.assertEqual((ev[-1].text, ev[-1].uuids, ev[-1].hook), ("Лимит исчерпан\nещё строка", ("u1",), True))

    def test_hook_stopped_with_empty_result_gives_the_last_hook_denial(self):
        ev = self.feed([
            j(type="assistant", parent_tool_use_id=None, message={"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}),
            j(type="user", parent_tool_use_id=None, message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                 "content": "PreToolUse:Bash hook error: Limit reached, back in 1h"}]}),
            j(type="result", subtype="success", is_error=False, num_turns=2, result="", session_id=SID,
              terminal_reason="hook_stopped", stop_reason="tool_use", user_message_uuids=["u1"]),
            j(type="result", subtype="success", is_error=False, num_turns=1, result="", session_id=SID),
        ])
        self.assertEqual([e.kind for e in ev], ["tool", "result", "result"])
        self.assertEqual((ev[1].text, ev[1].hook), ("Limit reached, back in 1h", True))
        self.assertEqual((ev[2].text, ev[2].hook), ("", False))  # the hook text belongs to its own turn only

    def test_model_answer_is_kept_after_a_non_stopping_hook_denial(self):
        ev = self.feed([
            j(type="user", parent_tool_use_id=None, message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                 "content": "PreToolUse:Bash hook error: no"}]}),
            j(type="result", subtype="success", is_error=False, num_turns=3, result="Skipped it.", session_id=SID),
        ])
        self.assertEqual((ev[-1].text, ev[-1].hook), ("Skipped it.", False))


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
        self.assertEqual(ui.status_line("ru", "work", 14), "⚙️ Работаю…")
        self.assertEqual(ui.status_line("en", "work", 44), "⚙️ Working… · 30 s")  # 15 s steps under 1 min
        self.assertEqual(ui.status_line("en", "work", 83), "⚙️ Working… · 1 min")  # 30 s steps under 2 min
        self.assertEqual(ui.status_line("en", "work", 95), "⚙️ Working… · 1 min 30 s")
        self.assertEqual(ui.status_line("en", "work", 179), "⚙️ Working… · 2 min")  # then whole minutes
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
        clock[0] = 16.0
        st.set("work")
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "⚙️ Работаю… · 15 с")
        n = len(calls)
        clock[0] = 16.5
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
        w.b.hushed.return_value = False
        w.ilock, w.interim, w.posted, w.stream_id = threading.Lock(), "Отдаю тиммейту.", "", 88
        w.st = mock.Mock()
        w.post_interim()
        w.post_interim()  # nothing pending: no second post
        w.b.send_answer.assert_called_once_with(1, 50, "Отдаю тиммейту.")
        w.b.quiet.assert_called_once_with("deleteMessage", chat_id=1, message_id=88)  # edit-mode draft replaced
        self.assertEqual((w.posted, w.stream_id), ("Отдаю тиммейту.", None))
        w.st.below.assert_called()

    def test_quiet_topic_folds_interim_text_into_the_status(self):
        w = object.__new__(bridge.Worker)
        w.b, w.chat, w.thread = mock.Mock(guard=None), 1, 50
        w.b.hushed.return_value = True
        w.noticed = w.tripped = False
        w.ilock, w.interim, w.posted, w.stream_id = threading.Lock(), "Читаю ответ продавца.", "", None
        st, clock, calls = self.status()
        w.st = st
        st.tool(streamjson.Event("tool", "🔧 Bash: x", name="Bash"))
        w.post_interim()
        w.b.send_answer.assert_not_called()  # no separate message
        self.assertEqual(w.posted, "")  # the final answer is never skipped as a duplicate
        clock[0] = 3.0
        st.tick()
        self.assertEqual(calls[-1][0][0], "sendMessage")
        self.assertEqual(calls[-1][1]["text"], "Читаю ответ продавца.\n\n⚙️ Работаю…")
        st.note("Дописываю импорты. " * 30)
        clock[0] = 3.5
        st.tick()  # a new progress line edits at once, the same message
        self.assertEqual(calls[-1][0][0], "editMessageText")
        self.assertTrue(calls[-1][1]["text"].startswith("Дописываю импорты."))
        self.assertLessEqual(len(calls[-1][1]["text"].split("\n\n")[0]), bridge.Status.MEMO)
        st.close()
        self.assertEqual(calls[-1][0], ("deleteMessage",))  # gone when the answer lands

    def test_quiet_command_and_flag(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = TopicCommands.bridge(self, d)
            self.assertFalse(b.hushed(50))
            TopicCommands.cmd(self, b, "/quiet")
            self.assertTrue(b.hushed(50))
            TopicCommands.cmd(self, b, "/quiet off")
            self.assertFalse(b.hushed(50))

    def test_timer_alone_edits_at_most_every_min_edit_phase_changes_at_once(self):
        st, clock, calls = self.status()
        st.tool(streamjson.Event("tool", "🔧 Bash: x", name="Bash"))
        clock[0] = 3.0
        st.tick()
        clock[0] = 14.0
        st.tool(streamjson.Event("tool", "📖 Read: x", name="Read"))
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "📖 Изучаю файлы…")  # phase change: at once
        n = len(calls)
        clock[0] = 15.0
        st.tick()
        self.assertEqual(len(calls), n)  # "· 15 с" waits MIN_EDIT after the last edit
        clock[0] = 24.0
        st.tick()
        self.assertEqual(calls[-1][1]["text"], "📖 Изучаю файлы… · 15 с")

    def test_detailed_batches_tool_edits(self):
        st, clock, calls = self.status(detailed=True)
        st.tool(streamjson.Event("tool", "🔧 Bash: a", name="Bash"))
        clock[0] = 2.5
        st.tick()  # first show: at once
        for i, t in enumerate(("📖 Read: b", "🔎 Grep: c", "🔧 Bash: d")):
            st.tool(streamjson.Event("tool", t, name=t.split()[1].rstrip(":")))
            clock[0] = 3.0 + i
            st.tick()
        self.assertEqual(len(calls), 1)  # a burst of tools: no edit per tool
        clock[0] = 2.5 + bridge.Status.VERBOSE_EDIT
        st.tick()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1][1]["text"].splitlines(), ["🔧 Bash: a", "📖 Read: b", "🔎 Grep: c", "🔧 Bash: d"])

    def test_typing_once_then_only_while_nothing_shows_progress(self):
        w = object.__new__(bridge.Worker)
        w.b, w.chat, w.thread = mock.Mock(), 1, 50
        w.st, w.stream_id, w.last_draft = None, None, 0.0
        self.assertFalse(w.shows_progress())
        w.st = mock.Mock(id=77)
        self.assertTrue(w.shows_progress())
        done = mock.Mock()
        done.is_set.side_effect = [False, False, False, True]
        w._typing(done)
        self.assertEqual(w.b.quiet.call_count, 1)  # turn start only: the status is visible after that
        w.st, w.last_draft = mock.Mock(id=None), bridge.time.monotonic()
        self.assertTrue(w.shows_progress())  # a fresh draft preview
        w.last_draft -= 60
        self.assertFalse(w.shows_progress())  # the draft died
        done.is_set.side_effect = [False, False, True]
        w._typing(done)
        self.assertEqual(w.b.quiet.call_count, 3)

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
            self.assertEqual(b.bot.calls, [])  # off by default
            b.cfg["reactions"] = True
            b.react(1, 9, "👀")
            self.assertEqual(b.bot.calls[-1][0], "setMessageReaction")
            b.cfg["reactions"], b.bot.calls = False, []
            for e in ("👀", "💔", None):
                b.react(1, 9, e)
            self.assertEqual(b.bot.calls, [])
            w = mock.Mock(draft_id=5, chat=1, thread=50)
            b.workers["50"] = w
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
        self.argv, self.env, self.ev, self.lines = argv, env, queue.Queue(), []
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

    def bridge(self, d, fail=None):
        b = super().bridge(d, fail)
        b.cfg["reactions"] = True
        return b

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
            r.ev.put(self.E("bg", count=0))  # helper done while idle -> a notification turn follows: stay open
            r.ev.put(self.E("session", "m", "s50"))
            until(lambda: w.ticks == 7)
            self.assertTrue(r.open)
            r.ev.put(self.E("result", "helper finished", "s50"))  # its result: nothing left -> close stdin
            until(lambda: not r.open)
            r.ev.put(None)
            until(lambda: w.run is None)
            self.assertEqual(self.answers(b), ["waiting", "still sleeping", "helper finished"])
            self.assertEqual(b.store.pending(), {})
            w.put(self.msg(3, "next"))  # no process now: a new one
            until(lambda: len(FakeRun.runs) == 2 and FakeRun.runs[1].lines == ["next"])
            FakeRun.runs[1].stop()
            until(lambda: w.run is None)

    def test_notification_turn_keeps_stdin_open_until_its_result(self):
        """bg 1, result, bg 0, notification turn starts another bg task, result: stdin closes only after that
        task ends and its own notification turn's result (closing early orphaned the new task)."""
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            b = self.bridge(d)
            w = b.worker(1, 50)
            w.put(self.msg(1, "watch the build"))
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]

            def feed(*evs, ticks):
                for e in evs:
                    r.ev.put(e)
                until(lambda: w.ticks == ticks)
            feed(self.E("session", "m", "s50"), self.E("user", "u1"), self.E("bg", count=1),
                 self.E("result", "started", "s50"), ticks=3)
            until(lambda: w.idle)
            self.assertTrue(r.open)  # the task runs
            feed(self.E("bg", count=0), self.E("done", "completed"), ticks=3)
            until(lambda: w.bg == 0)
            self.assertTrue(r.open)  # the notification turn has not run yet
            feed(self.E("session", "m", "s50"), self.E("bg", count=1), self.E("result", "next check", "s50"), ticks=5)
            until(lambda: w.idle and w.bg == 1)
            self.assertTrue(r.open)  # the new task runs
            feed(self.E("bg", count=0), self.E("done", "completed"), ticks=5)
            until(lambda: w.bg == 0)
            self.assertTrue(r.open)
            feed(self.E("session", "m", "s50"), self.E("result", "all done", "s50"), ticks=7)
            until(lambda: not r.open)
            r.ev.put(None)
            until(lambda: w.run is None)
            self.assertEqual(self.answers(b), ["started", "next check", "all done"])

    def test_task_ended_without_a_turn_closes_after_the_grace(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"), \
                mock.patch.object(bridge.Worker, "TURN_GRACE", 0.3):
            FakeRun.runs = []
            b = self.bridge(d)
            w = b.worker(1, 50)
            w.put(self.msg(1, "start and kill"))
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]
            for e in (self.E("session", "m", "s50"), self.E("user", "u1"), self.E("bg", count=1),
                      self.E("result", "running", "s50"), self.E("bg", count=0), self.E("done", "stopped")):
                r.ev.put(e)
            until(lambda: w.ticks == 3 and w.bg == 0)
            self.assertTrue(r.open)
            until(lambda: not r.open)  # no notification turn came: the fallback closes stdin
            r.ev.put(None)
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


class HookBlock(Inject):
    def test_blocked_prompt_posts_the_reason_and_acks_the_message(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename") as ren:
            FakeRun.runs = []
            b = self.bridge(d)
            b.store.update(50, implicit=True)
            w = b.worker(1, 50)
            w.put(self.msg(1, "hi"))
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            r = FakeRun.runs[0]
            for e in (self.E("session", "m", "s50"),  # no "user" replay: the hook blocked the line
                      self.E("result", "Limit reached", "s50", uuids=("u1",), hook=True)):
                r.ev.put(e)
            until(lambda: "👍" in self.reacts(b, 1))
            until(lambda: not r.open)  # nothing left unanswered: stdin closed, no hang
            r.ev.put(None)
            until(lambda: w.run is None)
            self.assertEqual(self.answers(b), ["Limit reached"])
            self.assertNotIn("💔", self.reacts(b, 1))
            self.assertEqual(b.store.pending(), {})
            ren.assert_not_called()  # a block reason is no answer to title the topic by


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
        want = str(Path("/home/u/100%/token").resolve()).replace("%", "%%")  # macOS: /home -> /System/Volumes/Data
        self.assertIn(f"LoadCredential=token:{want}", t)  # % escaped for systemd
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


class FloodGate(unittest.TestCase):
    """One 429 bans the whole chat: cosmetic calls are skipped locally, real sends wait it out (no cap)."""
    def bot(self, replies):
        clock = [0.0]
        bot = botapi.Bot("tok")
        bot.flood = botapi.Flood(clock=lambda: clock[0])
        posts = []

        def post(method, data, ctype, timeout):
            posts.append(method)
            r = replies.pop(0) if replies else {"message_id": 1}
            if isinstance(r, Exception):
                raise r
            return r

        def sleep(s):
            clock[0] += s
        return bot, clock, posts, mock.patch.object(bot, "_post", post), mock.patch.object(botapi.time, "sleep", sleep)

    def test_flood_wait_skips_cosmetic_and_waits_out_real_sends(self):
        ban = TgError("editMessageText", 429, "Too Many Requests: retry after 415", 415)
        bot, clock, posts, p1, p2 = self.bot([ban])
        with p1, p2, self.assertLogs("claude-tg", "WARNING") as logs:
            with self.assertRaises(TgError):  # the real 429
                bot.call("editMessageText", _retries=0, chat_id=1, message_id=5, text="x")
            for _ in range(20):  # the threads keep ticking during the ban: no HTTP request at all
                with self.assertRaises(botapi.Skipped):
                    bot.call("editMessageText", _retries=0, chat_id=1, message_id=5, text="x")
                with self.assertRaises(botapi.Skipped):
                    bot.call("sendChatAction", _retries=0, chat_id=1, action="typing")
            self.assertEqual(posts, ["editMessageText"])
            self.assertEqual(bot.call("sendMessage", chat_id=1, text="answer"), {"message_id": 1})
            self.assertGreaterEqual(clock[0], 415)  # waited the whole ban, not 30 s x retries
            self.assertEqual(posts, ["editMessageText", "sendMessage"])
            bot.call("getUpdates")  # no chat: never gated
        self.assertEqual(len(logs.output), 2, logs.output)  # one line when it starts, one when it ends
        self.assertIn("flood wait 415 s", logs.output[0])
        self.assertIn("flood wait over", logs.output[1])

    def test_real_send_retries_a_429_with_the_full_wait(self):
        bot, clock, posts, p1, p2 = self.bot([TgError("sendMessage", 429, "retry after 120", 120)])
        with p1, p2, self.assertLogs("claude-tg", "WARNING"):
            self.assertEqual(bot.call("sendMessage", chat_id=1, text="a"), {"message_id": 1})
        self.assertEqual(posts, ["sendMessage", "sendMessage"])
        self.assertGreaterEqual(clock[0], 120)

    def test_per_chat_budget_for_cosmetic_calls_real_sends_never_refused(self):
        bot, clock, posts, p1, p2 = self.bot([])
        with p1, p2:
            sent = 0
            for _ in range(40):  # 4 topics x 10 edits in the same second
                try:
                    bot.call("editMessageText", _retries=0, chat_id=1, message_id=5, text="x")
                    sent += 1
                except botapi.Skipped:
                    pass
            self.assertEqual(sent, botapi.Flood.BURST)
            for _ in range(10):
                bot.call("sendMessage", chat_id=1, text="answer")
            bot.call("editMessageText", _retries=0, chat_id=2, message_id=5, text="x")  # another chat: own budget
            bot.call("deleteMessage", _retries=0, chat_id=1, message_id=5)  # cleanup is never budgeted
            self.assertFalse(bot.flood.ready(1))
            clock[0] += 60
            self.assertTrue(bot.flood.ready(1))
        self.assertEqual(posts.count("sendMessage"), 10)

    def test_status_keeps_its_change_while_the_chat_is_over_budget(self):
        w = mock.Mock(chat=1, thread=50)
        w.b.guard, w.b.calm.return_value = None, False
        clock = [0.0]
        st = bridge.Status(w, False, "en", clock=lambda: clock[0], ticker=False)
        clock[0] = 5
        st.tick()
        w.b.quiet.assert_not_called()
        self.assertIsNone(st.shown)
        w.b.calm.return_value = True
        w.b.quiet.return_value = {"message_id": 9}
        st.tick()
        self.assertEqual(w.b.quiet.call_args[0][0], "sendMessage")

    def test_quiet_does_not_log_skipped_calls_and_retries_deletes_after_the_wait(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(config, "STATE_DIR", Path(d)):
                b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1), "tok")
            b.bot.flood.hit(1, 30, "sendMessage")
            with mock.patch.object(b.bot, "_post") as post, mock.patch.object(bridge.threading, "Timer") as timer, \
                    mock.patch.object(bridge.log, "info") as info:
                self.assertIsNone(b.quiet("editMessageText", chat_id=1, message_id=5, text="x"))
                timer.assert_not_called()
                b.quiet("deleteMessage", chat_id=1, message_id=5)
            post.assert_not_called()
            info.assert_not_called()
            self.assertGreater(timer.call_args[0][0], 30)
            self.assertEqual(timer.call_args[0][3], {"chat_id": 1, "message_id": 5})


class SharedFlood(unittest.TestCase):
    """The bot and CLI processes share one flood state file (STATE_DIR/flood.json)."""
    def test_wait_and_budget_cross_processes(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [1000.0]
            bot_side = botapi.Flood(clock=lambda: clock[0], path=Path(d) / "flood.json")
            cli_side = botapi.Flood(clock=lambda: clock[0], path=Path(d) / "flood.json")
            for _ in range(int(botapi.Flood.BURST)):
                self.assertTrue(bot_side.take(1, "editMessageText", True))
            self.assertFalse(cli_side.take(1, "editMessageForumTopic", True))  # the bot spent the budget
            self.assertTrue(cli_side.take(1, "sendMessage", False))  # real sends are never refused
            with self.assertLogs("claude-tg", "WARNING"):
                cli_side.hit(1, 300, "sendMessage")  # a 429 seen by the CLI
            self.assertGreater(bot_side.left(1), 299)
            self.assertFalse(bot_side.ready(1))
            clock[0] += 301
            with self.assertLogs("claude-tg", "WARNING") as logs:
                self.assertEqual(bot_side.left(1), 0.0)
            self.assertIn("flood wait over", logs.output[0])
            self.assertEqual(cli_side.left(1), 0.0)
            (Path(d) / "flood.json").write_text("garbage")
            self.assertEqual(cli_side.left(1), 0.0)  # a broken file never breaks sending

    def cli(self, d):
        bot = botapi.Bot("tok", state_dir=d, on_wait=mock.Mock())
        clock = [time_now()]
        bot.flood.clock = lambda: clock[0]
        posts = []

        def post(method, data, ctype, timeout):
            posts.append(method)
            return {"message_id": 1}

        def sleep(s):
            clock[0] += s
        return bot, clock, posts, mock.patch.object(bot, "_post", post), mock.patch.object(botapi.time, "sleep", sleep)

    def test_cli_skips_cosmetic_and_waits_real_sends_during_the_bots_wait(self):
        from src import inbox
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            bot, clock, posts, p1, p2 = self.cli(d)
            with self.assertLogs("claude-tg", "WARNING"):
                botapi.Flood(clock=lambda: clock[0], path=Path(d) / "flood.json").hit(1, 120, "editMessageText")
            with p1, p2, mock.patch("sys.stderr"), self.assertLogs("claude-tg", "WARNING"):
                r = inbox.topic_icon(bot, dict(config.DEFAULTS, owner_id=1), 50, "off")
                self.assertTrue(r["skipped"])
                self.assertEqual(posts, [])
                bot.call("sendMessage", chat_id=1, text="hi")
                self.assertEqual(posts, ["sendMessage"])
                self.assertGreaterEqual(clock[0] - time_now(), 119)
                bot.on_wait.assert_called_once()
                bot.flood.hit(1, 10, "sendMessage")
                bot.upload("sendDocument", "document", Path(__file__), chat_id=1)  # uploads wait too
                self.assertEqual(posts, ["sendMessage", "sendDocument"])

    def test_fail_line_is_a_real_send_waiting_out_the_flood(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(config, "STATE_DIR", Path(d)):
                b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1), "tok")
            bot, clock, posts, p1, p2 = self.cli(d)
            b.bot = bot
            with p1, p2, self.assertLogs("claude-tg", "WARNING"):
                bot.flood.hit(1, 60, "editMessageText")
                b.fail(1, 50, "boom.")
            self.assertEqual(posts, ["sendMessage"])


def time_now():
    import time
    return time.time()


class LookupCache(unittest.TestCase):
    """Sticker list and bot username are cached in STATE_DIR/cache.json."""
    def test_icons_and_username_hit_the_api_once(self):
        from src import inbox, notify
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            bot = Inbox.Bot()
            for _ in range(3):
                self.assertEqual(notify.icon_id(bot, "📋"), "222")
                self.assertEqual(inbox.link(bot, 5), "https://t.me/my_bot/5/2147483647")
            with mock.patch("sys.stderr"):
                self.assertIsNone(notify.icon_id(bot, "🦄"))  # fresh cache: no refetch for an unknown emoji
            methods = [m for m, _ in bot.calls]
            self.assertEqual((methods.count("getForumTopicIconStickers"), methods.count("getMe")), (1, 1))
            data = json.loads((Path(d) / "cache.json").read_text())
            data["stickers"]["at"] -= notify.MISS_TTL + 1
            (Path(d) / "cache.json").write_text(json.dumps(data))
            with mock.patch("sys.stderr"):
                self.assertIsNone(notify.icon_id(bot, "🦄"))  # an hour later: one refetch
            self.assertEqual([m for m, _ in bot.calls].count("getForumTopicIconStickers"), 2)


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



class People(unittest.TestCase):
    """Addressing rule: whoever the bot asks for something is mentioned (group: allowed_users, private: owner)."""
    G = -1004

    class Bot:
        def __init__(self, users):
            self.users, self.calls = users, []

        def call(self, method, **p):
            self.calls.append(method)
            uid = p.get("user_id", p.get("chat_id"))
            if uid not in self.users:
                raise TgError(method, 400, "Bad Request: user not found")
            u = dict(self.users[uid], id=uid)
            return {"user": u} if method == "getChatMember" else u

    def people(self, users, cfg, owner=None):
        from src import notify
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            bot = self.Bot(users)
            ps = notify.people(bot, cfg, owner)
            notify.people(bot, cfg, owner)
            return ps, bot.calls

    def test_group_people_with_aliases_cached(self):
        cfg = dict(config.DEFAULTS, group_id=self.G, allowed_users=[1, 2, 3], people_aliases={"2": ["Саша"]})
        ps, calls = self.people({1: {"username": "nik", "first_name": "Nikita"},
                                 2: {"first_name": "Alexandra", "last_name": "Z"}}, cfg)
        self.assertEqual(ps, [{"id": 1, "handle": "@nik", "names": ["Nikita"]},
                              {"id": 2, "handle": "[Alexandra](tg://user?id=2)",
                               "names": ["Alexandra", "Z", "Alexandra Z", "Саша"]}])
        self.assertEqual(calls, ["getChatMember"] * 3 + ["getChatMember"])  # failed lookup (3) is not cached

    def test_private_owner_via_get_chat(self):
        ps, calls = self.people({7: {"username": "own", "first_name": "Own"}}, dict(config.DEFAULTS), owner=7)
        self.assertEqual((ps, calls), ([{"id": 7, "handle": "@own", "names": ["Own"]}], ["getChat"]))

    def test_prompt_group_and_private(self):
        from src import notify
        ps = [{"id": 1, "handle": "@nik", "names": ["Nikita", "Никита"]}, {"id": 2, "handle": "@sa", "names": ["Саша"]}]
        g = notify.people_prompt(ps, True)
        self.assertIn("- Nikita / Никита: @nik", g)
        self.assertIn("starts with their mention(s) and the ask", g)
        self.assertIn("github-tasks needs", g)
        self.assertIn("starts with @nik and the ask", notify.people_prompt(ps[:1], False))
        self.assertEqual(notify.people_prompt([], True), "")

    def test_address_rewrites_name_headers_only(self):
        from src import notify
        ps = [{"id": 1, "handle": "@nik", "names": ["Никита"]}, {"id": 2, "handle": "@sa", "names": ["Саша", "Sasha"]}]
        md = ("Итог.\n\n**Саша:** выбери цвет\nНикита: проверь план\n- **sasha**: ок?\nСаша сказала да\n"
              "```\nСаша: code\n```")
        self.assertEqual(notify.address(md, ps), "Итог.\n\n@sa, выбери цвет\n@nik, проверь план\n- @sa, ок?\n"
                                                 "Саша сказала да\n```\nСаша: code\n```")
        self.assertEqual(notify.address("x", []), "x")

    def test_text_mention_link_renders(self):
        self.assertEqual(fmt.md_to_html("[Саша](tg://user?id=5), hi"), '<a href="tg://user?id=5">Саша</a>, hi')

    def test_bridge_appends_rule_and_rewrites_answer(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = bridge.Bridge(dict(config.DEFAULTS, group_id=self.G, allowed_users=[1]), "tok")
            b.bot = FakeBot()
            b.people = lambda: [{"id": 1, "handle": "@nik", "names": ["Никита"]}]
            b.send_answer(self.G, 5, "**Никита:** реши")
            self.assertEqual(b.bot.calls[-1][1]["text"], "@nik, реши")


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
                             {"chat": 7, "topics": {"Notifications": 300},
                              "meta": {"Notifications": {"name": "Notifications", "icon": None}}})

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

    def test_replace_sends_first_then_deletes_previous(self):
        class Bot(FakeBot):
            ids = iter(range(100, 200))

            def call(self, method, _timeout=35, _retries=3, **p):
                self.calls.append((method, p))
                if method == "deleteMessage" and p["message_id"] in self.fail:
                    raise TgError(method, *self.fail[p["message_id"]])
                return True if method == "deleteMessage" else {"message_id": next(self.ids)}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            cfg = dict(config.DEFAULTS, owner_id=7)
            bot = Bot()
            state = lambda: json.loads((Path(d) / "notify.json").read_text())["replace"]
            self.n.replace(bot, "dg", self.n.send(bot, cfg, "one", topic=None))
            self.assertEqual(state(), {"dg": {"chat": 7, "message_ids": [100]}})
            bot.calls.clear()
            self.n.replace(bot, "dg", self.n.send(bot, cfg, "x" * 5000, topic=None))
            self.assertEqual([c[0] for c in bot.calls], ["sendMessage", "sendMessage", "deleteMessage"])
            self.assertEqual(bot.calls[2][1], {"chat_id": 7, "message_id": 100})
            self.assertEqual(state()["dg"]["message_ids"], [101, 102])
            bot.fail = {101: (400, "Bad Request: message can't be deleted"), 102: (0, "network: down")}
            with mock.patch("sys.stderr"):
                self.n.replace(bot, "dg", self.n.send(bot, cfg, "three", topic=None))
            self.assertEqual(state()["dg"]["message_ids"], [102, 103])  # 400 forgotten, transient kept
            with mock.patch("sys.stderr"):
                self.assertEqual(self.n.forget(bot, cfg, ["dg", "nope"], []), 1)
            self.assertEqual(state()["dg"]["message_ids"], [102])
            bot.fail = {}
            bot.calls.clear()
            self.assertEqual(self.n.forget(bot, cfg, ["dg"], [55]), 0)
            self.assertEqual(state(), {})
            self.assertEqual(bot.calls, [("deleteMessage", {"chat_id": 7, "message_id": 102}),
                                         ("deleteMessage", {"chat_id": 7, "message_id": 55})])

    def test_failed_send_keeps_previous_replace(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            (Path(d) / "notify.json").write_text('{"replace": {"dg": {"chat": 7, "message_ids": [9]}}}')
            a = mock.Mock(file=None, text=["hi"], html=False, markdown=False, silent=False, button=None,
                          thread=5, chat=None, main_chat=False, topic=None, replace="dg")
            bot = FakeBot(fail={"sendMessage": "Bad Request: chat not found"})
            with mock.patch.object(self.n, "Bot", lambda *_, **__: bot), mock.patch.object(config, "read_token",
                                                                                     lambda c: "t"), \
                    mock.patch("sys.stderr"):
                self.assertEqual(self.n.main(dict(config.DEFAULTS, owner_id=7), a), 1)
            self.assertEqual([c[0] for c in bot.calls], ["sendMessage"])
            self.assertIn("dg", json.loads((Path(d) / "notify.json").read_text())["replace"])

    def test_reply_to_bot_message_is_quoted(self):
        bot_msg = {"message_id": 10, "from": {"is_bot": True}, "text": "Bill due 5 Oct"}
        self.assertIn("Bill due 5 Oct", bridge.reply_context({"reply_to_message": bot_msg}, 300))
        root = dict(bot_msg, message_id=300)
        self.assertIsNone(bridge.reply_context({"reply_to_message": root}, 300))
        human = dict(bot_msg, text="https://www.chaos.com one more",
                     **{"from": {"is_bot": False, "first_name": "Nikita", "username": "vaikus_n", "id": 7}})
        got = bridge.reply_context({"reply_to_message": human}, 300)
        self.assertIn("chaos.com", got)
        self.assertIn("@vaikus_n", got)


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


class DlBot:
    """download() fake: records calls; fail = TgError to raise."""
    def __init__(self, fail=None):
        self.got, self.fail = [], fail

    def download(self, file_id, dest, timeout=120):
        self.got.append((file_id, timeout))
        if self.fail:
            raise self.fail
        return dest


class BigFiles(unittest.TestCase):
    MB = 1 << 20

    def video(self, size, name="IMG_7945.MOV"):
        v = {"file_id": "F", "file_name": name, "mime_type": "video/quicktime"}
        if size is not None:
            v["file_size"] = size
        return {"message_id": 722, "video": v, "caption": "seizure"}

    def fetch(self, msg, bot, big=None):
        from src import media
        with tempfile.TemporaryDirectory() as d:
            return media.fetch(bot, msg, Path(d), big)

    def test_small_file_goes_through_the_cloud(self):
        bot = DlBot()
        files, audio, skipped = self.fetch(self.video(5 * self.MB), bot)
        self.assertEqual((len(files), audio, skipped, bot.got), (1, None, [], [("F", 120)]))

    def test_over_20mb_without_local_server_is_skipped_not_raised(self):
        bot = DlBot()
        files, _, skipped = self.fetch(self.video(90 * self.MB), bot)
        self.assertEqual((files, bot.got), ([], []))  # no doomed getFile call
        sk = skipped[0]
        self.assertEqual((sk.reason, sk.name, sk.kind, sk.mid), ("too_big", "IMG_7945.MOV", "video", 722))
        note = sk.note()
        for part in ("NOT downloaded", "IMG_7945.MOV", "video (video/quicktime)", "90.0 MB", "722", "20 MB"):
            self.assertIn(part, note)

    def test_cloud_too_big_without_size_falls_to_local_server(self):
        bot = DlBot(TgError("getFile", 400, "Bad Request: file is too big"))
        big = DlBot()
        files, _, skipped = self.fetch(self.video(None), bot, big)
        self.assertEqual((len(files), skipped), (1, []))
        self.assertEqual(big.got, [("F", 1800)])

    def test_over_20mb_uses_local_server_only(self):
        bot, big = DlBot(), DlBot()
        files, _, skipped = self.fetch(self.video(90 * self.MB), bot, big)
        self.assertEqual((len(files), skipped, bot.got, len(big.got)), (1, [], [], 1))

    def test_local_server_down_and_other_errors(self):
        down = DlBot(TgError("getFile", 0, "network: [Errno 111] Connection refused"))
        _, _, sk = self.fetch(self.video(90 * self.MB), DlBot(), down)
        self.assertEqual(sk[0].reason, "local_down")
        _, _, sk = self.fetch(self.video(1 * self.MB), DlBot(TgError("getFile", 400, "Bad Request: wrong file_id")))
        self.assertEqual((sk[0].reason, sk[0].detail), ("failed", "Bad Request: wrong file_id"))
        self.assertIn("download failed (Bad Request: wrong file_id)", sk[0].note())

    def test_big_voice_is_skipped_not_transcribed(self):
        msg = {"message_id": 5, "voice": {"file_id": "V", "file_size": 30 * self.MB, "mime_type": "audio/ogg"}}
        files, audio, skipped = self.fetch(msg, DlBot())
        self.assertEqual((files, audio, skipped[0].kind), ([], None, "voice"))

    def test_bridge_tells_owner_why_and_claude_gets_text_plus_note(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1, ui_lang="ru"), "tok")
            self.assertIsNone(b.big)
            b.bot = FakeBot()
            b.bot.download = DlBot().download
            w = bridge.Worker.__new__(bridge.Worker)
            w.b, w.chat, w.thread = b, 1, 50
            prompt = w.prompt([self.video(90 * self.MB)])
            self.assertTrue(prompt.startswith("seizure"))
            self.assertIn("[Attachment NOT downloaded: IMG_7945.MOV", prompt)
            said = [p["text"] for m, p in b.bot.calls if m == "sendMessage"]
            self.assertEqual(len(said), 1)
            self.assertIn("IMG_7945.MOV (видео, 90.0 МБ)", said[0])
            self.assertIn("больше 20 МБ, бот не может скачать его через Bot API", said[0])
            self.assertIn("Что сделать:", said[0])
            self.assertEqual(said and b.bot.calls[-1][1]["message_thread_id"], 50)

    def test_bridge_builds_local_bot_from_config(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1, local_api_url="http://127.0.0.1:8081/"), "tok")
            self.assertEqual((b.big.api, b.bot.api), ("http://127.0.0.1:8081", botapi.API))

    def test_local_server_file_path_is_moved_not_fetched(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "srv" / "tok" / "videos" / "file_0.MOV"
            src.parent.mkdir(parents=True)
            src.write_bytes(b"x" * 10)
            bot = botapi.Bot("tok", "http://127.0.0.1:8081")
            with mock.patch.object(bot, "call", return_value={"file_path": str(src)}) as call, \
                    mock.patch.object(botapi, "_open", side_effect=AssertionError("no HTTP for local paths")):
                out = bot.download("F", Path(d) / "out" / "v.MOV", timeout=1800)
            self.assertEqual(out.read_bytes(), b"x" * 10)
            self.assertFalse(src.exists())
            self.assertEqual(call.call_args.kwargs["_timeout"], 1800)
            self.assertEqual(bot._url("getFile"), "http://127.0.0.1:8081/bottok/getFile")


class LocalApiSecrets(unittest.TestCase):
    def test_literal_values_are_refused(self):
        from src import localapi
        for ref in ("12345", "abcdef0123", "", None, "vault:X"):
            with self.assertRaises(localapi.Fail):
                localapi.resolve(ref, "local_api_id")

    def test_env_and_cred_references(self):
        from src import localapi
        with mock.patch.dict(os.environ, {"TG_ID": "42"}):
            self.assertEqual(localapi.resolve("env:TG_ID", "id"), "42")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "hash").write_text("h\n")
            with mock.patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": d}):
                self.assertEqual(localapi.resolve("cred:hash", "hash"), "h")
            # user unit: no $CREDENTIALS_DIRECTORY -> user-scoped encrypted file, decrypted via systemd-creds
            (Path(d) / "TELEGRAM_API_HASH").write_bytes(b"ciphertext")
            dec = mock.Mock(returncode=0, stdout="abc\n", stderr="")
            with mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch.object(localapi, "USER_CREDSTORE", Path(d)), \
                    mock.patch.object(localapi.subprocess, "run", return_value=dec) as run:
                os.environ.pop("CREDENTIALS_DIRECTORY", None)
                self.assertEqual(localapi.resolve("cred:TELEGRAM_API_HASH", "hash"), "abc")
                self.assertEqual(run.call_args.args[0][:3], ["systemd-creds", "decrypt", "--user"])
                with self.assertRaisesRegex(localapi.Fail, "systemd-creds encrypt --user"):
                    localapi.resolve("cred:MISSING", "hash")
            bad = mock.Mock(returncode=1, stdout="", stderr="Permission denied")
            with mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch.object(localapi, "USER_CREDSTORE", Path(d)), \
                    mock.patch.object(localapi.subprocess, "run", return_value=bad):
                os.environ.pop("CREDENTIALS_DIRECTORY", None)
                with self.assertRaisesRegex(localapi.Fail, "Permission denied"):
                    localapi.resolve("cred:TELEGRAM_API_HASH", "hash")
        with self.assertRaisesRegex(localapi.Fail, "env:NAME or cred:NAME"):
            localapi.resolve("rbw:TELEGRAM_API_ID", "id")  # vault refs are gone: env file or systemd credential
        with mock.patch.dict(os.environ, {"TG_ID": ""}):
            with self.assertRaisesRegex(localapi.Fail, "export TG_ID=.*env_files"):
                localapi.resolve("env:TG_ID", "id")

    def test_read_env_file_undoes_shell_quoting(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "secrets.env"
            f.write_text("export A=plain\nexport B=a\\ b\\&c\nC='x y'\nexport D=\"q\"\n# x\nE=\n")
            self.assertEqual(config.read_env_file(str(f)), {"A": "plain", "B": "a b&c", "C": "x y", "D": "q", "E": ""})

    def test_env_files_rotation_reaches_next_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "secrets.env"
            f.write_text("export S=old\n")
            with mock.patch.object(config, "STATE_DIR", Path(d)):
                b = bridge.Bridge(dict(config.DEFAULTS, owner_id=1, env_files=[str(f)]), "tok")
            self.assertEqual(b.env["S"], "old")
            f.write_text("export S=rotated\n")
            os.utime(f, ns=(1, 2_000_000_000_000_000_000))  # mtime may not tick within a test
            self.assertEqual(b.env["S"], "rotated")  # no restart
            f.unlink()
            with self.assertLogs("claude-tg", "WARNING") as logs:
                self.assertEqual(b.env["S"], "rotated")  # gone/unreadable: last good values, no crash
                self.assertEqual(b.env["S"], "rotated")
            self.assertEqual(len(logs.output), 1)  # warned once

    def test_server_argv_keeps_secrets_out(self):
        from src import localapi
        cfg = dict(config.DEFAULTS, local_api_url="http://127.0.0.1:8081", local_api_bin="/x/telegram-bot-api")
        host, port = localapi.address(cfg)
        a = localapi.argv(cfg, host, port)
        self.assertEqual(a[:4], ["/x/telegram-bot-api", "--local", "--http-ip-address=127.0.0.1", "--http-port=8081"])
        self.assertFalse(any("api-id" in x or "api-hash" in x for x in a))
        with self.assertRaises(localapi.Fail):
            localapi.address(dict(cfg, local_api_url="https://api.telegram.org"))


class Inbox(unittest.TestCase):
    """claude-tg spawn / send / alive / topic-icon: scripts talk to the running bot through STATE_DIR/inbox."""
    from src import inbox as ib

    class Bot(FakeBot):
        def call(self, method, _timeout=35, _retries=3, **p):
            super().call(method, **p)
            if method == "createForumTopic":
                return {"message_thread_id": 400}
            if method == "getMe":
                return {"username": "my_bot"}
            if method == "getForumTopicIconStickers":
                return [{"emoji": "❗", "custom_emoji_id": "111"}, {"emoji": "📋", "custom_emoji_id": "222"}]
            return {"message_id": 77}

    def cfg(self):
        return dict(config.DEFAULTS, owner_id=1)

    def test_spawn_creates_topic_posts_prompt_and_bot_runs_it_with_topic_settings(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            bot = self.Bot()
            r = self.ib.spawn(bot, self.cfg(), "Задача", d, "сделай X", icon="📋", system="manager role")
            self.assertEqual((r["thread"], r["link"], r["message_id"]), (400, "https://t.me/my_bot/400/2147483647", 77))
            create = [p for m, p in bot.calls if m == "createForumTopic"][0]
            self.assertEqual((create["name"], create["icon_custom_emoji_id"]), ("Задача", "222"))
            posted = [p for m, p in bot.calls if m == "sendMessage"][0]
            self.assertEqual((posted["message_thread_id"], posted["text"]), (400, "сделай X"))
            self.assertTrue(self.ib.alive(400, proc=Path(d) / "noproc")["live"])  # queued in the inbox = live
            b = TopicCommands.bridge(self, d)
            b.drain_inbox()
            self.assertEqual(list((Path(d) / "inbox").glob("*.json")), [])
            t = b.store.topic(400)
            self.assertEqual((t["cwd"], t["title"], t["implicit"], t["icon"], t["system"]),
                             (str(Path(d).resolve()), "Задача", False, "222", "manager role"))
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            run = FakeRun.runs[0]
            self.assertEqual(run.lines, ["сделай X"])
            self.assertIn("--append-system-prompt", run.argv)
            self.assertEqual(run.argv[run.argv.index("--append-system-prompt") + 1], "manager role")
            self.assertIn("77", b.store.pending())  # request key = the posted message
            run.stop()
            until(lambda: b.workers["400"].run is None)
            b.workers["400"].close()

    def test_send_goes_into_a_live_run_and_bad_files_are_set_aside(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            b = TopicCommands.bridge(self, d)
            b.worker(1, 50).put([{"message_id": 5, "chat": {"id": 1, "type": "private"}, "date": 0, "text": "first"}])
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            self.ib.send(self.Bot(), self.cfg(), 50, "второе")
            self.ib.enqueue({"op": "nope", "thread": 50})
            b.drain_inbox()
            until(lambda: len(FakeRun.runs[0].lines) == 2)
            self.assertEqual(FakeRun.runs[0].lines[1], "второе")
            self.assertEqual(len(list((Path(d) / "inbox" / "bad").glob("*.json"))), 1)
            FakeRun.runs[0].stop()
            until(lambda: b.workers["50"].run is None)
            b.workers["50"].close()

    def test_show_line_stands_in_for_the_prompt_and_quiet_flag_travels(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            bot = self.Bot()
            self.ib.spawn(bot, self.cfg(), "#3 RAM", d, "Задача #3: длинный промпт", show="▶️ #3 RAM — взял в работу",
                          quiet=True)
            self.ib.send(bot, self.cfg(), 50, "Дождались: сырой заголовок письма", show="📬 #3 RAM", quiet=True)
            posted = [p["text"] for m, p in bot.calls if m == "sendMessage"]
            self.assertEqual(posted, ["▶️ #3 RAM — взял в работу", "📬 #3 RAM"])  # the prompts never show
            b = TopicCommands.bridge(self, d)
            b.drain_inbox()
            self.assertTrue(b.hushed(400) and b.hushed(50))
            until(lambda: len(FakeRun.runs) == 2 and all(r.lines for r in FakeRun.runs))
            self.assertEqual(sorted(r.lines[0] for r in FakeRun.runs),
                             ["Дождались: сырой заголовок письма", "Задача #3: длинный промпт"])
            for r in FakeRun.runs:
                r.stop()
            for t in (400, 50):
                until(lambda t=t: b.workers[str(t)].run is None)
                b.workers[str(t)].close()

    def test_alive_from_proc_env_and_pending(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            proc = Path(d) / "proc"
            (proc / "123").mkdir(parents=True)
            (proc / "123" / "environ").write_bytes(b"HOME=/h\0CLAUDE_TG_RUN_TOPIC=50\0")
            (proc / "self").mkdir()
            self.assertEqual(self.ib.alive(50, proc)["pids"], [123])
            self.assertFalse(self.ib.alive(51, proc)["live"])
            (Path(d) / "state.json").write_text(json.dumps({"topics": {"51": {}}, "pending": {"9": {"thread": 51}}}))
            r = self.ib.alive(51, proc)
            self.assertEqual((r["live"], r["pending"], r["known"]), (True, 1, True))

    def test_topic_icon_emoji_off_base_and_thread_links(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            (Path(d) / "state.json").write_text(json.dumps({"topics": {"50": {"icon": "222"}}}))
            bot = self.Bot()
            self.ib.topic_icon(bot, self.cfg(), 50, "❗")
            self.ib.topic_icon(bot, self.cfg(), 50, "base")
            self.ib.topic_icon(bot, self.cfg(), 51, "base")
            self.ib.topic_icon(bot, self.cfg(), 50, "off")
            got = [p["icon_custom_emoji_id"] for m, p in bot.calls if m == "editForumTopic"]
            self.assertEqual(got, ["111", "222", "", ""])
            with self.assertRaises(self.ib.NotifyError):
                self.ib.topic_icon(bot, self.cfg(), 50, "🦄")
        self.assertEqual(self.ib.thread_of("https://t.me/my_bot/400"), 400)
        self.assertEqual(self.ib.thread_of("https://t.me/my_bot/400/400"), 400)
        self.assertEqual(self.ib.thread_of("https://t.me/my_bot/400/2147483647"), 400)
        self.assertEqual(self.ib.thread_of(" 12 "), 12)
        with self.assertRaises(self.ib.NotifyError):
            self.ib.thread_of("https://example.com/x")

    def test_topic_link_opens_at_last_message(self):
        self.assertEqual(self.ib.topic_link("my_bot", 400), "https://t.me/my_bot/400/2147483647")
        self.assertEqual(self.ib.thread_of(self.ib.topic_link("my_bot", 400)), 400)
        self.assertEqual(self.ib.topic_link(None, 400), "")

    def test_icon_command_stores_base_icon(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = TopicCommands.bridge(self, d)
            b.bot = self.Bot()
            TopicCommands.cmd(self, b, "/icon ❗")
            self.assertEqual(b.store.topic(50)["icon"], "111")


class GroupMode(unittest.TestCase):
    """group_id + allowed_users: one forum supergroup, several people; private-owner mode stays as it was."""
    G, A, B = -1001234567890, 111, 222  # placeholder ids

    def cfg(self, **kw):
        return dict(config.DEFAULTS, group_id=self.G, allowed_users=[self.A, self.B], **kw)

    def bridge(self, d, cfg=None):
        with mock.patch.object(config, "STATE_DIR", Path(d)):
            b = bridge.Bridge(cfg or self.cfg(), "tok")
        b.bot = FakeBot()
        b.collected = []
        b.collect = lambda chat, thread, msg: b.collected.append((chat, thread, msg["message_id"]))
        return b

    def msg(self, mid=9, chat=None, uid=None, thread=55, text="hi", **kw):
        m = {"message_id": mid, "chat": {"id": self.G if chat is None else chat, "type": "supergroup", "is_forum": True},
             "from": {"id": self.A if uid is None else uid, "first_name": "Ann"}, "text": text, "date": 0}
        if thread:
            m.update(message_thread_id=thread, is_topic_message=True)
        m.update(kw)
        return {"message": m}

    def test_only_allowed_users_in_the_group_are_heard(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.handle(self.msg(1))
            b.handle(self.msg(2, uid=self.B))
            b.handle({"message": {"message_id": 4, "chat": {"id": self.A, "type": "private"},
                                  "from": {"id": self.A}, "text": "dm", "date": 0}})
            b.handle(self.msg(5, chat=-100999))                         # another group
            b.handle(self.msg(6, uid=333))                              # a member not in allowed_users
            b.handle(self.msg(7, uid=self.A, **{"sender_chat": {"id": self.G}}))  # anonymous admin
            bot_msg = self.msg(8)
            bot_msg["message"]["from"]["is_bot"] = True
            b.handle(bot_msg)
            self.assertEqual(b.collected, [(self.G, 55, 1), (self.G, 55, 2)])
            self.assertIsNone(b.owner)  # nobody became owner from a group

    def test_ignored_sources_are_logged_once_per_window(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            with self.assertLogs("claude-tg", "INFO") as cm:
                for i in range(5):
                    b.handle(self.msg(i, uid=333))
                b.handle(self.msg(9, chat=-100999))
            self.assertEqual(len([x for x in cm.output if "ignored" in x]), 2)

    def test_own_updates_dropped_silently_others_named(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.bot_id = 4242
            with self.assertLogs("claude-tg", "INFO") as cm:
                own = self.msg(1, uid=4242)
                own["message"]["from"]["is_bot"] = True
                b.handle(own)
                other = self.msg(2, uid=777)
                other["message"]["from"].update(is_bot=True, username="x_bot")
                b.handle(other)
                b.handle(self.msg(3, **{"sender_chat": {"id": self.G}}))
            out = "\n".join(cm.output)
            self.assertNotIn("4242", out)
            self.assertIn("bot 777 (@x_bot)", out)
            self.assertIn("anonymous admin", out)
            self.assertEqual(b.collected, [])

    def test_empty_allowed_users_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d, dict(config.DEFAULTS, group_id=self.G, allowed_users=[]))
            b.handle(self.msg(1))
            self.assertEqual(b.collected, [])

    def test_general_and_reply_threads_map_to_all_messages(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.handle(self.msg(1, thread=None))
            reply = self.msg(2, thread=None, message_thread_id=1)  # a reply in General: thread id, not a topic
            b.handle(reply)
            self.assertEqual([t for _, t, _ in b.collected], [bridge.GENERAL, bridge.GENERAL])

    def test_service_messages_never_become_prompts(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.handle(self.msg(1, thread=None, text=None, new_chat_members=[{"id": self.B}]))
            b.handle(self.msg(2, text=None, pinned_message={"message_id": 1}))
            self.assertEqual(b.collected, [])

    def test_user_created_topic_is_noted(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.handle(self.msg(70, thread=70, text=None, forum_topic_created={"name": "Kitchen"}))
            self.assertEqual(b.store.topic(70)["title"], "Kitchen")
            self.assertEqual(b.collected, [])

    def test_commands_for_other_bots_are_ignored_and_ours_answered_in_the_group(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.username = "my_bot"
            b.handle(self.msg(1, text="/status@other_bot"))
            self.assertEqual(b.bot.calls, [])
            b.handle(self.msg(2, text="/status@My_Bot"))
            self.assertEqual(b.bot.calls[-1][1]["chat_id"], self.G)
            self.assertEqual(b.bot.calls[-1][1]["message_thread_id"], 55)

    def test_stop_button_any_allowed_user_only_in_the_group(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            w = mock.Mock(st=mock.Mock(id=77), run=True)
            b.workers["55"] = w
            b.button({"id": "q", "from": {"id": 333}, "data": "stop", "message": {"message_id": 77, "chat": {"id": self.G}}})
            w.stop.assert_not_called()
            b.button({"id": "q", "from": {"id": self.B}, "data": "stop", "message": {"message_id": 77, "chat": {"id": -100999}}})
            w.stop.assert_not_called()
            b.button({"id": "q", "from": {"id": self.B}, "data": "stop", "message": {"message_id": 77, "chat": {"id": self.G}}})
            w.stop.assert_called_once_with(drop_queue=False)

    def test_added_to_a_foreign_group_leaves_it(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            ev = lambda chat: {"my_chat_member": {"chat": {"id": chat, "type": "supergroup"}, "from": {"id": 5},
                                                   "new_chat_member": {"status": "member"}}}
            b.handle(ev(self.G))
            self.assertEqual(b.bot.calls, [])
            b.handle(ev(-100999))
            self.assertEqual(b.bot.calls, [("leaveChat", {"chat_id": -100999})])
            p = self.bridge(d, dict(config.DEFAULTS, owner_id=1, owner_groups={"x": -100777}))
            p.handle(ev(-100777))  # private mode: an owner group stays
            own = ev(-100888)
            own["my_chat_member"]["from"]["id"] = 1  # added by the owner: stays (id logged for owner_groups)
            with self.assertLogs("claude-tg", "WARNING") as logs:
                p.handle(own)
            self.assertIn("-100888", "".join(logs.output))
            self.assertEqual(p.bot.calls, [])
            p.handle(ev(-100999))  # added by someone else: left
            self.assertEqual(p.bot.calls, [("leaveChat", {"chat_id": -100999})])

    def test_no_draft_streaming_in_groups(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            self.assertFalse(self.bridge(d).draft_ok)
            self.assertTrue(self.bridge(d, dict(config.DEFAULTS, owner_id=1)).draft_ok)

    def test_prompt_names_each_sender_in_group_mode_only(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            a = self.msg(1, text="one")["message"]
            a2 = self.msg(2, text="two")["message"]
            c = self.msg(3, uid=self.B, text="three")["message"]
            c["from"] = {"id": self.B, "first_name": "Bo", "username": "bo"}
            w = bridge.Worker(b, self.G, 55)
            self.assertEqual(w.prompt([a, a2, c]), f"[From: Ann (id {self.A})]\n\none\n\ntwo\n\n"
                                                   f"[From: Bo (@bo, id {self.B})]\n\nthree")
            script = {"message_id": 4, "chat": {"id": self.G}, "from": {"id": self.G}, "text": "job", "date": 0}
            self.assertEqual(w.prompt([script]), "job")  # inbox message: no person behind it
            p = self.bridge(d, dict(config.DEFAULTS, owner_id=1))
            self.assertEqual(bridge.Worker(p, 1, 55).prompt([a]), "one")

    def test_flood_budget_is_tighter_for_groups(self):
        clock = [1000.0]
        f = botapi.Flood(clock=lambda: clock[0])
        self.assertEqual(sum(f.take(self.G, "editMessageText", True) for _ in range(10)), 3)
        self.assertEqual(sum(f.take(7, "editMessageText", True) for _ in range(10)), 5)
        clock[0] += 5  # 0.2/s in a group vs 0.5/s private
        self.assertEqual(sum(f.take(self.G, "editMessageText", True) for _ in range(10)), 1)

    def test_notify_inbox_and_restart_report_target_the_group(self):
        from src import inbox, notify
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            self.assertEqual(notify.owner_chat(self.cfg(owner_id=1)), self.G)
            bot = Inbox.Bot()
            r = inbox.spawn(bot, self.cfg(), "Task", d, "do X")
            self.assertTrue(all(p["chat_id"] == self.G for _, p in bot.calls if "chat_id" in p))
            self.assertEqual(r["link"], "https://t.me/c/1234567890/400/2147483647")
            self.assertEqual(inbox.thread_of(r["link"]), 400)
            self.assertEqual(inbox.thread_of("t.me/c/1234567890/400"), 400)
            self.assertEqual(inbox.thread_of("https://t.me/my_bot/400/2147483647"), 400)
            sent = []
            with mock.patch.object(service, "Bot") as B, mock.patch.object(config, "read_token", lambda c: "tok"):
                B.return_value.call = lambda m, **p: sent.append(p)
                service._report(self.cfg(), "400", "restart_ok", rev="abc", state="active")
            self.assertEqual(sent[0]["chat_id"], self.G)

    def test_notify_topic_cache_follows_the_chat(self):
        from src import notify
        bot = Inbox.Bot()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            (Path(d) / "notify.json").write_text(json.dumps({"topics": {"Notifications": 12}}))
            self.assertEqual(notify.topic_id(bot, 7, "Notifications"), 12)  # old file: adopted, not reset
            self.assertEqual(json.loads((Path(d) / "notify.json").read_text())["chat"], 7)
            self.assertEqual(notify.topic_id(bot, self.G, "Notifications"), 400)  # switched to the group: new topic
            self.assertEqual(bot.calls[-1], ("createForumTopic", {"chat_id": self.G, "name": "Notifications"}))

    def test_doctor_group_rows(self):
        class Bot(FakeBot):
            def __init__(self, chat, member):
                super().__init__()
                self.chat, self.member = chat, member

            def call(self, method, _timeout=35, _retries=3, **p):
                return self.chat if method == "getChat" else self.member
        me = {"id": 42, "can_read_all_group_messages": False}

        def rows_of(chat, member, me=me):
            rows = []
            service.rows_group(Bot(chat, member), me, self.G, lambda c, ok, d="": rows.append(f"{c}\t{'ok' if ok else 'FAIL'}\t{d}"), rows)
            return [r.split("\t")[1] for r in rows]
        forum = {"type": "supergroup", "is_forum": True, "title": "T"}
        self.assertEqual(rows_of(forum, {"status": "administrator", "can_manage_topics": True}), ["ok", "ok"])
        self.assertEqual(rows_of(forum, {"status": "administrator"}), ["ok", "FAIL"])
        self.assertEqual(rows_of(forum, {"status": "member"}), ["ok", "FAIL"])
        self.assertEqual(rows_of(forum, {"status": "member"}, dict(me, can_read_all_group_messages=True)), ["ok", "WARN"])
        self.assertEqual(rows_of({"type": "supergroup", "title": "T"}, {"status": "administrator",
                                                                         "can_manage_topics": True}), ["FAIL", "ok"])

    def test_chats_lists_groups_and_senders_without_confirming(self):
        ups = [{"update_id": 1, "message": {"chat": {"id": self.G, "type": "supergroup", "title": "Studio",
                                                      "is_forum": True}, "from": {"id": self.A, "first_name": "Ann"}}},
               {"update_id": 2, "message": {"chat": {"id": self.A, "type": "private"}, "from": {"id": self.A}}}]
        calls = []
        with mock.patch.object(service, "Bot") as B, mock.patch.object(config, "read_token", lambda c: "tok"), \
                mock.patch("sys.stdout", new_callable=__import__("io").StringIO) as out:
            B.return_value.call = lambda m, **p: calls.append((m, p)) or ups
            self.assertEqual(service.chats(dict(config.DEFAULTS)), 0)
        self.assertNotIn("offset", calls[0][1])
        lines = out.getvalue().splitlines()
        self.assertIn(f"chat\t{self.G}\tsupergroup\tStudio\tforum", lines)
        self.assertIn(f"user\t{self.A}\tAnn\t-\t{self.G}", lines)
        self.assertEqual(len(lines), 3)


class OwnerGroups(unittest.TestCase):
    """Private mode + owner_groups: extra forum groups where only the owner talks; topics keyed per chat."""
    G, OWNER = -1001112223334, 1  # placeholder ids

    def cfg(self, **kw):
        return dict(config.DEFAULTS, owner_id=self.OWNER, owner_groups={"team": self.G}, **kw)

    def bridge(self, d):
        b = GroupMode.bridge(self, d, self.cfg())
        b.owner = self.OWNER
        return b

    def msg(self, mid=9, chat=None, uid=None, thread=55, **kw):
        return GroupMode.msg(self, mid, chat=self.G if chat is None else chat,
                             uid=self.OWNER if uid is None else uid, thread=thread, **kw)

    def test_config_keys_and_chat_refs(self):
        c = self.cfg()
        self.assertEqual(config.owner_groups(c), {"team": self.G})
        self.assertEqual(config.owner_groups(dict(c, group_id=-100555)), {})  # group mode: ignored
        self.assertEqual((config.topic_key(c, None, 5), config.topic_key(c, 1, 5)), ("5", "5"))
        self.assertEqual(config.topic_key(c, self.G, 5), f"{self.G}:5")
        self.assertEqual([config.chat_ref(c, r) for r in (None, "", "team", str(self.G), self.OWNER)],
                         [None, None, self.G, self.G, None])
        with self.assertRaises(ValueError):
            config.chat_ref(c, "nope")
        with self.assertRaises(ValueError):
            config.chat_ref(c, -100999)

    def test_only_the_owner_is_heard_in_an_owner_group(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            b = self.bridge(d)
            b.handle(self.msg(1))
            b.handle(self.msg(2, uid=333))                                    # another member
            b.handle(self.msg(3, chat=-100999))                               # a group not in owner_groups
            b.handle(self.msg(4, **{"sender_chat": {"id": self.G}}))          # anonymous admin
            b.handle(self.msg(5, thread=None))                                # General
            b.handle({"message": {"message_id": 6, "chat": {"id": 1, "type": "private"}, "from": {"id": 1},
                                  "text": "dm", "date": 0}})
            self.assertEqual([c for c in b.collected if c[0] == self.G], [(self.G, 55, 1), (self.G, bridge.GENERAL, 5)])
            self.assertEqual([m for c, _, m in b.collected if c == 1], [6])  # the private chat as before

    def test_same_thread_in_two_chats_stays_apart(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(runner, "Run", FakeRun), mock.patch.object(bridge.Worker, "rename"):
            FakeRun.runs = []
            b = TopicCommands.bridge(self, d)
            b.cfg, b.groups, b.group_chats = self.cfg(), {"team": self.G}, {self.G}
            b.store.update(55, session_id="home")
            b.store.update(b.key(self.G, 55), session_id="grp")
            self.assertEqual(b.store.topic(55)["session_id"], "home")
            self.assertEqual(b.store.topic(f"{self.G}:55")["session_id"], "grp")
            b.worker(self.G, 55).put([{"message_id": 7, "chat": {"id": self.G}, "from": {"id": 1}, "date": 0,
                                       "text": "x"}])
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            run = FakeRun.runs[0]
            self.assertEqual((run.env[config.RUN_TOPIC_ENV], run.env[config.RUN_CHAT_ENV]), ("55", str(self.G)))
            self.assertIn(f"{self.G}:7", b.store.pending())  # message ids are per chat
            self.assertNotIn("55", b.workers)
            run.stop()
            until(lambda: b.workers[f"{self.G}:55"].run is None)
            b.workers[f"{self.G}:55"].close()

    def test_old_pending_entries_without_topic_still_drop(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / "s.json", "/tmp")
            s.pend(9, thread=5, chat=1, msgs=[])  # written by an older bot
            s.drop(5)
            self.assertEqual(s.pending(), {})

    def test_spawn_send_alive_icon_target_the_group(self):
        from src import inbox
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)), \
                mock.patch.object(bridge.Worker, "rename"), mock.patch.object(runner, "Run", FakeRun):
            FakeRun.runs = []
            bot, c = Inbox.Bot(), self.cfg()
            chat = inbox.target_chat(c, "team")
            r = inbox.spawn(bot, c, "Task", d, "do X", chat=chat)
            self.assertEqual((r["link"], r["chat"]), ("https://t.me/c/1112223334/400/2147483647", self.G))
            self.assertTrue(all(p["chat_id"] == self.G for _, p in bot.calls if "chat_id" in p))
            self.assertEqual(inbox.ref_of(r["link"]), (self.G, 400))
            self.assertEqual(inbox.target_chat(c, None, r["link"]), self.G)  # the link carries the chat
            self.assertEqual(inbox.target_chat(c, None, "400"), self.OWNER)
            with self.assertRaises(inbox.NotifyError):
                inbox.target_chat(c, "nope")
            self.assertTrue(inbox.alive(400, Path(d) / "noproc", self.G, c)["live"])
            self.assertFalse(inbox.alive(400, Path(d) / "noproc", None, c)["live"])  # home topic 400: idle
            b = TopicCommands.bridge(self, d)
            b.cfg, b.groups, b.group_chats = c, {"team": self.G}, {self.G}
            b.drain_inbox()
            self.assertEqual(b.store.topic(f"{self.G}:400")["title"], "Task")
            self.assertNotIn("400", b.store.data["topics"])
            until(lambda: FakeRun.runs and FakeRun.runs[0].lines)
            FakeRun.runs[0].stop()
            until(lambda: b.workers[f"{self.G}:400"].run is None)
            b.workers[f"{self.G}:400"].close()

    def test_proc_scan_tells_chats_apart(self):
        from src import inbox
        with tempfile.TemporaryDirectory() as d:
            for pid, env in ((11, b"CLAUDE_TG_RUN_TOPIC=5\0"),
                             (12, f"CLAUDE_TG_RUN_TOPIC=5\0CLAUDE_TG_RUN_CHAT={self.G}\0".encode())):
                (Path(d) / str(pid)).mkdir()
                (Path(d) / str(pid) / "environ").write_bytes(env)
            self.assertEqual(inbox._proc_topics(Path(d), self.cfg()), {"5": [11], f"{self.G}:5": [12]})

    def test_notify_run_chat_default_and_per_chat_topic_cache(self):
        from src import notify
        c = self.cfg()
        a = mock.Mock(thread=None, chat=None, main_chat=False, topic=None)
        run = {config.RUN_TOPIC_ENV: "55", config.RUN_CHAT_ENV: str(self.G)}
        self.assertEqual(notify.target_chat(c, a, run), self.G)
        self.assertIsNone(notify.target_chat(c, a, {config.RUN_TOPIC_ENV: "55"}))  # older bot: home
        self.assertIsNone(notify.target_chat(c, mock.Mock(thread=None, chat=None, main_chat=False, topic="k"), run))
        self.assertEqual(notify.target_chat(c, mock.Mock(thread="t.me/c/1112223334/9", chat=None), {}), self.G)
        bot = Inbox.Bot()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            (Path(d) / "notify.json").write_text(json.dumps({"chat": 1, "topics": {"Notifications": 12}}))
            self.assertEqual(notify.topic_id(bot, self.G, "Notifications", cfg=c), 400)
            self.assertEqual(notify.topic_id(bot, 1, "Notifications", cfg=c), 12)  # home cache untouched
            self.assertEqual(json.loads((Path(d) / "notify.json").read_text())["chats"][str(self.G)]["topics"],
                             {"Notifications": 400})

    def test_restart_report_into_a_group_topic(self):
        sent = []
        with mock.patch.object(service, "Bot") as B, mock.patch.object(config, "read_token", lambda c: "tok"):
            B.return_value.call = lambda m, **p: sent.append(p)
            service._report(self.cfg(), f"{self.G}:55", "restart_ok", rev="abc", state="active")
            service._report(self.cfg(), "56", "restart_ok", rev="abc", state="active")
        self.assertEqual([(p["chat_id"], p["message_thread_id"]) for p in sent], [(self.G, 55), (1, 56)])

    def test_no_drafts_in_owner_groups(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            self.assertTrue(self.bridge(d).draft_ok)  # the private chat keeps them; Worker skips them for chat < 0


class SetupText(unittest.TestCase):
    def cfg(self, **kw):
        c = dict(config.DEFAULTS, token_file=str(Path(tempfile.mkdtemp()) / "token"))
        c.update(kw)
        return c

    def test_private_mode_mentions_threaded_and_owner(self):
        t = service.setup_text(self.cfg(), "/x/token")
        self.assertIn("Threaded Mode on", t)
        self.assertIn("first private-chat user becomes its only owner", t)

    def test_group_mode_has_no_owner_or_threaded_step(self):
        t = service.setup_text(self.cfg(group_id=-100123, allowed_users=[7, 5]), "/x/token")
        self.assertIn("group mode", t)
        self.assertIn("-100123", t)
        self.assertIn("5, 7", t)
        self.assertNotIn("Threaded Mode on", t)
        self.assertNotIn("first private-chat user", t)

    def test_no_tty_fails_loudly(self):
        with mock.patch.object(sys, "stdin") as stdin, mock.patch("sys.stderr"):
            stdin.isatty.return_value = False
            with self.assertRaisesRegex(service.Fail, "TTY"):
                service.setup(self.cfg(), token_stdin=False)


class Mention(unittest.TestCase):
    G = -1003

    class Bot:
        def __init__(self, users):
            self.users, self.calls = users, []

        def call(self, method, **p):
            self.calls.append(method)
            if p["user_id"] not in self.users:
                raise TgError("getChatMember", 400, "Bad Request: user not found")
            return {"user": {"id": p["user_id"], "username": self.users[p["user_id"]]}}

    def run_(self, users, text, specs, mode="plain", cfg=None):
        from src import notify
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "STATE_DIR", Path(d)):
            bot = self.Bot(users)
            out = notify.with_mentions(bot, cfg or dict(config.DEFAULTS, group_id=self.G), text, mode, specs)
            notify.with_mentions(bot, cfg or dict(config.DEFAULTS, group_id=self.G), text, mode, specs)
            return out, bot.calls

    def test_username_plain_and_cached(self):
        (t, mode), calls = self.run_({1: "nik"}, "👤 {who} — нужно решение <x>", ["1=Никита"])
        self.assertEqual((t, mode), ("👤 @nik — нужно решение <x>", "plain"))
        self.assertEqual(calls, ["getChatMember"])

    def test_no_username_falls_back_to_text_mention_html(self):
        (t, mode), _ = self.run_({1: "nik"}, "a <b> {who}", ["1=Никита", "2=Саша"])
        self.assertEqual(mode, "html")
        self.assertEqual(t, 'a &lt;b&gt; @nik, <a href="tg://user?id=2">Саша</a>')

    def test_private_mode_names_and_prefix(self):
        (t, mode), calls = self.run_({}, "текст", ["1=Никита"], cfg=dict(config.DEFAULTS))
        self.assertEqual((t, mode, calls), ("Никита текст", "plain", []))
