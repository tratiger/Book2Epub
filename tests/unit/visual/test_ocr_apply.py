"""Unit tests for multimodal OCR correction application engine (M9 Section 15-16)."""

from pathlib import Path
from typing import TypeVar

from PIL import Image
from pydantic import BaseModel

from book2epub.config import JobConfig, OCRCorrectionConfig
from book2epub.ir.models import (
    BBox,
    BookIR,
    BookMetadata,
    CodeBlock,
    Paragraph,
    SourceDocument,
    SourceRef,
    SourceTextSegment,
    Text,
)
from book2epub.paths import create_job_paths
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBlock, SemanticEvidenceBook
from book2epub.visual.models import (
    OCRCorrectionBatch,
    OCRCorrectionProposal,
    OCRSensitiveConfirmation,
)
from book2epub.visual.ocr_apply import run_ocr_correction
from book2epub.visual.source import VisualSource

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class MockOCRProvider:
    """Mock vision provider for OCR proposals and confirmations."""

    name: str = "mock-ocr"
    model: str = "mock-vlm-v1"

    def __init__(
        self,
        proposal: OCRCorrectionProposal | None = None,
        confirmation: OCRSensitiveConfirmation | None = None,
    ) -> None:
        self.proposal = proposal
        self.confirmation = confirmation
        self.calls_count = 0

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        self.calls_count += 1
        usage = ProviderUsage(input_tokens=100, output_tokens=30)

        if response_model == OCRCorrectionBatch:
            batch = OCRCorrectionBatch(
                schema_version="1.0",
                proposals=[self.proposal] if self.proposal else [],
            )
            res = StructuredInferenceResult(
                request_id=request.request_id,
                provider=self.name,
                model=self.model,
                raw_text=batch.model_dump_json(),
                parsed_json=batch.model_dump(),
                usage=usage,
                latency_ms=10,
            )
            return batch, res  # type: ignore[return-value]

        elif response_model == OCRSensitiveConfirmation:
            conf = self.confirmation or OCRSensitiveConfirmation(
                confirm=True, exact_visible_match=True, confidence=0.98
            )
            res = StructuredInferenceResult(
                request_id=request.request_id,
                provider=self.name,
                model=self.model,
                raw_text=conf.model_dump_json(),
                parsed_json=conf.model_dump(),
                usage=usage,
                latency_ms=10,
            )
            return conf, res  # type: ignore[return-value]

        raise ValueError(f"Unexpected response model: {response_model}")


def _setup_visual_source(tmp_path: Path) -> VisualSource:
    img_dir = tmp_path / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    return VisualSource(images_dir=img_dir)


def test_ocr_apply_mode_off_does_nothing(tmp_path: Path) -> None:
    """When mode is 'off', zero calls are made and text is unchanged."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    text = "Corrupted \ufffd word"
    seg = SourceTextSegment(
        segment_id="s1",
        block_id="p1",
        page_idx=0,
        text=text,
        text_sha256=compute_text_sha256(text),
        bbox=BBox(x0=10, y0=10, x1=50, y1=20),
    )
    para = Paragraph(id="p1", inlines=[Text(text=text, source_segments=[seg])])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                bbox=[10, 10, 50, 20],
                page_size=[600, 800],
            )
        ],
    )

    mock_provider = MockOCRProvider()
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="off"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    assert mock_provider.calls_count == 0
    assert len(audits) == 0
    assert res_ir == bookir


def test_ocr_apply_safe_mode_prose_correction(tmp_path: Path) -> None:
    """Safe mode corrects prose letter error and recomputes Text.text."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "すべてのファ\ufffdルを保存する"
    old_hash = compute_text_sha256(old_text)
    seg = SourceTextSegment(
        segment_id="p1-s0",
        block_id="p1",
        page_idx=0,
        text=old_text,
        text_sha256=old_hash,
        bbox=BBox(x0=10, y0=10, x1=200, y1=40),
    )
    para = Paragraph(id="p1", inlines=[Text(text=old_text, source_segments=[seg])])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )

    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                bbox=[10, 10, 200, 40],
                page_size=[600, 800],
            )
        ],
    )

    proposed_text = "すべてのファイルを保存する"
    mock_provider = MockOCRProvider(
        proposal=OCRCorrectionProposal(
            block_id="p1",
            segment_id="p1-s0",
            old_text_sha256=old_hash,
            proposed_text=proposed_text,
            confidence=0.99,
            visible_error_type="character_substitution",
            rationale="Replacement char \ufffd is clearly 'イ'",
        )
    )

    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    assert len(audits) == 1
    assert audits[0].status == "applied"
    assert audits[0].old_text == old_text
    assert audits[0].new_text == proposed_text

    # Verify BookIR was updated
    new_para = res_ir.blocks[0]
    assert isinstance(new_para, Paragraph)
    text_inl = new_para.inlines[0]
    assert isinstance(text_inl, Text)
    assert text_inl.text == proposed_text
    assert text_inl.source_segments[0].text == proposed_text
    assert text_inl.source_segments[0].text_sha256 == compute_text_sha256(proposed_text)

    # Verify audit file was written
    assert paths.semantic_ocr_corrections_json.is_file()
    assert paths.ir_corrected_json.is_file()


def test_ocr_apply_code_in_all_mode_with_confirmation(tmp_path: Path) -> None:
    """Code correction in 'all' mode requires and passes confirmation."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_code = "fn main() {\n  let retum = 1;\n}"
    old_hash = compute_text_sha256(old_code)
    code_blk = CodeBlock(
        id="c1",
        text=old_code,
        sources=[
            SourceRef(
                page_idx=0,
                bbox=BBox(x0=10, y0=10, x1=200, y1=100),
                source_type="code",
            )
        ],
    )
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[code_blk],
    )
    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="c1",
                page_idx=0,
                bbox=[10, 10, 200, 100],
                page_size=[600, 800],
            )
        ],
    )

    proposed_code = "fn main() {\n  let return = 1;\n}"
    mock_provider = MockOCRProvider(
        proposal=OCRCorrectionProposal(
            block_id="c1",
            segment_id="c1-seg-0",
            old_text_sha256=old_hash,
            proposed_text=proposed_code,
            confidence=0.99,
            visible_error_type="character_substitution",
            rationale="Typo 'retum' is clearly 'return'",
        ),
        confirmation=OCRSensitiveConfirmation(
            confirm=True, exact_visible_match=True, confidence=0.98
        ),
    )

    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="all"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    # Must make 2 calls: proposal + confirmation
    assert mock_provider.calls_count == 2
    assert len(audits) == 1
    assert audits[0].status == "applied"

    new_code = res_ir.blocks[0]
    assert isinstance(new_code, CodeBlock)
    assert new_code.text == proposed_code


def test_ocr_apply_hash_mismatch_rejected(tmp_path: Path) -> None:
    """Proposal with incorrect old_text_sha256 is rejected immediately."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "すべ1のファイルを保存する"
    seg = SourceTextSegment(
        segment_id="p1-s0",
        block_id="p1",
        page_idx=0,
        text=old_text,
        text_sha256=compute_text_sha256(old_text),
        bbox=BBox(x0=10, y0=10, x1=200, y1=40),
    )
    para = Paragraph(id="p1", inlines=[Text(text=old_text, source_segments=[seg])])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                bbox=[10, 10, 200, 40],
                page_size=[600, 800],
            )
        ],
    )

    # Provider supplies wrong old hash
    mock_provider = MockOCRProvider(
        proposal=OCRCorrectionProposal(
            block_id="p1",
            segment_id="p1-s0",
            old_text_sha256="wrong_hash_12345",
            proposed_text="すべてのファイルを保存する",
            confidence=0.99,
            visible_error_type="character_substitution",
            rationale="test",
        )
    )

    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert "Old text SHA-256 hash mismatch" in audits[0].rejection_reasons
    assert res_ir == bookir


def test_ocr_apply_digit_change_requires_confirmation(tmp_path: Path) -> None:
    """Digit change in prose requires confirmation pass; applied if confirmed."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    seg = SourceTextSegment(
        segment_id="p1-s0",
        block_id="p1",
        page_idx=0,
        text=old_text,
        text_sha256=old_hash,
        bbox=BBox(x0=10, y0=10, x1=50, y1=20),
    )
    para = Paragraph(id="p1", inlines=[Text(text=old_text, source_segments=[seg])])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                bbox=[10, 10, 50, 20],
                page_size=[600, 800],
            )
        ],
    )

    # Proposes digit change: "第1章"
    mock_provider = MockOCRProvider(
        proposal=OCRCorrectionProposal(
            block_id="p1",
            segment_id="p1-s0",
            old_text_sha256=old_hash,
            proposed_text="第1章",
            confidence=0.998,
            visible_error_type="missing_character",
            rationale="Digit 1 is clearly visible in crop",
        ),
        confirmation=OCRSensitiveConfirmation(
            confirm=True, exact_visible_match=True, confidence=0.99
        ),
    )

    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    assert mock_provider.calls_count == 2
    assert len(audits) == 1
    assert audits[0].status == "applied"
    assert audits[0].new_text == "第1章"


def test_ocr_apply_confirmation_disagreement_rejects(tmp_path: Path) -> None:
    """When confirmation pass disagrees (confirm=False), proposal is rejected."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    seg = SourceTextSegment(
        segment_id="p1-s0",
        block_id="p1",
        page_idx=0,
        text=old_text,
        text_sha256=old_hash,
        bbox=BBox(x0=10, y0=10, x1=50, y1=20),
    )
    para = Paragraph(id="p1", inlines=[Text(text=old_text, source_segments=[seg])])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                bbox=[10, 10, 50, 20],
                page_size=[600, 800],
            )
        ],
    )

    mock_provider = MockOCRProvider(
        proposal=OCRCorrectionProposal(
            block_id="p1",
            segment_id="p1-s0",
            old_text_sha256=old_hash,
            proposed_text="第1章",
            confidence=0.998,
            visible_error_type="missing_character",
            rationale="Digit 1 is guessed",
        ),
        confirmation=OCRSensitiveConfirmation(
            confirm=False, exact_visible_match=False, confidence=0.60
        ),
    )

    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    assert mock_provider.calls_count == 2
    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert res_ir == bookir


def test_ocr_apply_large_rewrite_rejected_by_budget(tmp_path: Path) -> None:
    """Proposal that rewrites too much text is rejected by edit distance limit."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "Short \ufffd"
    old_hash = compute_text_sha256(old_text)
    seg = SourceTextSegment(
        segment_id="p1-s0",
        block_id="p1",
        page_idx=0,
        text=old_text,
        text_sha256=old_hash,
        bbox=BBox(x0=10, y0=10, x1=50, y1=20),
    )
    para = Paragraph(id="p1", inlines=[Text(text=old_text, source_segments=[seg])])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                page_idx=0,
                bbox=[10, 10, 50, 20],
                page_size=[600, 800],
            )
        ],
    )

    # Propose replacing 7 chars with 30 new characters
    huge_text = "This is a completely fabricated replacement sentence."
    mock_provider = MockOCRProvider(
        proposal=OCRCorrectionProposal(
            block_id="p1",
            segment_id="p1-s0",
            old_text_sha256=old_hash,
            proposed_text=huge_text,
            confidence=0.99,
            visible_error_type="character_substitution",
            rationale="Hallucinated paragraph",
        )
    )

    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    res_ir, audits = run_ocr_correction(
        bookir=bookir,
        evidence=evidence,
        cfg=cfg,
        paths=paths,
        visual_source=visual_source,
        provider=mock_provider,
    )

    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert res_ir == bookir
