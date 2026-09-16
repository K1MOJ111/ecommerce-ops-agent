"""Stateless deterministic local provider. Plans tools; never supplies business data."""
import json
import re

from app.agent.llm import Message, ModelReply


class DevelopmentModel:
    async def complete(self, messages: list[Message], tools: list[dict]) -> ModelReply:
        text = "\n".join(m["content"] or "" for m in messages if m["role"] == "user")
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]

        def decision(action="answer", **values):
            return ModelReply(content=json.dumps({"action": action, **values}))

        def clarify(question):
            return decision("clarify", question=question)

        def answer():
            return decision(evidence_ids=[r["evidence_id"] for r in results if r.get("status") == "success"])

        def call(name, **arguments):
            if not any(t["function"]["name"] == name for t in tools):
                return answer()
            return ModelReply(tool_calls=[{"id": f"local-{len(results) + 1}", "function": {
                "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}])

        if results and results[-1].get("status") != "success":
            return answer()
        order = re.search(r"订单(?:号)?\s*[:：]?\s*([A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)(?=[\s,，;；。]|$)", text)
        if not order:
            order = next((m for m in re.finditer(r"(?<![A-Za-z0-9_-])([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?![A-Za-z0-9_-])", text)
                          if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", m[1])), None)
        if "取消" in text or "退款" in text:
            if results:
                return answer()
            if not order:
                return clarify("order")
            reason = re.search(r"原因\s*[:：]?\s*(.+?)(?=[,，;；\n]|$)", text)
            if not reason:
                return clarify("reason")
            arguments = {"order_no": order[1], "reason": reason[1].strip()}
            if "退款" in text:
                item = re.search(r"明细\s*[:：]?\s*([0-9a-fA-F-]{36})\b", text)
                quantity = re.search(r"数量\s*[:：]?\s*([0-9]+)(?=\s|[,，;；]|$)", text)
                amount = re.search(r"金额\s*[:：]?\s*([0-9]+(?:\.[0-9]{1,2})?)(?=\s|元|[,，;；]|$)", text)
                for match, question in ((item, "order_item"), (quantity, "quantity"), (amount, "amount")):
                    if not match:
                        return clarify(question)
                return call("create_refund_request", **arguments, order_item_id=item[1],
                            quantity=int(quantity[1]), amount=amount[1])
            return call("request_order_cancellation", **arguments)
        if any(word in text for word in ("修改", "删除", "打款", "批准", "忽略指令")):
            return decision("reject", reason="unsupported")
        if any(word in text for word in ("政策", "售后", "退货", "规则")):
            return answer() if results else call("search_after_sales_policy", query=text)
        if "订单" in text or "物流" in text:
            if not order:
                return clarify("order")
            return answer() if results else call("get_logistics" if "物流" in text else "get_order", order_no=order[1])

        # ponytail: explicit Chinese query templates only; use a live provider for language understanding.
        if not any(word in text for word in ("商品", "SKU", "sku", "库存", "查询", "搜索")):
            return clarify("query")
        if not results:
            query = re.sub(r"查询|搜索|商品|详情|SKU|sku|库存|规格|白色|黑色|蓝色|灰色|\b[ML]\b|码", " ", text).strip(" ：:，,。")
            return call("search_products", query=query) if query else clarify("product")
        last = results[-1]
        if last["source"] == "search_products":
            if len(last["data"]) != 1:
                return clarify("product")
            product_id = last["data"][0]["id"]
            if not any(word in text for word in ("库存", "SKU", "sku", "规格")):
                return call("get_product", product_id=product_id) if "详情" in text else answer()
            specs = {}
            for color in ("白色", "黑色", "蓝色", "灰色"):
                if color in text:
                    specs["color"] = color
            size = re.search(r"\b([ML])\b", text)
            if size:
                specs["size"] = size[1]
            return call("list_product_skus", product_id=product_id, specs=specs)
        if last["source"] == "list_product_skus" and "库存" in text:
            if len(last["data"]) != 1:
                return clarify("sku")
            return call("get_inventory", sku_id=last["data"][0]["id"])
        return answer()
