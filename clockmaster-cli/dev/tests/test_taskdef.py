import unittest

import base
import taskdef
from errors import ValidationError


class Parse(base.Case):
    def test_defaults(self):
        t = taskdef.from_text("a", 'schedule: "0 9 * * *"\ncommand: echo hi  # trailing\n')
        self.assertEqual(t.command, "echo hi")
        self.assertEqual((t.timeout, t.keep, t.enabled, t.notify, t.sound, t.group), (7200, 250, True, "failure", "Blow", ""))
        self.assertEqual(str(t.workdir), str(base.identity.home()))

    def test_values(self):
        t = taskdef.from_text("a", 'schedule: "* * * * *"\ncommand: "x # y"\ntimeout: none\nkeep: unlimited\n'
                                   'enabled: no\nnotify: on\nsound: off\ngroup: reports\n')
        self.assertEqual((t.command, t.timeout, t.keep, t.enabled, t.notify, t.sound, t.group),
                         ("x # y", None, None, False, "on", "off", "reports"))

    def test_errors_carry_location(self):
        for text, where in (('schedule: "* * * * *"\n  - list\n', "a.yaml:2"),
                            ('schedule: "* * * * *"\ncommand: x\ncommand: y\n', "a.yaml:3"),
                            ("schedule: '* * * * *\n", "a.yaml:1")):
            with self.assertRaises(ValidationError) as cm:
                taskdef.from_text("a", text)
            self.assertEqual(cm.exception.where, where)

    def test_bad_values(self):
        for extra in ("timeout: 5x", "keep: 0", "enabled: maybe", "notify: always", "sound: blow", "group: Bad Name"):
            with self.assertRaises(ValidationError, msg=extra):
                taskdef.from_text("a", f'schedule: "* * * * *"\ncommand: x\n{extra}\n')
        with self.assertRaises(ValidationError):
            taskdef.from_text("Bad_Name", 'schedule: "* * * * *"\ncommand: x\n')
        with self.assertRaises(ValidationError):
            taskdef.from_text("a", 'command: x\n')

    def test_load_all_and_find(self):
        self.write_task("b", 'schedule: "0 9 * * *"\ncommand: x\n')
        self.write_task("a", 'schedule: "0 9 * * *"\ncommand: x\n')
        self.assertEqual([t.name for t in taskdef.load_all()], ["a", "b"])
        self.assertIsNone(taskdef.find("zzz"))


class Edit(unittest.TestCase):
    def test_set_key_keeps_comment_and_order(self):
        text = '# head\nschedule: "0 9 * * *"  # morning\ncommand: x\n'
        out = taskdef.set_key(text, "schedule", '"0 10 * * *"')
        self.assertEqual(out, '# head\nschedule: "0 10 * * *"  # morning\ncommand: x\n')
        self.assertEqual(taskdef.set_key(out, "keep", "5"), out + "keep: 5\n")
        self.assertEqual(taskdef.set_key(out, "command", None), '# head\nschedule: "0 10 * * *"  # morning\n')

    def test_apply_edits(self):
        text = 'schedule: "0 9 * * *"\ncommand: x\ntimeout: 5m\n'
        out = taskdef.apply_edits(text, {"timeout": "", "description": "a # b"})
        self.assertEqual(out, 'schedule: "0 9 * * *"\ncommand: x\ndescription: "a # b"\n'.replace('"a # b"', "'a # b'"))
        for bad in ({"schedule": ""}, {"nope": "x"}, {"command": "a\nb"}):
            with self.assertRaises(ValidationError):
                taskdef.apply_edits(text, bad)

    def test_quote_roundtrip(self):
        for v in ("plain", "a # b", "'x'", ' pad', 'say "hi" # x'):
            self.assertEqual(taskdef.parse_flat(f"k: {taskdef.quote(v)}\n", "f")["k"], v)


if __name__ == "__main__":
    unittest.main()
