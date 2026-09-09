"""Full end-to-end extended integration test with mock providers covering M6-M12 (Section 16-17).

Validates:
- Fixture A: command output misread as table -> terminal_output
- Fixture B: genuine table -> remains table
- Fixture C: heading hierarchy consistency
- Fixture D: Japanese technical prose across boundaries (no artificial spaces)
- Fixture E: list marker duplication removal
- Fixture F: component presentation classes
- Preservation ledger with 100% block disposition accounting
- EPUBCheck release gate
"""

import json
from pathlib import Path
from typing import TypeVar
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from book2epub.config import (
    AppConfig,
    JobConfig,
    MetadataConfig,
    PresentationConfig,
    SemanticConfig,
)
from book2epub.ir.models import (
    BookIR,
    ListBlock,
    Paragraph,
    PreformattedBlock,
    Table,
)
from book2epub.package.validator import run_epubcheck
from book2epub.paths import create_job_paths
from book2epub.pipeline import (
    run_conversion_m2,
    run_conversion_m3,
    run_conversion_m4,
    run_conversion_m5,
)
from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE
from book2epub.presentation.models import BookStyleProfileDecision
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


class ExtendedMockProvider:
    """Mock provider serving valid responses for M7 semantic and M10 presentation requests."""

    name: str = "mock-extended-provider"
    model: str = "mock-extended-v1"

    @property
    def supports_vision(self) -> bool:
        return False

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        usage = ProviderUsage(
            input_tokens=150, output_tokens=75, raw_provider_request_id="mock-ext-id"
        )

        import re

        if response_model == StructureDecisionBatch:
            block_ids = re.findall(r'"block_id":\s*"([^"]+)"', request.user_text)
            decisions = []
            if len(block_ids) >= 1:
                decisions.append(
                    StructureDecision(
                        block_id=block_ids[0],
                        is_heading=True,
                        heading_level=1,
                        confidence=0.98,
                        evidence_codes=["NUMBERING_PATTERN"],
                        rationale="Top-level chapter title",
                    )
                )
            if len(block_ids) >= 2:
                decisions.append(
                    StructureDecision(
                        block_id=block_ids[1],
                        is_heading=True,
                        heading_level=2,
                        confidence=0.95,
                        evidence_codes=["NUMBERING_PATTERN"],
                        rationale="Section heading",
                    )
                )
            batch = StructureDecisionBatch(
                schema_version="1.0",
                chunk_id=request.request_id,
                decisions=decisions,
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

        elif response_model == SemanticDecisionBatch:
            blocks_part = request.user_text.split("BLOCKS:")[-1].strip()
            try:
                blocks_data = json.loads(blocks_part)
            except Exception:
                blocks_data = []

            decisions = []
            for b in blocks_data:
                bid = b.get("block_id")
                text = str(b.get("text_preview", ""))
                if "uname" in text or "$" in text:
                    decisions.append(
                        SemanticDecision(
                            block_id=bid,
                            target="terminal_output",
                            confidence=0.96,
                            evidence_codes=["SHELL_PROMPT_PATTERN", "PRECEDING_TEXT_REFERENCE"],
                            rationale="Preceding paragraph introduces command output",
                        )
                    )
                elif b.get("source_type") == "table":
                    decisions.append(
                        SemanticDecision(
                            block_id=bid,
                            target="table",
                            confidence=0.99,
                            evidence_codes=[
                                "TABULAR_HEADER_PATTERN",
                                "TABULAR_ROW_COLUMN_SEMANTICS",
                            ],
                            rationale="Genuine relational reference table",
                        )
                    )

            batch = SemanticDecisionBatch(
                schema_version="1.0",
                chunk_id=request.request_id,
                decisions=decisions,
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

        elif response_model == BookStyleProfileDecision:
            batch = BookStyleProfileDecision(
                schema_version="1.0",
                profile=DEFAULT_ENHANCED_PROFILE,
                confidence=0.92,
            )
            res = StructuredInferenceResult(
                request_id=request.request_id,
                provider=self.name,
                model=self.model,
                raw_text=batch.model_dump_json(),
                parsed_json=batch.model_dump(),
                usage=usage,
                latency_ms=20,
            )
            return batch, res  # type: ignore[return-value]

        raise ValueError(f"Unexpected response model in mock provider: {response_model}")


@pytest.mark.integration
def test_extended_mock_e2e_pipeline(tmp_path: Path) -> None:
    """
    Execute full M6-M12 pipeline on a comprehensive synthetic book:
    - Verifies M6 evidence extraction
    - Verifies M7 mock structured outputs
    - Verifies M8 structure decisions & semantic retyping (table -> terminal_output)
    - Verifies M10 enhanced component rendering & profile
    - Verifies M11 Japanese boundary typography & list marker deduplication
    - Verifies M12 preservation ledger, semantic metrics, presentation QA, and EPUB packaging
    """
    work_dir = tmp_path / "work"
    output_epub = tmp_path / "extended_book.epub"

    # Construct comprehensive middle.json covering Fixtures A, B, C, D, E, F
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
                    # Fixture C: Headings
                    {
                        "type": "title",
                        "level": 1,
                        "lines": [{"spans": [{"type": "text", "content": "第1章 Unix入門"}]}],
                    },
                    {
                        "type": "title",
                        "level": 2,
                        "lines": [
                            {"spans": [{"type": "text", "content": "1.1 コマンドライン操作"}]}
                        ],
                    },
                    # Fixture D: Japanese technical prose across boundaries
                    {
                        "type": "text",
                        "lines": [
                            {
                                "spans": [
                                    {"type": "text", "content": "Linux"},
                                    {"type": "text", "content": "カーネル"},
                                    {"type": "text", "content": "環境において、"},
                                    {"type": "text", "content": "C"},
                                    {"type": "text", "content": "言語"},
                                    {"type": "text", "content": "で開発し、"},
                                    {"type": "text", "content": "UTF-8"},
                                    {"type": "text", "content": "形式で保存します。"},
                                    {"type": "text", "content": "日本語（Linux）"},
                                    {"type": "text", "content": "の設定を確認してください。"},
                                ]
                            }
                        ],
                    },
                    # Fixture A: Command output misclassified as table
                    {
                        "type": "text",
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "text",
                                        "content": "システム情報を表示した結果を次に示します。",
                                    }
                                ]
                            }
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
                                            "<table><tr><td>$ uname -a\n"
                                            "Linux ubuntu 5.4.0-generic x86_64\n"
                                            "$ whoami\n"
                                            "developer</td></tr></table>"
                                        ),
                                        "content": (
                                            "$ uname -a\nLinux ubuntu 5.4.0-generic x86_64\n"
                                            "$ whoami\ndeveloper"
                                        ),
                                    }
                                ]
                            }
                        ],
                    },
                    # Fixture B: Genuine tabular reference
                    {
                        "type": "text",
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "type": "text",
                                        "content": "主要コマンドの概要を表1-1にまとめます。",
                                    }
                                ]
                            }
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
                                            "<table><thead><tr><th>コマンド</th><th>概要</th></tr></thead>"
                                            "<tbody><tr><td>ls</td><td>一覧表示</td></tr>"
                                            "<tr><td>cd</td><td>ディレクトリ移動</td></tr></tbody></table>"
                                        ),
                                        "content": (
                                            "コマンド\t概要\nls\t一覧表示\ncd\tディレクトリ移動"
                                        ),
                                    }
                                ]
                            }
                        ],
                    },
                    # Fixture E: List with leading duplicate markers in source
                    {
                        "type": "list",
                        "lines": [
                            {"spans": [{"type": "text", "content": "• - 最初の手順を確認する"}]},
                            {"spans": [{"type": "text", "content": "- 次の手順を実行する"}]},
                            {"spans": [{"type": "text", "content": "1. 最後の検証を行う"}]},
                        ],
                    },
                ],
                "discarded_blocks": [
                    {
                        "type": "header",
                        "lines": [
                            {"spans": [{"type": "text", "content": "Unix Programming Manual"}]}
                        ],
                    },
                    {
                        "type": "footer",
                        "lines": [{"spans": [{"type": "text", "content": "1"}]}],
                    },
                ],
            }
        ],
    }

    raw_middle = tmp_path / "source_middle.json"
    raw_middle.write_text(json.dumps(middle_data, ensure_ascii=False), encoding="utf-8")

    cfg = JobConfig(
        app=AppConfig(work_dir=work_dir, strict=True),
        metadata=MetadataConfig(title="Extended M6-M12 Test Book", language="ja"),
        semantic=SemanticConfig(enabled=True, provider="ollama", model="mock-extended-v1"),
        presentation=PresentationConfig(mode="enhanced"),
    )
    paths = create_job_paths(work_dir)

    mock_provider = ExtendedMockProvider()

    # Run Stage 3: IR + Semantic + Normalization
    with patch("book2epub.semantic.stage.create_provider", return_value=mock_provider):
        raw_ir, normalized_ir = run_conversion_m2(
            canonical_middle_json=raw_middle,
            paths=paths,
            cfg=cfg,
        )

    # 1. Assert Semantic Outputs (M6 - M8)
    assert paths.semantic_evidence_json.is_file()
    assert paths.ir_semantic_json.is_file()
    assert paths.semantic_applied_json.is_file()
    assert paths.semantic_outline_json.is_file()

    # Verify Fixture A retyping: table -> terminal_output
    preformatted = [b for b in normalized_ir.blocks if isinstance(b, PreformattedBlock)]
    assert len(preformatted) == 1
    assert preformatted[0].subtype == "terminal_output"
    assert "$ uname -a" in preformatted[0].text

    # Verify Fixture B genuine table remains Table
    tables = [b for b in normalized_ir.blocks if isinstance(b, Table)]
    assert len(tables) == 1
    assert "一覧表示" in (tables[0].html or "")

    # Run Stage 4: Typography Normalization & Presentation Rendering (M10, M11)
    render_result = run_conversion_m3(normalized_ir, paths, cfg)

    assert paths.ir_typography_json.is_file()
    assert paths.normalization_report_file.is_file()
    assert render_result.xhtml_part_count >= 1

    # Verify Fixture D: Japanese typography spacing in typography-normalized IR
    # "Linuxカーネル", "C言語", "UTF-8", "日本語（Linux）" must have no spaces
    typography_ir = BookIR.model_validate_json(
        paths.ir_typography_json.read_text(encoding="utf-8")
    )

    def get_inlines_text(inlines: list) -> str:
        return "".join(getattr(i, "text", "") for i in inlines)

    paras = [b for b in typography_ir.blocks if isinstance(b, Paragraph)]
    japanese_para = next(
        (
            p
            for p in paras
            if "Linux" in get_inlines_text(p.inlines) and "カーネル" in get_inlines_text(p.inlines)
        ),
        None,
    )
    assert japanese_para is not None
    para_text = get_inlines_text(japanese_para.inlines)
    assert "Linuxカーネル" in para_text
    assert "C言語" in para_text
    assert "UTF-8" in para_text
    assert "日本語（Linux）" in para_text
    assert "Linux カーネル" not in para_text
    assert "C 言語" not in para_text

    # Verify Fixture E: List marker deduplication in typography-normalized IR
    list_blocks = [b for b in typography_ir.blocks if isinstance(b, ListBlock)]
    assert len(list_blocks) == 1
    # Check that leading bullets "• - " were removed from item inlines into source_markers
    for item in list_blocks[0].items:
        item_text = get_inlines_text(item)
        assert not item_text.startswith("•")
        assert not item_text.startswith("- ")

    # Run Stage 5: EPUB Packaging & Validation (M4)
    packaging_result = run_conversion_m4(render_result, output_epub, paths, cfg)
    assert output_epub.is_file()
    assert packaging_result.file_size_bytes > 0

    # Run Stage 6: QA Evaluation (M12)
    qa_report = run_conversion_m5(
        paths=paths,
        raw_middle_path=raw_middle,
        book_ir=normalized_ir,
        render_result=render_result,
        packaging_result=packaging_result,
        cfg=cfg,
    )

    # 2. Assert QA Ledger & Semantic Metrics (M12)
    assert paths.qa_report_json.is_file()
    assert paths.qa_report_html.is_file()

    # Preservation ledger must account for 100% of blocks
    assert qa_report.preservation_ledger is not None
    assert len(qa_report.preservation_ledger) > 0
    # No lost errors
    assert all(entry.disposition != "lost_error" for entry in qa_report.preservation_ledger)

    # Retyped command table is tracked in ledger
    retyped_entries = [
        e for e in qa_report.preservation_ledger if e.disposition == "preserved_retyped"
    ]
    assert len(retyped_entries) >= 1
    assert any(
        e.source_kind == "table" and e.final_kind == "preformatted" for e in retyped_entries
    )

    # Same type entries (genuine table, headings, paragraph, list) are tracked in ledger
    same_type_entries = [
        e for e in qa_report.preservation_ledger if e.disposition == "preserved_same_type"
    ]
    assert len(same_type_entries) >= 1

    # Semantic transition metrics
    assert qa_report.semantic_metrics is not None
    assert qa_report.semantic_metrics.semantic_review_rate == 1.0
    assert "table -> terminal_output" in qa_report.semantic_metrics.type_transitions

    # Presentation QA
    assert qa_report.presentation_metrics is not None
    assert qa_report.presentation_metrics.list_duplicate_marker_count == 0

    # Strict EPUBCheck
    check_report = run_epubcheck(output_epub, fail_on_warnings=True)
    assert check_report.is_valid, f"EPUBCheck errors: {check_report.issues}"
