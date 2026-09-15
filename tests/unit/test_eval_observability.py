import asyncio
from copy import deepcopy
import json
import logging
from uuid import uuid4

import httpx
import pytest

from app.agent.graph import AgentContext, run_agent
from app.agent.llm import OpenAICompatibleModel
from app.agent.state import Evidence, FinalResponse
from app.core.config import Settings
from app.core.observability import FIELDS, logger
from app.core.security import RequestContext
from app.tools.registry import invoke_tool
from scripts.agent_eval import Capture, OUT, grounded_response, metrics, percentile, score
from scripts.eval_model import ScriptedModel


def settings():
    return Settings(_env_file=None, database_url="postgresql+asyncpg://localhost/unit_test")


@pytest.fixture
def capture():
    handler = Capture()
    previous = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield handler.events
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def test_dataset_is_versioned_unique_and_scripts_are_separate():
    for name in ("agent", "rag"):
        dataset = json.loads((OUT / f"{name}_eval_dataset.json").read_text(encoding="utf-8"))
        ids = [case["case_id" if name == "agent" else "id"] for case in dataset["cases"]]
        assert dataset["version"] and len(ids) == len(set(ids))
    dataset = json.loads((OUT / "agent_eval_dataset.json").read_text(encoding="utf-8"))
    for case in dataset["cases"]:
        assert {"category", "user_input", "trusted_context", "setup", "expected_behavior"} <= case.keys()
        assert "expected_behavior" not in json.dumps(case["setup"]["script"])


@pytest.mark.parametrize("text", ["库存是999", "\n价格是零", "\n订单已取消"])
def test_grounding_rejects_appended_unsupported_claim(text):
    final = FinalResponse(kind="answer", status="unconfirmed", text="没有足够的查询证据，无法确认。")
    assert grounded_response(final, {})
    final.text += text
    assert not grounded_response(final, {})


def test_grounding_rejects_forged_evidence_and_changed_value():
    from datetime import UTC, datetime
    from app.schemas.tools import ToolResult
    item = Evidence(id=1, tool_call_id="x", result=ToolResult(status="success", data={"available":17},
        source="get_inventory", queried_at=datetime.now(UTC), request_id=uuid4()))
    block = f"资料 [1] get_inventory（查询时间 {item.result.queried_at.isoformat()}）：\n" + json.dumps({"available":17},indent=2)
    final = FinalResponse(kind="answer", status="ok", text=block, evidence=[item])
    assert grounded_response(final, {1: deepcopy(item)})
    final.text = final.text.replace("17", "999")
    assert not grounded_response(final, {1: item})
    final.text = block
    assert not grounded_response(final, {})


async def test_parallel_request_correlation_and_no_prompt_logging(capture):
    ids = [uuid4(), uuid4()]
    async def run(rid):
        return await run_agent("PASSWORD-PRIVATE-ADDRESS", context=AgentContext(
            RequestContext(uuid4(), frozenset(), rid), ScriptedModel({"action":"clarify","question":"order"}),
            None, settings()))
    await asyncio.gather(*(run(rid) for rid in ids))
    assert {e["request_id"] for e in capture} == {str(i) for i in ids}
    assert all(set(e) <= FIELDS for e in capture)
    assert "PASSWORD" not in json.dumps(capture)
    done = [e for e in capture if e["event"] == "request_completed"]
    assert len(done) == 2 and all(e["llm_calls"] == 1 and e["tool_calls"] == 0 for e in done)


async def test_unknown_tool_and_arguments_never_logged(capture):
    await invoke_tool("SECRET-KEY-AS-TOOL", {"password":"PRIVATE"}, session=None,
                      context=RequestContext(uuid4(), frozenset(), uuid4()))
    assert capture[-1]["tool"] == "unknown" and capture[-1]["status"] == "invalid_argument"
    assert "PRIVATE" not in json.dumps(capture) and "SECRET" not in json.dumps(capture)


@pytest.mark.parametrize("exception", [RuntimeError, asyncio.CancelledError])
async def test_request_failure_and_cancellation_metadata(capture, exception):
    entered = asyncio.Event()
    class Failing:
        async def complete(self, messages, tools):
            if exception is asyncio.CancelledError:
                entered.set()
                await asyncio.Future()
            raise exception("SECRET-IN-EXCEPTION")
    task = asyncio.create_task(run_agent("private", context=AgentContext(RequestContext(uuid4(), frozenset(), uuid4()),
                               Failing(), None, settings())))
    if exception is asyncio.CancelledError:
        await entered.wait()
        task.cancel()
    with pytest.raises(exception):
        await task
    assert capture[-1]["event"] == "request_failed"
    assert capture[-1]["error_category"] == exception.__name__
    assert "SECRET" not in json.dumps(capture)


async def test_usage_only_accepts_nonnegative_integer_counts(capture):
    response = {"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":'{"action":"clarify","question":"order"}'}}],
                "usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12,"password":"SECRET"}}
    model = OpenAICompatibleModel(settings().model_copy(update={"llm_base_url":"https://example.test/v1", "llm_model":"unit",
        "llm_api_key": __import__('pydantic').SecretStr('PRIVATE')}), transport=httpx.MockTransport(lambda req:httpx.Response(200,json=response)))
    await model.complete([{"role":"user","content":"private"}], [])
    assert capture == [{"event":"model_usage", "prompt_tokens":10,"completion_tokens":2,"total_tokens":12}]


def test_metrics_denominators_and_nearest_rank_percentiles():
    rows = [{"case_id":str(i), "passed":i==0, "status":"ok", "category":"security", "checks":{"grounding":i==0,"security":i==0},
             "grounding_applicable":True,"unauthorized_action":i==1} for i in range(2)]
    report = metrics(rows)
    assert report["task_success_rate"] == report["unsupported_claim_rate"] == report["unauthorized_action_rate"] == .5
    assert percentile([1,2,3,4,100],.95) == 100 and percentile([],.5) is None


def test_scorer_does_not_accept_wrong_tool_or_expected_status():
    case = json.loads((OUT / "agent_eval_dataset.json").read_text(encoding="utf-8"))["cases"][0]
    final = FinalResponse(kind="answer",status="unconfirmed",text="没有足够的查询证据，无法确认。")
    result = score(case,[],final,[])
    assert not result["passed"] and not result["checks"]["tool_selection"] and not result["checks"]["status"]
