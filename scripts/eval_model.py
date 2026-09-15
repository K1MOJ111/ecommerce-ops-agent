"""Scripted control, not a language understanding model. Never receives the scoring oracle."""
import json
from copy import deepcopy
from app.agent.llm import ModelReply


class ScriptedModel:
    def __init__(self, *steps):
        self.steps = deepcopy(list(steps))
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(deepcopy(messages))
        if not self.steps:
            ids = [json.loads(m["content"])["evidence_id"] for m in messages if m["role"] == "tool"
                   and json.loads(m["content"]).get("status") == "success"]
            return ModelReply(content=json.dumps({"action": "answer", "evidence_ids": ids}))
        step = self.steps.pop(0)
        if isinstance(step, dict):
            return ModelReply(content=json.dumps(step))
        return ModelReply(tool_calls=[{"id": f"eval-{len(self.calls)}-{i}", "function": {
            "name": name, "arguments": json.dumps(args, ensure_ascii=False)}} for i, (name, args) in enumerate(step)])
