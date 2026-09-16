"""Bind a reply to the persisted question, before either provider plans tools."""
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

LABELS = {"order": "订单号", "order_item": "明细", "quantity": "数量", "amount": "金额", "reason": "原因"}
ORDER_CODE = r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*"


def bind_reply(question: str, message: str) -> str:
    label = LABELS.get(question)
    if not label:
        return message
    patterns = {"order": rf"订单(?:号)?\s*[:：]?\s*({ORDER_CODE})(?=[\s,，;；。]|$)",
                "order_item": r"明细(?:编号)?\s*[:：]?\s*([^\s,，;；]+)",
                "quantity": r"数量\s*[:：]?\s*([^\s,，;；]+)",
                "amount": r"金额\s*[:：]?\s*([^\s,，;；]+)",
                "reason": r"原因\s*[:：]?\s*(.+?)(?=[,，;；\n]|$)"}
    match = re.search(patterns[question], message)
    value = match[1].strip() if match else message.strip()
    if question == "order" and (not re.fullmatch(ORDER_CODE, value) or len(value) > 100):
        raise ValueError("invalid_clarification")
    if question == "order_item":
        UUID(value)
    if question == "quantity" and (not re.fullmatch(r"[0-9]+", value) or not 1 <= int(value) <= 2147483647):
        raise ValueError("invalid_clarification")
    if question == "amount":
        try:
            valid = bool(re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value)) and 0 < Decimal(value) < Decimal("1e16")
        except InvalidOperation:
            valid = False
        if not valid:
            raise ValueError("invalid_clarification")
    if question == "reason" and not 1 <= len(value) <= 500:
        raise ValueError("invalid_clarification")
    return message if match else f"{label}：{value}"
