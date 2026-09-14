from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.operations import RefundRequestInput
from app.tools.registry import TOOLS, WRITE_TOOLS, tool_schemas


def test_read_and_draft_registries_are_separate():
    assert set(TOOLS).isdisjoint(WRITE_TOOLS)
    assert len(tool_schemas()) == 7 and len(tool_schemas(include_write=True)) == 9
    for tool in WRITE_TOOLS.values():
        assert tool.requires_workflow
        assert not {"actor", "actor_id", "operation_id", "thread_id", "permissions"} & set(tool.input_schema.model_fields)


@pytest.mark.parametrize("overrides", [
    {"quantity": True}, {"quantity": 0}, {"quantity": -1}, {"quantity": "1"}, {"quantity": 1.1},
    {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": "0"}, {"amount": "-1"},
    {"amount": "0.001"}, {"amount": "10000000000000000"}, {"reason": " "},
    {"order_no": ""}, {"operation_id": str(uuid4())},
])
def test_money_and_identity_boundary(overrides):
    with pytest.raises(ValidationError):
        RefundRequestInput.model_validate({"order_no": "order", "order_item_id": str(uuid4()),
                                          "quantity": 1, "amount": "10.00", "reason": "reason", **overrides})


def test_production_rejects_local_fixed_identity():
    with pytest.raises(ValidationError, match="dev_actor_id_forbidden_in_production"):
        Settings(_env_file=None, database_url="postgresql+asyncpg://test:test@localhost/unit_test",
                 app_env="production", dev_actor_id=uuid4())
