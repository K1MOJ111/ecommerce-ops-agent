"""Allowlisted metadata only; business payloads never enter this logger."""
import contextvars
import functools
import inspect
import json
import logging
from time import perf_counter
from uuid import UUID

logger = logging.getLogger("ecommerce.observability")
_trace = contextvars.ContextVar("ops_trace", default=None)
FIELDS = {"event", "request_id", "thread_id", "operation_id", "duration_ms", "status",
          "error_category", "tool", "tool_calls", "llm_calls", "result_count", "mode",
          "prompt_tokens", "completion_tokens", "total_tokens"}


def configure_logging():
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False


def correlate(**ids):
    trace = _trace.get()
    if trace is not None:
        trace.update({key: str(value) for key, value in ids.items()
                      if key in {"thread_id", "operation_id"} and isinstance(value, UUID)})


def emit(event, **fields):
    trace = _trace.get() or {}
    record = {key: trace[key] for key in ("request_id", "thread_id", "operation_id") if key in trace}
    record.update({key: value for key, value in fields.items() if key in FIELDS})
    record["event"] = event
    logger.info(json.dumps(record, ensure_ascii=True, allow_nan=False))


def observed(kind):
    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs).arguments
            token = None
            if kind == "request":
                context = bound["context"]
                from app.core.security import RequestContext
                if not isinstance(context.request, RequestContext):
                    raise TypeError("server_request_context_required")
                trace = {"request_id": str(context.request.request_id), "tool_calls": 0, "llm_calls": 0}
                token = _trace.set(trace)
                correlate(thread_id=bound.get("thread_id"), operation_id=getattr(bound.get("request"), "operation_id", None))
            trace = _trace.get()
            fields = {}
            if kind == "tool":
                from app.tools.registry import TOOLS, WRITE_TOOLS
                name = bound.get("name")
                fields["tool"] = name if isinstance(name, str) and name in (TOOLS | WRITE_TOOLS) else "unknown"
                if trace is not None:
                    trace["tool_calls"] += 1
                emit("tool_call", **fields)
            elif kind == "model" and trace is not None:
                trace["llm_calls"] += 1
            elif kind == "request":
                emit("request_started")
            started = perf_counter()
            try:
                result = await fn(*args, **kwargs)
                fields["status"] = getattr(result, "status", "ok")
                if kind == "request" and isinstance(result, dict):
                    fields["status"] = getattr(result.get("final_response"), "status", "unconfirmed")
                if kind == "model" and isinstance(result, dict) and result.get("errors"):
                    fields["error_category"] = result["errors"][-1].code
                    fields["status"] = "error"
                if kind == "tool" and result.error:
                    fields["error_category"] = result.error.code
                if kind == "rag":
                    fields.update(result_count=len(result), mode=bound.get("mode", "hybrid"))
                return result
            except BaseException as exc:
                fields.update(status="failed", error_category=type(exc).__name__)
                raise
            finally:
                fields["duration_ms"] = round((perf_counter() - started) * 1000, 3)
                if kind == "request":
                    fields.update(tool_calls=trace["tool_calls"], llm_calls=trace["llm_calls"])
                event = {"request": "request_failed" if fields.get("status") == "failed" else "request_completed",
                         "tool": "tool_result", "model": "model_call", "rag": "rag_retrieval"}[kind]
                emit(event, **fields)
                if token is not None:
                    _trace.reset(token)
        return wrapped
    return decorate
