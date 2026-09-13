from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.commerce import Product, ProductSKU, ProductStatus, SKUStatus
from app.schemas.commerce import ProductDetail, ProductSummary, SKUData


def _check_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit_out_of_range")


async def search_products(
    session: AsyncSession, query: str, *, category_code: str | None = None, limit: int = 20,
) -> list[ProductSummary]:
    _check_limit(limit)
    query = query.strip()
    if not 1 <= len(query) <= 200:
        raise ValueError("invalid_query_length")
    statement = select(Product).where(Product.status == ProductStatus.ACTIVE, Product.name.icontains(query, autoescape=True))
    if category_code is not None:
        if not 1 <= len(category_code.strip()) <= 100:
            raise ValueError("invalid_category")
        statement = statement.where(Product.category_code == category_code.strip())
    # ponytail: literal substring search; evaluate trigram indexing only when query plans justify it.
    rows = await session.scalars(statement.order_by(Product.product_code).limit(limit))
    return [ProductSummary.model_validate(row) for row in rows]


async def get_product(session: AsyncSession, product_id: UUID) -> ProductDetail | None:
    row = await session.scalar(select(Product).where(Product.id == product_id, Product.status == ProductStatus.ACTIVE))
    return ProductDetail.model_validate(row) if row else None


async def list_product_skus(
    session: AsyncSession, product_id: UUID, *, specs: dict[str, str] | None = None, limit: int = 100,
) -> list[SKUData]:
    _check_limit(limit)
    statement = select(ProductSKU).join(Product).where(
        Product.id == product_id, Product.status == ProductStatus.ACTIVE, ProductSKU.status == SKUStatus.ACTIVE,
    )
    if specs is not None:
        if len(specs) > 8 or any(
            not isinstance(k, str) or not isinstance(v, str) or not 1 <= len(k.strip()) <= 64 or not 1 <= len(v.strip()) <= 100
            for k, v in specs.items()
        ):
            raise ValueError("invalid_specs_filter")
        statement = statement.where(ProductSKU.specs.contains(specs))
    rows = await session.scalars(statement.order_by(ProductSKU.sku_code).limit(limit))
    return [SKUData.model_validate(row) for row in rows]
