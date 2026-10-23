"""
Local HMAC-signing proxy for Bob's LiteLLM backend (API Key version).

Uses a Bob API key directly — no SSO interception or `bob` CLI needed.
Much simpler and faster startup than the SSO-based proxy.py.

Claude Code (Anthropic mode):
  ANTHROPIC_BASE_URL=http://localhost:8989/anthropic ANTHROPIC_API_KEY=proxy claude --model premium

Claude Code (Bedrock mode — no Claude Pro login needed):
  CLAUDE_CODE_USE_BEDROCK=1 ANTHROPIC_BEDROCK_BASE_URL=http://localhost:8989/bedrock CLAUDE_CODE_SKIP_BEDROCK_AUTH=1 claude --model premium

GitHub Copilot setup (VS Code settings.json):
    "github.copilot.chat.models": [
        {
            "name": "Bob",
            "vendor": "customoai",
            "apiKey": "${input:chat.lm.secret.<your-secret-id>}",
            "models": [
                {
                    "id": "premium",
                    "name": "Bob Premium",
                    "url": "http://localhost:8989/v1",
                    "toolCalling": true,
                    "vision": true,
                    "maxInputTokens": 128000,
                    "maxOutputTokens": 16000
                }
            ]
        }
    ]

Usage:
    1. Copy the repo-root .env.sample to .env and set your API key
    2. uv run python proxy-apikey.py  (or: docker compose up bob-proxy)

Listens on http://localhost:8989 and forwards to Bob's backend with
HMAC signing + API key auth injected into every request.
"""

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests as req
from flask import Flask, Response, request

# Load the nearest .env file walking up from this script (e.g. the repo root).
# In Docker, env vars come from compose's env_file instead.
_env_path = next((d / ".env" for d in Path(__file__).resolve().parents if (d / ".env").exists()), None)
if _env_path:
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

BASE_URL = "https://api.us-east.bob.ibm.com"
PORT = 8989

# Path prefix used by Bob's new gateway for OpenAI-style endpoints.
# /chat/completions -> /inference/v1/chat/completions
INFERENCE_PREFIX = "/inference/v1"

# API key — loaded from .env or environment variable
API_KEY = os.environ.get("BOB_API_KEY", "")
HMAC_SECRET = os.environ.get("BOB_HMAC_SECRET", "")
INSTANCE_ID = os.environ.get("BOB_INSTANCE_ID", "")
TEAM_ID = os.environ.get("BOB_TEAM_ID", "")

app = Flask(__name__)

# Map any Claude model name to the "premium" alias on Bob's backend
MODEL_MAP = {
    "premium": "premium",
    "premium-shell": "premium-shell",
    "premium-ide": "premium-ide",
    "explorer": "explorer",
    "openai/gpt-oss-20b": "openai/gpt-oss-20b",
}
DEFAULT_MODEL = "premium"


# ---------------------------------------------------------------------------
# HMAC signing (from main.py)
# ---------------------------------------------------------------------------
def sign_request(method: str, path: str, body: str = "") -> dict[str, str]:
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    message = f"{method.upper()}\n{path}\n{timestamp}\n{body_hash}"
    signature = hmac.new(HMAC_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return {
        "x-request-timestamp": timestamp,
        "x-request-signature": signature,
    }


# ---------------------------------------------------------------------------
# Anthropic <-> OpenAI translation helpers
# ---------------------------------------------------------------------------
def _sse(event_type: str, data) -> str:
    """Format a Server-Sent Event string."""
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event_type}\ndata: {payload}\n\n"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


def _translate_content_blocks(blocks) -> str | list:
    """Convert Anthropic content blocks to OpenAI content format.

    Returns a plain string if all blocks are text, otherwise a list of
    OpenAI content parts (text + image_url).
    """
    if isinstance(blocks, str):
        return blocks

    parts = []
    for block in blocks:
        btype = block.get("type", "")
        if btype == "text":
            parts.append({"type": "text", "text": block["text"]})
        elif btype == "image":
            source = block.get("source", {})
            if source.get("type") == "base64":
                data_uri = f"data:{source['media_type']};base64,{source['data']}"
                parts.append({"type": "image_url", "image_url": {"url": data_uri}})
        elif btype in ("thinking", "tool_use", "tool_result"):
            continue

    # Optimise: if only text parts, return plain string
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts if parts else ""


def _translate_messages(messages: list, system: str | list | None) -> list:
    """Convert Anthropic messages list to OpenAI messages list."""
    out: list[dict] = []

    # System prompt
    if system:
        if isinstance(system, list):
            # Anthropic system can be a list of content blocks
            text_parts = [b["text"] for b in system if b.get("type") == "text"]
            system = "\n\n".join(text_parts)
        out.append({"role": "system", "content": system})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Simple string content
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        # Content is a list of blocks
        if not isinstance(content, list):
            out.append({"role": role, "content": str(content)})
            continue

        # Check for tool_result blocks (these become role:tool messages)
        tool_results = [b for b in content if b.get("type") == "tool_result"]
        if tool_results and role == "user":
            # First, add all tool result messages
            for tr in tool_results:
                tr_content = tr.get("content", "")
                if isinstance(tr_content, list):
                    text_parts = [b.get("text", "") for b in tr_content if b.get("type") == "text"]
                    tr_content = "\n".join(text_parts) if text_parts else ""
                out.append({
                    "role": "tool",
                    "tool_call_id": tr.get("tool_use_id", ""),
                    "content": tr_content,
                })
            # Then, add any other content blocks as a user message
            other_blocks = [b for b in content if b.get("type") not in ("tool_result", "thinking")]
            if other_blocks:
                translated = _translate_content_blocks(other_blocks)
                out.append({"role": "user", "content": translated})
            continue

        # Check for tool_use blocks (assistant message with tool calls)
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if tool_uses and role == "assistant":
            text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            text_content = "\n".join(t for t in text_parts if t) or None
            tool_calls = []
            for tu in tool_uses:
                tool_calls.append({
                    "id": tu.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                    "type": "function",
                    "function": {
                        "name": tu["name"],
                        "arguments": json.dumps(tu.get("input", {})),
                    },
                })
            msg_out = {"role": "assistant", "content": text_content, "tool_calls": tool_calls}
            out.append(msg_out)
            continue

        # Regular content blocks (text, images, etc.)
        translated = _translate_content_blocks(content)
        out.append({"role": role, "content": translated})

    return out


def _translate_tools(tools: list | None) -> list | None:
    """Convert Anthropic tool definitions to OpenAI tool definitions."""
    if not tools:
        return None
    out = []
    for tool in tools:
        out.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _translate_tool_choice(tc) -> str | dict | None:
    """Convert Anthropic tool_choice to OpenAI tool_choice."""
    if tc is None:
        return None
    if isinstance(tc, str):
        mapping = {"auto": "auto", "any": "required", "none": "none"}
        return mapping.get(tc, "auto")
    if isinstance(tc, dict):
        tc_type = tc.get("type", "auto")
        if tc_type == "auto":
            return "auto"
        if tc_type == "any":
            return "required"
        if tc_type == "tool":
            return {"type": "function", "function": {"name": tc["name"]}}
        return "auto"
    return None


def _anthropic_request_to_openai(body: dict) -> dict:
    """Translate a full Anthropic /v1/messages request to OpenAI /v1/chat/completions."""
    openai_body: dict = {}

    # Model
    original_model = body.get("model", "")
    openai_body["model"] = MODEL_MAP.get(original_model, DEFAULT_MODEL)
    if openai_body["model"] != original_model:
        print(f"[anthropic->openai] Model rewrite: {original_model} -> {openai_body['model']}")

    # Messages
    openai_body["messages"] = _translate_messages(
        body.get("messages", []),
        body.get("system"),
    )

    # Tools
    tools = _translate_tools(body.get("tools"))
    if tools:
        openai_body["tools"] = tools

    # Tool choice
    tc = _translate_tool_choice(body.get("tool_choice"))
    if tc is not None:
        openai_body["tool_choice"] = tc

    # Parameters
    if "max_tokens" in body:
        openai_body["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        openai_body["temperature"] = body["temperature"]
    if "top_p" in body:
        openai_body["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        openai_body["stop"] = body["stop_sequences"]

    # Bedrock doesn't allow both temperature and top_p simultaneously
    if "temperature" in openai_body and "top_p" in openai_body:
        del openai_body["top_p"]

    # Streaming
    if body.get("stream", False):
        openai_body["stream"] = True
        openai_body["stream_options"] = {"include_usage": True}

    return openai_body


def _openai_response_to_anthropic(resp_json: dict, model: str) -> dict:
    """Convert a non-streaming OpenAI chat completion response to Anthropic message format."""
    choice = resp_json.get("choices", [{}])[0]
    message = choice.get("message", {})

    content_blocks = []

    # Text content
    if message.get("content"):
        content_blocks.append({"type": "text", "text": message["content"]})

    # Tool calls
    for tc in message.get("tool_calls", []):
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
            "name": fn.get("name", ""),
            "input": args,
        })

    # Stop reason mapping
    finish = choice.get("finish_reason", "stop")
    stop_reason_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
    }
    stop_reason = stop_reason_map.get(finish, "end_turn")

    usage = resp_json.get("usage", {})

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content_blocks if content_blocks else [{"type": "text", "text": ""}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def _stream_openai_to_anthropic(resp, model: str, input_tokens: int):
    """Generator: convert OpenAI SSE stream to Anthropic SSE events."""
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    # message_start
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    })
    yield _sse("ping", {"type": "ping"})

    block_index = 0
    current_text_open = False
    tool_calls_in_progress: dict[int, dict] = {}
    output_tokens = 0
    stop_reason = "end_turn"

    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        if not raw_line.startswith("data: "):
            continue
        data_str = raw_line[6:].strip()
        if data_str == "[DONE]":
            break

        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        # Usage info (may come in the final chunk)
        if chunk.get("usage"):
            output_tokens = chunk["usage"].get("completion_tokens", output_tokens)
            input_tokens = chunk["usage"].get("prompt_tokens", input_tokens)

        choices = chunk.get("choices", [])
        if not choices:
            continue

        choice = choices[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        if finish_reason:
            fr_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
            stop_reason = fr_map.get(finish_reason, "end_turn")

        # Handle text content delta
        text_delta = delta.get("content")
        if text_delta:
            if not current_text_open:
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": block_index,
                    "content_block": {"type": "text", "text": ""},
                })
                current_text_open = True
            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": block_index,
                "delta": {"type": "text_delta", "text": text_delta},
            })

        # Handle tool call deltas
        if delta.get("tool_calls"):
            # Close text block if open
            if current_text_open:
                yield _sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": block_index,
                })
                block_index += 1
                current_text_open = False

            for tc_delta in delta["tool_calls"]:
                tc_index = tc_delta.get("index", 0)

                if tc_index not in tool_calls_in_progress:
                    fn = tc_delta.get("function", {})
                    tc_id = tc_delta.get("id", f"toolu_{uuid.uuid4().hex[:24]}")
                    tc_name = fn.get("name", "")
                    tool_calls_in_progress[tc_index] = {
                        "id": tc_id,
                        "name": tc_name,
                        "args": "",
                        "block_index": block_index,
                    }
                    yield _sse("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tc_id,
                            "name": tc_name,
                            "input": {},
                        },
                    })
                    block_index += 1

                # Accumulate argument fragments
                fn_delta = tc_delta.get("function", {})
                args_fragment = fn_delta.get("arguments", "")
                if args_fragment:
                    tool_calls_in_progress[tc_index]["args"] += args_fragment
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": tool_calls_in_progress[tc_index]["block_index"],
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": args_fragment,
                        },
                    })

    # Close any open text block
    if current_text_open:
        yield _sse("content_block_stop", {
            "type": "content_block_stop",
            "index": block_index,
        })

    # Close any open tool call blocks
    for tc_info in tool_calls_in_progress.values():
        yield _sse("content_block_stop", {
            "type": "content_block_stop",
            "index": tc_info["block_index"],
        })

    # message_delta with stop_reason and usage
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason,
            "stop_sequence": None,
        },
        "usage": {
            "output_tokens": output_tokens,
        },
    })
    yield _sse("message_stop", {"type": "message_stop"})


# ---------------------------------------------------------------------------
# Helper: build headers for backend requests
# ---------------------------------------------------------------------------
def _backend_headers(method: str, path: str, body: str) -> dict[str, str]:
    """Build the standard headers for a request to Bob's backend."""
    headers = {
        "Authorization": f"Apikey {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "bobshell/1.0.4",
    }
    if INSTANCE_ID:
        headers["x-instance-id"] = INSTANCE_ID
    if TEAM_ID:
        headers["x-team-id"] = TEAM_ID
    headers.update(sign_request(method, path, body))
    return headers


# ---------------------------------------------------------------------------
# Anthropic API route handlers (must be registered before the catch-all)
# ---------------------------------------------------------------------------
@app.route('/anthropic/v1/messages/count_tokens', methods=['POST'])
def anthropic_count_tokens():
    """Estimate token count for an Anthropic-format request."""
    body = request.get_data(as_text=True)
    tokens = _estimate_tokens(body)
    print(f"[anthropic->openai] count_tokens -> {tokens}")
    return Response(
        json.dumps({"input_tokens": tokens}),
        status=200,
        content_type="application/json",
    )


@app.route('/anthropic/v1/messages', methods=['POST'])
def anthropic_messages():
    """Translate Anthropic /v1/messages to OpenAI /v1/chat/completions."""
    raw_body = request.get_data(as_text=True)
    try:
        anthropic_body = json.loads(raw_body)
    except json.JSONDecodeError as e:
        return Response(
            json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}}),
            status=400,
            content_type="application/json",
        )

    original_model = anthropic_body.get("model", "unknown")
    is_stream = anthropic_body.get("stream", False)

    # Translate request
    openai_body = _anthropic_request_to_openai(anthropic_body)
    openai_json = json.dumps(openai_body)

    print(f"[anthropic->openai] Translating: model={original_model}, stream={is_stream}, "
          f"messages={len(anthropic_body.get('messages', []))}, "
          f"tools={len(anthropic_body.get('tools', []))}")

    # Forward to Bob's /chat/completions
    target_path = f"{INFERENCE_PREFIX}/chat/completions"
    target_url = f"{BASE_URL}{target_path}"

    headers = _backend_headers("POST", target_path, openai_json)
    print(f"[anthropic->openai] Request headers: {json.dumps({k: v[:50] + '...' if len(v) > 50 else v for k, v in headers.items()}, indent=2)}")
    print(f"[anthropic->openai] Request body preview: {openai_json[:200]}...")

    resp = req.post(
        target_url,
        headers=headers,
        data=openai_json,
        stream=is_stream,
    )

    print(f"[anthropic->openai] POST {target_path} -> {resp.status_code}")
    print(f"[anthropic->openai] Response headers: {dict(resp.headers)}")

    if resp.status_code >= 400:
        error_text = resp.text[:1000] if not is_stream else "upstream error"
        print(f"[anthropic->openai] Error response: {error_text}")
        return Response(
            json.dumps({"type": "error", "error": {"type": "api_error", "message": error_text}}),
            status=resp.status_code,
            content_type="application/json",
        )

    if is_stream:
        input_tokens = _estimate_tokens(openai_json)
        return Response(
            _stream_openai_to_anthropic(resp, original_model, input_tokens),
            status=200,
            content_type="text/event-stream",
        )
    else:
        try:
            openai_resp = resp.json()
        except Exception:
            return Response(
                json.dumps({"type": "error", "error": {"type": "api_error", "message": "Invalid JSON from backend"}}),
                status=502,
                content_type="application/json",
            )
        anthropic_resp = _openai_response_to_anthropic(openai_resp, original_model)
        return Response(
            json.dumps(anthropic_resp),
            status=200,
            content_type="application/json",
        )


# ---------------------------------------------------------------------------
# Bedrock pass-through route handlers
# ---------------------------------------------------------------------------
@app.route('/bedrock/model/<path:model_id>/invoke', methods=['POST'])
def bedrock_invoke(model_id):
    """Handle Bedrock InvokeModel — non-streaming (with 30s timeout)."""
    raw_body = request.get_data(as_text=True)
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as e:
        return Response(
            json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}}),
            status=400,
            content_type="application/json",
        )

    original_model = body.pop("model", model_id)
    body.pop("anthropic_version", None)

    openai_body = _anthropic_request_to_openai(body)
    openai_json = json.dumps(openai_body)

    print(f"[bedrock] invoke: model={original_model}, "
          f"messages={len(body.get('messages', []))}, "
          f"tools={len(body.get('tools', []))}")

    target_path = f"{INFERENCE_PREFIX}/chat/completions"
    target_url = f"{BASE_URL}{target_path}"

    headers = _backend_headers("POST", target_path, openai_json)
    print(f"[bedrock] Request headers: {json.dumps({k: v[:50] + '...' if len(v) > 50 else v for k, v in headers.items()}, indent=2)}")
    print(f"[bedrock] Request body preview: {openai_json[:200]}...")

    try:
        resp = req.post(
            target_url,
            headers=headers,
            data=openai_json,
            stream=False,
            timeout=120,  # 120 second timeout (matches Cloudflare's limit)
        )
    except req.exceptions.Timeout:
        print(f"[bedrock] Request timed out after 120s - backend may be overloaded")
        return Response(
            json.dumps({"type": "error", "error": {"type": "timeout_error", "message": "Request timed out after 120 seconds. The backend may be overloaded. Try using Anthropic mode instead: ANTHROPIC_BASE_URL=http://localhost:8989/anthropic"}}),
            status=504,
            content_type="application/json",
        )
    except req.exceptions.RequestException as e:
        print(f"[bedrock] Request failed: {e}")
        return Response(
            json.dumps({"type": "error", "error": {"type": "api_error", "message": f"Request failed: {str(e)}"}}),
            status=502,
            content_type="application/json",
        )

    print(f"[bedrock] POST {target_path} -> {resp.status_code}")
    print(f"[bedrock] Response headers: {dict(resp.headers)}")

    if resp.status_code >= 400:
        error_text = resp.text[:1000]  # Show more error details
        print(f"[bedrock] Error response: {error_text}")
        return Response(
            json.dumps({"type": "error", "error": {"type": "api_error", "message": error_text}}),
            status=resp.status_code,
            content_type="application/json",
        )

    try:
        openai_resp = resp.json()
    except Exception:
        return Response(
            json.dumps({"type": "error", "error": {"type": "api_error", "message": "Invalid JSON from backend"}}),
            status=502,
            content_type="application/json",
        )

    anthropic_resp = _openai_response_to_anthropic(openai_resp, original_model)
    return Response(
        json.dumps(anthropic_resp),
        status=200,
        content_type="application/json",
    )


@app.route('/bedrock/model/<path:model_id>/invoke-with-response-stream', methods=['POST'])
def bedrock_invoke_stream(model_id):
    """Handle Bedrock InvokeModelWithResponseStream — streaming."""
    raw_body = request.get_data(as_text=True)
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as e:
        return Response(
            json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}}),
            status=400,
            content_type="application/json",
        )

    original_model = body.pop("model", model_id)
    body.pop("anthropic_version", None)
    body["stream"] = True

    openai_body = _anthropic_request_to_openai(body)
    openai_json = json.dumps(openai_body)

    print(f"[bedrock] invoke-stream: model={original_model}, "
          f"messages={len(body.get('messages', []))}, "
          f"tools={len(body.get('tools', []))}")

    target_path = f"{INFERENCE_PREFIX}/chat/completions"
    target_url = f"{BASE_URL}{target_path}"

    headers = _backend_headers("POST", target_path, openai_json)
    print(f"[bedrock-stream] Request headers: {json.dumps({k: v[:50] + '...' if len(v) > 50 else v for k, v in headers.items()}, indent=2)}")
    print(f"[bedrock-stream] Request body preview: {openai_json[:200]}...")

    resp = req.post(
        target_url,
        headers=headers,
        data=openai_json,
        stream=True,
    )

    print(f"[bedrock-stream] POST {target_path} -> {resp.status_code}")
    print(f"[bedrock-stream] Response headers: {dict(resp.headers)}")

    if resp.status_code >= 400:
        error_text = resp.text[:1000]
        print(f"[bedrock-stream] Error response: {error_text}")
        return Response(
            json.dumps({"type": "error", "error": {"type": "api_error", "message": error_text}}),
            status=resp.status_code,
            content_type="application/json",
        )

    input_tokens = _estimate_tokens(openai_json)
    return Response(
        _stream_openai_to_anthropic(resp, original_model, input_tokens),
        status=200,
        content_type="text/event-stream",
    )


# ---------------------------------------------------------------------------
# OpenAI models list — served locally (Bob's backend returns 403 for it)
# ---------------------------------------------------------------------------
_MODELS_CREATED = int(datetime.now(timezone.utc).timestamp())


def _model_object(model_id: str) -> dict:
    return {"id": model_id, "object": "model", "created": _MODELS_CREATED, "owned_by": "bob"}


@app.route('/v1/models', methods=['GET'])
def list_models():
    """List the models known to MODEL_MAP in OpenAI format."""
    return Response(
        json.dumps({"object": "list", "data": [_model_object(m) for m in MODEL_MAP]}),
        status=200,
        content_type="application/json",
    )


@app.route('/v1/models/<path:model_id>', methods=['GET'])
def get_model(model_id):
    """Retrieve a single model in OpenAI format."""
    if model_id not in MODEL_MAP:
        return Response(
            json.dumps({"error": {
                "message": f"The model '{model_id}' does not exist",
                "type": "invalid_request_error",
                "param": None,
                "code": "model_not_found",
            }}),
            status=404,
            content_type="application/json",
        )
    return Response(
        json.dumps(_model_object(model_id)),
        status=200,
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Proxy route — catch-all
# ---------------------------------------------------------------------------
@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def proxy(path):
    target_path = f"/{path}" if path else "/"

    # OpenAI-style routes posted by clients (e.g. /v1/chat/completions from Copilot,
    # or bare /chat/completions) need to be rewritten to Bob's gateway path:
    # /v1/chat/completions  -> /inference/v1/chat/completions
    # /chat/completions     -> /inference/v1/chat/completions
    if target_path.startswith("/v1/"):
        target_path = INFERENCE_PREFIX + target_path[len("/v1"):]
    elif target_path == "/chat/completions":
        target_path = f"{INFERENCE_PREFIX}/chat/completions"

    # Preserve query string from original request
    query_string = request.query_string.decode()
    signed_path = f"{target_path}?{query_string}" if query_string else target_path
    target_url = f"{BASE_URL}{signed_path}"
    body = request.get_data(as_text=True)

    # Rewrite model names (Claude Code sends "claude-*", backend expects "premium")
    if body:
        try:
            payload = json.loads(body)
            if "model" in payload:
                original_model = payload["model"]
                payload["model"] = MODEL_MAP.get(original_model, DEFAULT_MODEL)
                if payload["model"] != original_model:
                    print(f"[proxy] Model rewrite: {original_model} -> {payload['model']}")
                # Bedrock doesn't allow both temperature and top_p simultaneously
                if "temperature" in payload and "top_p" in payload:
                    del payload["top_p"]
                # Bob's gateway rejects reasoning fields that clients (e.g. Hermes)
                # echo back on prior assistant messages ("unexpected property")
                for msg in payload.get("messages") or []:
                    if isinstance(msg, dict):
                        for k in ("reasoning", "reasoning_content", "reasoning_details"):
                            msg.pop(k, None)
                body = json.dumps(payload)
        except (json.JSONDecodeError, KeyError):
            pass

    # Check if streaming is requested
    is_stream = False
    if body:
        try:
            is_stream = json.loads(body).get("stream", False)
        except (json.JSONDecodeError, KeyError):
            pass

    headers = _backend_headers(request.method, signed_path, body)
    if request.content_type:
        headers["Content-Type"] = request.content_type

    resp = req.request(
        method=request.method,
        url=target_url,
        headers=headers,
        data=body,
        stream=is_stream,
    )

    print(f"[proxy] {request.method} {signed_path} -> {resp.status_code}")

    if is_stream:
        def generate():
            for chunk in resp.iter_content(chunk_size=None):
                yield chunk

        return Response(
            generate(),
            status=resp.status_code,
            content_type=resp.headers.get('Content-Type', 'text/event-stream'),
        )

    return Response(
        resp.content,
        status=resp.status_code,
        content_type=resp.headers.get('Content-Type', 'application/json'),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _discover_instance_and_team() -> None:
    """Populate INSTANCE_ID / TEAM_ID by calling /admin/v1/profile if not set."""
    global INSTANCE_ID, TEAM_ID
    if INSTANCE_ID and TEAM_ID:
        return
    try:
        path = "/admin/v1/profile"
        sig_headers = sign_request("GET", path, "")
        r = req.get(
            f"{BASE_URL}{path}",
            headers={
                "Authorization": f"Apikey {API_KEY}",
                "User-Agent": "bobshell/1.0.4",
                **sig_headers,
            },
            timeout=10,
        )
        if r.status_code != 200:
            print(f"[startup] /admin/v1/profile -> {r.status_code}: {r.text[:200]}")
            return
        data = r.json()
        instances = data.get("instances", [])
        if not instances:
            print("[startup] No instances on profile; cannot auto-discover team.")
            return
        inst = instances[0]
        if not INSTANCE_ID:
            INSTANCE_ID = inst.get("instance_id", "")
        teams = inst.get("teams", [])
        if not TEAM_ID and teams:
            TEAM_ID = teams[0].get("id", "")
    except Exception as e:
        print(f"[startup] Failed to auto-discover instance/team: {e}")


if __name__ == '__main__':
    if not API_KEY:
        print("ERROR: No API key configured.")
        print("Set BOB_API_KEY environment variable or edit API_KEY in proxy-apikey.py")
        raise SystemExit(1)
    if not HMAC_SECRET:
        print("ERROR: No HMAC secret configured.")
        print("Set BOB_HMAC_SECRET environment variable (see .env.sample)")
        raise SystemExit(1)

    _discover_instance_and_team()

    print("=== Bob HMAC Proxy (API Key mode) ===\n")
    print(f"[1] Using API key: {API_KEY[:10]}...{API_KEY[-4:]}")
    print(f"    Instance:    {INSTANCE_ID or '(not set)'}")
    print(f"    Team:        {TEAM_ID or '(not set)'}")
    print(f"[2] Proxy listening on http://localhost:{PORT}")
    print(f"    Forwarding to {BASE_URL}\n")
    print(f"Models: {', '.join(MODEL_MAP)}\n")
    print("OpenCode / OpenAI-compatible clients:")
    print(f"  baseURL: http://localhost:{PORT}/v1")
    print(f"  apiKey:  any-value\n")
    print("Claude Code (Anthropic mode):")
    print(f"  ANTHROPIC_BASE_URL=http://localhost:{PORT}/anthropic ANTHROPIC_API_KEY=proxy claude --model premium\n")
    print("Claude Code (Bedrock mode — no Claude Pro login needed):")
    print(f"  CLAUDE_CODE_USE_BEDROCK=1 ANTHROPIC_BEDROCK_BASE_URL=http://localhost:{PORT}/bedrock CLAUDE_CODE_SKIP_BEDROCK_AUTH=1 claude --model premium\n")
    app.run(host='0.0.0.0', port=PORT)
