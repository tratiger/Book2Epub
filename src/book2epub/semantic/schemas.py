"""JSON Schema normalization for strict provider structured outputs (M7 spec Section 7)."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def _enforce_strict_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively ensure all object schemas have 'additionalProperties: False'
    and that all declared properties are in 'required' if required by strict modes.
    """
    schema_type = schema.get("type")

    if schema_type == "object" or "properties" in schema:
        schema["additionalProperties"] = False
        if "properties" in schema:
            # For strict OpenAI Structured Outputs, all properties must be required
            props = schema["properties"]
            current_required = set(schema.get("required", []))
            for prop_name, prop_schema in props.items():
                if isinstance(prop_schema, dict):
                    props[prop_name] = _enforce_strict_object_schema(prop_schema)
                current_required.add(prop_name)
            schema["required"] = sorted(list(current_required))

    elif schema_type == "array" and "items" in schema:
        if isinstance(schema["items"], dict):
            schema["items"] = _enforce_strict_object_schema(schema["items"])

    # Handle $defs / definitions
    for defs_key in ("$defs", "definitions"):
        if defs_key in schema and isinstance(schema[defs_key], dict):
            for d_name, d_val in schema[defs_key].items():
                if isinstance(d_val, dict):
                    schema[defs_key][d_name] = _enforce_strict_object_schema(d_val)

    return schema


def _strip_anthropic_unsupported_keywords(schema: dict[str, Any]) -> dict[str, Any]:
    """Keep canonical constraints local while avoiding Anthropic schema 400s."""
    unsupported = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
    for key in list(schema):
        if key in unsupported:
            del schema[key]
    for value in schema.values():
        if isinstance(value, dict):
            _strip_anthropic_unsupported_keywords(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_anthropic_unsupported_keywords(item)
    return schema


def build_provider_schema(
    model: type[BaseModel], provider: str | None = None
) -> dict[str, Any]:
    """
    Generate and normalize a strict JSON Schema from a Pydantic model suitable
    for OpenAI, Gemini, Ollama, and Anthropic structured outputs.
    """
    raw_schema = _enforce_strict_object_schema(model.model_json_schema())
    if provider == "anthropic":
        return _strip_anthropic_unsupported_keywords(deepcopy(raw_schema))
    return raw_schema


def adapt_provider_schema(schema: dict[str, Any], provider: str) -> dict[str, Any]:
    """Adapt an already-built canonical schema at the provider boundary."""
    adapted = deepcopy(schema)
    if provider == "anthropic":
        return _strip_anthropic_unsupported_keywords(adapted)
    if provider == "ollama":
        # Ollama accepts ordinary JSON Schema.  The canonical schema is made
        # strict for providers such as OpenAI, which makes every nullable field
        # required.  Keeping those nullable fields optional materially reduces
        # local-model output without weakening additionalProperties or local
        # Pydantic validation.
        _relax_nullable_required_fields(adapted)
    return adapted


def _schema_allows_null(schema: dict[str, Any]) -> bool:
    if schema.get("type") == "null":
        return True
    any_of = schema.get("anyOf") or schema.get("oneOf") or []
    return any(isinstance(item, dict) and _schema_allows_null(item) for item in any_of)


def _relax_nullable_required_fields(schema: dict[str, Any]) -> None:
    """Preserve canonical constraints while relaxing nullable fields for Ollama."""
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [
                name
                for name in required
                if not (
                    isinstance(properties.get(name), dict)
                    and _schema_allows_null(properties[name])
                )
            ]
        for child in properties.values():
            if isinstance(child, dict):
                _relax_nullable_required_fields(child)
    for key in ("items", "additionalProperties"):
        child = schema.get(key)
        if isinstance(child, dict):
            _relax_nullable_required_fields(child)
    for key in ("$defs", "definitions"):
        definitions = schema.get(key)
        if isinstance(definitions, dict):
            for child in definitions.values():
                if isinstance(child, dict):
                    _relax_nullable_required_fields(child)
    for key in ("anyOf", "oneOf", "allOf"):
        children = schema.get(key)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    _relax_nullable_required_fields(child)
