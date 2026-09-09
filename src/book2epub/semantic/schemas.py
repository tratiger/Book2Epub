"""JSON Schema normalization for strict provider structured outputs (M7 spec Section 7)."""

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


def build_provider_schema(model: type[BaseModel]) -> dict[str, Any]:
    """
    Generate and normalize a strict JSON Schema from a Pydantic model suitable
    for OpenAI, Gemini, Ollama, and Anthropic structured outputs.
    """
    raw_schema = model.model_json_schema()
    return _enforce_strict_object_schema(raw_schema)
