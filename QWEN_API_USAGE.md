# Qwen2.5-7B-Instruct API — Usage Guide

A standalone HTTP API serving an open-source Qwen2.5-7B-Instruct model (4-bit NF4 quantized) behind FastAPI/uvicorn. This document is for anyone who wants to call the API directly — no SDK required, just HTTP.

---

## 1. Server info

| | |
|---|---|
| **Base URL** | `http://10.10.35.88:8005` |
| **Model** | `Qwen2.5-7B-Instruct` (4-bit NF4) |
| **API version** | `1.2.0` |
| **Auth** | None — open within the network. VPN required if off-LAN. |
| **Concurrency** | Single-request: `model.generate()` is sync-blocking. Two callers will queue. |
| **Interactive docs** | `http://10.10.35.88:8005/docs` (Swagger UI) |
| **OpenAPI schema** | `http://10.10.35.88:8005/openapi.json` |

> Not OpenAI-compatible. Endpoints are custom (`/chat`, `/chat/stream`) — `/v1/chat/completions` does **not** exist.

---

## 2. Endpoints at a glance

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/` | Banner / liveness — returns model name, quantization, status |
| `GET`  | `/health` | GPU memory snapshot — use this for readiness probes |
| `POST` | `/chat` | Single-shot generation, returns full response as JSON |
| `POST` | `/chat/stream` | Server-Sent Events stream of tokens |
| `POST` | `/cleanup` | Manually free GPU memory if generations get sluggish |

---

## 3. Endpoint reference

### 3.1 `GET /`

Liveness banner. Returns `200` even if generation is broken — only confirms the HTTP layer is up.

```bash
curl http://10.10.35.88:8005/
```

```json
{
  "model": "Qwen2.5-7B-Instruct",
  "quantization": "4-bit NF4",
  "status": "ready",
  "endpoints": ["/health", "/chat", "/chat/stream", "/cleanup"]
}
```

---

### 3.2 `GET /health`

Real readiness check — touches the GPU. Use this for monitoring.

```bash
curl http://10.10.35.88:8005/health
```

```json
{
  "status": "ready",
  "gpu_memory_allocated_gb": 5.18,
  "gpu_memory_reserved_gb": 5.33,
  "gpu_memory_free_gb": 8.77
}
```

A non-200 here means the model is down even if `/` returns 200.

---

### 3.3 `POST /chat` — non-streaming

Single round-trip generation.

#### Request body (`ChatRequest`)

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `messages` | `Message[]` (required) | — | Chat history. Each entry: `{ "role": "system" \| "user" \| "assistant", "content": "..." }` |
| `max_tokens` | `int` | `200` | Upper bound on generated tokens |
| `temperature` | `float` | `0.7` | Sampling temperature. Use a tiny floor like `0.01` for "deterministic"; some sampling backends deadlock on exactly `0` |
| `top_p` | `float` | `0.9` | Nucleus sampling |
| `do_sample` | `bool` | `true` | Set `false` for greedy decoding |

#### Response body (`ChatResponse`)

```json
{
  "response": "string — the assistant's reply text",
  "tokens_generated": 60,
  "generation_time": 5.14,
  "tokens_per_second": 11.7
}
```

#### Example — curl

```bash
curl -X POST http://10.10.35.88:8005/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a concise assistant."},
      {"role": "user", "content": "In two sentences, explain what an LLM is."}
    ],
    "max_tokens": 120,
    "temperature": 0.7
  }'
```

#### Example — Python (httpx)

```python
import httpx

resp = httpx.post(
    "http://10.10.35.88:8005/chat",
    json={
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Explain LLMs in one sentence."},
        ],
        "max_tokens": 80,
        "temperature": 0.7,
    },
    timeout=120.0,
)
resp.raise_for_status()
data = resp.json()
print(data["response"])
```

---

### 3.4 `POST /chat/stream` — Server-Sent Events

Same request body as `/chat`. Response is SSE: each line is `data: <json>\n\n`.

#### Event shapes

| Frame | Meaning |
|-------|---------|
| `data: {"token": "..."}` | One generated token (concatenate `token` strings to assemble the full reply) |
| `data: {"done": true}` | End of stream — close the connection |
| `data: {"error": "..."}` | Server-side error — abort |

#### Example — curl

```bash
curl -N -X POST http://10.10.35.88:8005/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Count: 1, 2, 3"}],"max_tokens":20}'
```

```
data: {"token": "Sure! "}

data: {"token": "Here's "}

data: {"token": "the "}

data: {"token": "count:\n\n"}

data: {"token": "1, "}

data: {"token": "2, "}

data: {"token": "3"}

data: {"done": true}
```

#### Example — Python (httpx async)

```python
import json
import httpx

async def stream_chat(prompt: str) -> str:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 200,
        "temperature": 0.7,
    }
    full = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            "http://10.10.35.88:8005/chat/stream",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):].strip())
                if "token" in event:
                    full.append(event["token"])
                elif event.get("done"):
                    break
                elif "error" in event:
                    raise RuntimeError(event["error"])
    return "".join(full)
```

---

### 3.5 `POST /cleanup`

Frees cached GPU memory. Useful if generations slow down after long sessions.

```bash
curl -X POST http://10.10.35.88:8005/cleanup
```

```json
{ "status": "cleaned", "gpu_memory_allocated_gb": 5.2, "gpu_memory_free_gb": 8.75 }
```

---

## 4. Function calling (tool use)

The server **does not natively support** the OpenAI-style `tools` / `tool_choice` parameters or output structured tool-call payloads. To get function-calling behaviour you do it via **prompt engineering**: describe the tools in the system message, ask the model to emit a structured tag, and parse it client-side.

This section gives you the exact pattern that's been validated against this deployment.

### 4.1 The pattern

1. **Describe each tool** in the system prompt: name, one-line description, parameter names.
2. **Instruct the model** to reply with a single `<tool_call>{...}</tool_call>` block when it wants a tool, and plain text when it doesn't.
3. **Parse** the model output: regex-extract `<tool_call>...</tool_call>`, then `json.loads` the inside.
4. **Execute** the matched function locally.
5. **Feed the tool result back** as a `user` message of the form `"Tool <name> returned: <result>"` and call `/chat` again to get the final natural-language answer.

> Why this shape? The `<tool_call>...</tool_call>` tag is what Qwen3-family chat templates already use internally — Qwen 2.5 will follow it reliably when prompted. `Exactly ONE tool per response` keeps the parsing simple.

### 4.2 System-prompt template

Append this block to your real system prompt, filling the `- name(args)` lines from your tool registry:

```
You have these tools available:
- get_weather(city, units): Get current weather for a city.
- get_time(timezone): Get the current local time.

When you need to call a tool, respond with ONLY this exact format and nothing else:
<tool_call>
{"name": "<tool_name>", "arguments": {<args>}}
</tool_call>

Do not say you cannot access data — you have these tools. Use them.
To answer the user directly without a tool, respond with plain text.
Exactly ONE tool per response.
```

### 4.3 Parsing the response

```python
import json
import re

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)

def parse_tool_call(text: str) -> dict | None:
    """Return {'name': str, 'arguments': dict} if the model emitted a tool call,
    else None (treat as plain text answer)."""
    m = _TOOL_CALL_RE.search(text.strip())
    if not m:
        return None
    try:
        body = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    name = body.get("name")
    args = body.get("arguments") or body.get("args") or {}
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return {"name": name, "arguments": args}
```

### 4.4 Full end-to-end example

```python
import json
import re
import httpx

BASE_URL = "http://10.10.35.88:8005"

# 1. Define your tools (names must match what you advertise in the prompt).
def get_weather(city: str, units: str = "celsius") -> dict:
    # Replace with a real API call.
    return {"city": city, "temperature": 22, "units": units, "condition": "sunny"}

def get_time(timezone: str) -> dict:
    return {"timezone": timezone, "now": "2026-04-30T14:30:00"}

TOOL_REGISTRY = {
    "get_weather": get_weather,
    "get_time": get_time,
}

TOOL_DIRECTIVE = """
You have these tools available:
- get_weather(city, units): Get current weather for a city.
- get_time(timezone): Get the current local time.

When you need to call a tool, respond with ONLY this exact format and nothing else:
<tool_call>
{"name": "<tool_name>", "arguments": {<args>}}
</tool_call>

Do not say you cannot access data — you have these tools. Use them.
To answer the user directly without a tool, respond with plain text.
Exactly ONE tool per response.
""".strip()

# 2. Helpers.
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)

def parse_tool_call(text: str):
    m = _TOOL_CALL_RE.search(text.strip())
    if not m:
        return None
    try:
        body = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    name = body.get("name")
    args = body.get("arguments") or body.get("args") or {}
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return {"name": name, "arguments": args}

def call_qwen(messages: list[dict], max_tokens: int = 1200) -> str:
    """One round trip to /chat. Bumped max_tokens because tool-call JSON
    needs more headroom than chat-only completions."""
    resp = httpx.post(
        f"{BASE_URL}/chat",
        json={
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.9,
        },
        timeout=180.0,
    )
    resp.raise_for_status()
    return resp.json()["response"]

# 3. The agent loop.
def chat_with_tools(user_message: str, max_iters: int = 4) -> str:
    messages = [
        {"role": "system", "content": TOOL_DIRECTIVE},
        {"role": "user", "content": user_message},
    ]
    for _ in range(max_iters):
        reply = call_qwen(messages)
        call = parse_tool_call(reply)
        if call is None:
            return reply  # plain-text answer — done.

        fn = TOOL_REGISTRY.get(call["name"])
        if fn is None:
            # Unknown tool — surface as an error turn so model can recover.
            tool_result = {"error": f"unknown tool {call['name']!r}"}
        else:
            try:
                tool_result = fn(**call["arguments"])
            except Exception as exc:
                tool_result = {"error": f"{type(exc).__name__}: {exc}"}

        # Echo the assistant's tool call back, then feed the result.
        messages.append({"role": "assistant", "content": reply})
        messages.append({
            "role": "user",
            "content": f"Tool {call['name']} returned: {json.dumps(tool_result)}",
        })
    return "[max iterations reached]"

# 4. Use it.
if __name__ == "__main__":
    print(chat_with_tools("What's the weather in Karachi right now?"))
```

### 4.5 Practical tips

- **Bump `max_tokens` to ≥ 1200** when tools are in play. Tool-call JSON gets truncated at the default 200, which produces unparseable output.
- **Lower temperature for tool calls** (e.g. `0.2`) — sampling noise increases the chance of malformed JSON.
- **Cap iterations** in your loop (4–6 is plenty). The model can occasionally loop on bad tool output; an iteration cap keeps you safe.
- **Validate tool names** against your registry before executing. The model will sometimes invent a tool that doesn't exist.
- **Strip code fences.** The model occasionally wraps the tag in <code>```json ... ```</code>. Either strip fences before the regex, or extend your regex to match either form.
- **One tool per turn.** Don't try to coax it into emitting multiple `<tool_call>` blocks at once — reliability falls off a cliff.
- **Keep the directive at the top.** Putting it on the system message rather than the user message dramatically improves compliance.

---

## 5. Limits, gotchas, troubleshooting

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| `/` returns 200 but `/chat` returns **HTTP 500** | Model failed to load on GPU; FastAPI process is alive, inference layer is dead | Restart the Qwen service on the host. `/health` will also be 500 in this state. |
| Tool call returns truncated/invalid JSON | `max_tokens` too small for tool-mode output | Set `max_tokens` ≥ 1200 when tools are bound |
| Long generations slow down over time | KV-cache / fragmentation | `POST /cleanup` between heavy requests |
| Two concurrent callers stall | `model.generate()` is sync-blocking | Serialize requests at your client, or queue them |
| `temperature=0` hangs / errors | Some sampling backends deadlock on exact zero | Use `0.01` instead |
| First token slow (~5–10s) | Cold load / prefill | Send a tiny warm-up call after deploy |
| Server unreachable from outside the LAN | Network policy | Connect via VPN |

### Throughput rough numbers (live measurement)

- Cold call (`max_tokens=20`, ~2 tokens generated): ~1.5–2 s end-to-end.
- Warm call (`max_tokens=120`, ~60 tokens generated): ~5 s, ~12 tok/s.
- Don't expect production-grade throughput — this is a single-instance dev box.

---

## 6. Quick reference card

```bash
# liveness
curl http://10.10.35.88:8005/

# readiness (includes GPU stats)
curl http://10.10.35.88:8005/health

# one-shot completion
curl -X POST http://10.10.35.88:8005/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hello"}],"max_tokens":50}'

# streaming (SSE)
curl -N -X POST http://10.10.35.88:8005/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Hello"}],"max_tokens":50}'

# free GPU memory
curl -X POST http://10.10.35.88:8005/cleanup
```

