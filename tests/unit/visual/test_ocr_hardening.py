"""
Comprehensive unit tests for M9 OCR correction hardening:
Identity binding, independent confirmation, JSON contract, and nested prose scope (Tests A-M).
"""

import json
from pathlib import Path
from typing import TypeVar

from PIL import Image
from pydantic import BaseModel

from book2epub.config import JobConfig, OCRCorrectionConfig
from book2epub.ir.models import (
    Aside,
    BBox,
    Block,
    BookIR,
    BookMetadata,
    Callout,
    CodeBlock,
    DefinitionItem,
    DefinitionList,
    DisplayMath,
    ExampleBlock,
    Figure,
    Footnote,
    InlineMath,
    ListBlock,
    Paragraph,
    SourceDocument,
    SourceRef,
    SourceTextSegment,
    Table,
    Text,
)
from book2epub.paths import create_job_paths
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.qa.ocr import evaluate_ocr_qa
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.models import SemanticEvidenceBlock, SemanticEvidenceBook
from book2epub.visual.models import (
    OCRCorrectionAuditFile,
    OCRCorrectionBatch,
    OCRCorrectionProposal,
    OCRIndependentRead,
)
from book2epub.visual.ocr_apply import apply_segment_replacements, run_ocr_correction
from book2epub.visual.ocr_candidates import (
    detect_ocr_candidates,
    iter_ocr_eligible_segments,
)
from book2epub.visual.source import VisualSource

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class HardenedMockOCRProvider:
    """Configurable mock OCR provider supporting multi-proposal batches and independent reads."""

    name: str = "mock-ocr"
    model: str = "mock-vlm-v1"

    def __init__(
        self,
        proposals: list[OCRCorrectionProposal] | None = None,
        independent_read: OCRIndependentRead | None = None,
    ) -> None:
        self.proposals = proposals or []
        self.independent_read = independent_read
        self.calls_count = 0
        self.recorded_requests: list[StructuredInferenceRequest] = []

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        self.calls_count += 1
        self.recorded_requests.append(request)
        usage = ProviderUsage(input_tokens=120, output_tokens=35)

        if response_model == OCRCorrectionBatch:
            batch = OCRCorrectionBatch(schema_version="1.0", proposals=self.proposals)
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

        elif response_model == OCRIndependentRead:
            assert self.independent_read is not None
            res = StructuredInferenceResult(
                request_id=request.request_id,
                provider=self.name,
                model=self.model,
                raw_text=self.independent_read.model_dump_json(),
                parsed_json=self.independent_read.model_dump(),
                usage=usage,
                latency_ms=10,
            )
            return self.independent_read, res  # type: ignore[return-value]

        raise ValueError(f"Unexpected response model: {response_model}")


def _setup_visual_source(tmp_path: Path) -> VisualSource:
    img_dir = tmp_path / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 800), color="white").save(img_dir / "page_001.png")
    return VisualSource(images_dir=img_dir)


def _make_para(block_id: str, text: str, page_idx: int = 0) -> Paragraph:
    seg = SourceTextSegment(
        segment_id=f"{block_id}-s0",
        block_id=block_id,
        page_idx=page_idx,
        text=text,
        text_sha256=compute_text_sha256(text),
        bbox=BBox(x0=10, y0=10, x1=100, y1=30),
    )
    inl = Text(text=text, source_segments=[seg])
    return Paragraph(id=block_id, inlines=[inl])


def _make_evidence(block_id: str, page_idx: int = 0) -> SemanticEvidenceBook:
    return SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id=block_id,
                page_idx=page_idx,
                bbox=[10, 10, 100, 30],
                page_size=[600, 800],
            )
        ],
    )


# --- Test A: Identity Mismatch Rejected ---
def test_a_identity_mismatch_rejected(tmp_path: Path) -> None:
    """Test A: If proposal has mismatched block_id, segment_id, or old_sha256, it is rejected."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "テキスト破損 \ufffd 発見"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    # A1: Mismatched segment_id
    provider_wrong_seg = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="wrong-segment-id",
                old_text_sha256=old_hash,
                proposed_text="テキスト破損 を 発見",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="test",
            )
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider_wrong_seg
    )
    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert res_ir == bookir

    # A2: Mismatched block_id
    provider_wrong_blk = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="wrong-block-id",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="テキスト破損 を 発見",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="test",
            )
        ]
    )
    res_ir2, audits2 = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider_wrong_blk
    )
    assert len(audits2) == 1
    assert audits2[0].status == "rejected"
    assert res_ir2 == bookir


# --- Test B: Duplicate / Conflicting Proposals in Same Batch Rejected ---
def test_b_duplicate_conflicting_proposals_rejected(tmp_path: Path) -> None:
    """Test B: Multiple proposals for same candidate segment cause a conflict rejection."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "テキスト破損 \ufffd 発見"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="テキスト破損 を 発見",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="First interpretation",
            ),
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="テキスト破損 が 発見",
                confidence=0.985,
                visible_error_type="character_substitution",
                rationale="Second conflicting interpretation",
            ),
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert any("Conflict: received 2 proposals" in r for r in audits[0].rejection_reasons)
    assert res_ir == bookir


# --- Test C: Blind proposals[0] Prevented ---
def test_c_blind_proposals_zero_prevented(tmp_path: Path) -> None:
    """Test C: Batch proposals are matched by candidate identity, not blind proposals[0]."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "すべてのファ\ufffdルを保存する"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    # proposals[0] is for another block p999, proposals[1] is the correct one for p1
    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p999",
                segment_id="p999-s0",
                old_text_sha256="dummy_hash",
                proposed_text="irrelevant",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="other",
            ),
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="すべてのファイルを保存する",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="Target proposal correctly positioned second",
            ),
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "applied"
    assert audits[0].new_text == "すべてのファイルを保存する"


# --- Test D: Independent Read Exact Agreement Applied ---
def test_d_independent_read_exact_agreement_applied(tmp_path: Path) -> None:
    """Test D: Sensitive prose with >= 0.995 confidence and exact Pass 2 agreement is applied."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="第1章",
                confidence=0.998,
                visible_error_type="missing_character",
                rationale="Digit 1 clearly printed",
            )
        ],
        independent_read=OCRIndependentRead(
            block_id="p1",
            segment_id="p1-s0",
            observed_text="第1章",
            confidence=0.997,
            clear_enough=True,
        ),
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "applied"
    assert audits[0].confirmation_result is True
    assert audits[0].confirmation_observed_text == "第1章"


# --- Test E: Independent Read Disagreement Rejected ---
def test_e_independent_read_disagreement_rejected(tmp_path: Path) -> None:
    """Test E: Pass 2 independent transcription disagreement rejects proposal."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="第1章",
                confidence=0.998,
                visible_error_type="missing_character",
                rationale="test",
            )
        ],
        independent_read=OCRIndependentRead(
            block_id="p1",
            segment_id="p1-s0",
            observed_text="第2章",  # Disagreement!
            confidence=0.998,
            clear_enough=True,
        ),
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert audits[0].confirmation_result is False
    assert any("Independent read disagreement" in r for r in audits[0].rejection_reasons)
    assert res_ir == bookir


# --- Test F: Independent Read Not Clear Enough Rejected ---
def test_f_independent_read_not_clear_enough_rejected(tmp_path: Path) -> None:
    """Test F: Pass 2 with clear_enough=False rejects proposal."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="第1章",
                confidence=0.998,
                visible_error_type="missing_character",
                rationale="test",
            )
        ],
        independent_read=OCRIndependentRead(
            block_id="p1",
            segment_id="p1-s0",
            observed_text="第1章",
            confidence=0.998,
            clear_enough=False,  # Visual evidence ambiguous
        ),
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "rejected"
    assert any("evidence not clear enough" in r for r in audits[0].rejection_reasons)
    assert res_ir == bookir


# --- Test G: Sensitive Prose Requires >= 0.995 Threshold ---
def test_g_sensitive_prose_requires_high_threshold(tmp_path: Path) -> None:
    """Test G: Sensitive prose proposal with confidence 0.98 fails (requires >= 0.995)."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="第1章",
                confidence=0.98,  # Below 0.995
                visible_error_type="missing_character",
                rationale="test",
            )
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "suggested_below_threshold"
    assert res_ir == bookir


# --- Test H: Code in Mode All Requires >= 0.995 Threshold ---
def test_h_code_in_all_mode_requires_high_threshold(tmp_path: Path) -> None:
    """Test H: Code correction in mode all with confidence 0.98 fails (requires >= 0.995)."""
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
                page_idx=0, bbox=BBox(x0=10, y0=10, x1=200, y1=100), source_type="code"
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

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="c1",
                segment_id="c1-seg-0",
                old_text_sha256=old_hash,
                proposed_text="fn main() {\n  let return = 1;\n}",
                confidence=0.98,  # Below 0.995 required for code
                visible_error_type="character_substitution",
                rationale="test",
            )
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="all"))
    res_ir, audits = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "suggested_below_threshold"
    assert res_ir == bookir


# --- Test I: Visual Recommendation Flags Real Prose Segment ---
def test_i_visual_recommendation_flags_real_prose_segment() -> None:
    """Test I: ocr_recommended_block_ids targets real SourceTextSegment, not block-seg-0."""
    para = Paragraph(
        id="blk-custom",
        inlines=[
            Text(
                text="正常なテキストですが要確認",
                source_segments=[
                    SourceTextSegment(
                        segment_id="blk-custom-p001-l002-s003",
                        page_idx=0,
                        block_id="blk-custom",
                        text="正常なテキストですが要確認",
                        text_sha256=compute_text_sha256("正常なテキストですが要確認"),
                    )
                ],
            )
        ],
    )
    # Block has no corruption patterns, but is flagged by visual review
    cands = detect_ocr_candidates(
        blocks=[para],
        mode="safe",
        ocr_recommended_block_ids={"blk-custom"},
    )
    assert len(cands) == 1
    assert cands[0].block_id == "blk-custom"
    assert cands[0].segment_id == "blk-custom-p001-l002-s003"
    assert cands[0].reason == "EXPLICIT_VISUAL_REVIEW_RECOMMENDED"


# --- Test J: Nested Prose Traversal & Replacement ---
def test_j_nested_prose_traversal_and_replacement() -> None:
    """Test J: Traversal and replacements handle Callout, List, Aside, Footnote, Figure, Def, Ex."""
    callout_para = _make_para("callout-p1", "コールアウト \ufffd テキスト")

    callout = Callout(id="callout-1", subtype="note", blocks=[callout_para])

    list_seg = SourceTextSegment(
        segment_id="list-s0",
        block_id="list-1",
        page_idx=0,
        text="リスト項目 \ufffd テキスト",
        text_sha256=compute_text_sha256("リスト項目 \ufffd テキスト"),
    )
    list_blk = ListBlock(
        id="list-1",
        items=[[Text(text="リスト項目 \ufffd テキスト", source_segments=[list_seg])]],
    )

    aside_seg = SourceTextSegment(
        segment_id="aside-s0",
        block_id="aside-1",
        page_idx=0,
        text="サイドアサイド \ufffd",
        text_sha256=compute_text_sha256("サイドアサイド \ufffd"),
    )
    aside_blk = Aside(
        id="aside-1",
        inlines=[Text(text="サイドアサイド \ufffd", source_segments=[aside_seg])],
    )

    fn_seg = SourceTextSegment(
        segment_id="fn-s0",
        block_id="fn-1",
        page_idx=0,
        text="脚注 \ufffd",
        text_sha256=compute_text_sha256("脚注 \ufffd"),
    )
    fn_blk = Footnote(
        id="fn-1",
        inlines=[Text(text="脚注 \ufffd", source_segments=[fn_seg])],
    )

    fig_cap_seg = SourceTextSegment(
        segment_id="fig-s0",
        block_id="fig-1",
        page_idx=0,
        text="図キャプション \ufffd",
        text_sha256=compute_text_sha256("図キャプション \ufffd"),
    )
    fig_blk = Figure(
        id="fig-1",
        asset_id="asset-1",
        caption=[Text(text="図キャプション \ufffd", source_segments=[fig_cap_seg])],
    )

    def_seg = SourceTextSegment(
        segment_id="def-s0",
        block_id="def-1",
        page_idx=0,
        text="用語定義 \ufffd",
        text_sha256=compute_text_sha256("用語定義 \ufffd"),
    )
    def_blk = DefinitionList(
        id="def-1",
        items=[
            DefinitionItem(
                term=[Text(text="用語")],
                definitions=[[Text(text="用語定義 \ufffd", source_segments=[def_seg])]],
            )
        ],
    )

    example_para = _make_para("ex-p1", "例題 \ufffd テキスト")
    ex_blk = ExampleBlock(id="ex-1", blocks=[example_para])

    blocks: list[Block] = [
        callout,
        list_blk,
        aside_blk,
        fn_blk,
        fig_blk,
        def_blk,
        ex_blk,
    ]

    eligible = list(iter_ocr_eligible_segments(blocks, mode="safe"))
    eligible_seg_ids = {s.segment_id for s in eligible}

    assert "callout-p1-s0" in eligible_seg_ids
    assert "list-s0" in eligible_seg_ids
    assert "aside-s0" in eligible_seg_ids
    assert "fn-s0" in eligible_seg_ids
    assert "fig-s0" in eligible_seg_ids
    assert "def-s0" in eligible_seg_ids
    assert "ex-p1-s0" in eligible_seg_ids

    # Verify replacement works across all of them
    replacements = {
        ("callout-p1", "callout-p1-s0"): "コールアウト 正常 テキスト",
        ("list-1", "list-s0"): "リスト項目 正常 テキスト",
        ("aside-1", "aside-s0"): "サイドアサイド 正常",
        ("fn-1", "fn-s0"): "脚注 正常",
        ("fig-1", "fig-s0"): "図キャプション 正常",
        ("def-1", "def-s0"): "用語定義 正常",
        ("ex-p1", "ex-p1-s0"): "例題 正常 テキスト",
    }
    replaced_blocks = apply_segment_replacements(blocks, replacements, mode="safe")

    # Assert Callout replaced
    new_callout = replaced_blocks[0]
    assert isinstance(new_callout, Callout)
    assert new_callout.blocks[0].inlines[0].text == "コールアウト 正常 テキスト"  # type: ignore[union-attr]

    # Assert Figure caption replaced
    new_fig = replaced_blocks[4]
    assert isinstance(new_fig, Figure)
    assert new_fig.caption[0].text == "図キャプション 正常"  # type: ignore[union-attr]


# --- Test K: Math and Table HTML Strictly Immutable ---
def test_k_math_and_table_html_strictly_immutable() -> None:
    """Test K: DisplayMath, InlineMath, and Table.html are never touched by OCR candidate/apply."""
    math_latex = r"\frac{\ufffd}{2}"
    table_html = "<table><tr><td>\ufffd error</td></tr></table>"

    math_blk = DisplayMath(id="m1", latex=math_latex)
    table_blk = Table(id="t1", html=table_html)
    para_math = Paragraph(
        id="p-math",
        inlines=[
            InlineMath(latex=r"x = \ufffd"),
            Text(text="普通テキスト"),
        ],
    )

    blocks: list[Block] = [math_blk, table_blk, para_math]

    # 1. Eligible segments exclude DisplayMath, InlineMath, and Table html
    eligible = list(iter_ocr_eligible_segments(blocks, mode="all"))
    assert not any(s.block_id in ("m1", "t1") for s in eligible)
    assert len(eligible) == 0  # "普通テキスト" has no source_segments

    # 2. Candidate detection produces zero candidates
    cands = detect_ocr_candidates(blocks, mode="all")
    assert len(cands) == 0

    # 3. apply_segment_replacements leaves them unchanged
    replacements = {("m1", "m1-seg-0"): r"\frac{1}{2}", ("t1", "t1-seg-0"): "clean"}
    replaced = apply_segment_replacements(blocks, replacements, mode="all")
    assert getattr(replaced[0], "latex") == math_latex
    assert getattr(replaced[1], "html") == table_html


# --- Test L: OCRCorrectionAuditFile Contract & QA Evaluator ---
def test_l_ocr_audit_file_contract_and_qa_evaluator(tmp_path: Path) -> None:
    """Test L: OCRCorrectionAuditFile complies 100% with contract and evaluate_ocr_qa parses it."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "すべてのファ\ufffdルを保存する"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="すべてのファイルを保存する",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="test",
            )
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    run_ocr_correction(bookir, evidence, cfg, paths, visual_source, provider=provider)

    # 1. Verify file exists and parses as OCRCorrectionAuditFile
    assert paths.semantic_ocr_corrections_json.is_file()
    audit_file = OCRCorrectionAuditFile.model_validate_json(
        paths.semantic_ocr_corrections_json.read_text(encoding="utf-8")
    )
    assert audit_file.schema_version == "1.0"
    assert audit_file.mode == "safe"
    assert audit_file.applied_count == 1
    assert audit_file.candidate_count == 1
    assert audit_file.eligible_segment_count == 1
    assert audit_file.budget_exceeded is False
    assert len(audit_file.audits) == 1
    assert audit_file.audits[0].status == "applied"

    # 2. Evaluate via QA module
    metrics, violations = evaluate_ocr_qa(paths.semantic_ocr_corrections_json, cfg_mode="safe")
    assert metrics.ocr_applied_count == 1
    assert metrics.ocr_proposal_count == 1
    assert metrics.ocr_candidate_count == 1
    assert metrics.ocr_budget_exceeded is False
    assert len(violations) == 0


# --- Test M: Provider Usage Recorded for Proposal & Confirmation ---
def test_m_provider_usage_recorded_for_proposal_and_confirmation(tmp_path: Path) -> None:
    """Test M: Provider usage file records both ocr_proposal and ocr_confirmation passes."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "第\ufffd章"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="第1章",
                confidence=0.998,
                visible_error_type="missing_character",
                rationale="test",
            )
        ],
        independent_read=OCRIndependentRead(
            block_id="p1",
            segment_id="p1-s0",
            observed_text="第1章",
            confidence=0.998,
            clear_enough=True,
        ),
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    run_ocr_correction(bookir, evidence, cfg, paths, visual_source, provider=provider)

    # Verify semantic/provider-usage.json
    usage_file = paths.semantic_provider_usage_json
    assert usage_file.is_file()
    usage_records = json.loads(usage_file.read_text(encoding="utf-8"))
    assert len(usage_records) == 2

    passes = [r.get("pass") for r in usage_records]
    assert "ocr_proposal" in passes
    assert "ocr_confirmation" in passes

    for rec in usage_records:
        assert rec["provider"] == "mock-ocr"
        assert rec["model"] == "mock-vlm-v1"
        assert "usage" in rec
        assert "latency_ms" in rec


# --- Test N: Old Text SHA-256 in Prompt ---
def test_n_old_text_sha256_in_prompt(tmp_path: Path) -> None:
    """Test N: Pass 1 user prompt contains the exact old_text_sha256 token."""
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "すべてのファ\ufffdルを保存する"
    old_hash = compute_text_sha256(old_text)
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="p1",
                segment_id="p1-s0",
                old_text_sha256=old_hash,
                proposed_text="すべてのファイルを保存する",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="test",
            )
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))
    run_ocr_correction(bookir, evidence, cfg, paths, visual_source, provider=provider)

    assert len(provider.recorded_requests) >= 1
    req_text = provider.recorded_requests[0].user_text
    assert f"Old Text SHA-256: {old_hash}" in req_text
    assert old_hash in req_text


# --- Test O: Crop and API Failure Audit Invariant ---
def test_o_crop_and_api_failure_audit_invariant(tmp_path: Path) -> None:
    """Test O: Crop or API failures produce rejected audit records.

    Also tests that candidate_count == applied_count + rejected_count == len(audits).
    """
    from unittest.mock import patch

    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "テキスト破損 \ufffd 発見"
    para = _make_para("p1", old_text)
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[para],
    )
    evidence = _make_evidence("p1")
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    # 1. Crop Failure
    provider_crop = HardenedMockOCRProvider()
    with patch(
        "book2epub.visual.ocr_apply.map_and_crop",
        side_effect=RuntimeError("Simulated crop failure"),
    ):
        res_ir, audits_crop = run_ocr_correction(
            bookir, evidence, cfg, paths, visual_source, provider=provider_crop
        )

    assert len(audits_crop) == 1
    assert audits_crop[0].status == "rejected"
    assert any("Failed to generate visual crop" in r for r in audits_crop[0].rejection_reasons)
    audit_file_crop = OCRCorrectionAuditFile.model_validate_json(
        paths.semantic_ocr_corrections_json.read_text(encoding="utf-8")
    )
    assert audit_file_crop.candidate_count == 1
    assert audit_file_crop.applied_count == 0
    assert audit_file_crop.rejected_count == 1
    assert (
        audit_file_crop.candidate_count
        == audit_file_crop.applied_count + audit_file_crop.rejected_count
        == len(audit_file_crop.audits)
    )

    # 2. Provider API Failure
    class FailingProvider(HardenedMockOCRProvider):
        def infer(self, request, response_model):
            self.calls_count += 1
            raise RuntimeError("API timeout failure")

    provider_fail = FailingProvider()
    res_ir, audits_fail = run_ocr_correction(
        bookir, evidence, cfg, paths, visual_source, provider=provider_fail
    )

    assert len(audits_fail) == 1
    assert audits_fail[0].status == "rejected"
    assert any(
        "OCR proposal provider inference failed" in r
        for r in audits_fail[0].rejection_reasons
    )
    audit_file_fail = OCRCorrectionAuditFile.model_validate_json(
        paths.semantic_ocr_corrections_json.read_text(encoding="utf-8")
    )
    assert audit_file_fail.candidate_count == 1
    assert audit_file_fail.applied_count == 0
    assert audit_file_fail.rejected_count == 1
    assert (
        audit_file_fail.candidate_count
        == audit_file_fail.applied_count + audit_file_fail.rejected_count
        == len(audit_file_fail.audits)
    )


# --- Test P: Nested Prose Page Size Lookup and Safe Coordinate Failure ---
def test_p_nested_prose_page_size_lookup_and_failure(tmp_path: Path) -> None:
    """Test P: Nested prose resolves page size from page_size_lookup.

    Fails safely if page size is missing.
    """
    visual_source = _setup_visual_source(tmp_path)
    paths = create_job_paths(tmp_path / "work")
    paths.ensure_directories()

    old_text = "例題内の破損 \ufffd"
    old_hash = compute_text_sha256(old_text)
    # ex-p1 is nested inside ex-1; top-level evidence only has ex-1
    nested_para = _make_para("ex-p1", old_text, page_idx=0)
    ex_blk = ExampleBlock(id="ex-1", blocks=[nested_para])
    bookir = BookIR(
        metadata=BookMetadata(title="Test"),
        source=SourceDocument(page_count=1),
        blocks=[ex_blk],
    )

    # 1. Evidence has page_size [700, 1000] on top-level block ex-1
    evidence_with_page_size = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="ex-1",
                page_idx=0,
                bbox=[10, 10, 200, 100],
                page_size=[700, 1000],  # Non-standard page size
            )
        ],
    )

    provider = HardenedMockOCRProvider(
        proposals=[
            OCRCorrectionProposal(
                block_id="ex-p1",
                segment_id="ex-p1-s0",
                old_text_sha256=old_hash,
                proposed_text="例題内の破損 修",
                confidence=0.99,
                visible_error_type="character_substitution",
                rationale="test",
            )
        ]
    )
    cfg = JobConfig(ocr_correction=OCRCorrectionConfig(mode="safe"))

    res_ir, audits = run_ocr_correction(
        bookir, evidence_with_page_size, cfg, paths, visual_source, provider=provider
    )
    assert len(audits) == 1
    assert audits[0].status == "applied"
    assert audits[0].new_text == "例題内の破損 修"

    # 2. Evidence has NO valid page_size for page_idx 0 -> candidate is rejected safely
    evidence_no_page_size = SemanticEvidenceBook(
        schema_version="1.0",
        source_middle_sha256="h1",
        raw_bookir_sha256="h2",
        blocks=[
            SemanticEvidenceBlock(
                block_id="ex-1",
                page_idx=0,
                bbox=[10, 10, 200, 100],
                page_size=[0.0, 0.0],
            )
        ],
    )
    res_ir2, audits2 = run_ocr_correction(
        bookir, evidence_no_page_size, cfg, paths, visual_source, provider=provider
    )
    assert len(audits2) == 1
    assert audits2[0].status == "rejected"
    assert any(
        "Source page dimensions unavailable for coordinate mapping" in r
        for r in audits2[0].rejection_reasons
    )

