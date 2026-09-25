"""Contract tests with mocked HTTP. Run: python3 -m unittest discover -s dev/tests"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from model_cli import cli, core, http  # noqa: E402
from model_cli.backends import hf, openrouter, pollinations  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

OR_MODELS = {"data": [
    {"id": "z-ai/glm-5.2:free", "name": "GLM 5.2 (free)", "created": 2,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["temperature", "max_tokens"],
     "default_parameters": {"temperature": 0.7}, "context_length": 32768},
    {"id": "qwen/qwen-max", "name": "Qwen Max", "created": 3,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
     "pricing": {"prompt": "0.000004", "completion": "0.000012", "overrides": {"x": 1}}},
    {"id": "google/img-gen", "name": "Img Gen", "created": 1,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["image", "text"]},
     "pricing": {"prompt": "0", "completion": "0"}},
]}
HF_LIST = [
    {"id": "black-forest-labs/FLUX.1-schnell", "pipeline_tag": "text-to-image", "likes": 6000,
     "inferenceProviderMapping": [{"provider": "fal-ai", "status": "live", "task": "text-to-image"}]},
    {"id": "dead/model", "pipeline_tag": "text-to-image", "likes": 5,
     "inferenceProviderMapping": [{"provider": "x", "status": "error", "task": "text-to-image"}]},
]
HF_ONE = {"id": "black-forest-labs/FLUX.1-schnell", "pipeline_tag": "text-to-image", "likes": 6000,
          "inferenceProviderMapping": {"fal-ai": {"status": "live", "task": "text-to-image"}}}
SPEC = {"properties": {"inputs": {"type": "string"}, "parameters": {"$ref": "#/$defs/P"}},
        "$defs": {"P": {"properties": {"width": {"type": "integer", "description": "W"},
                                       "seed": {"type": "integer"}}}}}
POLL = [{"name": "openai/gpt-5.4-nano", "aliases": ["openai"], "category": "text", "pricing": {"currency": "pollen"},
         "paid_only": False, "supported_parameters": ["max_tokens"]}]


class FakeNet:
    """Route mocked requests by URL substring; record calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, method, url, *, headers=None, body=None, timeout=60):
        self.calls.append((method, url, body, headers or {}))
        for key, resp in self.routes:
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                if isinstance(resp, tuple):
                    return resp
                return 200, {"Content-Type": "application/json"}, json.dumps(resp).encode()
        raise AssertionError(f"unmocked URL {url}")


def run_cli(argv, routes, env=None):
    net = FakeNet(routes)
    out, err = io.StringIO(), io.StringIO()
    openrouter._catalog = None
    pollinations._catalog = None
    tmp = tempfile.mkdtemp()
    envs = {"MODEL_CLI_TEST": "1", **(env or {})}
    clear = [k for k in ("HF_TOKEN", "OPENROUTER_API_KEY", "POLLINATIONS_API_KEY") if k not in envs]
    with mock.patch.object(http, "request", net), \
            mock.patch.dict(os.environ, envs), \
            mock.patch.object(core, "OUT_DIR", Path(tmp)), \
            mock.patch.object(core, "CONFIG_PATH", Path(tmp) / "none.json"), \
            mock.patch.object(cli, "CONFIG_PATH", Path(tmp) / "none.json"), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        for k in clear:
            os.environ.pop(k, None)
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue(), net


class ParseTests(unittest.TestCase):
    def test_split_ref(self):
        self.assertEqual(cli.split_ref("hf:a/b"), ("hf", "a/b"))
        self.assertEqual(cli.split_ref("or:z/glm:free"), ("openrouter", "z/glm:free"))
        self.assertEqual(cli.split_ref("z/glm:free"), (None, "z/glm:free"))
        self.assertEqual(cli.split_ref("a/b", "or"), ("openrouter", "a/b"))

    def test_params_auto_typed(self):
        ns = mock.Mock(param=["steps=4", "g=0.5", "flag=true", "name=abc", "l=[1,2]"], params_json='{"x": 1}')
        self.assertEqual(cli.parse_params(ns), {"x": 1, "steps": 4, "g": 0.5, "flag": True, "name": "abc", "l": [1, 2]})

    def test_bad_params_json_is_usage(self):
        code, _, err, _ = run_cli(["run", "hf:a/b", "x", "--params-json", "{bad"], [])
        self.assertEqual(code, 2)
        self.assertIn("--params-json", err)

    def test_long_prompt_is_text_not_path(self):
        prompt = "a flat illustration, " * 30  # one path component > 255 bytes
        self.assertEqual(cli.read_input(prompt, None), {"text": prompt})

    def test_sniff(self):
        self.assertEqual(core.sniff_ext(PNG, "bin"), "png")
        self.assertEqual(core.sniff_ext(b"RIFF\0\0\0\0WAVEfmt", "bin"), "wav")
        self.assertEqual(core.sniff_ext(b"\0\0\0\x18ftypmp42", "bin"), "mp4")


class SearchInfoTests(unittest.TestCase):
    routes = [("openrouter.ai/api/v1/models", OR_MODELS), ("huggingface.co/api/models", HF_LIST),
              ("gen.pollinations.ai/models", POLL)]

    def test_search_free_default_hides_paid_and_dead(self):
        code, out, err, net = run_cli(["search", "", "--task", "llm"], self.routes)
        self.assertEqual(code, 0)
        self.assertIn("openrouter:z-ai/glm-5.2:free", out)
        self.assertNotIn("qwen-max", out)
        self.assertIn("free-only filter on", err)
        hf_call = [c for c in net.calls if "huggingface.co" in c[1]][0][1]
        self.assertIn("pipeline_tag=text-generation", hf_call)
        self.assertIn("inference_provider=all", hf_call)

    def test_search_all_shows_paid_json_fields(self):
        code, out, _, _ = run_cli(["search", "qwen", "--all", "--backend", "or", "-j", "--fields", "id,free"],
                                  self.routes)
        self.assertEqual(json.loads(out), [{"id": "openrouter:qwen/qwen-max", "free": "no"}])

    def test_search_hf_drops_non_live(self):
        code, out, _, _ = run_cli(["search", "flux", "--task", "image", "--backend", "hf", "--no-header"],
                                  self.routes)
        self.assertEqual(out.strip().splitlines()[0].split("\t")[0], "hf:black-forest-labs/FLUX.1-schnell")
        self.assertNotIn("dead/model", out)

    def test_search_cap_announced(self):
        _, _, err, _ = run_cli(["search", "", "--task", "image", "--limit", "1"], self.routes)
        self.assertIn("showing 1 (limit 1)", err)

    def test_info_hf_schema(self):
        routes = [("huggingface.co/api/models/", HF_ONE), ("raw.githubusercontent.com", SPEC)]
        code, out, err, _ = run_cli(["info", "hf:black-forest-labs/FLUX.1-schnell", "-j"], routes)
        j = json.loads(out)
        self.assertEqual([p["name"] for p in j["params"]], ["width", "seed"])
        self.assertEqual(j["params"][0]["type"], "integer")

    def test_info_openrouter_bare_id(self):
        code, out, _, _ = run_cli(["info", "z-ai/glm-5.2:free"], self.routes)
        self.assertEqual(code, 0)
        self.assertIn("temperature\t\t0.7", out)

    def test_not_found_exit1(self):
        routes = self.routes[:1] + [("huggingface.co/api/models/", http.HttpError(404, "nope", "u"))]
        code, _, err, _ = run_cli(["info", "no/such"], routes)
        self.assertEqual(code, 1)
        self.assertIn("not found", err)


class RunTests(unittest.TestCase):
    def test_paid_guard_exit3_nothing_sent(self):
        code, _, err, net = run_cli(["run", "or:qwen/qwen-max", "hi"], [("api/v1/models", OR_MODELS)],
                                    env={"OPENROUTER_API_KEY": "k"})
        self.assertEqual(code, 3)
        self.assertFalse([c for c in net.calls if c[0] == "POST"])

    def test_missing_token_exit2_with_signup(self):
        code, _, err, _ = run_cli(["run", "z-ai/glm-5.2:free", "hi"], [("api/v1/models", OR_MODELS)])
        self.assertEqual(code, 2)
        self.assertIn("https://openrouter.ai/settings/keys", err)

    def test_openrouter_text(self):
        resp = {"model": "z-ai/glm-5.2", "choices": [{"message": {"content": "pong"}}], "usage": {"cost": 0}}
        code, out, _, net = run_cli(["run", "z-ai/glm-5.2:free", "ping", "--param", "max_tokens=5"],
                                    [("api/v1/models", OR_MODELS), ("chat/completions", resp)],
                                    env={"OPENROUTER_API_KEY": "k"})
        self.assertEqual(code, 0)
        j = json.loads(out)
        self.assertEqual((j["text"], j["backend"], j["task"], j["cost"]), ("pong", "openrouter", "llm", 0))
        body = [c for c in net.calls if c[0] == "POST"][0][2]
        self.assertEqual(body["max_tokens"], 5)
        self.assertIn("duration_ms", j)

    def test_openrouter_image_output_saved(self):
        url = "data:image/png;base64," + base64.b64encode(PNG).decode()
        resp = {"choices": [{"message": {"content": "", "images": [{"image_url": {"url": url}}]}}]}
        d = tempfile.mkdtemp()
        code, out, _, net = run_cli(["run", "or:google/img-gen", "a fox", "-o", d + "/"],
                                    [("api/v1/models", OR_MODELS), ("chat/completions", resp)],
                                    env={"OPENROUTER_API_KEY": "k"})
        j = json.loads(out)
        self.assertTrue(j["path"].startswith(d) and j["path"].endswith(".png"))
        self.assertEqual(Path(j["path"]).read_bytes(), PNG)
        self.assertEqual([c for c in net.calls if c[0] == "POST"][0][2]["modalities"], ["image", "text"])

    def test_provider_error_verbatim(self):
        err_exc = http.HttpError(400, "max_tokens: must be <= 4096", "u")
        code, _, err, _ = run_cli(["run", "z-ai/glm-5.2:free", "hi"],
                                  [("api/v1/models", OR_MODELS), ("chat/completions", err_exc)],
                                  env={"OPENROUTER_API_KEY": "k"})
        self.assertEqual(code, 1)
        self.assertIn("max_tokens: must be <= 4096", err)

    def test_hf_image_bytes_and_extra_body(self):
        seen = {}

        class FakeClient:
            def text_to_image(self, prompt, *, width=None, model=None, extra_body=None):
                seen.update(prompt=prompt, width=width, model=model, extra_body=extra_body)
                return PNG

        with mock.patch.object(hf, "_client", lambda cfg: FakeClient()):
            code, out, _, _ = run_cli(["run", "hf:black-forest-labs/FLUX.1-schnell", "fox",
                                       "--param", "width=512", "--param", "lora=x"],
                                      [("huggingface.co/api/models/", HF_ONE)], env={"HF_TOKEN": "t"})
        j = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(j["path"].endswith(".png"))
        self.assertEqual(seen, {"prompt": "fox", "width": 512, "model": "black-forest-labs/FLUX.1-schnell",
                                "extra_body": {"lora": "x"}})

    def test_shortcut_falls_back_to_keyless(self):
        routes = [("text.pollinations.ai/", (200, {"Content-Type": "text/plain"}, b"pong\n")),
                  ("api/v1/models", OR_MODELS)]
        code, out, _, _ = run_cli(["llm", "ping"], routes)
        j = json.loads(out)
        self.assertEqual((code, j["text"], j["model"], j["cost"]), (0, "pong", "pollinations:default", 0))

    def test_shortcut_no_usable_default_names_first_token(self):
        code, _, err, _ = run_cli(["asr", "x.mp3"], [])
        self.assertEqual(code, 2)
        self.assertIn("HF_TOKEN", err)

    def test_pollinations_default_needs_task_on_run(self):
        code, _, err, _ = run_cli(["run", "pollinations:default", "hi"], [])
        self.assertEqual(code, 2)
        self.assertIn("--task", err)

    def test_pollinations_retry_then_error(self):
        err_exc = http.HttpError(500, "Internal Server Error", "u")
        with mock.patch("time.sleep"):
            code, _, err, net = run_cli(["run", "pollinations:default", "fox", "--task", "image"],
                                        [("image.pollinations.ai", err_exc)])
        self.assertEqual(code, 1)
        self.assertEqual(len(net.calls), 2)

    def test_llm_text_output_file(self):
        routes = [("text.pollinations.ai/", (200, {}, b"hello"))]
        d = tempfile.mkdtemp()
        code, out, _, _ = run_cli(["llm", "hi", "-o", d + "/a.txt"], routes + [("api/v1/models", OR_MODELS)])
        self.assertEqual(Path(d, "a.txt").read_text(), "hello")
        self.assertEqual(json.loads(out)["path"], d + "/a.txt")


if __name__ == "__main__":
    unittest.main()
