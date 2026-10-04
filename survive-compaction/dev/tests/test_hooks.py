"""Hook contract tests against the repo scripts with a throwaway HOME.
Run: python3 -m unittest discover -s dev/tests   (needs bash + jq)"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "scripts" / "hooks"
SID = "sess-1234-abcd"


class Base(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.claude = self.home / ".claude"
        self.state = self.claude / ".ctx-usage.d"
        self.docs = self.claude / "progress"
        self.state.mkdir(parents=True)
        self.docs.mkdir()
        self.tp = self.home / "proj" / f"{SID}.jsonl"
        (self.tp.parent / SID / "subagents").mkdir(parents=True)
        self.tp.write_text("")
        self.cwd = self.home / "myrepo"
        self.cwd.mkdir()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_script(self, path, payload, check=True):
        env = dict(os.environ, HOME=str(self.home))
        data = payload if isinstance(payload, str) else json.dumps(payload)
        p = subprocess.run(["bash", str(path)], input=data, capture_output=True, text=True, env=env)
        if check:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def hook(self, name, payload):
        return self.run_script(HOOKS / name, payload).stdout

    def tool(self, **extra):
        base = {"session_id": SID, "transcript_path": str(self.tp), "cwd": str(self.cwd),
                "hook_event_name": "PostToolUse", "tool_name": "Bash"}
        base.update(extra)
        return base

    def counter(self, n):
        (self.state / SID).write_text(f"{n}\n")

    def ctx(self, out):
        if not out.strip():
            return ""
        doc = json.loads(out)
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        return doc["hookSpecificOutput"]["additionalContext"]

    def sub_log(self, aid, name=None):
        return self.tp.parent / SID / "subagents" / (name or f"agent-{aid}.jsonl")

    def usage_line(self, total, usage_first=False):
        u = {"input_tokens": total - 100, "cache_read_input_tokens": 60, "cache_creation_input_tokens": 40}
        if usage_first:  # real transcripts put "usage" before "type"
            return '{"message":{"usage":%s},"type":"assistant"}\n' % json.dumps(u, separators=(",", ":"))
        return json.dumps({"type": "assistant", "message": {"usage": u}}, separators=(",", ":")) + "\n"


class MainSession(Base):
    def test_silent_without_counter_or_session(self):
        self.assertEqual(self.hook("watch.sh", self.tool()), "")
        self.assertEqual(self.hook("watch.sh", {"cwd": "/x"}), "")
        self.assertEqual(self.hook("watch.sh", "not json"), "")

    def test_first_order_once_then_second_then_rearm(self):
        (self.docs / "myrepo-old.md").write_text("x")
        self.counter(120000)
        t = self.ctx(self.hook("watch.sh", self.tool()))
        self.assertIn("120k tokens", t)
        self.assertIn("around 168k", t)
        self.assertIn("~/.claude/progress/myrepo-<task-slug>.md", t)
        self.assertIn("myrepo-old.md", t)
        self.assertIn("CLAUDE.md progress-doc rule", t)
        self.assertEqual(self.hook("watch.sh", self.tool()), "")
        self.counter(150000)
        self.assertIn("is close", self.ctx(self.hook("watch.sh", self.tool())))
        self.assertEqual(self.hook("watch.sh", self.tool()), "")
        self.counter(50000)
        self.assertEqual(self.hook("watch.sh", self.tool()), "")
        self.counter(115000)
        self.assertIn("in force", self.ctx(self.hook("watch.sh", self.tool())))

    def test_jump_past_first_limit_marks_both(self):
        self.counter(160000)
        self.assertIn("is close", self.ctx(self.hook("watch.sh", self.tool())))
        self.counter(130000)
        self.assertEqual(self.hook("watch.sh", self.tool()), "")

    def test_override_file_and_conf(self):
        (self.state / f"{SID}.override").write_text("1000 2000 500\n")
        self.counter(1500)
        self.assertIn("1k tokens", self.ctx(self.hook("watch.sh", self.tool())))

    def test_existing_docs_capped_at_three(self):
        for i in range(5):
            (self.docs / f"myrepo-t{i}.md").write_text("x")
        self.counter(120000)
        t = self.ctx(self.hook("watch.sh", self.tool()))
        self.assertEqual(t.count("myrepo-t"), 3)


class Subagent(Base):
    AID = "a1b2c3"

    def call(self):
        return self.ctx(self.hook("watch.sh", self.tool(agent_id=self.AID, agent_type="worker")))

    def test_order_from_own_transcript(self):
        self.sub_log(self.AID).write_text(self.usage_line(5000) + self.usage_line(120000, usage_first=True))
        t = self.call()
        self.assertIn("120k tokens", t)
        self.assertIn("your brief gave you", t)
        self.assertNotIn("Already present", t)
        self.assertEqual(self.call(), "")

    def test_transcript_name_fallbacks(self):
        self.sub_log(self.AID, f"{self.AID}.jsonl").write_text(self.usage_line(120000))
        self.assertIn("120k", self.call())

    def test_missing_transcript_is_silent(self):
        self.assertEqual(self.call(), "")

    def test_new_boundary_gives_post_compaction_order(self):
        log = self.sub_log(self.AID)
        log.write_text(self.usage_line(120000))
        self.assertIn("in force", self.call())
        with log.open("a") as f:
            f.write('{"type":"system","subtype":"compact_boundary"}\n' + self.usage_line(30000))
        t = self.call()
        self.assertIn("Compaction just happened inside agent worker", t)
        self.assertIn("takes precedence", t)
        self.assertEqual(self.call(), "")  # 30k: below every limit

    def test_boundary_seen_on_first_look_is_not_news(self):
        self.sub_log(self.AID).write_text('{"type":"system","subtype":"compact_boundary"}\n' + self.usage_line(30000))
        self.assertEqual(self.call(), "")

    def test_pending_marker_from_archive(self):
        self.sub_log(self.AID).write_text(self.usage_line(30000))
        self.hook("archive.sh", {"session_id": SID, "agent_id": self.AID, "agent_type": "worker",
                                 "compact_summary": "s", "cwd": str(self.cwd)})
        self.assertIn("inside agent worker", self.call())
        self.assertEqual(self.call(), "")


class Reorient(Base):
    def payload(self):
        return {"session_id": SID, "cwd": str(self.cwd), "hook_event_name": "SessionStart", "source": "compact"}

    def test_lists_and_steps(self):
        (self.docs / "myrepo-a.md").write_text("x")
        (self.docs / "other-b.md").write_text("x")
        old = self.docs / "other-old.md"
        old.write_text("x")
        t = time.time() - 13 * 3600
        os.utime(old, (t, t))
        out = self.hook("reorient.sh", self.payload())
        self.assertTrue(out.startswith("Compaction just happened. Before anything else"))
        self.assertIn("Docs for directory myrepo", out)
        self.assertIn("myrepo-a.md (modified ", out)
        recent = out.split("last 12 h:")[1].split("Next:")[0]
        self.assertIn("other-b.md", recent)
        self.assertNotIn("other-old.md", recent)
        self.assertIn("progress/compact/sess-123*-NN.md", out)
        self.assertIn("start a new ~/.claude/progress/myrepo-<task-slug>.md", out)

    def test_none_placeholders(self):
        out = self.hook("reorient.sh", self.payload())
        self.assertEqual(out.count(" - none"), 2)


class Ledger(Base):
    def rows(self):
        return (self.state / "compact-log.tsv").read_text().splitlines()

    def test_main_row_with_size(self):
        self.counter(168000)
        self.hook("ledger.sh", {"session_id": SID, "trigger": "auto", "cwd": "/w", "transcript_path": str(self.tp)})
        head, row = self.rows()
        self.assertEqual(head.split("\t")[4], "tokens_at_compact")
        f = row.split("\t")
        self.assertEqual(f[1:5], [SID[:8], "main", "auto", "168000"])
        self.assertIn("session_id", f[6])

    def test_small_main_counter_means_subagent(self):
        self.counter(40000)
        self.sub_log("x", "agent-zeta.jsonl").write_text("{}\n")
        self.hook("ledger.sh", {"session_id": SID, "trigger": "auto", "transcript_path": str(self.tp)})
        f = self.rows()[1].split("\t")
        self.assertEqual(f[2], "teammate?:zeta")
        self.assertEqual(f[4], "n/a(main counter=40000)")

    def test_named_agent_and_garbage(self):
        self.hook("ledger.sh", {"session_id": SID, "agent_id": "q1", "agent_type": "w"})
        self.assertEqual(self.rows()[1].split("\t")[2:5:2], ["w(q1)", "n/a(subagent)"])
        self.assertEqual(self.run_script(HOOKS / "ledger.sh", "garbage").returncode, 0)


class Archive(Base):
    def shelf(self):
        return sorted(p.name for p in (self.docs / "compact").glob("*.md"))

    def test_numbering_header_and_skip(self):
        p = {"session_id": SID, "trigger": "manual", "cwd": "/w", "compact_summary": "SUM"}
        self.hook("archive.sh", p)
        self.hook("archive.sh", p)
        self.hook("archive.sh", {"session_id": SID})  # no summary: nothing
        self.assertEqual(self.shelf(), [f"{SID[:8]}-01.md", f"{SID[:8]}-02.md"])
        body = (self.docs / "compact" / f"{SID[:8]}-02.md").read_text()
        for s in ("- trigger: manual", "- agent: main", "- cwd: /w", f"- session: {SID}", "SUM"):
            self.assertIn(s, body)

    def test_number_follows_highest_existing(self):
        (self.docs / "compact").mkdir()
        (self.docs / "compact" / f"{SID[:8]}-03.md").write_text("x")
        self.hook("archive.sh", {"session_id": SID, "compact_summary": "S"})
        self.assertIn(f"{SID[:8]}-04.md", self.shelf())

    def test_labels_and_prune(self):
        (self.docs / "compact").mkdir()
        stale = self.docs / "compact" / "old-01.md"
        stale.write_text("x")
        t = time.time() - 15 * 86400
        os.utime(stale, (t, t))
        self.counter(20000)
        self.sub_log("x", "agent-beta.jsonl").write_text("{}\n")
        self.hook("archive.sh", {"session_id": SID, "compact_summary": "S", "transcript_path": str(self.tp)})
        self.hook("archive.sh", {"session_id": SID, "compact_summary": "S", "agent_type": "my agent!"})
        self.assertEqual(self.shelf(), [f"{SID[:8]}-my_agent_-01.md", f"{SID[:8]}-teammate-beta-01.md"])


class Meter(Base):
    def test_counter_and_default_line(self):
        out = self.hook("meter.sh", {"session_id": SID, "model": {"display_name": "M"},
                                     "context_window": {"total_input_tokens": 42000, "used_percentage": 21.4}})
        self.assertEqual((self.state / SID).read_text().strip(), "42000")
        self.assertEqual(out.strip(), "M | ctx 42k (21%)")

    def test_previous_statusline_rendered(self):
        dest = self.claude / "hooks" / "checkpoint"
        shutil.copytree(HOOKS, dest)
        (dest / "statusline.orig").write_text("jq -r '\"prev:\" + .session_id'\n")
        out = self.run_script(dest / "meter.sh", {"session_id": SID, "context_window": {"total_input_tokens": 5}}).stdout
        self.assertEqual(out.strip(), f"prev:{SID}")


class Install(Base):
    def sh(self, name):
        return self.run_script(ROOT / "scripts" / name, "")

    def settings(self):
        return json.loads((self.claude / "settings.json").read_text())

    def commands(self):
        s = self.settings()
        return [h["command"] for ev in s.get("hooks", {}).values() for e in ev for h in e["hooks"]]

    def legacy_setup(self):
        old = self.claude / "hooks"
        old.mkdir()
        for n in ("ctx-threshold", "compact-context", "compact-log", "compact-dump", "ctx-statusline"):
            (old / f"{n}.sh").write_text("#!/bin/bash\necho legacy\n")
        (old / "ctx-statusline.inner").write_text("echo inner-line\n")
        (old / "ctx-guard.conf").write_text("T1=1\nT2=2\nRESET_BELOW=3\nCOMPACT_AT=4\n")
        ent = lambda c: [{"hooks": [{"type": "command", "command": f'"$HOME/.claude/hooks/{c}"'}]}]
        (self.claude / "settings.json").write_text(json.dumps({
            "hooks": {"PostToolUse": ent("ctx-threshold.sh"), "PreCompact": ent("compact-log.sh"),
                      "Stop": ent("other.sh")},
            "statusLine": {"type": "command", "command": '"$HOME/.claude/hooks/ctx-statusline.sh"'}}))

    def test_fresh_install_idempotent_and_uninstall(self):
        (self.claude / "settings.json").write_text(json.dumps({"autoCompactWindow": 100000,
                                                               "statusLine": {"type": "command", "command": "echo hi"}}))
        self.sh("install.sh")
        first = self.settings()
        self.sh("install.sh")
        self.assertEqual(self.settings(), first)
        self.assertEqual(len(self.commands()), 4)
        conf = (self.claude / "hooks/checkpoint/checkpoint.conf").read_text()
        self.assertIn("NUDGE_AT=55000", conf)
        self.assertIn("COMPACT_NEAR_K=84", conf)
        self.assertEqual(first["hooks"]["SessionStart"][0]["matcher"], "compact")
        self.assertEqual(first["hooks"]["PostCompact"][0]["hooks"][0]["timeout"], 10)
        self.assertIn("meter.sh", first["statusLine"]["command"])
        self.assertEqual((self.claude / "hooks/checkpoint/statusline.orig").read_text().strip(), "echo hi")
        md = (self.claude / "CLAUDE.md").read_text()
        self.assertEqual(md.count("# Progress doc"), 1)
        self.assertTrue((self.claude / "settings.json.checkpoint-backup").exists())
        st = self.sh("selftest.sh")
        self.assertIn("all checks passed", st.stdout)
        self.sh("uninstall.sh")
        s = self.settings()
        self.assertEqual(s.get("hooks"), {})
        self.assertEqual(s["statusLine"]["command"], "echo hi")
        self.assertFalse((self.claude / "hooks/checkpoint").exists())
        self.assertTrue(self.docs.exists())

    def test_migrates_compact_guard(self):
        self.legacy_setup()
        self.sh("install.sh")
        cmds = self.commands()
        self.assertFalse([c for c in cmds if "ctx-threshold" in c or "compact-log" in c])
        self.assertIn('"$HOME/.claude/hooks/other.sh"', cmds)
        self.assertEqual(sum("hooks/checkpoint/" in c for c in cmds), 4)
        dest = self.claude / "hooks/checkpoint"
        self.assertEqual((dest / "statusline.orig").read_text().strip(), "echo inner-line")
        self.assertIn("NUDGE_AT=1\n", (dest / "checkpoint.conf").read_text())
        self.assertFalse((self.claude / "hooks/ctx-guard.conf").exists())
        shim = (self.claude / "hooks/ctx-threshold.sh").read_text()
        self.assertIn('exec "$HOME/.claude/hooks/checkpoint/watch.sh"', shim)
        self.sh("uninstall.sh")
        self.assertFalse((self.claude / "hooks/ctx-threshold.sh").exists())

    def test_rule_found_through_import(self):
        (self.claude / "base").mkdir()
        (self.claude / "base" / "CLAUDE.md").write_text("# Progress doc (x)\n- rule\n")
        (self.claude / "CLAUDE.md").write_text("@~/.claude/base/CLAUDE.md\n\n# Mine\n")
        self.sh("install.sh")
        self.assertNotIn("Progress doc", (self.claude / "CLAUDE.md").read_text())

    def test_selftest_output_is_clean(self):
        self.sh("install.sh")
        st = self.sh("selftest.sh")
        self.assertEqual(st.stderr, "")
        self.assertNotIn("FAIL", st.stdout)

    def test_statusline_that_already_records_is_untouched(self):
        sl = self.claude / "mystatus.sh"
        sl.write_text('echo x > "$HOME/.claude/.ctx-usage.d/$sid"\n')
        (self.claude / "settings.json").write_text(json.dumps(
            {"statusLine": {"type": "command", "command": "bash ~/.claude/mystatus.sh"}}))
        self.sh("install.sh")
        self.assertEqual(self.settings()["statusLine"]["command"], "bash ~/.claude/mystatus.sh")


if __name__ == "__main__":
    unittest.main()
