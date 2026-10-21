"""Server validation is independent of provider strict-schema enforcement."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from customerops_ai.schemas.products import ProductFilters


class ToolArguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False
    )


class SearchProducts(ToolArguments):
    query: str = Field(min_length=1, max_length=120)
    filters: ProductFilters | None


class SearchKnowledge(ToolArguments):
    query: str = Field(min_length=1, max_length=500)


class ProductLookup(ToolArguments):
    product_id: UUID


class OrderLookup(ToolArguments):
    order_id: UUID


class CreateSupportTicket(ToolArguments):
    subject: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
