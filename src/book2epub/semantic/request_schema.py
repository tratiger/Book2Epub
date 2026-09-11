"""Request-scoped structured-output schemas for semantic chunks.

The Pydantic models remain the canonical local contract.  This module adds the
finite scope of one request and bounded cardinalities before the schema reaches
a provider.  Post-generation validation remains mandatory because not every
provider enforces every JSON Schema keyword.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from book2epub.semantic.schemas import adapt_provider_schema, build_provider_schema

REQUEST_SCOPED_SCHEMA_CONTRACT_VERSION = "1.0"


def _set_string_scope(schema: dict[str, Any], allowed_ids: list[str]) -> None:
    """Constrain string/nullable string branches to the current chunk IDs."""
    enum = list(allowed_ids)
    if "type" in schema and schema.get("type") == "string":
        schema.clear()
        schema.update({"type": "string", "enum": enum})
        return
    for key in ("anyOf", "oneOf"):
        branches = schema.get(key)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    _set_string_scope(branch, allowed_ids)


def _walk_scope(node: Any, allowed_ids: list[str], *, parent_name: str = "") -> None:
    if isinstance(node, list):
        for item in node:
            _walk_scope(item, allowed_ids, parent_name=parent_name)
        return
    if not isinstance(node, dict):
        return

    properties = node.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            if not isinstance(child, dict):
                continue
            if name in {"chunk_id", "block_id", "target_block_id", "paragraph_continuation_of"}:
                _set_string_scope(child, allowed_ids)
            elif name in {"source_block_ids", "example_block_ids"}:
                items = child.get("items")
                if isinstance(items, dict):
                    _set_string_scope(items, allowed_ids)
                child["maxItems"] = len(allowed_ids)
            _walk_scope(child, allowed_ids, parent_name=name)

    items = node.get("items")
    if isinstance(items, dict):
        _walk_scope(items, allowed_ids, parent_name=parent_name)
    for key in ("$defs", "definitions"):
        definitions = node.get(key)
        if isinstance(definitions, dict):
            for definition in definitions.values():
                _walk_scope(definition, allowed_ids, parent_name=parent_name)
    for key in ("anyOf", "oneOf", "allOf"):
        _walk_scope(node.get(key), allowed_ids, parent_name=parent_name)


def _set_property_max_items(schema: dict[str, Any], property_name: str, maximum: int) -> None:
    if isinstance(schema.get("properties"), dict):
        child = schema["properties"].get(property_name)
        if isinstance(child, dict):
            child["maxItems"] = maximum
    for key in ("$defs", "definitions"):
        definitions = schema.get(key)
        if isinstance(definitions, dict):
            for child in definitions.values():
                if isinstance(child, dict):
                    _set_property_max_items(child, property_name, maximum)


def build_request_scoped_schema(
    model: type[BaseModel],
    *,
    provider: str,
    chunk_id: str,
    block_ids: list[str],
    pass_name: str,
) -> dict[str, Any]:
    """Build a provider-adapted schema bounded to one semantic request."""
    del pass_name  # Kept in the API to make call sites explicit and auditable.
    allowed_ids = list(dict.fromkeys(block_ids))
    schema = deepcopy(build_provider_schema(model))
    _walk_scope(schema, allowed_ids)
    _set_property_max_items(schema, "chunk_id", 1)

    # Top-level chunk_id is represented as an enum for broad provider support.
    properties = schema.get("properties")
    if isinstance(properties, dict) and isinstance(properties.get("chunk_id"), dict):
        _set_string_scope(properties["chunk_id"], [chunk_id])

    if model.__name__ == "StructureDecisionBatch":
        _set_property_max_items(schema, "decisions", len(allowed_ids))
    elif model.__name__ == "SemanticDecisionBatch":
        _set_property_max_items(schema, "decisions", len(allowed_ids))
        # A block may be both a caption/footnote source and a member of a
        # grouping relation, hence 2x is useful but still tied to input scope.
        _set_property_max_items(schema, "relations", max(1, 2 * len(allowed_ids)))
        _set_property_max_items(schema, "observations", 1)

    return adapt_provider_schema(schema, provider)


def semantic_output_token_budget(block_count: int, pass_name: str) -> int:
    """Bound output independently of the provider's context setting."""
    per_block = 160 if pass_name == "pass_a" else 220
    return min(4096, max(1024, 256 + max(1, block_count) * per_block))
