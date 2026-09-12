"""End-to-end document semantic reconstruction stage orchestration
(M8 spec Section 2, 3, 13, 14)."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from book2epub.cache import compute_semantic_cache_key
from book2epub.config import JobConfig
from book2epub.ir.models import Block, BookIR
from book2epub.paths import JobPaths
from book2epub.providers.base import StructuredProvider
from book2epub.providers.factory import create_provider
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.providers.usage import record_provider_usage as _record_provider_usage
from book2epub.qa.stage import StageState, record_stage_status
from book2epub.semantic.apply import (
    apply_semantic_decisions,
    apply_semantic_relations,
    apply_structure_decisions,
    validate_semantic_target,
)
from book2epub.semantic.book_state import (
    BookState,
    BookStateObservationBatch,
    compute_initial_book_state,
    get_book_state_prompt_view,
    merge_book_state_observations,
)
from book2epub.semantic.chunking import create_semantic_chunks
from book2epub.semantic.decisions import (
    SemanticAuditRecord,
    SemanticDecisionBatch,
    SemanticRelationAuditRecord,
)
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import (
    SEMANTIC_DECISION_SCHEMA_VERSION,
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)
from book2epub.semantic.prompts import (
    COMMON_SYSTEM_INSTRUCTION,
    PASS_A_USER_PROMPT_TEMPLATE,
    PASS_B_USER_PROMPT_TEMPLATE,
)
from book2epub.semantic.reconcile import (
    ReconciledSemanticDecision,
    ReconciledStructureDecision,
    reconcile_semantic_batches,
    reconcile_structure_batches,
)
from book2epub.semantic.relations import (
    ReconciledRelation,
    RelationKey,
    reconcile_relation_batches,
    validate_relation,
    validate_unique_block_ids,
)
from book2epub.semantic.request_schema import (
    REQUEST_SCOPED_SCHEMA_CONTRACT_VERSION,
    build_request_scoped_schema,
    semantic_output_token_budget,
)
from book2epub.semantic.schemas import build_provider_schema
from book2epub.semantic.structure import (
    BookOutline,
    StructureDecisionBatch,
    build_book_outline,
)
from book2epub.semantic.validation import (
    filter_out_of_scope_semantic_decisions,
    filter_out_of_scope_structure_decisions,
    validate_book_state_observation_scope,
    validate_semantic_batch_scope,
    validate_structure_batch_scope,
)

logger = logging.getLogger(__name__)


def _semantic_cache_key(
    raw_ir: BookIR,
    evidence: SemanticEvidenceBook,
    cfg: JobConfig,
    provider: StructuredProvider,
) -> str:
    return compute_semantic_cache_key(
        evidence=evidence,
        raw_ir=raw_ir,
        provider=provider.name,
        model=provider.model,
        system_prompt="\n".join(
            [COMMON_SYSTEM_INSTRUCTION, PASS_A_USER_PROMPT_TEMPLATE, PASS_B_USER_PROMPT_TEMPLATE]
        ),
        response_schemas=(
            build_provider_schema(StructureDecisionBatch),
            build_provider_schema(SemanticDecisionBatch),
        ),
        thresholds={
            "auto_apply": cfg.semantic.auto_apply_threshold,
            "review_floor": cfg.semantic.review_floor,
        },
        chunk_settings={
            "max_chars": cfg.semantic.max_chunk_chars,
            "max_blocks": cfg.semantic.max_chunk_blocks,
            "overlap_blocks": cfg.semantic.overlap_blocks,
        },
        observation_contract={
            "schema_version": "1.0",
            "semantic_decision_schema_version": SEMANTIC_DECISION_SCHEMA_VERSION,
            "relation_application_contract": "1.0",
            "request_scoped_schema_contract": REQUEST_SCOPED_SCHEMA_CONTRACT_VERSION,
            "provider_schema_adapter_contract": "2.0",
            "semantic_output_budget_contract": "1.0",
            "schema_hash": compute_text_sha256(
                json.dumps(
                    build_provider_schema(BookStateObservationBatch),
                    sort_keys=True,
                    ensure_ascii=False,
                )
            ),
        },
    )


def _load_reconciled_decisions(
    path: Path,
) -> tuple[
    dict[str, ReconciledStructureDecision],
    dict[str, ReconciledSemanticDecision],
    dict[RelationKey, ReconciledRelation],
    list[SemanticRelationAuditRecord],
]:
    data = json.loads(path.read_text(encoding="utf-8"))
    struct = {
        block_id: ReconciledStructureDecision(**value)
        for block_id, value in data.get("pass_a", {}).items()
    }
    semantic = {
        block_id: ReconciledSemanticDecision(**value)
        for block_id, value in data.get("pass_b", {}).items()
    }
    relations = {
        relation.key: relation
        for relation in (
            ReconciledRelation.from_dict(item)
            for item in data.get("pass_b_relations", [])
        )
    }
    relation_scope_audits = [
        SemanticRelationAuditRecord.model_validate(item)
        for item in data.get("pass_b_relation_scope_audits", [])
    ]
    return struct, semantic, relations, relation_scope_audits


def _deferred_relation_group_ids(
    relations: dict[RelationKey, ReconciledRelation],
    intermediate_blocks: list[Block],
    semantic_decisions: dict[str, ReconciledSemanticDecision],
    evidence_lookup: dict[str, SemanticEvidenceBlock],
    auto_apply_threshold: float,
    single_vote_threshold: float = 0.85,
) -> set[str]:
    """Return only safely materializable callout groups.

    Deferring a block decision is safe only when the relation itself would pass
    structural validation and the relation's subtype supplier is independently
    authorized by the same evidence/threshold gates as block materialization.
    """
    deferred: set[str] = set()
    blocks_by_id = {block.id: block for block in intermediate_blocks}
    block_order = {block.id: index for index, block in enumerate(intermediate_blocks)}
    for relation in relations.values():
        if relation.relation_type != "member_of_callout" or relation.is_conflict:
            continue
        threshold = single_vote_threshold if relation.single_vote else auto_apply_threshold
        if relation.confidence < threshold:
            continue
        valid, _ = validate_relation(relation, blocks_by_id, block_order)
        if not valid:
            continue

        subtype_supplied = False
        safe = True
        for block_id in relation.source_block_ids:
            decision = semantic_decisions.get(block_id)
            if decision is None:
                if blocks_by_id[block_id].kind == "callout":
                    subtype_supplied = True
                continue
            if decision.is_conflict:
                safe = False
                break
            decision_threshold = (
                single_vote_threshold if decision.single_vote else auto_apply_threshold
            )
            target = decision.target
            if target.startswith("callout_") or target == "sidebar":
                evidence = evidence_lookup.get(block_id)
                if (
                    evidence is None
                    or decision.confidence < decision_threshold
                    or not validate_semantic_target(evidence, target)
                ):
                    safe = False
                    break
                subtype_supplied = True
        if safe and subtype_supplied:
            deferred.update(relation.source_block_ids)
    return deferred


def _relation_scope_audit(
    relation: object,
    chunk_id: str,
    reason: str,
) -> SemanticRelationAuditRecord:
    return SemanticRelationAuditRecord(
        relation_id=(
            f"relation-{getattr(relation, 'relation_type', 'unknown')}-"
            f"{'-'.join(getattr(relation, 'source_block_ids', []))}-"
            f"{getattr(relation, 'target_block_id', None) or 'none'}"
        ),
        relation_type=getattr(relation, "relation_type"),
        source_block_ids=list(getattr(relation, "source_block_ids", [])),
        target_block_id=getattr(relation, "target_block_id", None),
        confidence=float(getattr(relation, "confidence", 0.0)),
        evidence_codes=list(getattr(relation, "evidence_codes", [])),
        provider="semantic",
        model="semantic",
        request_ids=[chunk_id],
        status="rejected",
        rejection_reason=reason,
    )


def _materialize_cached_semantic_result(
    raw_ir: BookIR,
    evidence: SemanticEvidenceBook,
    cfg: JobConfig,
    paths: JobPaths,
    provider: StructuredProvider,
    cache_key: str,
    reconciled_path: Path,
    state_path: Path,
) -> SemanticStageResult:
    evidence_lookup = {b.block_id: b for b in evidence.blocks}
    (
        struct_decisions,
        semantic_decisions,
        relations,
        relation_scope_audits,
    ) = _load_reconciled_decisions(reconciled_path)
    book_state = BookState.model_validate_json(state_path.read_text(encoding="utf-8"))
    intermediate_blocks, pass_a_audits = apply_structure_decisions(
        blocks=raw_ir.blocks,
        decisions=struct_decisions,
        evidence_lookup=evidence_lookup,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
    )
    final_blocks, pass_b_audits = apply_semantic_decisions(
        blocks=intermediate_blocks,
        decisions=semantic_decisions,
        evidence_lookup=evidence_lookup,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
        defer_relation_group_block_ids=_deferred_relation_group_ids(
            relations,
            intermediate_blocks,
            semantic_decisions,
            evidence_lookup,
            cfg.semantic.auto_apply_threshold,
        ),
    )
    final_blocks, relation_apply_audits = apply_semantic_relations(
        blocks=final_blocks,
        relations=relations,
        semantic_decisions=semantic_decisions,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
        evidence_lookup=evidence_lookup,
    )
    relation_audits = relation_scope_audits + relation_apply_audits
    duplicate_ids = validate_unique_block_ids(final_blocks)
    if duplicate_ids:
        raise ValueError(
            "Semantic relation application produced duplicate IDs: " + "; ".join(duplicate_ids)
        )
    outline = build_book_outline(final_blocks)
    semantic_ir = raw_ir.model_copy(update={"blocks": final_blocks})
    audits = pass_a_audits + pass_b_audits
    paths.semantic_outline_json.write_text(outline.model_dump_json(indent=2), encoding="utf-8")
    paths.semantic_book_state_json.write_text(
        book_state.model_dump_json(indent=2), encoding="utf-8"
    )
    paths.ir_semantic_json.write_text(semantic_ir.model_dump_json(indent=2), encoding="utf-8")
    paths.semantic_applied_m8_json.write_text(
        json.dumps([a.model_dump() for a in audits], indent=2), encoding="utf-8"
    )
    paths.semantic_applied_json.write_text(
        json.dumps([a.model_dump() for a in audits], indent=2), encoding="utf-8"
    )
    paths.semantic_relations_json.write_text(
        json.dumps([a.model_dump() for a in relation_audits], indent=2), encoding="utf-8"
    )
    record_stage_status(
        paths.semantic_stage_json,
        "semantic_structure",
        StageState.CACHE_HIT,
        input_hash=cache_key,
        cache_key=cache_key,
        provider=provider.name,
        model=provider.model,
        output_artifact=str(paths.ir_semantic_json),
        reason="reconciled decisions and BookState cache hit",
    )
    return SemanticStageResult(
        bookir=semantic_ir,
        outline=outline,
        book_state=book_state,
        audits=audits,
        reviewed_blocks_count=len(raw_ir.blocks),
        applied_changes_count=sum(1 for a in audits if a.status == "applied"),
        preserved_originals_count=sum(1 for a in audits if "preserved" in a.status),
        low_confidence_count=sum(
            1 for a in audits if a.status == "preserved_original_low_confidence"
        ),
        conflict_count=sum(1 for a in audits if "conflict" in a.status),
        struct_decisions=struct_decisions,
        semantic_decisions=semantic_decisions,
        relation_audits=relation_audits,
    )


@dataclass
class SemanticStageResult:
    """Summary of M8 semantic reconstruction stage execution."""

    bookir: BookIR
    outline: BookOutline
    book_state: BookState
    audits: list[SemanticAuditRecord]
    reviewed_blocks_count: int
    applied_changes_count: int
    preserved_originals_count: int
    low_confidence_count: int
    conflict_count: int
    struct_decisions: dict[str, ReconciledStructureDecision] = field(default_factory=dict)
    semantic_decisions: dict[str, ReconciledSemanticDecision] = field(default_factory=dict)
    relation_audits: list[SemanticRelationAuditRecord] = field(default_factory=list)


def run_semantic_reconstruction(

    raw_ir: BookIR,
    evidence: SemanticEvidenceBook,
    draft: SemanticDraftBook,
    cfg: JobConfig,
    paths: JobPaths,
    provider: StructuredProvider | None = None,
) -> SemanticStageResult:
    """
    Execute two-pass document-level semantic reconstruction:
    Pass A: Hierarchy and cross-page boundaries -> provisional BookOutline
    Pass B: Semantic block retyping and conventions -> semantic BookIR

    The authoritative M8 audit list is written to semantic/applied.m8.json.
    After M9 visual arbitration completes (in pipeline.py), it is responsible
    for writing the final authoritative semantic/applied.json.
    """
    if provider is None:
        provider = create_provider(cfg, purpose="semantic")

    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.semantic_chunks_dir.mkdir(parents=True, exist_ok=True)
    paths.semantic_decisions_dir.mkdir(parents=True, exist_ok=True)

    cache_key = _semantic_cache_key(raw_ir, evidence, cfg, provider)
    cache_dir = cfg.app.work_dir / "cache" / "semantic" / cache_key
    cached_reconciled = cache_dir / "reconciled.json"
    cached_state = cache_dir / "book_state.json"
    if (
        not cfg.app.force_semantic
        and cached_reconciled.is_file()
        and cached_state.is_file()
    ):
        return _materialize_cached_semantic_result(
            raw_ir,
            evidence,
            cfg,
            paths,
            provider,
            cache_key,
            cached_reconciled,
            cached_state,
        )

    record_stage_status(
        paths.semantic_stage_json,
        "semantic_structure",
        StageState.RUNNING,
        input_hash=cache_key,
        cache_key=cache_key,
        provider=provider.name,
        model=provider.model,
        reason="semantic reconstruction requested",
    )
    evidence_lookup = {b.block_id: b for b in evidence.blocks}

    # 1. Create Initial Dynamic Chunks
    chunks = create_semantic_chunks(
        draft_book=draft,
        cfg=cfg.semantic,
        provider=provider.name,
        model=provider.model,
        save_dir=paths.semantic_chunks_dir,
    )

    overlap_ids: set[str] = set()
    for chk in chunks:
        overlap_ids.update(chk.overlap_block_ids)

    # Build chunk lookup for scope validation
    chunk_by_id = {chk.chunk_id: chk for chk in chunks}

    # 2. Pass A: Structure & Hierarchy
    pass_a_dir = paths.semantic_decisions_dir / "pass-a"
    pass_a_dir.mkdir(parents=True, exist_ok=True)
    pass_a_batches: list[StructureDecisionBatch] = []

    for chunk_index, chunk in enumerate(chunks, start=1):
        blocks_json = json.dumps([b.model_dump() for b in chunk.blocks], ensure_ascii=False)
        logger.info(
            "[Semantic Pass A] chunk %d/%d blocks=%d chars=%d overlap=%d",
            chunk_index,
            len(chunks),
            len(chunk.block_ids),
            len(blocks_json),
            len(chunk.overlap_block_ids),
        )
        user_text = PASS_A_USER_PROMPT_TEMPLATE.format(
            chunk_id=chunk.chunk_id,
            book_state_json=json.dumps(chunk.book_state, ensure_ascii=False),
            outline_context_json=json.dumps(
                [o.model_dump() for o in chunk.preceding_outline], ensure_ascii=False
            ),
            semantic_draft_blocks_json=blocks_json,
        )

        req = StructuredInferenceRequest(
            request_id=f"{chunk.chunk_id}-pass-a",
            system_instruction=COMMON_SYSTEM_INSTRUCTION,
            user_text=user_text,
            response_model_name="StructureDecisionBatch",
            response_schema=build_request_scoped_schema(
                StructureDecisionBatch,
                provider=provider.name,
                chunk_id=chunk.chunk_id,
                block_ids=chunk.block_ids,
                pass_name="pass_a",
            ),
            max_output_tokens=semantic_output_token_budget(len(chunk.block_ids), "pass_a"),
            debug_artifact_path=(
                paths.semantic_dir
                / "provider-debug"
                / f"{chunk.chunk_id}-pass-a.truncated.json"
            ),
        )

        batch_obj, inf_res = provider.infer(req, StructureDecisionBatch)
        logger.info(
            "[Semantic Pass A] chunk %d/%d completed latency=%.1fs prompt_tokens=%s "
            "output_tokens=%s response_chars=%s done_reason=%s schema_retry=%d",
            chunk_index,
            len(chunks),
            inf_res.latency_ms / 1000,
            inf_res.usage.input_tokens,
            inf_res.usage.output_tokens,
            inf_res.response_chars,
            inf_res.done_reason,
            inf_res.schema_retry_count,
        )

        # Scope validation: check chunk_id and block_ids before using batch
        try:
            violations = validate_structure_batch_scope(batch_obj, chunk, req.request_id)
            if violations:
                logger.warning(
                    "Pass A batch for chunk %s has %d out-of-scope decisions; filtering.",
                    chunk.chunk_id,
                    len(violations),
                )
            batch_obj = filter_out_of_scope_structure_decisions(batch_obj, chunk)
        except Exception as exc:
            logger.error(
                "Pass A batch scope validation failed for chunk %s: %s. Skipping batch.",
                chunk.chunk_id,
                exc,
            )
            # Use empty batch to protect pipeline integrity
            batch_obj = StructureDecisionBatch(
                schema_version="1.0",
                chunk_id=chunk.chunk_id,
                decisions=[],
            )

        pass_a_batches.append(batch_obj)

        (pass_a_dir / f"{chunk.chunk_id}.json").write_text(
            batch_obj.model_dump_json(indent=2), encoding="utf-8"
        )
        _record_provider_usage(
            paths,
            {
                "request_id": inf_res.request_id,
                "requested_request_id": req.request_id,
                "provider": provider.name,
                "model": provider.model,
                "pass": "pass_a",
                "latency_ms": inf_res.latency_ms,
                "attempt_count": inf_res.attempt_count,
                "transport_attempt_count": inf_res.transport_attempt_count,
                "schema_retry_count": inf_res.schema_retry_count,
                "provider_request_ids": inf_res.provider_request_ids,
                "response_chars": inf_res.response_chars,
                "done_reason": inf_res.done_reason,
                "usage": inf_res.usage.model_dump(),
            },
        )

    # Reconcile Pass A decisions
    reconciled_struct, struct_conflicts = reconcile_structure_batches(pass_a_batches, overlap_ids)

    intermediate_blocks, pass_a_audits = apply_structure_decisions(
        blocks=raw_ir.blocks,
        decisions=reconciled_struct,
        evidence_lookup=evidence_lookup,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
    )

    # 3. Deterministic Outline Construction
    provisional_outline = build_book_outline(intermediate_blocks)
    paths.semantic_outline_json.write_text(
        provisional_outline.model_dump_json(indent=2), encoding="utf-8"
    )

    # 4. Initial Deterministic BookState
    book_state = compute_initial_book_state(intermediate_blocks, evidence.blocks)
    paths.semantic_book_state_json.write_text(
        book_state.model_dump_json(indent=2), encoding="utf-8"
    )

    # 5. Pass B: Semantic Block Adjudication
    # Regenerate chunks with outline and book_state context
    pass_b_chunks = create_semantic_chunks(
        draft_book=draft,
        cfg=cfg.semantic,
        outline=provisional_outline,
        book_state=book_state,
        provider=provider.name,
        model=provider.model,
    )

    pass_b_dir = paths.semantic_decisions_dir / "pass-b"
    pass_b_dir.mkdir(parents=True, exist_ok=True)
    pass_b_batches: list[SemanticDecisionBatch] = []
    relation_scope_audits: list[SemanticRelationAuditRecord] = []

    running_book_state = book_state
    observation_dir = paths.semantic_dir / "book-state-observations"
    observation_dir.mkdir(parents=True, exist_ok=True)

    for chunk_index, chunk in enumerate(pass_b_chunks, start=1):
        # The chunk list is deterministic, but BookState is intentionally dynamic:
        # each request gets the state merged from all earlier chunks.
        chunk = chunk.model_copy(
            update={"book_state": get_book_state_prompt_view(running_book_state)}
        )
        blocks_json = json.dumps([b.model_dump() for b in chunk.blocks], ensure_ascii=False)
        logger.info(
            "[Semantic Pass B] chunk %d/%d blocks=%d chars=%d overlap=%d",
            chunk_index,
            len(pass_b_chunks),
            len(chunk.block_ids),
            len(blocks_json),
            len(chunk.overlap_block_ids),
        )
        user_text = PASS_B_USER_PROMPT_TEMPLATE.format(
            chunk_id=chunk.chunk_id,
            book_state_json=json.dumps(chunk.book_state, ensure_ascii=False),
            outline_context_json=json.dumps(
                [o.model_dump() for o in chunk.preceding_outline], ensure_ascii=False
            ),
            semantic_draft_blocks_json=blocks_json,
        )

        req = StructuredInferenceRequest(
            request_id=f"{chunk.chunk_id}-pass-b",
            system_instruction=COMMON_SYSTEM_INSTRUCTION,
            user_text=user_text,
            response_model_name="SemanticDecisionBatch",
            response_schema=build_request_scoped_schema(
                SemanticDecisionBatch,
                provider=provider.name,
                chunk_id=chunk.chunk_id,
                block_ids=chunk.block_ids,
                pass_name="pass_b",
            ),
            max_output_tokens=semantic_output_token_budget(len(chunk.block_ids), "pass_b"),
            debug_artifact_path=(
                paths.semantic_dir
                / "provider-debug"
                / f"{chunk.chunk_id}-pass-b.truncated.json"
            ),
        )

        batch_b, inf_b = provider.infer(req, SemanticDecisionBatch)
        logger.info(
            "[Semantic Pass B] chunk %d/%d completed latency=%.1fs prompt_tokens=%s "
            "output_tokens=%s response_chars=%s done_reason=%s schema_retry=%d",
            chunk_index,
            len(pass_b_chunks),
            inf_b.latency_ms / 1000,
            inf_b.usage.input_tokens,
            inf_b.usage.output_tokens,
            inf_b.response_chars,
            inf_b.done_reason,
            inf_b.schema_retry_count,
        )
        raw_relations = list(batch_b.relations)

        # Scope validation for Pass B
        try:
            violations = validate_semantic_batch_scope(batch_b, chunk, req.request_id)
            if violations:
                logger.warning(
                    "Pass B batch for chunk %s has %d out-of-scope decisions; filtering.",
                    chunk.chunk_id,
                    len(violations),
                )
            batch_b = filter_out_of_scope_semantic_decisions(batch_b, chunk)
            accepted_relation_keys = {
                (rel.relation_type, tuple(rel.source_block_ids), rel.target_block_id)
                for rel in batch_b.relations
            }
            for relation in raw_relations:
                relation_identity = (
                    relation.relation_type,
                    tuple(relation.source_block_ids),
                    relation.target_block_id,
                )
                if relation_identity not in accepted_relation_keys:
                    relation_scope_audits.append(
                        _relation_scope_audit(
                            relation,
                            chunk.chunk_id,
                            "Relation failed chunk scope or duplicate validation",
                        )
                    )
            accepted_observations: list[BookStateObservationBatch] = []
            for obs in batch_b.observations:
                observation_violations = validate_book_state_observation_scope(obs, chunk)
                if observation_violations:
                    logger.warning(
                        "Rejected BookState observations for chunk %s: %s",
                        chunk.chunk_id,
                        "; ".join(observation_violations),
                    )
                    continue
                accepted_observations.append(obs)
                running_book_state = merge_book_state_observations(
                    running_book_state, obs, evidence_lookup
                )
            if accepted_observations:
                observation_path = observation_dir / f"{chunk.chunk_id}.json"
                observation_path.write_text(
                    json.dumps(
                        [obs.model_dump() for obs in accepted_observations],
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            batch_b = batch_b.model_copy(update={"observations": accepted_observations})
        except Exception as exc:
            logger.error(
                "Pass B batch scope validation failed for chunk %s: %s. Skipping batch.",
                chunk.chunk_id,
                exc,
            )
            batch_b = SemanticDecisionBatch(
                chunk_id=chunk.chunk_id,
                decisions=[],
            )
            relation_scope_audits.extend(
                _relation_scope_audit(
                    relation,
                    chunk.chunk_id,
                    f"Relation batch scope validation failed: {exc}",
                )
                for relation in raw_relations
            )

        pass_b_batches.append(batch_b)

        (pass_b_dir / f"{chunk.chunk_id}.json").write_text(
            batch_b.model_dump_json(indent=2), encoding="utf-8"
        )
        _record_provider_usage(
            paths,
            {
                "request_id": inf_b.request_id,
                "requested_request_id": req.request_id,
                "provider": provider.name,
                "model": provider.model,
                "pass": "pass_b",
                "latency_ms": inf_b.latency_ms,
                "attempt_count": inf_b.attempt_count,
                "transport_attempt_count": inf_b.transport_attempt_count,
                "schema_retry_count": inf_b.schema_retry_count,
                "provider_request_ids": inf_b.provider_request_ids,
                "response_chars": inf_b.response_chars,
                "done_reason": inf_b.done_reason,
                "usage": inf_b.usage.model_dump(),
            },
        )

    # Reconcile Pass B decisions
    reconciled_sem, sem_conflicts = reconcile_semantic_batches(pass_b_batches, overlap_ids)
    reconciled_relations, relation_conflicts = reconcile_relation_batches(
        pass_b_batches, overlap_ids
    )

    # Save reconciled decisions
    reconciled_summary = {
        "pass_a": {k: v.__dict__ for k, v in reconciled_struct.items()},
        "pass_b": {k: v.__dict__ for k, v in reconciled_sem.items()},
        "pass_b_relations": [
            relation.to_dict() for relation in reconciled_relations.values()
        ],
        "pass_a_conflicts": [c.model_dump() for c in struct_conflicts],
        "pass_b_conflicts": [c.model_dump() for c in sem_conflicts],
        "pass_b_relation_conflicts": [
            {
                "source_block_ids": list(conflict.source_block_ids),
                "relation_keys": [
                    [key[0], list(key[1]), key[2]] for key in conflict.relation_keys
                ],
                "chunk_ids": conflict.chunk_ids,
                "reason": conflict.reason,
            }
            for conflict in relation_conflicts
        ],
        "pass_b_relation_scope_audits": [
            audit.model_dump() for audit in relation_scope_audits
        ],
    }
    (paths.semantic_decisions_dir / "reconciled.json").write_text(
        json.dumps(reconciled_summary, indent=2), encoding="utf-8"
    )

    final_blocks, pass_b_audits = apply_semantic_decisions(
        blocks=intermediate_blocks,
        decisions=reconciled_sem,
        evidence_lookup=evidence_lookup,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
        defer_relation_group_block_ids=_deferred_relation_group_ids(
            reconciled_relations,
            intermediate_blocks,
            reconciled_sem,
            evidence_lookup,
            cfg.semantic.auto_apply_threshold,
        ),
    )
    final_blocks, relation_apply_audits = apply_semantic_relations(
        blocks=final_blocks,
        relations=reconciled_relations,
        semantic_decisions=reconciled_sem,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
        evidence_lookup=evidence_lookup,
    )
    relation_audits = relation_scope_audits + relation_apply_audits
    duplicate_ids = validate_unique_block_ids(final_blocks)
    if duplicate_ids:
        raise ValueError(
            "Semantic relation application produced duplicate IDs: " + "; ".join(duplicate_ids)
        )

    # 6. Final Outputs and Metrics
    semantic_ir = raw_ir.model_copy(update={"blocks": final_blocks})
    final_outline = build_book_outline(final_blocks)
    paths.semantic_outline_json.write_text(
        final_outline.model_dump_json(indent=2), encoding="utf-8"
    )
    paths.ir_semantic_json.write_text(semantic_ir.model_dump_json(indent=2), encoding="utf-8")

    all_audits = pass_a_audits + pass_b_audits

    book_state = running_book_state
    paths.semantic_book_state_json.write_text(
        book_state.model_dump_json(indent=2), encoding="utf-8"
    )

    # Write provisional M8 audit artifact (before M9 visual arbitration updates it).
    # pipeline.py is responsible for writing the authoritative final applied.json
    # after M9 completes (either by updating it or by copying applied.m8.json if no M9).
    paths.semantic_applied_m8_json.parent.mkdir(parents=True, exist_ok=True)
    paths.semantic_applied_m8_json.write_text(
        json.dumps([a.model_dump() for a in all_audits], indent=2), encoding="utf-8"
    )
    # Also write to applied.json as provisional; pipeline.py will overwrite with final
    # M9-updated version if visual arbitration runs.
    paths.semantic_applied_json.write_text(
        json.dumps([a.model_dump() for a in all_audits], indent=2), encoding="utf-8"
    )
    paths.semantic_relations_json.write_text(
        json.dumps([a.model_dump() for a in relation_audits], indent=2), encoding="utf-8"
    )

    # Cache only source-grounded decisions/state.  Re-materialization on a later
    # run uses that run's raw IR and evidence, so cached paths never leak into it.
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths.semantic_decisions_dir / "reconciled.json", cached_reconciled)
    shutil.copy2(paths.semantic_book_state_json, cached_state)
    record_stage_status(
        paths.semantic_stage_json,
        "semantic_structure",
        StageState.COMPLETE,
        input_hash=cache_key,
        cache_key=cache_key,
        provider=provider.name,
        model=provider.model,
        output_artifact=str(paths.ir_semantic_json),
        reason="semantic reconstruction complete",
    )

    applied_count = sum(1 for a in all_audits if a.status == "applied")
    preserved_count = sum(1 for a in all_audits if "preserved" in a.status)
    low_conf_count = sum(1 for a in all_audits if a.status == "preserved_original_low_confidence")
    total_conflicts = len(struct_conflicts) + len(sem_conflicts) + len(relation_conflicts)

    # Suppress unused variable warning (chunk_by_id used for scope validation)
    _ = chunk_by_id

    return SemanticStageResult(
        bookir=semantic_ir,
        outline=final_outline,
        book_state=book_state,
        audits=all_audits,
        reviewed_blocks_count=len(raw_ir.blocks),
        applied_changes_count=applied_count,
        preserved_originals_count=preserved_count,
        low_confidence_count=low_conf_count,
        conflict_count=total_conflicts,
        struct_decisions=reconciled_struct,
        semantic_decisions=reconciled_sem,
        relation_audits=relation_audits,
    )
