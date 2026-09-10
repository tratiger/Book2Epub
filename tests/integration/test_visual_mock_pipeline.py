"""
Integration test for full end-to-end multimodal visual arbitration
and OCR correction pipeline (M9 Section 17).
"""

import json
from pathlib import Path
from typing import TypeVar

from PIL import Image
from pydantic import BaseModel

from book2epub.config import (
    AppConfig,
    JobConfig,
    OCRCorrectionConfig,
    SemanticConfig,
)
from book2epub.ir.models import PreformattedBlock
from book2epub.paths import create_job_paths
from book2epub.pipeline import (
    run_conversion_m2,
    run_conversion_m3,
    run_conversion_m4,
)
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.semantic.decisions import (
    SemanticDecision,
    SemanticDecisionBatch,
)
from book2epub.semantic.hashing import compute_text_sha256
from book2epub.semantic.structure import (
    StructureDecision,
    StructureDecisionBatch,
)
from book2epub.visual.models import (
    OCRCorrectionBatch,
    OCRCorrectionProposal,
    VisualSemanticBatch,
    VisualSemanticDecision,
)

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class MockMultimodalPipelineProvider:
    """Mock multimodal provider handling text semantic, visual arbitration, and OCR correction."""

    name: str = "mock-multimodal"
    model: str = "mock-vlm-v1"

    @property
    def supports_vision(self) -> bool:
        return True

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        usage = ProviderUsage(input_tokens=200, output_tokens=50)

        import re

        block_ids = re.findall(r'"block_id":\s*"([^"]+)"', request.user_text)
        chunk_match = re.search(r"CHUNK_ID:\s*(\S+)", request.user_text)
        chunk_id = chunk_match.group(1) if chunk_match else request.request_id

        if response_model == StructureDecisionBatch:
            batch = StructureDecisionBatch(
                schema_version="1.0",
                chunk_id=chunk_id,
                decisions=[
                    StructureDecision(
                        block_id=block_ids[0] if block_ids else "blk-00001",
                        is_heading=True,
                        heading_level=1,
                        confidence=0.96,
                        evidence_codes=["NUMBERING_PATTERN"],
                        rationale="Chapter heading",
                    )
                ],
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

        elif response_model == SemanticDecisionBatch:
            # Proposed as terminal_output with confidence 0.70 (<0.80 -> queued for visual review)
            batch = SemanticDecisionBatch(
                schema_version="1.0",
                chunk_id=chunk_id,
                decisions=[
                    SemanticDecision(
                        block_id=block_ids[-1] if block_ids else "blk-00003",
                        target="terminal_output",
                        confidence=0.70,
                        evidence_codes=["SHELL_PROMPT_PATTERN"],
                        rationale="Low-confidence shell output, queuing for visual check",
                    )
                ],
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

        elif response_model == VisualSemanticBatch:
            # Visual arbitration confirms terminal_output with high confidence (0.94)
            batch = VisualSemanticBatch(
                schema_version="1.0",
                decisions=[
                    VisualSemanticDecision(
                        block_id=block_ids[0] if block_ids else "blk-00003",
                        decision="confirm_proposed",
                        target="terminal_output",
                        confidence=0.94,
                        visual_evidence_codes=["MONOSPACE_VISUAL_STYLE", "SHELL_PROMPT_VISIBLE"],
                        rationale="Visual crop proves terminal box with black background",
                        ocr_review_recommended=True,
                    )
                ],
            )
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

        elif response_model == OCRCorrectionBatch:
            # Propose correction for paragraph typo
            batch = OCRCorrectionBatch(
                schema_version="1.0",
                proposals=[
                    OCRCorrectionProposal(
                        block_id="blk-00002",
                        segment_id="blk-00002-seg-0",
                        old_text_sha256=compute_text_sha256("すべてのファ\ufffdルを保存する"),
                        proposed_text="すべてのファイルを保存する",
                        confidence=0.99,
                        visible_error_type="character_substitution",
                        rationale="Replacement char \ufffd is clearly 'イ'",
                    )
                ],
            )
            res = StructuredInferenceResult(
                request_id=request.request_id,
                provider=self.name,
                model=self.model,
                raw_text=batch.model_dump_json(),
                parsed_json=batch.model_dump(),
                usage=usage,
                latency_ms=12,
            )
            return batch, res  # type: ignore[return-value]

        raise ValueError(f"Unexpected response model: {response_model}")


def test_visual_mock_pipeline_e2e(tmp_path: Path) -> None:
    """Run complete pipeline through M8 semantic, M9 visual arbitration, and M9 OCR correction."""
    work_dir = tmp_path / ".work"
    output_epub = tmp_path / "multimodal_test.epub"

    # 1. Create synthetic source images directory
    source_images_dir = tmp_path / "source_pages"
    source_images_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(source_images_dir / "page_001.png")

    # 2. Synthetic middle.json
    middle_data = {
        "_version_name": "3.4.5",
        "_backend": "hybrid",
        "_effort": "high",
        "_ocr_enable": True,
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [600, 800],
                "para_blocks": [
                    {
                        "type": "title",
                        "level": 1,
                        "bbox": [50, 50, 300, 80],
                        "lines": [{"spans": [{"type": "text", "content": "Chapter 1"}]}],
                    },
                    {
                        "type": "text",
                        "bbox": [50, 100, 500, 140],
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "text",
                                        "content": "すべてのファ\ufffdルを保存する",
                                    }
                                ]
                            }
                        ],
                    },
                    {
                        "type": "table",
                        "bbox": [50, 160, 500, 300],
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "table",
                                        "html": (
                                            "<table><tr><td>$ cargo run\n"
                                            "   Finished.</td></tr></table>"
                                        ),
                                        "content": "$ cargo run\n   Finished.",
                                    }
                                ]
                            }
                        ],
                    },
                ],
                "discarded_blocks": [],
            }
        ],
    }

    raw_middle = tmp_path / "source_middle.json"
    raw_middle.write_text(json.dumps(middle_data, ensure_ascii=False), encoding="utf-8")

    paths = create_job_paths(work_dir)

    cfg = JobConfig(
        app=AppConfig(
            work_dir=work_dir,
            source_images_dir=source_images_dir,
        ),
        metadata={"title": "Multimodal Integration Book"},
        semantic=SemanticConfig(
            enabled=True,
            provider="ollama",
            model="mock-vlm",
            vision="auto",
        ),
        ocr_correction=OCRCorrectionConfig(mode="safe"),
    )

    mock_provider = MockMultimodalPipelineProvider()

    from unittest.mock import patch

    with (
        patch("book2epub.semantic.stage.create_provider", return_value=mock_provider),
        patch("book2epub.providers.factory.create_provider", return_value=mock_provider),
    ):
        raw_ir, normalized_ir = run_conversion_m2(
            canonical_middle_json=raw_middle,
            paths=paths,
            cfg=cfg,
        )

    # 3. Assert M9 outputs
    assert paths.ir_corrected_json.is_file()
    assert paths.semantic_ocr_corrections_json.is_file()

    # Table was converted to PreformattedBlock with terminal_output subtype
    preformatted_blocks = [b for b in normalized_ir.blocks if isinstance(b, PreformattedBlock)]
    assert len(preformatted_blocks) == 1
    assert preformatted_blocks[0].subtype == "terminal_output"

    # Typo was corrected in normalized IR
    target_para = next(b for b in normalized_ir.blocks if b.id == "blk-00002")
    assert any(
        "すべてのファイルを保存する" in inl.text
        for inl in getattr(target_para, "inlines", [])
        if hasattr(inl, "text")
    )

    # 4. Render and package EPUB
    render_result = run_conversion_m3(normalized_ir, paths, cfg)
    assert render_result.xhtml_part_count >= 1

    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)
    assert output_epub.is_file()
    assert packaging_result.file_size_bytes > 0
