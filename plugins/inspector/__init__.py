"""Inspector plugin: records tool calls, LLM turns and provider requests.

Every event is appended as one JSON line to INSPECTOR_LOG_DIR/inspector.jsonl
(default /opt/data/logs, which compose maps to ./data/logs on the host).

All hooks are observers: they never block, modify or inject anything.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("inspector")

LOG_DIR = Path(os.environ.get("INSPECTOR_LOG_DIR", "/opt/data/logs"))
LOG_FILE = LOG_DIR / "inspector.jsonl"
MAX_FIELD = int(os.environ.get("INSPECTOR_MAX_FIELD", "4000"))

_lock = threading.Lock()
# Crude secret masking; extend it for your own key formats.
_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,})")


def _clean(obj, depth=0):
    """Make any payload JSON-safe, redacted and size-limited."""
    if depth > 6:
        return "<max depth>"
    if isinstance(obj, str):
        text = _SECRET.sub("[REDACTED]", obj)
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


def _write(event: str, **fields):
    """Append one JSON line. Never raises: a logging bug must not break the agent."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **{k: _clean(v) for k, v in fields.items()},
        }
        line = json.dumps(record, ensure_ascii=False)
        with _lock:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        logger.exception("inspector failed to write event %s", event)


# --------------------------------------------------------------------------
# Hooks. Always accept **kwargs: Hermes may add fields in future versions.
# --------------------------------------------------------------------------
def pre_tool_call(tool_name=None, args=None, task_id="", session_id="",
                  tool_call_id="", turn_id="", **kwargs):
    _write("pre_tool_call", tool=tool_name, args=args, task_id=task_id,
           session_id=session_id, tool_call_id=tool_call_id, turn_id=turn_id)
    return None  # None = allow. Returning {"action": "block", ...} would veto the call.


def post_tool_call(tool_name=None, args=None, result=None, duration_ms=0,
                   status=None, error_type=None, error_message=None,
                   task_id="", session_id="", tool_call_id="", turn_id="", **kwargs):
    _write("post_tool_call", tool=tool_name, args=args, result=result,
           duration_ms=duration_ms, status=status, error_type=error_type,
           error_message=error_message, task_id=task_id, session_id=session_id,
           tool_call_id=tool_call_id, turn_id=turn_id)


def pre_llm_call(session_id="", user_message=None, conversation_history=None,
                 is_first_turn=False, model="", platform="", **kwargs):
    history = conversation_history or []
    _write("pre_llm_call", session_id=session_id, model=model, platform=platform,
           is_first_turn=is_first_turn, user_message=user_message,
           history_len=len(history),
           last_message=history[-1] if history else None)
    return None  # None = inject nothing, block nothing


def post_llm_call(session_id="", user_message=None, assistant_response=None,
                  conversation_history=None, model="", platform="", **kwargs):
    _write("post_llm_call", session_id=session_id, model=model, platform=platform,
           user_message=user_message, assistant_response=assistant_response,
           history_len=len(conversation_history or []))


def pre_api_request(session_id="", model="", provider="", base_url="",
                    message_count=None, tool_count=None, approx_input_tokens=None,
                    api_call_count=None, retry_count=None, **kwargs):
    # Deliberately omits request_messages (raw transcript) to keep the log small.
    _write("pre_api_request", session_id=session_id, model=model, provider=provider,
           base_url=base_url, message_count=message_count, tool_count=tool_count,
           approx_input_tokens=approx_input_tokens, api_call_count=api_call_count,
           retry_count=retry_count)


def post_api_request(session_id="", model="", provider="", api_duration=None,
                     finish_reason=None, usage=None, assistant_tool_call_count=None,
                     api_call_count=None, **kwargs):
    _write("post_api_request", session_id=session_id, model=model, provider=provider,
           api_duration=api_duration, finish_reason=finish_reason, usage=usage,
           assistant_tool_call_count=assistant_tool_call_count,
           api_call_count=api_call_count)


def register(ctx):
    ctx.register_hook("pre_tool_call", pre_tool_call)
    ctx.register_hook("post_tool_call", post_tool_call)
    ctx.register_hook("pre_llm_call", pre_llm_call)
    ctx.register_hook("post_llm_call", post_llm_call)
    ctx.register_hook("pre_api_request", pre_api_request)
    ctx.register_hook("post_api_request", post_api_request)
    logger.info("inspector plugin registered, logging to %s", LOG_FILE)