# Local coding model recommendation for RTX 5090

Research date: 2026-08-09

## Recommendation

Replace `laguna-xs-2.1:latest` with `qwen3.6:27b` (`Q4_K_M`) as the primary local coding-agent model.

This recommendation is for the current use case: local Ollama inference used by a coding-agent harness. The current machine has an RTX 5090 with 32 GB VRAM. Although the PC has 64 GB physical RAM, WSL is configured with `memory=24GB`; recommendations that require CPU offload into 40–60 GB of system RAM are therefore not viable without changing `.wslconfig`.

The official Ollama build of Qwen3.6 27B is 17 GB, supports tools, thinking, vision, and a 256K context window. It should fit wholly in 32 GB VRAM with room for a useful KV cache. The currently installed Laguna XS 2.1 build is 20 GB (`Q4_K_M`), so Qwen also reduces model-weight VRAM by roughly 3 GB.

## Why Qwen3.6 27B

The first-party benchmark evidence favors Qwen3.6 27B over Laguna XS 2.1 for the relevant work:

| Model | Ollama Q4 size | SWE-bench Verified | SWE-bench Pro | Terminal-Bench 2.0 | Relevant strengths |
| --- | ---: | ---: | ---: | ---: | --- |
| Qwen3.6 27B | 17 GB | 77.2 | 53.5 | 59.3 | Tools, preserved thinking, vision, repo-level coding |
| Laguna XS 2.1 | 20 GB | 70.9 | 47.6 | 37.5 | Tools, interleaved thinking, coding specialization |
| GLM-4.7-Flash | 19 GB | 59.2 | Not reported | Not reported | Fast 30B-A3B MoE, tools, thinking |

Qwen also reports 48.2 on SkillsBench evaluated through OpenCode, 36.2 on NL2Repo, and a native 262,144-token context. Its 27B dense model outscored its own 35B-A3B variant on every listed coding-agent benchmark, so the larger/faster MoE is not the quality pick for this machine.

These scores are vendor-reported, use different harnesses in some cases, and generally evaluate higher-precision checkpoints rather than the Ollama Q4 builds. They are useful screening evidence, not proof that the quantized model will be better in this exact harness. Run an A/B acceptance suite before removing Laguna.

Sources:

- [Qwen3.6-27B official model card and benchmark methodology](https://huggingface.co/Qwen/Qwen3.6-27B)
- [Official Ollama Qwen3.6 library entry](https://ollama.com/library/qwen3.6)
- [Official Ollama Qwen3.6 27B Q4_K_M artifact](https://ollama.com/library/qwen3.6:27b)
- [Laguna XS 2.1 official model card and benchmarks](https://huggingface.co/poolside/Laguna-XS-2.1)
- [GLM-4.7-Flash official model card](https://huggingface.co/zai-org/GLM-4.7-Flash)
- [Official Ollama GLM-4.7-Flash artifact](https://ollama.com/library/glm-4.7-flash)

## Serving profile

Start with:

- Model: `qwen3.6:27b`
- Context: 128K
- Parallel requests: 1 while validating memory use
- Flash Attention: enabled
- KV cache quantization: `q8_0`
- Thinking: enabled for long-horizon implementation and debugging
- Coding sampling: temperature `0.6`, top-p `0.95`, top-k `20`

Qwen recommends retaining at least 128K context for its thinking behavior. Ollama recommends at least 64K for coding tools and agents. If `ollama ps` does not show 100% GPU residency at 128K, reduce to 64K before accepting CPU offload. Parallel requests multiply context memory, so validate a single request first.

Sources:

- [Ollama context-length guidance](https://docs.ollama.com/context-length)
- [Ollama FAQ: Flash Attention, KV cache quantization, and parallel context memory](https://docs.ollama.com/faq)
- [Qwen3.6 official sampling and context guidance](https://huggingface.co/Qwen/Qwen3.6-27B)

## Alternatives not selected

### GLM-4.7-Flash

The best speed-oriented fallback. Its 30B-A3B MoE activates only 3B parameters and its official Ollama Q4 build is 19 GB. Its published SWE-bench result is well below Qwen3.6 27B, so choose it only if interactive speed matters more than coding-agent completion rate.

### Qwen3-Coder-Next

Strong coding specialization, 256K context, and only 3B active parameters, but its official Ollama Q4 build is 52 GB. It cannot reside in 32 GB VRAM and also exceeds the current 24 GB WSL RAM cap. CPU/GPU offload would undermine the main benefit of the 5090 and is not a sensible default here.

Source: [Official Ollama Qwen3-Coder-Next artifact](https://ollama.com/library/qwen3-coder-next)

### NVIDIA Nemotron 3 Nano 30B-A3B

Efficient and capable, with NVIDIA-native FP8 support and long context, but the official evidence is weaker for end-to-end software-agent work than Qwen3.6's current coding-agent suite. It is a reasonable experiment, not the first replacement.

Source: [NVIDIA Nemotron 3 Nano official model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8)

## Acceptance test before removing Laguna

Run both models through the same 10–20 real tasks drawn from the work Laguna actually performs. Include repository navigation, a multi-file bug fix, test-driven implementation, tool-call recovery after a failed command, a long-context change, and an instruction-heavy task. Record:

- task completion without human rescue;
- tests passing;
- invalid or malformed tool calls;
- wall-clock time and generated tokens per second;
- peak VRAM and whether `ollama ps` remains `100% GPU`;
- regressions caused by Q4 quantization.

Promote Qwen only if it improves completion rate without introducing tool-call instability. Keep Laguna installed until that comparison is complete.
