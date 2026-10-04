"""adf.py: both directions, round-trip stability, strictness.

Run: python3 -m unittest discover -s dev/tests   (from the skill folder)
Fixtures are synthetic on purpose: real descriptions can hold credentials.
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "adf.py"
spec = importlib.util.spec_from_file_location("adf", SCRIPT)
adf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adf)

SAMPLE = """DEMO-1 summary line

**Approved.**

## Steps {#1e53a3}
1. Open `settings` and press **Save**.
2. Read [the guide](https://example.invalid/guide).

## Result {#ba424c}
A single numbered line stays a paragraph:

3. Step title

*italic* with @[Pat Doe](557058:00000000-aaaa) and a break<br>here.

```python
print("hi")
```

![screen.png](11111111-2222-3333-4444-555555555555 =800x600)

### Environment
| Key | Value |
| --- | --- |
| `build` | 1.2.3 |
| a \\| b | ![c.png](66666666-7777-8888-9999-000000000000 =20x10)<br>second |
|  |  |

- flat item
- item with blocks

  second paragraph
  1. nested one
  2. nested two
-
  - only a nested list

|  |  |
| --- | --- |
| no header | body row |

\\- not a bullet

\\# not a heading
"""


def node_types(node, acc=None):
    acc = set() if acc is None else acc
    if isinstance(node, dict):
        if "type" in node:
            acc.add(node["type"])
        for value in node.values():
            node_types(value, acc)
    elif isinstance(node, list):
        for value in node:
            node_types(value, acc)
    return acc


def blocks(md):
    return adf.to_adf(md)["content"]


class RoundTrip(unittest.TestCase):
    def test_sample_is_stable(self):
        doc = adf.to_adf(SAMPLE)
        first = adf.to_md(doc)
        second = adf.to_md(adf.to_adf(first))
        third = adf.to_md(adf.to_adf(second))
        self.assertEqual(first, second)
        self.assertEqual(second, third)

    def test_sample_covers_the_dialect(self):
        want = {"heading", "paragraph", "orderedList", "bulletList", "listItem",
                "codeBlock", "mediaSingle", "media", "table", "tableRow",
                "tableHeader", "tableCell", "mention", "hardBreak", "text"}
        self.assertLessEqual(want, node_types(adf.to_adf(SAMPLE)))

    def test_check_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "doc.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"fields": {"description": adf.to_adf(SAMPLE)}}, fh)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(adf.main(["check", path]), 0)
            self.assertIn("OK", out.getvalue())


class ToAdf(unittest.TestCase):
    def test_heading_level_and_color(self):
        h = blocks("### Title {#2b9b62}")[0]
        self.assertEqual(h["attrs"]["level"], 3)
        self.assertEqual(h["content"][0]["marks"],
                         [{"type": "textColor", "attrs": {"color": "#2b9b62"}}])

    def test_color_never_stacks_on_code(self):
        h = blocks("## Run `x` now {#2b9b62}")[0]
        code = [n for n in h["content"] if n.get("marks", [{}])[0].get("type") == "code"]
        self.assertEqual(code[0]["marks"], [{"type": "code"}])

    def test_lone_numbered_line_is_paragraph(self):
        p = blocks("7. Hop title")[0]
        self.assertEqual(p, {"type": "paragraph",
                             "content": [{"type": "text", "text": "7. Hop title"}]})

    def test_two_numbered_lines_are_a_list(self):
        ol = blocks("4. a\n5. b")[0]
        self.assertEqual(ol["type"], "orderedList")
        self.assertEqual(ol["attrs"]["order"], 4)

    def test_escaped_number_is_text(self):
        self.assertEqual([b["type"] for b in blocks("1\\. a\n\n2\\. b")],
                         ["paragraph", "paragraph"])
        self.assertEqual(blocks("1\\. a")[0]["content"][0]["text"], "1. a")

    def test_headerless_table(self):
        t = blocks("|  |  |\n| --- | --- |\n| a | b |")[0]
        self.assertEqual([r["content"][0]["type"] for r in t["content"]], ["tableCell"])

    def test_image_attrs(self):
        m = blocks("![a.png](abc-1 =10x20)")[0]
        self.assertEqual(m["attrs"], {"layout": "center", "width": 10, "widthType": "pixel"})
        self.assertEqual(m["content"][0]["attrs"],
                         {"type": "file", "id": "abc-1", "collection": "",
                          "alt": "a.png", "width": 10, "height": 20})

    def test_paragraph_lines_merge(self):
        self.assertEqual(blocks("one\ntwo")[0]["content"][0]["text"], "one two")


class ToMd(unittest.TestCase):
    def doc(self, *content):
        return {"type": "doc", "version": 1, "content": list(content)}

    def test_finds_doc_inside_any_json(self):
        wrapped = [{"key": "X-1", "fields": {"description": adf.to_adf("hi")}}]
        self.assertEqual(adf.to_md(wrapped), "hi\n")

    def test_smart_link_becomes_link(self):
        p = {"type": "paragraph", "content": [
            {"type": "inlineCard", "attrs": {"url": "https://e.invalid/x"}}]}
        self.assertEqual(adf.to_md(self.doc(p)), "[https://e.invalid/x](https://e.invalid/x)\n")

    def test_underline_dropped(self):
        p = {"type": "paragraph", "content": [
            {"type": "text", "text": "u", "marks": [{"type": "underline"}]}]}
        self.assertEqual(adf.to_md(self.doc(p)), "u\n")

    def test_strict_on_unknown_nodes(self):
        bad = self.doc({"type": "panel", "content": []},
                       {"type": "paragraph", "content": [
                           {"type": "text", "text": "x",
                            "marks": [{"type": "strong"}, {"type": "em"}]}]})
        with self.assertRaises(adf.Outside) as err:
            adf.to_md(bad)
        self.assertIn("block node panel", str(err.exception))
        self.assertIn("stacked marks em+strong", str(err.exception))

    def test_merged_cell_rejected(self):
        t = {"type": "table", "content": [{"type": "tableRow", "content": [
            {"type": "tableCell", "attrs": {"colspan": 2}, "content": []}]}]}
        with self.assertRaises(adf.Outside):
            adf.to_md(self.doc(t))

    def test_paragraph_that_looks_like_a_block_is_escaped(self):
        p = {"type": "paragraph", "content": [{"type": "text", "text": "- x"}]}
        md = adf.to_md(self.doc(p))
        self.assertEqual(md, "\\- x\n")
        self.assertEqual(adf.to_adf(md)["content"][0], p)


class Cli(unittest.TestCase):
    def run_cli(self, *args, stdin=""):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin,
                              capture_output=True, text=True, encoding="utf-8")

    def test_pipe_both_ways(self):
        out = self.run_cli("to-adf", stdin="**hi** ✓")
        self.assertEqual(out.returncode, 0, out.stderr)
        back = self.run_cli("to-md", stdin=out.stdout)
        self.assertEqual(back.stdout, "**hi** ✓\n")

    def test_strict_exit_keeps_stdout_empty(self):
        doc = json.dumps({"type": "doc", "content": [{"type": "rule"}]})
        out = self.run_cli("to-md", stdin=doc)
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout, "")
        self.assertIn("block node rule", out.stderr)


if __name__ == "__main__":
    unittest.main()
