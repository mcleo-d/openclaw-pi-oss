# Ollama Model Research — Pi 5 (8GB) + OpenClaw

Researched: 2026-02-26

## Context

This research identifies the most appropriate Ollama model for the following constraints:

- **Hardware:** Raspberry Pi 5, 8GB RAM, ARM Cortex-A76 (aarch64), CPU inference only — no GPU
- **Available RAM for Ollama:** ~5–6GB (OS ~300MB + OpenClaw Docker container ~2GB already consumed)
- **Use case:** AI agent backend for OpenClaw — requires strong tool/function calling, multi-step reasoning, and instruction following
- **Interface:** Interactive Telegram/Signal messaging — response latency matters
- **Quantisation target:** Q4_K_M (best quality/RAM balance for this hardware — see section below)

---

## Actual Results — Measured on This Pi (2026-02-26 → 2026-02-27)

### Initial benchmark (2026-02-26) — direct Ollama, small context

> **Note:** qwen2.5:3b was selected after this benchmark but the selection was later reversed after production testing revealed a context-window performance cliff. See "Context window performance cliff" and "Production fix" sections below for the full story. **Current primary model is `qwen3:1.7b-q4_K_M`.**

Both shortlisted models were pulled and benchmarked under real conditions (Ollama v0.17.0, native systemd, no Docker overhead, tool-call-style request at Ollama default num_ctx ~2048).

| Model | RAM loaded (actual) | Generation speed | Tool call output tokens | Tool call wall time | Initial verdict |
|---|---|---|---|---|---|
| `qwen2.5:3b-instruct-q4_K_M` | ~2.0 GB | **5.18 t/s** | **20 tokens** | **19 s** | ✅ Selected initially (later reversed) |
| `qwen3:1.7b-q4_K_M` | ~1.7 GB | 6.89 t/s | 289 tokens | 51 s | ❌ Thinking mode overhead (later mitigated) |

The qwen3 benchmark was done with thinking mode enabled, generating 289 internal reasoning tokens per call. This made it 2.7× slower end-to-end despite faster per-token generation. The thinking penalty was later eliminated by the proxy injecting `think: false`.

### Context window performance cliff (2026-02-27) — discovered in production

When OpenClaw ran, both models became completely unusable. Root cause: OpenClaw sends `num_ctx=contextWindow` (16384) to Ollama on every request, causing a massive KV cache allocation:

| Model | KV cache at num_ctx=16384 | Result |
|---|---|---|
| `qwen2.5:3b-instruct-q4_K_M` | 576 MiB | Inference never completes (>5 min timeout) |
| `qwen3:1.7b-q4_K_M` | **1.8 GiB** | Also hangs, but eventually completed in 30s without proxy |

The Pi 5's Cortex-A76 hits a cache-miss cliff above roughly 4096 context. At 16384, the KV cache + compute buffers overflow CPU caches, making every token generation order-of-magnitude slower than the benchmark suggested.

### Production fix (2026-02-27) — ollama-proxy + new engine

**Solution:** An `ollama-proxy` service on port <your-proxy-port> intercepts requests and:

- Caps `num_ctx` at 4096 → KV cache drops to 448 MiB
- Injects `think: false` → disables qwen3 thinking mode entirely
- Truncates system messages to 500 chars (~125 tokens) → prefill drops from ~248s to ~10s

With the new engine enabled (default in Ollama v0.17.0+):

| Model | Context | KV cache | Warm response time | Status |
|---|---|---|---|---|
| `qwen3:1.7b-q4_K_M` | 4096 (capped) | 448 MiB | **2–7 seconds** | ✅ **Current primary** |
| `qwen2.5:3b-instruct-q4_K_M` | 4096 (capped) | 144 MiB | Not re-tested (fallback only) | ⬇️ Fallback |

**Why qwen3:1.7b won in production:**

- Faster per token (6.89 vs 5.18 t/s)
- With thinking disabled, token count per call is minimal (comparable to qwen2.5:3b's 20 tokens)
- The initial thinking-mode penalty no longer applies once the proxy injects `think: false`
- Handles the 16384 context request more gracefully than qwen2.5:3b even without the proxy (30s vs never completing)

**Conclusion:** `qwen3:1.7b-q4_K_M` with the proxy is the confirmed primary. `qwen2.5:3b-instruct-q4_K_M` retained as fallback — it is available if qwen3 fails, but will also benefit from the proxy's context cap.

---

## Benchmark Data: Token/Second on Pi 5

Community benchmarks (Stratosphere Labs June 2025, arxiv 2511.07425, DFRobot, BlackDevice CM5) converge on the following:

| Model | RAM | t/s (generation) | Tool calling |
|---|---|---|---|
| qwen3:0.6b | ~1.3GB | ~21 t/s | Adequate |
| qwen2.5:1.5b | ~2GB | ~10–15 t/s | Good |
| qwen3:1.7b | ~2.2GB | ~9–12 t/s | Very good |
| llama3.2:3b | ~4.2GB | ~5.5 t/s | Good |
| **qwen2.5:3b** | **~5.4GB** | **~5–6 t/s** | **Excellent** |
| gemma3:4b | ~3.5GB | ~4 t/s | Good (see note) |
| phi4-mini:3.8b | ~2.5GB | ~3 t/s | Good |
| phi3.5:3.8b | ~2.2GB | ~3.4 t/s | Limited |
| mistral:7b | ~4.1GB | ~1 t/s | Good |
| llama3.1:8b | ~4.7GB | ~1.2 t/s | Good |

**Practical latency note:** At 5–6 t/s, a 100-token response takes ~17–20 seconds. Acceptable for async Telegram/Signal messaging. Sub-3 t/s (7B+ models) is painful for interactive use.

**Important caveat:** Some DFRobot benchmarks report 15–20 t/s for Qwen2.5:3b — this is likely the *prompt evaluation* (prefill) rate, not the *generation* rate. Generation throughput is 5–6 t/s.

---

## Quantisation: Why Q4_K_M

| Quantisation | Quality vs FP16 | RAM vs FP16 | Recommendation |
|---|---|---|---|
| Q4_0 | ~93% | ~25% | Avoid — worse than Q4_K_M at same size |
| **Q4_K_M** | **~95%** | **~25%** | **Recommended — best quality/RAM trade-off** |
| Q5_K_M | ~98% | ~31% | Only worthwhile for ≤2B models where absolute RAM is small |
| Q8_0 | ~99.5% | ~50% | Near-FP16 quality but doubles RAM — not worth it on Pi 5 |

Q4_K_M uses mixed-precision K-quant with higher precision on attention layers. The ~5% quality loss vs FP16 is negligible for instruction-following and tool-calling tasks. This is the consensus recommendation from the llama.cpp community and all Pi 5 benchmarks reviewed.

---

## Tool/Function Calling Support

For agentic use (OpenClaw dispatching tools), reliable JSON tool-call emission is critical. Tier ranking:

**Tier 1 — Excellent (confirmed native Ollama tools API support):**

- Qwen2.5 family (all instruct variants) — specifically trained on function-calling data; community consensus best small-model tool caller
- Qwen3 family — tool-use is a primary training objective; works across all sizes including 0.6B
- Llama 3.1 / 3.2 instruct — Meta's official tool calling introduced in 3.1
- Phi4-mini — Microsoft added native function calling (requires Ollama ≥0.5.13)

**Tier 2 — Capable but less reliable at small sizes:**

- gemma3:1b — fast but tool calling requires community variant (`orieg/gemma3-tools:4b`)
- qwen2.5:0.5b — technically supports tools but unreliable below 1.5B

**Tier 3 — Avoid for agentic use:**

- deepseek-r1:1.5b — poor structured output quality at this size
- tinyllama:1.1b — unreliable output

The Stratosphere Labs paper specifically noted: *"Qwen2 models consistently deliver the highest performance in structured output scenarios like generating function calls or JSON data."*

---

## Top 5 Ranked Recommendations

### 1. Primary Pick — `qwen3:1.7b-q4_K_M` (via ollama-proxy)

```bash
ollama pull qwen3:1.7b-q4_K_M
```

| Property | Value |
|---|---|
| RAM (at 4096 ctx) | ~1.9 GB (1.3 GB weights + 448 MiB KV cache) |
| Speed (warm, 4096 ctx) | **2–7 seconds per response** |
| Tool calling | Very good |
| Native context window | 131K tokens |
| Disk size | ~1.1 GB |

**Requires `ollama-proxy` to be running.** Without the proxy, OpenClaw sends `num_ctx=16384`+ and inference hangs. The proxy caps to 4096, injects `think: false` to eliminate thinking-mode overhead, and truncates the system message to prevent prefill timeout. The new engine is enabled by default in Ollama v0.17.0+ — no extra configuration needed.

---

### 2. Fallback — `qwen2.5:3b-instruct-q4_K_M` (via ollama-proxy)

```bash
ollama pull qwen2.5:3b-instruct-q4_K_M
```

| Property | Value |
|---|---|
| RAM (at 4096 ctx) | ~1.5 GB (1.8 GB weights + 144 MiB KV cache) |
| Speed | ~5–6 t/s (not re-benchmarked at 4096 ctx) |
| Tool calling | Excellent |
| Native context window | 32K tokens |
| Disk size | ~1.9 GB |

Good fallback if qwen3 fails. Does not have a thinking mode, so no `think: false` injection needed. Will also benefit from the proxy's context cap. The tight RAM fit (~0.5–0.6 GB headroom at full load) is less of a concern at 4096 context than at 16384.

---

### 3. Quality Ceiling — `gemma3:4b-it-q4_K_M`

```bash
# For reliable tool calling, use the community tool-enabled variant:
ollama pull orieg/gemma3-tools:4b
# Standard variant (limited native tool support):
ollama pull gemma3:4b-it-q4_K_M
```

| Property | Value |
|---|---|
| RAM | ~3.5GB |
| Speed | ~4 t/s |
| Tool calling | Good (use orieg variant for reliability) |
| Context window | **128K tokens** — largest of any Pi-feasible model |
| Disk size | ~2.5GB |

Best reasoning quality at the Pi 5 performance ceiling. The 128K context window is valuable for long agent chains. Use the `orieg/gemma3-tools:4b` variant for function calling reliability.

---

### 4. Ultra-Fast / Routing — `qwen3:0.6b-q5_K_M`

```bash
ollama pull qwen3:0.6b-q5_K_M
```

| Property | Value |
|---|---|
| RAM | ~1.3GB |
| Speed | ~15–21 t/s |
| Tool calling | Adequate (less reliable on complex multi-tool chains) |
| Context window | 32K tokens |

Useful as a fast routing/triage model — classify incoming messages or handle simple queries, escalate complex tasks to the 3B model. Consider a dual-model architecture once the stack is stable.

---

### 5. Reasoning Alternative — `phi4-mini:3.8b-q4_K_M`

```bash
ollama pull phi4-mini:3.8b-q4_K_M
```

| Property | Value |
|---|---|
| RAM | ~2.5GB |
| Speed | ~3 t/s |
| Tool calling | Good (requires Ollama ≥0.5.13) |
| Context window | 128K tokens |

Microsoft Phi-4-mini with native function calling. Better RAM efficiency than Qwen2.5:3B. Strong at math and logic-heavy agent tasks. Requires Ollama 0.5.13+.

---

## ARM64 / Raspberry Pi Optimisations

- **Ollama (via llama.cpp) has first-class ARM64 support.** The Pi 5's Cortex-A76 NEON and dotprod SIMD extensions are detected and used automatically — no manual flags required.
- **OpenBLAS** is used for matrix operations and provides a measurable speedup over naive inference.
- **Overclocking the Pi 5 to 3.0 GHz** reportedly improves inference speed meaningfully — worth considering with adequate cooling.
- Must run **64-bit Raspberry Pi OS** — 32-bit OS cannot address the full 8GB RAM and will severely hamper performance. ✓ Already confirmed on this Pi.
- No Pi-specific model family exists — all GGUF Q4_K_M models via Ollama run correctly on aarch64.

---

## Connecting Ollama to OpenClaw (Docker)

OpenClaw runs in Docker; Ollama runs natively on the Pi host. They are connected via three components working together.

### Architecture

```text
OpenClaw container
  │  http://host.docker.internal:<your-proxy-port>
  ▼
ollama-proxy  (/etc/ollama-proxy/proxy.py, systemd service, port <your-proxy-port>)
  │  Caps num_ctx → 4096, injects think=false, truncates system message
  │  http://127.0.0.1:11434
  ▼
Ollama  (native systemd, 127.0.0.1:11434 — loopback only)
```

### Step 1 — Keep Ollama on loopback

Ollama defaults to `127.0.0.1:11434`. Confirm the systemd drop-in does not override this with `0.0.0.0`:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

**Verify:** `sudo ss -tlnp | grep 11434` — must show `127.0.0.1:11434`, not `*:11434`.

No ufw rule for port 11434 is needed — loopback traffic is not reachable from the LAN regardless.

**Note:** `OLLAMA_NEW_ENGINE=1` is no longer required as a separate drop-in. Ollama v0.17.0+ enables the new engine by default. Do not add a `new-engine.conf` drop-in.

**Note:** Do NOT add `ufw allow in on <bridge> to any port 11434` — containers should not reach Ollama directly. All container access goes through the proxy on port <your-proxy-port> instead.

### Step 2 — Deploy the Ollama proxy

The proxy is required because:

1. OpenClaw sends `num_ctx=16384`+ to Ollama, causing a 1.8 GiB KV cache allocation that freezes inference on Pi 5 hardware
2. OpenClaw cannot send `think: false` to Ollama itself, so qwen3's thinking mode stays on and generates 200+ overhead tokens per call
3. OpenClaw sends a ~4,600-token system prompt on every request — the Pi 5 prefills at ~16.5 t/s, making this ~248s of prefill time alone (exceeds OpenClaw's timeout)

```bash
sudo mkdir -p /etc/ollama-proxy

sudo tee /etc/ollama-proxy/proxy.py << 'PYEOF'
# (copy from /etc/ollama-proxy/proxy.py on the Pi — kept as the authoritative source)
PYEOF

sudo tee /etc/systemd/system/ollama-proxy.service << 'EOF'
[Unit]
Description=Ollama Proxy (num_ctx cap + think=false)
After=ollama.service network.target
Requires=ollama.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /etc/ollama-proxy/proxy.py
Restart=always
RestartSec=5
User=ollama

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ollama-proxy
```

Add ufw rules for the proxy port:

```bash
BRIDGE=$(docker network inspect openclaw_net --format '{{index .Options "com.docker.network.bridge.name"}}')
sudo ufw allow in on $BRIDGE to any port <your-proxy-port> proto tcp comment 'Ollama proxy: openclaw_net bridge'
sudo ufw deny <your-proxy-port> comment 'Block external Ollama proxy access'
```

**Note:** Do NOT add a rule for `docker0` — OpenClaw runs on the `openclaw_net` bridge, not the Docker default bridge. The `docker0` bridge rule is dead code.

### Step 3 — Configure OpenClaw

In `docker-compose.yml`, add `host-gateway` mapping so the container can resolve the host:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

In `~/.openclaw/openclaw.json`, point at the proxy:

```json
{
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://host.docker.internal:<your-proxy-port>",
        "apiKey": "ollama-local",
        "api": "ollama"
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/qwen3:1.7b-q4_K_M",
        "fallbacks": ["ollama/qwen2.5:3b-instruct-q4_K_M"]
      }
    }
  }
}
```

### Verify connectivity

```bash
# Test proxy reachable from container network
ssh <hostname> "docker run --rm --network openclaw_net --add-host=host.docker.internal:host-gateway alpine/curl curl -s http://host.docker.internal:<your-proxy-port>/api/tags | python3 -c \"import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]\""

# Verify proxy is capping num_ctx (check logs after a request)
ssh <hostname> "sudo journalctl -u ollama-proxy -n 10 --no-pager"
```

### Verify model has tool calling capability

```bash
ssh <hostname> "ollama show qwen3:1.7b-q4_K_M | grep -i capabilit"
```

---

## Recommended Installation Sequence

```bash
# 1. Install Ollama
ssh <hostname> "curl -fsSL https://ollama.com/install.sh | sh"

# 2. Confirm Ollama is bound to loopback (127.0.0.1:11434)
# (see "Connecting Ollama to OpenClaw — Step 1" above)

# 3. Pull primary and fallback models
ssh <hostname> "ollama pull qwen3:1.7b-q4_K_M"
ssh <hostname> "ollama pull qwen2.5:3b-instruct-q4_K_M"

# 4. Quick smoke test (uses Ollama default num_ctx ~2048 — should respond in ~5s)
ssh <hostname> "ollama run qwen3:1.7b-q4_K_M 'List three steps to make tea. Be concise.' --nowordwrap"

# 5. Check memory after model load
ssh <hostname> "free -h"

# 6. Deploy the Ollama proxy
# (see "Connecting Ollama to OpenClaw — Step 2" above)

# 7. Configure OpenClaw to use the proxy
# (see "Connecting Ollama to OpenClaw — Step 3" above)
```

---

## 2026-03-21 Addendum — qwen3:4b Instability Root Cause + Model Evaluation

### Root causes of qwen3:4b-q4_K_M instability

qwen3:4b was evaluated as an alternative primary model but produced empty responses under production load. Two compounding bugs were identified:

#### Bug 1 — think:false proxy injection silently broken (CRITICAL)

`proxy.py` was injecting `think: false` into `payload["options"]["think"]`. The Ollama API expects `think` as a **top-level field** (`payload["think"]`), not inside `options{}`. The injection was silently ignored — thinking mode was active on every call.

Effect: qwen3:4b generated 147+ internal reasoning tokens per simple request, consuming its entire `num_predict` budget before producing visible output. Response was empty.

Fix: Changed `opts.setdefault("think", False)` to `payload.setdefault("think", False)` in both proxy variants. Verified: eval_count dropped from 147 to ~23 for a short prompt.

#### Bug 2 — RAM pressure at num_ctx=8192

At `num_ctx=8192`, qwen3:4b-q4_K_M allocates ~4.2 GB RAM, leaving only ~1.5 GB headroom on an 8 GB device. Any concurrent memory spike triggers OOM pressure → inference hangs.

### Model evaluation — 2026-03-21

| Model | Capability check | Outcome |
|---|---|---|
| `gemma3:1b` (official) | `ollama show` → Capabilities: `completion` only — no `tools` | ❌ Rejected — requires tools capability |
| Community 1b variant | Tag not found on Ollama Hub | ❌ Does not exist |
| `qwen3:1.7b-q4_K_M` | tools capability confirmed, proven stable previously | ✅ Selected |

### Benchmark — qwen3:1.7b-q4_K_M at num_ctx=8192

| Metric | Value | Threshold | Result |
|---|---|---|---|
| RAM (Ollama, loaded) | 2.4 GB | — | INFO |
| RAM headroom available | >5 GB | ≥ 3 GB | PASS |
| Warm t/s | 8.3 t/s | ≥ 8.0 | PASS |
| eval_count (simple prompt, think:false active) | ~23 tokens | ≤ 100 | PASS |
| Response non-empty | yes | required | PASS |
| Tool calls emitted | verified | required | PASS |

### Accepted constraints

| Constraint | Detail |
|---|---|
| Context window pressure | ~4,600-token OpenClaw system prompt consumes ~56% of an 8192-token context window at `PROXY_MAX_CTX=8192`. Limits tool-chain depth to ~2–3 calls before context pressure. Roadmap: system prompt compression. |
| gemma3:1b future path | Recheck official `gemma3:1b` tool support in future Ollama versions. If tools capability is added, it offers ~1.0–1.2 GB RAM at 8192 ctx — further headroom improvement. |

---

## Sources

| Source | Key data |
|---|---|
| [Stratosphere Labs — LLMs on Raspberry Pi 5 (June 2025)](https://www.stratosphereips.org/blog/2025/6/5/how-well-do-llms-perform-on-a-raspberry-pi-5) | Benchmark t/s for 25 models on Pi 5 |
| [arxiv 2511.07425 — LLMs on Single-Board Computers](https://arxiv.org/html/2511.07425v1) | Cross-SBC benchmark including Pi 5; Q4_K_M analysis |
| [DFRobot — SLM Performance on Pi 5](https://www.dfrobot.com/blog-14068.html) | Phi3.5, Qwen, Llama benchmarks |
| [BlackDevice — Ollama on Raspberry Pi CM5](https://blackdevice.com/installing-local-llms-raspberry-pi-cm5-benchmarking-performance/) | Gemma3:4b, deepseek-r1 benchmarks |
| [Byteiota — Qwen 3B on Pi 5](https://byteiota.com/qwen-3b-raspberry-pi-5-real-time-ai-2/) | Qwen2.5:3b real-world Pi 5 testing |
| [Pamir-AI — Qwen3 on Pi 5](https://pamir-ai.hashnode.dev/qwen-3-on-a-raspberry-pi-5-small-models-big-agent-energy) | Qwen3 family agent-focused benchmark |
| [Ollama — Tool Calling Docs](https://docs.ollama.com/capabilities/tool-calling) | Official tool calling model list |
| [OpenClaw Docs — Ollama Provider](https://docs.openclaw.ai/providers/ollama) | Official OpenClaw/Ollama integration |
| [Collabnix — Best Ollama Models for Function Calling (2025)](https://collabnix.com/best-ollama-models-for-function-calling-tools-complete-guide-2025/) | Tool calling tier ranking |
| [llama.cpp — Quantisation discussion](https://github.com/ggml-org/llama.cpp/discussions/2094) | Q4_K_M vs Q8 analysis |
