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

from model_cli import audio, cli, core, http, onboarding  # noqa: E402
from model_cli.backends import compat, hf, openrouter, pollinations  # noqa: E402

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
                if callable(resp):
                    resp = resp()
                    if isinstance(resp, Exception):
                        raise resp
                return 200, {"Content-Type": "application/json"}, json.dumps(resp).encode()
        raise AssertionError(f"unmocked URL {url}")


def run_cli(argv, routes, env=None):
    net = FakeNet(routes)
    out, err = io.StringIO(), io.StringIO()
    openrouter._catalog = None
    pollinations._catalog = None
    tmp = tempfile.mkdtemp()
    envs = {"MODEL_CLI_TEST": "1", **(env or {})}
    every = {e for m in cli.BACKENDS.values() for e in (getattr(m, "ENVS", None) or [m.ENV])}
    clear = [k for k in every if k not in envs]
    for m in cli.BACKENDS.values():
        if isinstance(m, compat.Compat):
            m._live = None
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


class DefectFixTests(unittest.TestCase):
    OR_ROUTES = [("api/v1/models", OR_MODELS)]

    def test_search_multi_word(self):
        code, out, _, _ = run_cli(["search", "glm", "5.2", "--backend", "or", "--no-header"],
                                  SearchInfoTests.routes)
        self.assertEqual(code, 0)
        self.assertIn("openrouter:z-ai/glm-5.2:free", out)

    def test_no_reasoning_and_max_tokens(self):
        resp = {"choices": [{"message": {"content": "ok"}}]}
        code, _, _, net = run_cli(["run", "z-ai/glm-5.2:free", "hi", "--no-reasoning", "--max-tokens", "300"],
                                  self.OR_ROUTES + [("chat/completions", resp)], env={"OPENROUTER_API_KEY": "k"})
        body = [c for c in net.calls if c[0] == "POST"][0][2]
        self.assertEqual((code, body["reasoning"], body["max_tokens"]), (0, {"enabled": False}, 300))

    def test_empty_length_output_announced(self):
        resp = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        _, _, err, _ = run_cli(["run", "z-ai/glm-5.2:free", "hi"], self.OR_ROUTES + [("chat/completions", resp)],
                               env={"OPENROUTER_API_KEY": "k"})
        self.assertIn("--no-reasoning", err)

    def test_openrouter_429_backoff(self):
        replies = [http.HttpError(429, "temporarily rate-limited upstream", "u")] * 2 + \
                  [{"choices": [{"message": {"content": "pong"}}]}]
        with mock.patch("time.sleep") as sl:
            code, out, err, _ = run_cli(["run", "z-ai/glm-5.2:free", "hi"],
                                        self.OR_ROUTES + [("chat/completions", lambda: replies.pop(0))],
                                        env={"OPENROUTER_API_KEY": "k"})
        self.assertEqual((code, json.loads(out)["text"]), (0, "pong"))
        self.assertEqual([c.args[0] for c in sl.call_args_list], [4, 8])
        self.assertIn("retry 1/3", err)

    def test_hf_vision_sends_image(self):
        seen = {}

        class FakeClient:
            def chat_completion(self, *, messages, model=None, max_tokens=None, extra_body=None):
                seen["content"] = messages[0]["content"]
                return mock.Mock(choices=[mock.Mock(message=mock.Mock(content="a fox"))])

        vlm = {"id": "q/vl", "pipeline_tag": "image-text-to-text",
               "inferenceProviderMapping": {"x": {"status": "live", "task": "image-text-to-text"}}}
        img = Path(tempfile.mkdtemp(), "t.png")
        img.write_bytes(PNG)
        with mock.patch.object(hf, "_client", lambda cfg: FakeClient()):
            code, out, err, _ = run_cli(["run", "hf:q/vl", str(img), "--prompt", "what?", "--no-reasoning"],
                                        [("huggingface.co/api/models/", vlm)], env={"HF_TOKEN": "t"})
        self.assertEqual((code, json.loads(out)["text"]), (0, "a fox"))
        self.assertEqual(seen["content"][0], {"type": "text", "text": "what?"})
        self.assertTrue(seen["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertIn("ignored on hf", err)


GROQ = {"GROQ_API_KEY": "g"}
CF = {"CLOUDFLARE_API_TOKEN": "c", "CLOUDFLARE_ACCOUNT_ID": "acc1"}


def _audio(name="a.ogg", size=100):
    p = Path(tempfile.mkdtemp(), name)
    p.write_bytes(b"OggS" + b"0" * size)
    return p


class FreeBackendTests(unittest.TestCase):
    def test_asr_default_routes_to_groq_multipart(self):
        f = _audio()
        code, out, _, net = run_cli(["asr", str(f), "--param", "language=ru"],
                                    [("api.groq.com/openai/v1/audio/transcriptions", {"text": "privet"})], env=GROQ)
        j = json.loads(out)
        self.assertEqual((code, j["text"], j["model"], j["cost"]), (0, "privet", "groq:whisper-large-v3-turbo", 0))
        method, url, body, hdrs = net.calls[0]
        self.assertIn("multipart/form-data; boundary=", hdrs["Content-Type"])
        self.assertEqual(hdrs["Authorization"], "Bearer g")
        self.assertIn(b'name="model"\r\n\r\nwhisper-large-v3-turbo', body)
        self.assertIn(b'name="language"\r\n\r\nru', body)
        self.assertIn(b'filename="a.ogg"', body)

    def test_asr_no_token_lists_every_free_option(self):
        code, _, err, _ = run_cli(["asr", str(_audio())], [])
        self.assertEqual(code, 2)
        for env in ("GROQ_API_KEY", "GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN", "HF_TOKEN", "model-cli setup"):
            self.assertIn(env, err)

    def test_asr_oversize_is_chunked_and_joined(self):
        f = _audio("big.wav", 50)
        parts = [str(_audio("p1.ogg")), str(_audio("p2.ogg"))]
        replies = [{"text": "one"}, {"text": "two"}]
        with mock.patch.object(audio, "prepare", lambda p, mx, fm: parts) as _:
            code, out, _, net = run_cli(["run", "groq:whisper-large-v3", str(f)],
                                        [("audio/transcriptions", lambda: replies.pop(0))], env=GROQ)
        self.assertEqual((code, json.loads(out)["text"]), (0, "one\ntwo"))
        self.assertEqual(len(net.calls), 2)

    def test_prepare_fits_as_is_and_needs_ffmpeg_otherwise(self):
        f = _audio("a.ogg", 10)
        self.assertEqual(audio.prepare(str(f), 1000, {"ogg"}), [str(f)])
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(core.UsageError) as e:
                audio.prepare(str(f), 5, {"ogg"})
        self.assertIn("ffmpeg", str(e.exception))

    def test_gemini_llm_interactions_shape(self):
        resp = {"steps": [{"type": "thought", "content": [{"type": "text", "text": "hmm"}]},
                          {"type": "model_output", "content": [{"type": "text", "text": "pong"}]}]}
        code, out, _, net = run_cli(["llm", "ping", "-m", "gemini:gemini-3.5-flash", "--no-reasoning",
                                     "--max-tokens", "50", "--param", "system_instruction=terse"],
                                    [("v1beta/interactions", resp)], env={"GEMINI_API_KEY": "k"})
        self.assertEqual((code, json.loads(out)["text"]), (0, "pong"))
        _, url, body, hdrs = net.calls[0]
        self.assertEqual(hdrs["x-goog-api-key"], "k")
        self.assertEqual(body["input"], [{"type": "text", "text": "ping"}])
        self.assertEqual(body["generation_config"], {"thinking_level": "low", "max_output_tokens": 50})
        self.assertEqual(body["system_instruction"], "terse")

    def test_gemini_asr_sends_inline_audio(self):
        resp = {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "hello"}]}]}
        code, out, _, net = run_cli(["asr", str(_audio()), "-m", "gemini:gemini-3.5-flash"],
                                    [("v1beta/interactions", resp)], env={"GEMINI_API_KEY": "k"})
        self.assertEqual((code, json.loads(out)["text"]), (0, "hello"))
        part = net.calls[0][2]["input"][1]
        self.assertEqual((part["type"], part["mime_type"]), ("audio", "audio/ogg"))
        self.assertIn("Transcribe", net.calls[0][2]["input"][0]["text"])

    def test_gemini_tts_pcm_wrapped_to_wav(self):
        pcm = base64.b64encode(b"\0\1" * 100).decode()
        resp = {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": pcm}]}]}
        code, out, _, net = run_cli(["tts", "hello", "--param", "voice=Puck"], [("v1beta/interactions", resp)],
                                    env={"GEMINI_API_KEY": "k"})
        j = json.loads(out)
        self.assertEqual((code, j["model"]), (0, "gemini:gemini-3.8-flash-tts"))
        self.assertTrue(j["path"].endswith(".wav"))
        self.assertEqual(Path(j["path"]).read_bytes()[:4], b"RIFF")
        body = net.calls[0][2]
        self.assertEqual(body["generation_config"]["speech_config"], [{"voice": "Puck"}])
        self.assertEqual(body["response_format"], {"type": "audio"})

    def test_google_list_error_shape_verbatim(self):
        self.assertEqual(http._error_text('[{"error": {"code": 400, "message": "API key not valid."}}]'),
                         "API key not valid.")

    def test_cloudflare_image_and_account_url(self):
        jpg = b"\xff\xd8\xff" + b"0" * 10
        resp = {"result": {"image": base64.b64encode(jpg).decode()}, "success": True}
        code, out, _, net = run_cli(["image", "a fox", "--param", "steps=4"],
                                    [("accounts/acc1/ai/run/@cf/black-forest-labs/flux-1-schnell", resp)], env=CF)
        j = json.loads(out)
        self.assertEqual((code, j["backend"]), (0, "cloudflare"))
        self.assertTrue(j["path"].endswith(".jpg"))
        self.assertEqual(net.calls[0][2], {"prompt": "a fox", "steps": 4})

    def test_cloudflare_needs_account_id_too(self):
        code, _, err, _ = run_cli(["run", "cf:@cf/openai/gpt-oss-120b", "hi"], [],
                                  env={"CLOUDFLARE_API_TOKEN": "c"})
        self.assertEqual(code, 2)
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", err)

    def test_cloudflare_error_envelope(self):
        self.assertEqual(http._error_text('{"success":false,"errors":[{"code":10000,"message":"Authentication error"}]}'),
                         "Authentication error")

    def test_search_lists_quota_models_without_keys(self):
        code, out, _, net = run_cli(["search", "whisper", "--task", "asr", "--backend", "groq,cf", "--no-header"], [])
        self.assertEqual(code, 0)
        self.assertIn("groq:whisper-large-v3-turbo\tgroq\tasr\tquota", out)
        self.assertIn("cloudflare:@cf/openai/whisper-large-v3-turbo", out)
        self.assertEqual(net.calls, [])

    def test_groq_live_list_merged_when_key_set(self):
        live = {"data": [{"id": "whisper-large-v3-turbo"}, {"id": "new/llm-x"}]}
        code, out, _, _ = run_cli(["search", "llm-x", "--backend", "groq", "--no-header"],
                                  [("api.groq.com/openai/v1/models", live)], env=GROQ)
        self.assertIn("groq:new/llm-x\tgroq\tllm", out)

    def test_groq_no_reasoning_gpt_oss(self):
        resp = {"choices": [{"message": {"content": "ok"}}]}
        code, _, _, net = run_cli(["llm", "hi", "--no-reasoning"], [("chat/completions", resp)], env=GROQ)
        body = net.calls[0][2]
        self.assertEqual((code, body["model"], body["reasoning_effort"]), (0, "openai/gpt-oss-120b", "low"))

    def test_setup_table_probe_and_steps(self):
        routes = [("api.groq.com", http.HttpError(401, "Invalid API Key", "u"))]
        code, out, err, _ = run_cli(["setup", "-j", "--fields", "backend,status"], routes, env=GROQ)
        rows = {r["backend"]: r["status"] for r in json.loads(out)}
        self.assertEqual(rows["groq"], "invalid (HTTP 401: Invalid API Key)")
        self.assertTrue(rows["gemini"].startswith("missing GEMINI_API_KEY"))
        code, out, _, net = run_cli(["setup", "cloudflare", "--no-probe"], [])
        self.assertEqual((code, net.calls), (0, []))
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", out)
        self.assertIn("security add-generic-password" if onboarding.USE_KEYCHAIN else "chmod 600", out)
        self.assertIn("Workers AI", out)

    def test_openrouter_audio_transcoded_to_mp3(self):
        f = _audio("v.ogg")
        mp3 = Path(tempfile.mkdtemp(), "v.mp3")
        mp3.write_bytes(b"ID3" + b"0" * 10)
        resp = {"choices": [{"message": {"content": "hi"}}]}
        with mock.patch.object(audio, "prepare", return_value=[str(mp3)]) as prep:
            code, out, _, net = run_cli(["run", "z-ai/glm-5.2:free", str(f)],
                                        [("api/v1/models", OR_MODELS), ("chat/completions", resp)],
                                        env={"OPENROUTER_API_KEY": "k"})
        self.assertEqual(code, 0)
        self.assertEqual(prep.call_args.args[2], {"wav", "mp3"})
        part = [c for c in net.calls if c[0] == "POST"][0][2]["messages"][0]["content"][1]
        self.assertEqual(part["input_audio"]["format"], "mp3")


if __name__ == "__main__":
    unittest.main()
