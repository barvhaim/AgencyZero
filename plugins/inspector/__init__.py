"""Inspector plugin: records tool calls, LLM turns and provider requests.

Events are sent to an external JSONL logging server, authenticated with a
shared bearer secret (INSPECTOR_SECRET).

All hooks are observers: they never block, modify or inject anything.

SECURITY NOTE: this plugin runs inside the agent's process, so everything it
reports is the agent's own claim, and the agent can read INSPECTOR_SECRET.
The secret only keeps *other* network peers from posting events. Do not treat
this log as tamper-proof evidence; cross-check it against an outside observer.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("inspector")

LOGGER_URL = os.environ.get("INSPECTOR_LOGGER_URL")
INSPECTOR_SECRET = os.environ.get("INSPECTOR_KEY", "")
MAX_FIELD = int(os.environ.get("INSPECTOR_MAX_FIELD", "4000"))

# Only send events when both the URL and the secret are configured.
ENABLED = bool(LOGGER_URL and INSPECTOR_SECRET)

# Crude secret masking; extend it for your own key formats.
_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,})")

CAPTURE_REASONING = False
CAPTURE_TEXT_DELTA_STREAM = False

# Failure reporting state: log the first failure, then every Nth, to avoid
# flooding logs when the server is down, rejecting us, or its log is full.
_FAILURE_LOG_EVERY = 100
_failure_count = 0


def _redact(text: str) -> str:
    text = _SECRET.sub("[REDACTED]", text)
    # Also strip the inspector secret itself, in case the agent echoes its
    # environment or config into a tool result.
    if INSPECTOR_SECRET:
        text = text.replace(INSPECTOR_SECRET, "[REDACTED]")
    return text


def _clean(obj, depth=0):
    """Make any payload JSON-safe, redacted and size-limited."""
    if depth > 6:
        return "<max depth>"

    if isinstance(obj, str):
        text = _redact(obj)
        if len(text) > MAX_FIELD:
            text = text[:MAX_FIELD] + f"...[+{len(text) - MAX_FIELD} chars]"
        return text

    if isinstance(obj, dict):
        return {str(k): _clean(v, depth + 1) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [_clean(v, depth + 1) for v in obj[:50]]

    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj

    return _clean(str(obj), depth + 1)


def _report_failure(event: str, reason: str) -> None:
    global _failure_count
    _failure_count += 1
    if _failure_count == 1 or _failure_count % _FAILURE_LOG_EVERY == 0:
        logger.warning(
            "inspector failed to send event %s (%s); %d failure(s) so far",
            event, reason, _failure_count,
        )


def _write(event: str, **fields):
    """Send one JSON event to the external logger. Never raises."""
    if not ENABLED:
        return

    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **{k: _clean(v) for k, v in fields.items()},
        }

        data = json.dumps(record, ensure_ascii=False).encode("utf-8")

        request = urllib.request.Request(
            LOGGER_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {INSPECTOR_SECRET}",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=2):
            pass

    except urllib.error.HTTPError as exc:
        # 401 = bad/missing secret, 507 = server log full, 413/400 = bad payload.
        _report_failure(event, f"HTTP {exc.code}")
        exc.close()
    except Exception as exc:
        _report_failure(event, type(exc).__name__)


# --------------------------------------------------------------------------
# Hooks. Always accept **kwargs: Hermes may add fields in future versions.
# --------------------------------------------------------------------------

def pre_tool_call(tool_name=None, args=None, task_id="", session_id="",
                  tool_call_id="", turn_id="", **kwargs):
    _write(
        "pre_tool_call",
        tool=tool_name,
        args=args,
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        turn_id=turn_id,
    )
    return None


def post_tool_call(tool_name=None, args=None, result=None, duration_ms=0,
                   status=None, error_type=None, error_message=None,
                   task_id="", session_id="", tool_call_id="", turn_id="", **kwargs):
    _write(
        "post_tool_call",
        tool=tool_name,
        args=args,
        result=result,
        duration_ms=duration_ms,
        status=status,
        error_type=error_type,
        error_message=error_message,
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        turn_id=turn_id,
    )


def pre_llm_call(session_id="", user_message=None, conversation_history=None,
                 is_first_turn=False, model="", platform="", **kwargs):
    history = conversation_history or []
    _write(
        "pre_llm_call",
        session_id=session_id,
        model=model,
        platform=platform,
        is_first_turn=is_first_turn,
        user_message=user_message,
        history_len=len(history),
        last_message=history[-1] if history else None,
    )
    return None


def post_llm_call(session_id="", user_message=None, assistant_response=None,
                  conversation_history=None, model="", platform="", **kwargs):
    history = conversation_history or []
    _write(
        "post_llm_call",
        session_id=session_id,
        model=model,
        platform=platform,
        user_message=user_message,
        assistant_response=assistant_response,
        history_len=len(history),
    )


def pre_api_request(session_id="", model="", provider="", base_url="",
                    message_count=None, tool_count=None, approx_input_tokens=None,
                    api_call_count=None, retry_count=None, **kwargs):
    # Deliberately omits request_messages (raw transcript) to keep the log small.
    _write(
        "pre_api_request",
        session_id=session_id,
        model=model,
        provider=provider,
        base_url=base_url,
        message_count=message_count,
        tool_count=tool_count,
        approx_input_tokens=approx_input_tokens,
        api_call_count=api_call_count,
        retry_count=retry_count,
    )


def post_api_request(session_id="", model="", provider="", api_duration=None,
                     finish_reason=None, usage=None, assistant_tool_call_count=None,
                     api_call_count=None, **kwargs):
    _write(
        "post_api_request",
        session_id=session_id,
        model=model,
        provider=provider,
        api_duration=api_duration,
        finish_reason=finish_reason,
        usage=usage,
        assistant_tool_call_count=assistant_tool_call_count,
        api_call_count=api_call_count,
    )


def on_stream_delta(delta="", kind="text", **kwargs):
    if kind == "reasoning" and not CAPTURE_REASONING:
        return
    if kind == "text" and not CAPTURE_TEXT_DELTA_STREAM:
        return
    _write(
        "stream_delta",
        kind=kind,
        delta=delta,
        **kwargs,
    )


def register(ctx):
    if LOGGER_URL and not INSPECTOR_SECRET:
        logger.warning(
            "INSPECTOR_LOGGER_URL is set but INSPECTOR_SECRET is not; "
            "inspector plugin is disabled (the server would reject every event)"
        )
    elif not LOGGER_URL:
        logger.info("INSPECTOR_LOGGER_URL not set; inspector plugin is disabled")

    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("pre_api_request", pre_api_request)
    ctx.register_hook("post_api_request", post_api_request)
    ctx.register_hook("on_stream_delta", on_stream_delta)

    if ENABLED:
        logger.info("inspector plugin registered, sending events to %s", LOGGER_URL)