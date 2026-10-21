"""Validated catalog search filters, shared by tools and business services."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProductFilters(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False
    )

    category: str | None = Field(default=None, min_length=1, max_length=100)
    min_price: float | None = Field(default=None, ge=0, le=1_000_000)
    max_price: float | None = Field(default=None, ge=0, le=1_000_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    in_stock: bool | None = None

    @model_validator(mode="after")
    def price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("Invalid price range")
        return self
