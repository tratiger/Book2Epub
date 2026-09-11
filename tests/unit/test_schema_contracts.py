"""Canonical M8/M9 provider schema contract tests."""

import json

import pytest
from pydantic import ValidationError

from book2epub.cache import (
    compute_ocr_cache_key,
    compute_semantic_cache_key,
    compute_visual_cache_key,
)
from book2epub.ir.models import BookIR, SourceDocument
from book2epub.semantic.book_state import BookStateObservationBatch
from book2epub.semantic.decisions import (
    SemanticBlockDecision,
    SemanticDecisionBatch,
    SemanticRelationDecision,
)
from book2epub.semantic.models import (
    BOOK_STATE_OBSERVATION_SCHEMA_VERSION,
    PROMPT_CONTRACT_VERSION,
    SEMANTIC_DECISION_SCHEMA_VERSION,
    SEMANTIC_PATCH_SCHEMA_VERSION,
    SEMANTIC_RELATION_SCHEMA_VERSION,
    SemanticEvidenceBook,
)
from book2epub.semantic.prompts import PASS_B_USER_PROMPT_TEMPLATE
from book2epub.semantic.schemas import build_provider_schema
from book2epub.visual.models import OCRCorrectionProposal, VisualSemanticDecision


def test_pass_b_prompt_and_version_constants_match_contract() -> None:
    assert SEMANTIC_DECISION_SCHEMA_VERSION == "1.1"
    assert SEMANTIC_RELATION_SCHEMA_VERSION == "1.0"
    assert SEMANTIC_PATCH_SCHEMA_VERSION == "1.1"
    assert BOOK_STATE_OBSERVATION_SCHEMA_VERSION == "1.0"
    assert PROMPT_CONTRACT_VERSION == "1.1"

    prompt = PASS_B_USER_PROMPT_TEMPLATE.format(
        chunk_id="chunk-1",
        book_state_json="{}",
        outline_context_json="[]",
        semantic_draft_blocks_json="[]",
    )
    assert "SCHEMA_VERSION: 1.1" in prompt
    assert "`decisions`" in prompt
    assert "`relations`" in prompt
    assert "`observations`" in prompt
    for relation_type in (
        "caption_of",
        "footnote_of",
        "paragraph_continuation",
        "member_of_callout",
        "member_of_example",
    ):
        assert relation_type in prompt
    assert "only block IDs supplied in this prompt" in prompt


def test_pass_b_schema_is_canonical_1_1_and_relation_aware() -> None:
    schema = build_provider_schema(SemanticDecisionBatch)
    decision_properties = schema["$defs"]["SemanticBlockDecision"]["properties"]
    assert {"decisions", "relations", "observations"} <= schema["properties"].keys()
    assert {"operation", "target_type", "subtype"} <= decision_properties.keys()
    assert "target" not in decision_properties
    assert "related_block_ids" not in decision_properties
    assert SemanticDecisionBatch.model_fields["schema_version"].default == "1.1"

    batch = SemanticDecisionBatch(
        chunk_id="chunk-1",
        decisions=[
            SemanticBlockDecision(
                block_id="b1",
                operation="retype",
                target_type="terminal_output",
                confidence=0.9,
            )
        ],
        relations=[
            SemanticRelationDecision(
                relation_type="caption_of",
                source_block_ids=["caption-1"],
                target_block_id="figure-1",
                confidence=0.8,
            )
        ],
        observations=[BookStateObservationBatch(chunk_id="chunk-1")],
    )
    assert batch.schema_version == "1.1"
    assert len(batch.relations) == 1
    assert len(batch.observations) == 1


def test_pass_b_rejects_old_schema_enum_and_content_fields() -> None:
    with pytest.raises(ValidationError):
        SemanticDecisionBatch.model_validate(
            {
                "schema_version": "1.0",
                "chunk_id": "chunk-1",
                "decisions": [],
                "relations": [],
                "observations": [],
            }
        )

    with pytest.raises(ValidationError):
        SemanticDecisionBatch.model_validate(
            {
                "schema_version": "1.1",
                "chunk_id": "chunk-1",
                "decisions": [
                    {
                        "block_id": "b1",
                        "operation": "keep",
                        "confidence": 0.9,
                        "evidence_codes": ["PRECEDING_TEXT_REFERENCE"],
                    }
                ],
                "relations": [],
                "observations": [],
            }
        )

    decision_schema = build_provider_schema(SemanticBlockDecision)
    decision_properties = decision_schema["properties"]
    forbidden_fields = (
        "text",
        "replacement_text",
        "content",
        "html",
        "css",
        "latex",
        "code_body",
        "caption_text",
    )
    for forbidden in forbidden_fields:
        assert forbidden not in decision_properties

    with pytest.raises(ValidationError):
        SemanticBlockDecision.model_validate(
            {
                "block_id": "b1",
                "operation": "keep",
                "confidence": 0.9,
                "text": "generated prose",
            }
        )


def test_pass_b_cache_identity_changes_for_schema_1_1() -> None:
    evidence = SemanticEvidenceBook(
        source_middle_sha256="middle",
        raw_bookir_sha256="raw",
    )
    raw_ir = BookIR(source=SourceDocument(page_count=1))
    common = {
        "evidence": evidence,
        "raw_ir": raw_ir,
        "provider": "mock",
        "model": "mock-model",
        "system_prompt": "prompt",
        "thresholds": {},
        "chunk_settings": {},
        "observation_contract": {
            "schema_version": "1.0",
            "semantic_decision_schema_version": "1.1",
        },
    }
    old_key = compute_semantic_cache_key(
        **common,
        response_schemas=[{"schema_version": "1.0", "decisions": []}],
    )
    new_key = compute_semantic_cache_key(
        **common,
        response_schemas=[build_provider_schema(SemanticDecisionBatch)],
    )
    assert old_key != new_key


def test_visual_and_ocr_cache_identity_includes_canonical_schema_shape() -> None:
    visual_common = {
        "semantic_decision_hash": "semantic",
        "evidence_hash": "evidence",
        "visual_hash": "visual",
        "provider": "mock",
        "model": "mock-model",
        "prompt": "prompt",
        "mode": "auto",
        "thresholds": {},
    }
    old_visual_key = compute_visual_cache_key(
        **visual_common,
        schema={"target": "table", "visual_evidence_codes": []},
    )
    new_visual_key = compute_visual_cache_key(
        **visual_common,
        schema=build_provider_schema(VisualSemanticDecision),
    )
    assert old_visual_key != new_visual_key

    ocr_common = {
        "pre_ocr_ir_hash": "ir",
        "candidate_old_hash": "candidate",
        "visual_hash": "visual",
        "mode": "safe",
        "provider": "mock",
        "model": "mock-model",
        "prompt": "prompt",
        "policy_version": "policy-1",
    }
    old_ocr_key = compute_ocr_cache_key(
        **ocr_common,
        schema={"visible_error_type": "character_substitution"},
    )
    new_ocr_key = compute_ocr_cache_key(
        **ocr_common,
        schema=build_provider_schema(OCRCorrectionProposal),
    )
    assert old_ocr_key != new_ocr_key


def test_visual_schema_uses_only_canonical_target_and_evidence_fields() -> None:
    schema = build_provider_schema(VisualSemanticDecision)
    properties = schema["properties"]
    assert "target_type" in properties
    assert "target" not in properties
    assert "evidence_codes" in properties
    assert "visual_evidence_codes" not in properties
    assert "confirms_text_decision" not in properties

    with pytest.raises(ValidationError):
        VisualSemanticDecision.model_validate(
            {
                "block_id": "b1",
                "decision": "confirm_proposed",
                "target": "table",
                "confidence": 0.9,
            }
        )


def test_ocr_proposal_has_canonical_identity_and_verification_fields() -> None:
    schema = build_provider_schema(OCRCorrectionProposal)
    properties = schema["properties"]
    assert {
        "segment_id",
        "old_text_sha256",
        "proposed_text",
        "reason_code",
        "visually_verified",
    } <= properties.keys()
    assert "visible_error_type" not in properties
    assert "rationale" not in properties
    assert {"proposed_text", "reason_code", "visually_verified"} <= set(schema["required"])

    proposal = OCRCorrectionProposal.model_validate(
        {
            "block_id": "b1",
            "segment_id": "s1",
            "line_index": 0,
            "span_index": 0,
            "old_text_sha256": "old",
            "proposed_text": "new",
            "confidence": 0.99,
            "reason_code": "GLYPH_CONFUSION",
            "visually_verified": True,
        }
    )
    assert proposal.reason_code == "GLYPH_CONFUSION"

    with pytest.raises(ValidationError):
        OCRCorrectionProposal.model_validate(
            {
                "block_id": "b1",
                "segment_id": "s1",
                "old_text_sha256": "old",
                "proposed_text": "new",
                "confidence": 0.99,
                "visible_error_type": "character_substitution",
            }
        )


def test_provider_schemas_do_not_expose_legacy_names() -> None:
    payload = json.dumps(
        {
            "semantic": build_provider_schema(SemanticDecisionBatch),
            "visual": build_provider_schema(VisualSemanticDecision),
            "ocr": build_provider_schema(OCRCorrectionProposal),
        },
        ensure_ascii=False,
    )
    assert "PRECEDING_TEXT_REFERENCE" not in payload
    assert "visual_evidence_codes" not in payload
    assert "confirms_text_decision" not in payload
    assert "visible_error_type" not in payload
