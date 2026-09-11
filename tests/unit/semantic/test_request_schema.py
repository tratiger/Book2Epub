from pydantic import BaseModel

from book2epub.semantic.decisions import SemanticDecisionBatch
from book2epub.semantic.request_schema import (
    build_request_scoped_schema,
    semantic_output_token_budget,
)
from book2epub.semantic.schemas import build_provider_schema
from book2epub.semantic.structure import StructureDecisionBatch


def _definition(schema: dict[str, object], name: str) -> dict[str, object]:
    definitions = schema.get("$defs")
    assert isinstance(definitions, dict)
    definition = definitions.get(name)
    assert isinstance(definition, dict)
    return definition


def test_pass_a_schema_is_bounded_to_current_chunk() -> None:
    schema = build_request_scoped_schema(
        StructureDecisionBatch,
        provider="ollama",
        chunk_id="chunk-12",
        block_ids=["b1", "b2", "b3"],
        pass_name="pass_a",
    )

    assert schema["properties"]["chunk_id"]["enum"] == ["chunk-12"]
    assert schema["properties"]["decisions"]["maxItems"] == 3
    decision = _definition(schema, "StructureDecision")
    assert decision["properties"]["block_id"]["enum"] == ["b1", "b2", "b3"]
    assert decision["properties"]["paragraph_continuation_of"]["anyOf"][0]["enum"] == [
        "b1",
        "b2",
        "b3",
    ]


def test_pass_b_schema_bounds_decisions_relations_and_observations() -> None:
    ids = [f"b{i}" for i in range(20)]
    schema = build_request_scoped_schema(
        SemanticDecisionBatch,
        provider="ollama",
        chunk_id="chunk-20",
        block_ids=ids,
        pass_name="pass_b",
    )

    properties = schema["properties"]
    assert properties["chunk_id"]["enum"] == ["chunk-20"]
    assert properties["decisions"]["maxItems"] == 20
    assert properties["relations"]["maxItems"] == 40
    assert properties["observations"]["maxItems"] == 1
    relation = _definition(schema, "SemanticRelationDecision")
    assert relation["properties"]["source_block_ids"]["items"]["enum"] == ids
    assert relation["properties"]["source_block_ids"]["maxItems"] == 20
    assert relation["properties"]["target_block_id"]["anyOf"][0]["enum"] == ids


def test_ollama_schema_keeps_nullable_fields_optional_but_openai_contract_stays_strict() -> None:
    class OptionalResponse(BaseModel):
        required_value: str
        optional_value: str | None = None

    canonical = build_provider_schema(OptionalResponse)
    ollama = build_request_scoped_schema(
        OptionalResponse,
        provider="ollama",
        chunk_id="chunk-1",
        block_ids=["b1"],
        pass_name="pass_a",
    )

    assert "optional_value" in canonical["required"]
    assert "optional_value" not in ollama["required"]


def test_semantic_output_budget_is_bounded_and_scales_with_scope() -> None:
    assert semantic_output_token_budget(1, "pass_a") < semantic_output_token_budget(20, "pass_b")
    assert semantic_output_token_budget(1000, "pass_b") == 4096
