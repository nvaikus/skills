"""Body text: quote/signature stripping and HTML conversion (pure functions)."""
import json
import unittest
from pathlib import Path

import support  # noqa: F401

from src.api import render  # noqa: E402


class TestStrip(unittest.TestCase):
    def strip(self, text, subject=""):
        return render.strip(text, subject)[0]

    def test_gmail_wrote(self):
        t = "Sure, 5pm.\n\nOn Tue, Mar 4, 2026 at 9:12 AM Anna <a@x.com> wrote:\n> can we meet?\n"
        self.assertEqual(self.strip(t), "Sure, 5pm.")

    def test_wrote_split_over_two_lines(self):
        t = "Ok\n\nOn Tue, Mar 4, 2026 at 9:12 AM Anna Very Long Name <\na@x.com> wrote:\n> hi"
        self.assertEqual(self.strip(t), "Ok")

    def test_russian(self):
        t = "Да, подходит.\n\nвт, 4 мар. 2026 г. в 09:12, Анна <a@x.com>:\n> встретимся?"
        self.assertEqual(self.strip(t), "Да, подходит.")

    def test_outlook_block(self):
        t = "Approved.\n\n________________________________\nFrom: Bob <b@x.com>\nSent: Monday\nTo: me\nSubject: Q\n\nold"
        self.assertEqual(self.strip(t), "Approved.")

    def test_forward_keeps_body(self):
        t = "FYI\n\n---------- Forwarded message ---------\nFrom: Bob <b@x.com>\nDate: Mon\nSubject: Q\nTo: me\n\nthe content"
        self.assertIn("the content", self.strip(t, "Fwd: Q"))

    def test_signature_and_mobile(self):
        self.assertEqual(self.strip("Yes\n\nSent from my iPhone"), "Yes")
        self.assertEqual(self.strip("Yes\n-- \nBob\n+1 555"), "Yes")

    def test_plain_sentence_with_wrote_kept(self):
        t = "Here is what she wrote:\nthe plan is fine"
        self.assertEqual(self.strip(t), t)


class TestHtml(unittest.TestCase):
    def test_links_lists_and_quotes(self):
        h = ("<div>Hi<br>see <a href='https://x.com/a'>doc</a></div><ul><li>one</li><li>two</li></ul>"
             "<div class='gmail_quote'>On ... wrote:<blockquote>old</blockquote></div>")
        t = render.html_to_text(h)
        self.assertIn("[doc](https://x.com/a)", t)
        self.assertIn("one", t)
        self.assertNotIn("old", render.strip(t)[0])

    def test_long_tracking_url_dropped(self):
        t = render.html_to_text(f"<a href='https://t.co/{'x' * 300}'>Click</a>")
        self.assertEqual(t, "Click")


class TestCharset(unittest.TestCase):
    def test_mislabeled_latin_header_utf8_body(self):
        """ActivoBank: Content-Type charset ISO-8859-15, bytes UTF-8 -> was 'informaÃ§Ã£o'."""
        fx = json.loads((Path(__file__).parent / "fixtures" / "mislabeled_charset.json").read_text("utf-8"))
        plain, htm = render.bodies(fx["payload"])
        t = render.html_to_text(htm)
        self.assertIsNone(plain)
        self.assertIn("Aqui está a informação dos seus movimentos, são 12 meses.", t)
        self.assertIn("Olá,", t)
        self.assertIn("Conservatória do Registo, n.º 23.", t)
        self.assertNotRegex(t, "[ÃÂ]")

    def test_declared_charset_honored(self):
        self.assertEqual(render.decode_text("são".encode("latin-1"), "iso-8859-1"), "são")
        self.assertEqual(render.decode_text("Привет".encode("koi8-r"), "koi8-r"), "Привет")
        self.assertEqual(render.decode_text("Привет".encode("cp1251"), "windows-1251"), "Привет")
        self.assertEqual(render.decode_text("日本語".encode("shift_jis"), "shift_jis"), "日本語")

    def test_missing_or_unknown_charset(self):
        self.assertEqual(render.decode_text("são".encode()), "são")
        self.assertEqual(render.decode_text("são".encode(), "x-bogus"), "são")
        self.assertEqual(render.decode_text("são".encode("latin-1")), "são")
        self.assertEqual(render.decode_text("são".encode("latin-1"), "us-ascii"), "são")

    def test_double_encoded_repaired(self):
        self.assertEqual(render.decode_text("sÃ£o â€“ 5â‚¬".encode(), "utf-8"), "são – 5€")
        self.assertEqual(render.html_to_text("<p>s&Atilde;&pound;o</p>"), "são")

    def test_genuine_latin_text_kept(self):
        for s in ("Ãgua", "café – bar", "À la carte", "naïve Æsir"):
            self.assertEqual(render.decode_text(s.encode(), "utf-8"), s)


class TestHttpErrorText(unittest.TestCase):
    def test_html_error_page_is_summarized(self):
        from src.core.http import _msg
        page = "<html>\n <head><title>403  Forbidden</title><style>a{b:c}</style></head><body>x</body></html>"
        self.assertEqual(_msg(page), "html page: 403 Forbidden")
        self.assertEqual(_msg("<!DOCTYPE html><p>no title</p>"), "html page")
        self.assertEqual(_msg("plain\n  text"), "plain text")


if __name__ == "__main__":
    unittest.main()
