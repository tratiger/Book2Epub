"""Unit tests for multimodal visual semantic arbitration (M9 Section 7-8)."""

from pathlib import Path
from typing import TypeVar

import pytest
from PIL import Image
from pydantic import BaseModel

from book2epub.config import AppConfig, JobConfig, SemanticConfig
from book2epub.errors import ConfigurationError
from book2epub.ir.models import (
    BookIR,
    BookMetadata,
    PreformattedBlock,
    SourceDocument,
    Table,
)
from book2epub.paths import create_job_paths
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.semantic.decisions import SemanticAuditRecord
from book2epub.semantic.models import (
    DraftBlock,
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)
from book2epub.visual.arbitration import (
    run_visual_arbitration,
    should_trigger_visual_review,
)
from book2epub.visual.models import VisualSemanticBatch, VisualSemanticDecision
from book2epub.visual.source import VisualSource

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class MockVisualArbitrationProvider:
    """Mock vision provider returning predetermined VisualSemanticBatch decisions."""

    name: str = "mock-vision"
    model: str = "mock-vlm-v1"

    def __init__(self, decisions: list[VisualSemanticDecision]) -> None:
        self.decisions = decisions

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        batch = VisualSemanticBatch(schema_version="1.0", decisions=self.decisions)
        usage = ProviderUsage(input_tokens=150, output_tokens=40)
        res = StructuredInferenceResult(
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            raw_text=batch.model_dump_json(),
            parsed_json=batch.model_dump(),
            usage=usage,
            latency_ms=15,
        )
        return batch, res  # type: ignore[return-value]


def test_should_trigger_visual_review() -> None:
    """Test trigger predicates for M9 visual review."""
    base_audit = SemanticAuditRecord(
        decision_id="test-1",
        block_id="blk-01",
        source_kind="paragraph",
        proposed_target="paragraph",
        final_target="paragraph",
        confidence=0.95,
        provider="mock",
        model="mock",
        status="applied",
    )

    # When vision is off, never trigger
    assert not should_trigger_visual_review(base_audit, "off", 0.80, 0.45)

    # Overlap conflict triggers
    conflict_audit = base_audit.model_copy(update={"status": "preserved_original_conflict"})
    assert should_trigger_visual_review(conflict_audit, "auto", 0.80, 0.45)

    # Queued for visual review triggers
    queued_audit = base_audit.model_copy(update={"status": "queued_visual_review"})
    assert should_trigger_visual_review(queued_audit, "auto", 0.80, 0.45)

    # Confidence between review_floor and auto_apply_threshold triggers
    mid_conf_audit = base_audit.model_copy(
        update={"confidence": 0.65, "proposed_target": "heading_h2"}
    )
    assert should_trigger_visual_review(mid_conf_audit, "auto", 0.80, 0.45)

    # Table retype to preformatted triggers
    table_audit = base_audit.model_copy(
        update={"source_kind": "table", "proposed_target": "terminal_output"}
    )
    assert should_trigger_visual_review(table_audit, "auto", 0.80, 0.45)


def test_visual_source_missing_configuration_policies(tmp_path: Path) -> None:
    """Verify ConfigurationError on vision=on without source, and warning on vision=auto."""
    cfg_on = JobConfig(
        app=AppConfig(work_dir=tmp_path),
        semantic=SemanticConfig(enabled=True, vision="on"),
    )
    # vision=on without visual source must raise ConfigurationError
    with pytest.raises(ConfigurationError):
        VisualSource.resolve(cfg_on)

    # vision=auto without visual source must return has_visual=False without raising
    cfg_auto = JobConfig(
        app=AppConfig(work_dir=tmp_path),
        semantic=SemanticConfig(enabled=True, vision="auto"),
    )
    vs = VisualSource.resolve(cfg_auto)
    assert vs.has_visual is False


def test_visual_arbitration_high_confidence_override(tmp_path: Path) -> None:
    """High-confidence visual decision overrides M8 queued table-to-terminal retype."""
    # Setup dummy source image
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    visual_source = VisualSource(images_dir=img_dir)

    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    # Initial Table block in BookIR
    table_block = Table(
        id="blk-table-1",
        html="<table><tr><td>$ cargo build</td></tr></table>",
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[table_block],
    )

    evidence_book = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="dummy",
        raw_bookir_sha256="dummy",
        blocks=[
            SemanticEvidenceBlock(
                block_id="blk-table-1",
                page_idx=0,
                bbox=[50.0, 50.0, 200.0, 200.0],
                page_size=[600.0, 800.0],
                allowed_targets=["keep", "keep_original", "terminal_output"],
                preformatted_text="$ cargo build\nDone.",
            )
        ],
    )
    draft_book = SemanticDraftBook(
        schema_version="1.0",
        book_id="test",
        blocks=[DraftBlock(block_id="blk-table-1", page_idx=0, current_type="table")],
    )

    m8_audit = SemanticAuditRecord(
        decision_id="m8-decision",
        block_id="blk-table-1",
        source_kind="table",
        proposed_target="terminal_output",
        final_target="table",
        confidence=0.65,
        status="queued_visual_review",
        provider="mock-m8",
        model="mock-m8",
    )

    mock_vlm = MockVisualArbitrationProvider(
        decisions=[
            VisualSemanticDecision(
                block_id="blk-table-1",
                decision="confirm_proposed",
                target="terminal_output",
                confidence=0.92,
                visual_evidence_codes=["MONOSPACE_VISUAL_STYLE", "SHELL_PROMPT_VISIBLE"],
                rationale="Visual crop shows distinct terminal background and shell prompt",
            )
        ]
    )

    cfg = JobConfig(semantic=SemanticConfig(enabled=True, vision="auto"))

    new_ir, updated_audits, ocr_rec = run_visual_arbitration(
        bookir=bookir,
        evidence=evidence_book,
        draft=draft_book,
        audits=[m8_audit],
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_vlm,
    )

    assert len(updated_audits) == 1
    assert updated_audits[0].status == "visual_override_applied"
    assert updated_audits[0].final_target == "terminal_output"

    # IR block must now be PreformattedBlock with terminal_output subtype
    assert len(new_ir.blocks) == 1
    assert isinstance(new_ir.blocks[0], PreformattedBlock)
    assert new_ir.blocks[0].subtype == "terminal_output"
    assert "$ cargo build" in new_ir.blocks[0].text


def test_visual_arbitration_reject_restores_original(tmp_path: Path) -> None:
    """Visual arbitration rejection preserves original document AI block."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    visual_source = VisualSource(images_dir=img_dir)
    paths = create_job_paths(tmp_path / "work")

    table_block = Table(
        id="blk-table-2",
        html="<table><tr><td>Real Table Header</td></tr></table>",
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[table_block],
    )

    evidence_book = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="dummy",
        raw_bookir_sha256="dummy",
        blocks=[
            SemanticEvidenceBlock(
                block_id="blk-table-2",
                page_idx=0,
                bbox=[50.0, 50.0, 200.0, 200.0],
                page_size=[600.0, 800.0],
                allowed_targets=["keep", "keep_original", "terminal_output"],
                preformatted_text="Real Table Header",
            )
        ],
    )
    draft_book = SemanticDraftBook(
        schema_version="1.0",
        book_id="test",
        blocks=[DraftBlock(block_id="blk-table-2", page_idx=0, current_type="table")],
    )

    m8_audit = SemanticAuditRecord(
        decision_id="m8-decision-2",
        block_id="blk-table-2",
        source_kind="table",
        proposed_target="terminal_output",
        final_target="table",
        confidence=0.60,
        status="preserved_original_conflict",
        provider="mock-m8",
        model="mock-m8",
    )

    # VLM explicitly rejects the proposed retype
    mock_vlm = MockVisualArbitrationProvider(
        decisions=[
            VisualSemanticDecision(
                block_id="blk-table-2",
                decision="reject_keep_original",
                confidence=0.95,
                visual_evidence_codes=["TABLE_GRID_OR_COLUMNS_SEMANTIC", "TABLE_HEADER_VISIBLE"],
                rationale="Visual crop clearly shows a table grid with headers, not terminal",
            )
        ]
    )

    cfg = JobConfig(semantic=SemanticConfig(enabled=True, vision="auto"))

    new_ir, updated_audits, _ = run_visual_arbitration(
        bookir=bookir,
        evidence=evidence_book,
        draft=draft_book,
        audits=[m8_audit],
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_vlm,
    )

    assert updated_audits[0].status == "preserved_original_conflict"
    assert updated_audits[0].final_target == "table"
    assert isinstance(new_ir.blocks[0], Table)


# ---------------------------------------------------------------------------
# Hardening Tests A, B, C, D, J
# ---------------------------------------------------------------------------


def test_visual_arbitration_undo_m8_applied_change(tmp_path: Path) -> None:
    """Test A: When M8 *applied* a Table->Preformatted change and M9 rejects it,
    the IR block must be reverted back to Table (source kind).
    This verifies the BookIR invariant: final_target in audit == IR node kind."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    visual_source = VisualSource(images_dir=img_dir)
    paths = create_job_paths(tmp_path / "work")

    # M8 *applied* the change: the bookir block is already a PreformattedBlock
    pre_block = PreformattedBlock(
        id="blk-pre-undo",
        subtype="terminal_output",
        text="$ make test\nOK",
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Test Undo"),
        source=SourceDocument(page_count=1),
        blocks=[pre_block],
    )

    evidence_book = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="dummy",
        raw_bookir_sha256="dummy",
        blocks=[
            SemanticEvidenceBlock(
                block_id="blk-pre-undo",
                page_idx=0,
                bbox=[50.0, 50.0, 200.0, 200.0],
                page_size=[600.0, 800.0],
                allowed_targets=["keep", "keep_original", "terminal_output", "table"],
                preformatted_text="$ make test\nOK",
                table_html="<table><tr><td>$ make test</td></tr><tr><td>OK</td></tr></table>",
                table_html_available=True,
                raw_bookir_kind="table",
            )
        ],
    )
    draft_book = SemanticDraftBook(
        schema_version="1.0",
        book_id="test",
        blocks=[DraftBlock(block_id="blk-pre-undo", page_idx=0, current_type="preformatted")],
    )

    # The M8 audit recorded "applied" status — it was actually applied
    m8_audit = SemanticAuditRecord(
        decision_id="m8-undo",
        block_id="blk-pre-undo",
        source_kind="table",
        proposed_target="terminal_output",
        final_target="terminal_output",
        confidence=0.72,
        status="applied",  # M8 applied the change
        provider="mock-m8",
        model="mock-m8",
    )

    # VLM rejects the proposed retype with high confidence
    mock_vlm = MockVisualArbitrationProvider(
        decisions=[
            VisualSemanticDecision(
                block_id="blk-pre-undo",
                decision="reject_keep_original",
                confidence=0.91,
                visual_evidence_codes=["TABLE_GRID_OR_COLUMNS_SEMANTIC"],
                rationale="Block is actually a structured table",
            )
        ]
    )

    cfg = JobConfig(semantic=SemanticConfig(enabled=True, vision="auto"))

    new_ir, updated_audits, _ = run_visual_arbitration(
        bookir=bookir,
        evidence=evidence_book,
        draft=draft_book,
        audits=[m8_audit],
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_vlm,
    )

    assert len(updated_audits) == 1
    # Audit must reflect preserved_original_conflict and source_kind as final_target
    assert updated_audits[0].status == "preserved_original_conflict"
    assert updated_audits[0].final_target == "table"

    # IR block must be restored to Table (Test J invariant: audit final_target == IR kind)
    assert len(new_ir.blocks) == 1
    assert isinstance(new_ir.blocks[0], Table), (
        f"Expected Table after M9 undo, got {type(new_ir.blocks[0]).__name__}"
    )


def test_visual_arbitration_alternate_target(tmp_path: Path) -> None:
    """Test C: Visual arbitration can choose a target different from both
    proposed_target and source_kind (replace_with_alternate)."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    visual_source = VisualSource(images_dir=img_dir)
    paths = create_job_paths(tmp_path / "work")

    table_block = Table(
        id="blk-alt-tgt",
        html="<table><tr><td>$ ls /tmp</td></tr></table>",
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Test Alternate"),
        source=SourceDocument(page_count=1),
        blocks=[table_block],
    )

    evidence_book = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="dummy",
        raw_bookir_sha256="dummy",
        blocks=[
            SemanticEvidenceBlock(
                block_id="blk-alt-tgt",
                page_idx=0,
                bbox=[50.0, 50.0, 200.0, 200.0],
                page_size=[600.0, 800.0],
                allowed_targets=[
                    "keep", "keep_original", "terminal_output", "shell_command", "table"
                ],
                preformatted_text="$ ls /tmp",
                table_html="<table><tr><td>$ ls /tmp</td></tr></table>",
                table_html_available=True,
            )
        ],
    )
    draft_book = SemanticDraftBook(
        schema_version="1.0",
        book_id="test",
        blocks=[DraftBlock(block_id="blk-alt-tgt", page_idx=0, current_type="table")],
    )

    m8_audit = SemanticAuditRecord(
        decision_id="m8-alt",
        block_id="blk-alt-tgt",
        source_kind="table",
        proposed_target="terminal_output",  # M8 proposed terminal_output
        final_target="table",
        confidence=0.65,
        status="queued_visual_review",
        provider="mock-m8",
        model="mock-m8",
    )

    # VLM chooses shell_command instead (replace_with_alternate)
    mock_vlm = MockVisualArbitrationProvider(
        decisions=[
            VisualSemanticDecision(
                block_id="blk-alt-tgt",
                decision="replace_with_alternate",
                target="shell_command",  # Different from proposed terminal_output
                confidence=0.90,
                visual_evidence_codes=["SHELL_PROMPT_VISIBLE"],
                rationale="Single command line, better classified as shell_command",
            )
        ]
    )

    cfg = JobConfig(semantic=SemanticConfig(enabled=True, vision="auto"))

    new_ir, updated_audits, _ = run_visual_arbitration(
        bookir=bookir,
        evidence=evidence_book,
        draft=draft_book,
        audits=[m8_audit],
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_vlm,
    )

    assert len(updated_audits) == 1
    assert updated_audits[0].status == "visual_override_applied"
    assert updated_audits[0].final_target == "shell_command"

    # IR block must be the alternate target type
    assert isinstance(new_ir.blocks[0], PreformattedBlock)
    assert new_ir.blocks[0].subtype == "shell_command"


def test_visual_arbitration_scope_out_of_allowed_targets(tmp_path: Path) -> None:
    """Test D: Visual decision choosing a target not in allowed_targets must be
    rejected and source kind preserved instead."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    visual_source = VisualSource(images_dir=img_dir)
    paths = create_job_paths(tmp_path / "work")

    table_block = Table(
        id="blk-scope-tgt",
        html="<table><tr><td>data</td></tr></table>",
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Test Scope"),
        source=SourceDocument(page_count=1),
        blocks=[table_block],
    )

    evidence_book = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="dummy",
        raw_bookir_sha256="dummy",
        blocks=[
            SemanticEvidenceBlock(
                block_id="blk-scope-tgt",
                page_idx=0,
                bbox=[50.0, 50.0, 200.0, 200.0],
                page_size=[600.0, 800.0],
                # allowed_targets does NOT include 'source_code'
                allowed_targets=["keep", "keep_original", "table"],
                preformatted_text="data",
                table_html="<table><tr><td>data</td></tr></table>",
                table_html_available=True,
            )
        ],
    )
    draft_book = SemanticDraftBook(
        schema_version="1.0",
        book_id="test",
        blocks=[DraftBlock(block_id="blk-scope-tgt", page_idx=0, current_type="table")],
    )

    m8_audit = SemanticAuditRecord(
        decision_id="m8-scope",
        block_id="blk-scope-tgt",
        source_kind="table",
        proposed_target="terminal_output",
        final_target="table",
        confidence=0.65,
        status="queued_visual_review",
        provider="mock-m8",
        model="mock-m8",
    )

    # VLM hallucinates a target ('source_code') that is not in allowed_targets
    mock_vlm = MockVisualArbitrationProvider(
        decisions=[
            VisualSemanticDecision(
                block_id="blk-scope-tgt",
                decision="replace_with_alternate",
                target="source_code",  # NOT in allowed_targets!
                confidence=0.91,
                visual_evidence_codes=[],
                rationale="Looks like code",
            )
        ]
    )

    cfg = JobConfig(semantic=SemanticConfig(enabled=True, vision="auto"))

    new_ir, updated_audits, _ = run_visual_arbitration(
        bookir=bookir,
        evidence=evidence_book,
        draft=draft_book,
        audits=[m8_audit],
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_vlm,
    )

    # Out-of-allowed-targets visual decision must be reverted to source kind
    assert updated_audits[0].final_target == "table"
    # IR block must remain as Table
    assert isinstance(new_ir.blocks[0], Table)


def test_audit_ir_final_target_invariant(tmp_path: Path) -> None:
    """Test J: After visual arbitration, final_target in audit must equal
    the kind of the corresponding IR node (audit/IR invariant)."""
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    visual_source = VisualSource(images_dir=img_dir)
    paths = create_job_paths(tmp_path / "work")

    table_block = Table(
        id="blk-inv",
        html="<table><tr><td>$ curl -v</td></tr></table>",
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Invariant Test"),
        source=SourceDocument(page_count=1),
        blocks=[table_block],
    )

    evidence_book = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="dummy",
        raw_bookir_sha256="dummy",
        blocks=[
            SemanticEvidenceBlock(
                block_id="blk-inv",
                page_idx=0,
                bbox=[50.0, 50.0, 200.0, 200.0],
                page_size=[600.0, 800.0],
                allowed_targets=["keep", "keep_original", "terminal_output", "table"],
                preformatted_text="$ curl -v",
            )
        ],
    )
    draft_book = SemanticDraftBook(
        schema_version="1.0",
        book_id="test",
        blocks=[DraftBlock(block_id="blk-inv", page_idx=0, current_type="table")],
    )

    m8_audit = SemanticAuditRecord(
        decision_id="m8-inv",
        block_id="blk-inv",
        source_kind="table",
        proposed_target="terminal_output",
        final_target="table",
        confidence=0.60,
        status="queued_visual_review",
        provider="mock-m8",
        model="mock-m8",
    )

    # High confidence visual confirm
    mock_vlm = MockVisualArbitrationProvider(
        decisions=[
            VisualSemanticDecision(
                block_id="blk-inv",
                decision="confirm_proposed",
                target="terminal_output",
                confidence=0.93,
                visual_evidence_codes=["SHELL_PROMPT_VISIBLE"],
                rationale="Confirmed terminal output",
            )
        ]
    )

    cfg = JobConfig(semantic=SemanticConfig(enabled=True, vision="auto"))

    new_ir, updated_audits, _ = run_visual_arbitration(
        bookir=bookir,
        evidence=evidence_book,
        draft=draft_book,
        audits=[m8_audit],
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_vlm,
    )

    # Invariant: audit.final_target == kind of IR block
    assert len(updated_audits) == 1
    assert len(new_ir.blocks) == 1
    audit_final = updated_audits[0].final_target
    ir_block = new_ir.blocks[0]

    # The IR block kind should match the audit final_target
    if isinstance(ir_block, PreformattedBlock):
        assert audit_final == ir_block.subtype or audit_final == "preformatted", (
            f"Audit final_target={audit_final!r} doesn't match "
            f"IR PreformattedBlock.subtype={ir_block.subtype!r}"
        )
    elif isinstance(ir_block, Table):
        assert audit_final == "table" or audit_final == ir_block.kind, (
            f"Audit final_target={audit_final!r} but IR is Table"
        )

