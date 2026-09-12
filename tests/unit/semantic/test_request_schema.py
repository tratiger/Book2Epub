import json
from math import ceil

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
    assert (
        _definition(schema, "SemanticBlockDecision")["properties"]["evidence_codes"]["maxItems"]
        == 8
    )
    assert (
        _definition(schema, "SemanticRelationDecision")["properties"]["evidence_codes"]["maxItems"]
        == 8
    )
    relation = _definition(schema, "SemanticRelationDecision")
    assert relation["properties"]["source_block_ids"]["items"]["enum"] == ids
    assert relation["properties"]["source_block_ids"]["maxItems"] == 20
    assert relation["properties"]["target_block_id"]["anyOf"][0]["enum"] == ids


def test_pass_b_nested_chunk_id_uses_chunk_scope_and_block_ids_stay_separate() -> None:
    ids = ["b1", "b2", "b3"]
    schema = build_request_scoped_schema(
        SemanticDecisionBatch,
        provider="ollama",
        chunk_id="sem-0007-current",
        block_ids=ids,
        pass_name="pass_b",
    )

    observation = _definition(schema, "BookStateObservationBatch")
    assert observation["properties"]["chunk_id"]["enum"] == ["sem-0007-current"]
    assert observation["properties"]["chunk_id"].get("maxItems") is None
    heading_observation = _definition(schema, "HeadingPatternObservation")
    assert heading_observation["properties"]["example_block_ids"]["items"]["enum"] == ids
    numbering_example = _definition(schema, "NumberingConventionExample")
    assert numbering_example["properties"]["block_id"]["enum"] == ids
    domain_observation = _definition(schema, "DomainTermObservation")
    assert domain_observation["properties"]["source_block_id"]["enum"] == ids


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
    assert semantic_output_token_budget(17, "pass_b") == 16384
    assert semantic_output_token_budget(20, "pass_b") == 16384
    assert semantic_output_token_budget(1000, "pass_b") == 16384


def test_twenty_block_realistic_worst_case_fits_pass_b_budget() -> None:
    ids = [f"block-{index:02d}" for index in range(20)]
    evidence_codes = [
        "TABLE_HAS_REAL_ROW_COLUMN_SEMANTICS",
        "OUTLINE_CONTEXT",
        "MINERU_CLASSIFICATION_SUPPORTED",
        "AMBIGUOUS",
    ]
    payload = {
        "schema_version": "1.1",
        "chunk_id": "sem-0020-current",
        "decisions": [
            {
                "block_id": block_id,
                "operation": "retype_and_set_subtype",
                "target_type": "generic_preformatted",
                "subtype": "generic_preformatted",
                "heading_level": None,
                "confidence": 0.91,
                "evidence_codes": evidence_codes,
                "rationale": "bounded source-grounded rationale " * 8,
            }
            for block_id in ids
        ],
        "relations": [
            {
                "relation_type": "paragraph_continuation",
                "source_block_ids": [ids[index % 20], ids[(index + 1) % 20]],
                "target_block_id": ids[(index + 2) % 20],
                "confidence": 0.88,
                "evidence_codes": ["FOLLOWING_PROSE_REFERS_TO_OUTPUT"],
                "rationale": "adjacent source-order continuation " * 8,
            }
            for index in range(40)
        ],
        "observations": [
            {
                "schema_version": "1.0",
                "chunk_id": "sem-0020-current",
                "heading_patterns": [],
                "preformatted_conventions": [],
                "callout_conventions": [],
                "numbering_conventions": [],
                "domain_terms": [
                    {"term": f"TERM-{index}", "source_block_id": ids[index], "confidence": 0.9}
                    for index in range(20)
                ],
            }
        ],
    }
    # Live qwen3-vl measurement: 20,038 response chars / 7,120 eval tokens
    # ~= 2.81 chars/token.  Use that observed ratio rather than an optimistic
    # generic 4-char/token estimate for this JSON-heavy response.
    estimated_tokens = ceil(
        len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) / 2.81
    )

    budget = semantic_output_token_budget(20, "pass_b")
    assert estimated_tokens < budget

    # The live 17-block failure measured 10,435 prompt tokens.  Scale that
    # observed request shape to 20 blocks and verify the configured output cap
    # still leaves headroom inside the explicit 32K Ollama context target.
    estimated_prompt_tokens = ceil(10_435 * 20 / 17)
    assert estimated_prompt_tokens + budget < 32_768
