"""Shared JSON transport values, independent of provider and persistence libraries."""

from pydantic import JsonValue

type JsonObject = dict[str, JsonValue]
