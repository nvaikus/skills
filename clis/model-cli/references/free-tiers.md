# Free tiers - non-obvious facts

## Hugging Face Inference Providers
- Free account = $0.10/month routed credit (PRO $2). Exhausted → 402 until next month or bought credits. `free` column `credit` means this pool.
- One fal-ai FLUX.1-schnell image costs about $0.003; a text-to-video run usually exceeds the whole $0.10 → `video` is effectively not free.
- The Hub lists a provider mapping with `status: error` for dead routes; `search` keeps only models with a `live` provider. `hf_provider: auto` picks the first live one in the user's HF provider order (settings/inference-providers).
- Cost is not returned per call (`cost: null`); spend shows at huggingface.co/settings/billing.
- `hf-inference` (HF's own) serves mostly CPU tasks (embeddings, classification, whisper); image/video/tts go through fal-ai, replicate, wavespeed, deepinfra.
- Token: fine-grained with the "Make calls to Inference Providers" permission (the Inference preset at huggingface.co/settings/tokens).

## OpenRouter
- `:free` models: 20 req/min; 50 req/day total across all free models while lifetime purchases < $10, 1000/day after buying $10. Limits: `model-cli doctor` (GET /api/v1/key).
- `openrouter/free` routes to any free model; `served_by` in the result names the one used.
- Free image-output models: none at the time of writing (`search --task image --backend openrouter --all` lists paid ones). `google/lyria-3-*` are free audio-output previews but need streaming - `run` refuses audio output for now.
- Providers behind free models may log or train on prompts - never send secrets or customer data.

## Pollinations (keyless fallback)
- Without a key only the server-picked `pollinations:default` works: image via `image.pollinations.ai/prompt/...`, llm via `text.pollinations.ai/...`. Choosing `model=` or tts/video needs `POLLINATIONS_API_KEY`.
- Anonymous image: ~45 s per call, intermittent 500 (upstream 429); `run` retries once. Adds a pollinations.ai watermark even with `nologo=true`.
- `gen.pollinations.ai` rejects anonymous generation with 401 except for cached identical prompts (live-proven, do not "fix" to the new host).

## Paid fallback (image)
- `google/gemini-3.1-flash-lite-image` ≈ $0.034/image, ~4 s; aspect via `--params-json '{"image_config":{"aspect_ratio":"16:9"}}'` (1376×768). Returns JPEG even when `-o` says `.png`.
