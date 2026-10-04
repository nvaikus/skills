# Free tiers - non-obvious facts

Signup, limits and key steps per backend: `model-cli setup [backend]`. Below: only what that does not say.

## Groq
- Whisper free: 25 MB/file (dev tier 100 MB), min 10 s billed; `run` transcodes/chunks at 24 MB.
- Orpheus TTS is English/Arabic only; 100 req/day. May demand one-time terms acceptance in the console playground.
- gpt-oss cannot turn thinking off: `--no-reasoning` = `reasoning_effort=low`.

## Gemini (AI Studio key)
- Calls go to the Interactions API (`/v1beta/interactions`), not generateContent: new models land there only.
- Free: flash / flash-lite 3.x, 2.5-pro/flash, TTS 3.8-flash(-lite)-tts. No free image (Nano Banana), Veo, Lyria - they 429 with limit 0.
- Inline cap 20 MB per request incl. base64 -> `run` chunks audio at 14 MB. Audio = 32 tokens/s.
- TTS voices: Kore (default), Puck, Charon, ... (`--param voice=`); style goes in the text ("Say cheerfully: ...").
- Free tier: prompts may train Google models.

## Cloudflare Workers AI
- Needs two env vars: token + account id. 10k neurons/day shared by all models, reset 00:00 UTC; over the cap = error, no billing on the free plan.
- `@cf/openai/whisper-large-v3-turbo` takes base64 JSON; plain `@cf/openai/whisper` takes raw bytes (`run` handles both).
- Partner models (Deepgram nova/aura, Leonardo) bill outside the free neurons.

## Mistral
- Experiment plan = free, SMS-verified; prompts may be used for training.
- `voxtral-mini-latest` for ASR (13 languages incl. ru); vision via `mistral-small/medium-latest` + image file.

## Not wired (checked 2026-09)
- GitHub Models: retired 2026-07-30. Cerebras: free tier now needs a card + expiring credits.
- Azure AI Speech F0 (5 h STT + 0.5M chars TTS/month) and Google Cloud STT (60 min/month): free but need a card/billing account.

## Hugging Face Inference Providers
- Free account = $0.10/month routed credit (PRO $2). Exhausted → 402 until next month or bought credits. `free` column `credit` means this pool.
- Vision (image-text-to-text) calls drain it fast: ~20 image calls → 402.
- One fal-ai FLUX.1-schnell image costs about $0.003; a text-to-video run usually exceeds the whole $0.10 → `video` is effectively not free.
- The Hub lists a provider mapping with `status: error` for dead routes; `search` keeps only models with a `live` provider. `hf_provider: auto` picks the first live one in the user's HF provider order (settings/inference-providers).
- Cost is not returned per call (`cost: null`); spend shows at huggingface.co/settings/billing.
- `hf-inference` (HF's own) serves mostly CPU tasks (embeddings, classification, whisper); image/video/tts go through fal-ai, replicate, wavespeed, deepinfra.
- Token: fine-grained with the "Make calls to Inference Providers" permission (the Inference preset at huggingface.co/settings/tokens).

## OpenRouter
- `:free` models: 20 req/min; 50 req/day total across all free models while lifetime purchases < $10, 1000/day after buying $10. Limits: `model-cli doctor` (GET /api/v1/key).
- Free Gemma 4 / Qwen 3.8 vision models: upstream 429 on ~90% of calls even after `run`'s backoff → pick another model, don't retry harder.
- `thinkingmachines/inkling-small:free` / `inkling:free` return 403 outside agentic harnesses → skip them.
- No free ASR here: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` accepts `input_audio` but ignores it ("no audio was provided", or an unrelated answer); ogg is a 400. Cheapest working audio input: `google/gemini-2.5-flash-lite` (paid).
- `openrouter/free` routes to any free model; `served_by` in the result names the one used.
- Free audio-input (ASR-capable) models: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` often fails upstream `ResourceExhausted`; `inkling:free` 403 -> use a real asr backend. Audio input is wav/mp3 only (`run` converts).
- Free image-output models: none at the time of writing (`search --task image --backend openrouter --all` lists paid ones). `google/lyria-3-*` are free audio-output previews but need streaming - `run` refuses audio output for now.
- Providers behind free models may log or train on prompts - never send secrets or customer data.

## Pollinations (keyless fallback)
- Without a key only the server-picked `pollinations:default` works: image via `image.pollinations.ai/prompt/...`, llm via `text.pollinations.ai/...`. Choosing `model=` or tts/video needs `POLLINATIONS_API_KEY`.
- Anonymous image: ~45 s per call, intermittent 500 (upstream 429); `run` retries once. Adds a pollinations.ai watermark even with `nologo=true`.
- `gen.pollinations.ai` rejects anonymous generation with 401 except for cached identical prompts (live-proven, do not "fix" to the new host).

## Paid fallback (image)
- `google/gemini-3.1-flash-lite-image` ≈ $0.034/image, ~4 s; aspect via `--params-json '{"image_config":{"aspect_ratio":"16:9"}}'` (1376×768). Returns JPEG even when `-o` says `.png`.
