from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import RequestContext
from app.schemas.commerce import InventoryResult, LogisticsResult, OrderData, ProductDetail, ProductSummary, SKUData
from app.schemas.tools import (
    GetInventoryInput, GetProductInput, ListProductSKUsInput, OrderQueryInput,
    SearchProductsInput, ToolError, ToolInput, ToolResult, ToolStatus,
)
from app.services import catalog, inventory, orders

ERROR_MESSAGES = {
    "not_found": "No matching data was found.",
    "invalid_argument": "Invalid tool arguments; check the input schema.",
    "forbidden": "The requested order is not accessible.",
    "temporarily_unavailable": "The query service is temporarily unavailable.",
}


def _failure(
    result_schema: type[ToolResult], source: str, context: RequestContext,
    status: ToolStatus, *, code: str | None = None,
) -> ToolResult:
    return result_schema(
        status=status, source=source, queried_at=datetime.now(UTC), request_id=context.request_id,
        error=ToolError(code=code or status, message=ERROR_MESSAGES[status]),
    )


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_schema: type[ToolInput]
    result_schema: type[ToolResult]
    service: Callable[..., Awaitable[object]]
    requires_context: bool = False

    async def invoke(
        self, arguments: object, *, session: AsyncSession, context: RequestContext,
    ) -> ToolResult:
        # Context is supplied separately by server code, never deserialized from arguments.
        if not isinstance(context, RequestContext):
            raise TypeError("server_request_context_required")
        if not isinstance(arguments, dict):
            return _failure(self.result_schema, self.name, context, "invalid_argument")
        try:
            params = self.input_schema.model_validate(arguments).model_dump(by_alias=True)
        except ValidationError:
            return _failure(self.result_schema, self.name, context, "invalid_argument")

        try:
            if self.requires_context:
                data = await self.service(session, context, **params)
            else:
                data = await self.service(session, **params)
        except orders.OrderNotAccessible:
            # The Service hides absence from self-scoped callers. Only read:any can distinguish it.
            status = "not_found" if "orders:read:any" in context.permissions else "forbidden"
            return _failure(self.result_schema, self.name, context, status)
        except ValidationError:
            raise  # A broken Service output is a programming error, not invalid model input.
        except ValueError:
            return _failure(self.result_schema, self.name, context, "invalid_argument")
        except (TimeoutError, ConnectionError, PoolTimeoutError):
            return _failure(self.result_schema, self.name, context, "temporarily_unavailable")
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", "") or ""
            if not (
                isinstance(exc, (OperationalError, InterfaceError)) or exc.connection_invalidated
                or sqlstate[:2] in {"08", "40", "53"}
                or sqlstate in {"55P03", "57014", "57P01", "57P02", "57P03"}
            ):
                raise
            return _failure(self.result_schema, self.name, context, "temporarily_unavailable")

        if data is None or data == []:
            return _failure(self.result_schema, self.name, context, "not_found")
        return self.result_schema(
            status="success", data=data, source=self.name, request_id=context.request_id,
            queried_at=getattr(data, "queried_at", datetime.now(UTC)),
        )

    def schema(self) -> dict[str, object]:
        return {
            "name": self.name, "description": self.description,
            "parameters": self.input_schema.model_json_schema(),
            "result": self.result_schema.model_json_schema(mode="serialization"),
        }


TOOLS = MappingProxyType({tool.name: tool for tool in (
    Tool("search_products", "Search active products by name and optional category code.",
         SearchProductsInput, ToolResult[list[ProductSummary]], catalog.search_products),
    Tool("get_product", "Get an active product by UUID.",
         GetProductInput, ToolResult[ProductDetail], catalog.get_product),
    Tool("list_product_skus", "List active SKUs with optional exact specification filters.",
         ListProductSKUsInput, ToolResult[list[SKUData]], catalog.list_product_skus),
    Tool("get_inventory", "Get stock by SKU UUID; empty stocks means unknown, not zero.",
         GetInventoryInput, ToolResult[InventoryResult], inventory.get_inventory),
    Tool("get_order", "Get an order by number within the server-authorized scope.",
         OrderQueryInput, ToolResult[OrderData], orders.get_order, requires_context=True),
    Tool("get_logistics", "Get authorized order packages and their synchronization times.",
         OrderQueryInput, ToolResult[LogisticsResult], orders.get_logistics, requires_context=True),
)})


def get_tool(name: str) -> Tool:
    return TOOLS[name]


def tool_schemas() -> list[dict[str, object]]:
    return [tool.schema() for tool in TOOLS.values()]


async def invoke_tool(
    name: str, arguments: object, *, session: AsyncSession, context: RequestContext,
) -> ToolResult:
    if not isinstance(context, RequestContext):
        raise TypeError("server_request_context_required")
    if not isinstance(name, str) or name not in TOOLS:
        return _failure(ToolResult[None], "registry", context, "invalid_argument", code="unknown_tool")
    return await get_tool(name).invoke(arguments, session=session, context=context)
