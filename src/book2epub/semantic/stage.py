"""End-to-end document semantic reconstruction stage orchestration
(M8 spec Section 2, 3, 13, 14)."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from book2epub.config import JobConfig
from book2epub.ir.models import BookIR
from book2epub.paths import JobPaths
from book2epub.providers.base import StructuredProvider
from book2epub.providers.factory import create_provider
from book2epub.providers.models import StructuredInferenceRequest
from book2epub.semantic.apply import (
    apply_semantic_decisions,
    apply_structure_decisions,
)
from book2epub.semantic.book_state import (
    BookState,
    compute_initial_book_state,
)
from book2epub.semantic.chunking import create_semantic_chunks
from book2epub.semantic.decisions import (
    SemanticAuditRecord,
    SemanticDecisionBatch,
)
from book2epub.semantic.models import (
    SemanticDraftBook,
    SemanticEvidenceBook,
)
from book2epub.semantic.prompts import (
    COMMON_SYSTEM_INSTRUCTION,
    PASS_A_USER_PROMPT_TEMPLATE,
    PASS_B_USER_PROMPT_TEMPLATE,
)
from book2epub.semantic.reconcile import (
    reconcile_semantic_batches,
    reconcile_structure_batches,
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
    validate_semantic_batch_scope,
    validate_structure_batch_scope,
)

logger = logging.getLogger(__name__)


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


def _record_provider_usage(paths: JobPaths, usage_dict: dict[str, Any]) -> None:
    """Append a token usage record to semantic/provider-usage.json."""
    usage_file = paths.semantic_provider_usage_json
    usage_list: list[dict[str, Any]] = []
    if usage_file.is_file():
        try:
            loaded = json.loads(usage_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                usage_list = loaded
        except Exception:
            pass
    usage_list.append(usage_dict)
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    usage_file.write_text(json.dumps(usage_list, indent=2), encoding="utf-8")


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

    evidence_lookup = {b.block_id: b for b in evidence.blocks}

    paths.semantic_dir.mkdir(parents=True, exist_ok=True)
    paths.semantic_chunks_dir.mkdir(parents=True, exist_ok=True)
    paths.semantic_decisions_dir.mkdir(parents=True, exist_ok=True)

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

    for chunk in chunks:
        blocks_json = json.dumps([b.model_dump() for b in chunk.blocks], ensure_ascii=False)
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
            response_schema=build_provider_schema(StructureDecisionBatch),
        )

        batch_obj, inf_res = provider.infer(req, StructureDecisionBatch)

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
                "request_id": req.request_id,
                "provider": provider.name,
                "model": provider.model,
                "pass": "pass_a",
                "latency_ms": inf_res.latency_ms,
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

    for chunk in pass_b_chunks:
        blocks_json = json.dumps([b.model_dump() for b in chunk.blocks], ensure_ascii=False)
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
            response_schema=build_provider_schema(SemanticDecisionBatch),
        )

        batch_b, inf_b = provider.infer(req, SemanticDecisionBatch)

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
        except Exception as exc:
            logger.error(
                "Pass B batch scope validation failed for chunk %s: %s. Skipping batch.",
                chunk.chunk_id,
                exc,
            )
            batch_b = SemanticDecisionBatch(
                schema_version="1.0",
                chunk_id=chunk.chunk_id,
                decisions=[],
            )

        pass_b_batches.append(batch_b)

        (pass_b_dir / f"{chunk.chunk_id}.json").write_text(
            batch_b.model_dump_json(indent=2), encoding="utf-8"
        )
        _record_provider_usage(
            paths,
            {
                "request_id": req.request_id,
                "provider": provider.name,
                "model": provider.model,
                "pass": "pass_b",
                "latency_ms": inf_b.latency_ms,
                "usage": inf_b.usage.model_dump(),
            },
        )

    # Reconcile Pass B decisions
    reconciled_sem, sem_conflicts = reconcile_semantic_batches(pass_b_batches, overlap_ids)

    # Save reconciled decisions
    reconciled_summary = {
        "pass_a": {k: v.__dict__ for k, v in reconciled_struct.items()},
        "pass_b": {k: v.__dict__ for k, v in reconciled_sem.items()},
        "pass_a_conflicts": [c.model_dump() for c in struct_conflicts],
        "pass_b_conflicts": [c.model_dump() for c in sem_conflicts],
    }
    (paths.semantic_decisions_dir / "reconciled.json").write_text(
        json.dumps(reconciled_summary, indent=2), encoding="utf-8"
    )

    final_blocks, pass_b_audits = apply_semantic_decisions(
        blocks=intermediate_blocks,
        decisions=reconciled_sem,
        evidence_lookup=evidence_lookup,
        auto_apply_threshold=cfg.semantic.auto_apply_threshold,
    )

    # 6. Final Outputs and Metrics
    semantic_ir = raw_ir.model_copy(update={"blocks": final_blocks})
    paths.ir_semantic_json.write_text(semantic_ir.model_dump_json(indent=2), encoding="utf-8")

    all_audits = pass_a_audits + pass_b_audits

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

    applied_count = sum(1 for a in all_audits if a.status == "applied")
    preserved_count = sum(1 for a in all_audits if "preserved" in a.status)
    low_conf_count = sum(1 for a in all_audits if a.status == "preserved_original_low_confidence")
    total_conflicts = len(struct_conflicts) + len(sem_conflicts)

    # Suppress unused variable warning (chunk_by_id used for scope validation)
    _ = chunk_by_id

    return SemanticStageResult(
        bookir=semantic_ir,
        outline=provisional_outline,
        book_state=book_state,
        audits=all_audits,
        reviewed_blocks_count=len(raw_ir.blocks),
        applied_changes_count=applied_count,
        preserved_originals_count=preserved_count,
        low_confidence_count=low_conf_count,
        conflict_count=total_conflicts,
    )
