"""Integration test for full end-to-end semantic pipeline with mock provider (M8 Section 17)."""

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from book2epub.config import JobConfig, SemanticConfig
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
from book2epub.semantic.structure import (
    StructureDecision,
    StructureDecisionBatch,
)

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class MockSemanticProvider:
    """Deterministic in-memory mock provider returning valid structured decisions."""

    name: str = "mock-provider"
    model: str = "mock-model-v1"

    @property
    def supports_vision(self) -> bool:
        return False

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        """Return predetermined structured decisions based on requested schema."""
        usage = ProviderUsage(input_tokens=100, output_tokens=50, raw_provider_request_id="mock-id")

        import re

        block_ids = re.findall(r'"block_id":\s*"([^"]+)"', request.user_text)

        if response_model == StructureDecisionBatch:
            heading_id = block_ids[0] if block_ids else "blk-00001"
            batch = StructureDecisionBatch(
                schema_version="1.0",
                chunk_id=request.request_id,
                decisions=[
                    StructureDecision(
                        block_id=heading_id,
                        is_heading=True,
                        heading_level=1,
                        confidence=0.96,
                        evidence_codes=["NUMBERING_PATTERN"],
                        rationale="Clear chapter heading",
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
            # Decide that the table block should be retyped to terminal_output
            table_id = block_ids[-1] if block_ids else "blk-00003"
            batch = SemanticDecisionBatch(
                schema_version="1.0",
                chunk_id=request.request_id,
                decisions=[
                    SemanticDecision(
                        block_id=table_id,
                        target="terminal_output",
                        confidence=0.95,
                        evidence_codes=["PRECEDING_TEXT_REFERENCE", "SHELL_PROMPT_PATTERN"],
                        rationale="Preceding paragraph introduces command output",
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

        raise ValueError(f"Unexpected response model: {response_model}")


def test_semantic_mock_pipeline_e2e(tmp_path: Path) -> None:
    """
    Run complete flow:
    middle fixture -> raw IR -> evidence -> M8 semantic -> normalize -> renderer -> packaging
    """
    work_dir = tmp_path / ".work"
    output_epub = tmp_path / "test_book.epub"

    # 1. Create synthetic middle.json with:
    # - a title block: "Chapter 1"
    # - a paragraph: "以下のコマンドを実行してビルドします。"
    # - a table block misclassified by Document AI that contains shell command text
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
                        "lines": [{"spans": [{"type": "text", "content": "Chapter 1"}]}],
                    },
                    {
                        "type": "text",
                        "lines": [
                            {"spans": [{"type": "text", "content": "以下のコマンドを実行。"}]}
                        ],
                    },
                    {
                        "type": "table",
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "table",
                                        "html": (
                                            "<table><tr><td>$ cargo build\n"
                                            "   Done.</td></tr></table>"
                                        ),
                                        "content": "$ cargo build\n   Done.",
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

    cfg = JobConfig(
        app={"work_dir": work_dir},
        metadata={"title": "Semantic Integration Book"},
        semantic=SemanticConfig(enabled=True, provider="ollama", model="mock-model"),
    )
    paths = create_job_paths(work_dir)

    mock_provider = MockSemanticProvider()

    from unittest.mock import patch

    with patch("book2epub.semantic.stage.create_provider", return_value=mock_provider):
        raw_ir, normalized_ir = run_conversion_m2(
            canonical_middle_json=raw_middle,
            paths=paths,
            cfg=cfg,
        )

    # Verify M8 semantic outputs
    assert paths.ir_semantic_json.is_file()
    assert paths.semantic_outline_json.is_file()
    assert paths.semantic_book_state_json.is_file()
    assert paths.semantic_applied_json.is_file()

    # Verify that the table block was converted to PreformattedBlock with terminal_output subtype
    applied_audits = json.loads(paths.semantic_applied_json.read_text(encoding="utf-8"))
    assert any(
        a["status"] == "applied" and a["proposed_target"] == "terminal_output"
        for a in applied_audits
    )

    preformatted_blocks = [b for b in normalized_ir.blocks if isinstance(b, PreformattedBlock)]
    assert len(preformatted_blocks) == 1
    assert preformatted_blocks[0].subtype == "terminal_output"
    assert "$ cargo build" in preformatted_blocks[0].text

    # Verify renderer (M3)
    render_result = run_conversion_m3(normalized_ir, paths, cfg)
    assert render_result.xhtml_part_count >= 1

    # Verify packaging (M4)
    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)
    assert output_epub.is_file()
    assert packaging_result.file_size_bytes > 0
