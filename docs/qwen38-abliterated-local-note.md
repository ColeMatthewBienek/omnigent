# Qwen3.8 Abliterated 27B for local Pi

Research date: 2026-08-19

## Recommendation

The requested model is transport-compatible with Pi through an
OpenAI-compatible Chat Completions endpoint. Use the exact model ID
`huihui_ai/Qwen3.8-abliterated:27b` and pull it with:

```sh
ollama pull huihui_ai/Qwen3.8-abliterated:27b
```

The deployed setup serves Ollama's verified model and projector blobs through
the bundled llama.cpp server at `http://localhost:8080/v1`, with a 65,536-token
context and the Chat Completions wire. The local Ollama 0.32.5 server loaded the
model but returned `unknown renderer "qwen3.8"`; direct llama.cpp serving avoids
that broken renderer layer. A live probe verified model discovery, ordinary
completion, and a structured tool call before Pi and Hindsight were switched.

Sources:

- [Ollama artifact and exact run name](https://ollama.com/huihui_ai/Qwen3.8-abliterated:27b)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Omnigent Pi OpenAI-provider routing](../omnigent/inner/pi_executor.py)

## Artifact and hardware implications

The current `:27b` manifest totals 17,741,871,760 bytes (shown as 18 GB by
Ollama). Its main model blob is a 27.3B-parameter `Q4_K_M` GGUF of about 17 GB;
the manifest also contains a vision projector. The model metadata declares a
262,144-token context window.

The local RTX 5090 reports 32,607 MiB VRAM. The weights should fit, but full GPU
residency at a large context is not guaranteed because the KV cache and runtime
allocations need memory in addition to the weights. Ollama defaults a 24–48
GiB GPU to 32K context while recommending at least 64K for agents and coding
tools. Start with one parallel request and 64K context, then use `ollama ps` to
confirm `100% GPU`; reduce context before accepting CPU offload if performance
is the priority. This sizing guidance is an inference from the published
artifact size, the observed GPU, and Ollama's memory guidance—not a measured
benchmark of this model on this machine.

Sources:

- [Artifact model metadata](https://ollama.com/huihui_ai/Qwen3.8-abliterated:27b/blobs/6c2c13cef892)
- [Ollama context and GPU-residency guidance](https://docs.ollama.com/context-length)
- [Ollama memory and parallelism FAQ](https://docs.ollama.com/faq)

## Context and rollout caveats

The OpenAI-compatible API cannot set context size per request. The deployed
`qwen-local.service` pins llama.cpp to 65,536 tokens and one parallel slot;
change the service setting before evaluating a different context policy.

The tag is publisher-maintained rather than an official Ollama-library Qwen
artifact, and “abliterated” denotes modified behavior. Its tool badge alone
does not prove reliable structured calls or safe behavior. Before deleting a
prior model, test prompt adherence, malformed-tool-call recovery, multi-turn
tool results, long-context work, and output safety.

Before migration, the local llama.cpp endpoint on port 8080 advertised
`thinkingcap`. After migration, the same protected endpoint advertises
`huihui_ai/Qwen3.8-abliterated:27b`, preserving the network contract used by
Hindsight while replacing the model and service definition.

Source: [Ollama context configuration for OpenAI clients](https://docs.ollama.com/api/openai-compatibility#setting-the-context-size)
