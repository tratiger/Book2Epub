"""Live and semantic-cache relation path integration tests."""

import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from book2epub.config import JobConfig, SemanticConfig
from book2epub.ir.models import BookIR, CodeBlock, Paragraph, SourceDocument, SourceRef, Text
from book2epub.paths import create_job_paths
from book2epub.pipeline import run_conversion_m3, run_conversion_m4
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.semantic.decisions import (
    SemanticBlockDecision,
    SemanticDecisionBatch,
    SemanticRelationDecision,
)
from book2epub.semantic.models import (
    DraftBlock,
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)
from book2epub.semantic.stage import run_semantic_reconstruction
from book2epub.semantic.structure import StructureDecisionBatch

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class _RelationProvider:
    name = "relation-provider"
    model = "relation-model"

    def __init__(self) -> None:
        self.calls = 0

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        self.calls += 1
        chunk_match = re.search(r"CHUNK_ID: (\S+)", request.user_text)
        assert chunk_match is not None
        chunk_id = chunk_match.group(1)
        if response_model == StructureDecisionBatch:
            batch: BaseModel = StructureDecisionBatch(chunk_id=chunk_id)
        else:
            batch = SemanticDecisionBatch(
                chunk_id=chunk_id,
                decisions=[
                    SemanticBlockDecision(
                        block_id="code",
                        operation="keep",
                        confidence=0.95,
                    )
                ],
                relations=[
                    SemanticRelationDecision(
                        relation_type="caption_of",
                        source_block_ids=["caption"],
                        target_block_id="code",
                        confidence=0.95,
                    ),
                    SemanticRelationDecision(
                        relation_type="caption_of",
                        source_block_ids=["ghost"],
                        target_block_id="code",
                        confidence=0.95,
                    ),
                ],
            )
        result = StructuredInferenceResult(
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            raw_text=batch.model_dump_json(),
            parsed_json=batch.model_dump(),
            usage=ProviderUsage(input_tokens=1, output_tokens=1),
            latency_ms=0,
        )
        return batch, result  # type: ignore[return-value]


class _CalloutRelationProvider(_RelationProvider):
    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        self.calls += 1
        chunk_match = re.search(r"CHUNK_ID: (\S+)", request.user_text)
        assert chunk_match is not None
        chunk_id = chunk_match.group(1)
        if response_model == StructureDecisionBatch:
            batch: BaseModel = StructureDecisionBatch(chunk_id=chunk_id)
        else:
            batch = SemanticDecisionBatch(
                chunk_id=chunk_id,
                decisions=[
                    SemanticBlockDecision(
                        block_id="p1",
                        operation="retype",
                        target_type="callout_warning",
                        confidence=0.95,
                    )
                ],
                relations=[
                    SemanticRelationDecision(
                        relation_type="member_of_callout",
                        source_block_ids=["p1", "p2"],
                        confidence=0.95,
                    )
                ],
            )
        result = StructuredInferenceResult(
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            raw_text=batch.model_dump_json(),
            parsed_json=batch.model_dump(),
            usage=ProviderUsage(input_tokens=1, output_tokens=1),
            latency_ms=0,
        )
        return batch, result  # type: ignore[return-value]


class _CalloutSafetyProvider(_RelationProvider):
    def __init__(self, relation_source_ids: list[str]) -> None:
        super().__init__()
        self.relation_source_ids = relation_source_ids

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        self.calls += 1
        chunk_match = re.search(r"CHUNK_ID: (\S+)", request.user_text)
        assert chunk_match is not None
        chunk_id = chunk_match.group(1)
        if response_model == StructureDecisionBatch:
            batch: BaseModel = StructureDecisionBatch(chunk_id=chunk_id)
        else:
            batch = SemanticDecisionBatch(
                chunk_id=chunk_id,
                decisions=[
                    SemanticBlockDecision(
                        block_id="p1",
                        operation="retype",
                        target_type="callout_warning",
                        confidence=0.95,
                    )
                ],
                relations=[
                    SemanticRelationDecision(
                        relation_type="member_of_callout",
                        source_block_ids=self.relation_source_ids,
                        confidence=0.95,
                    )
                ],
            )
        result = StructuredInferenceResult(
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            raw_text=batch.model_dump_json(),
            parsed_json=batch.model_dump(),
            usage=ProviderUsage(input_tokens=1, output_tokens=1),
            latency_ms=0,
        )
        return batch, result  # type: ignore[return-value]


def _fixture() -> tuple[BookIR, SemanticEvidenceBook, SemanticDraftBook]:
    caption = Paragraph(
        id="caption",
        sources=[SourceRef(page_idx=0, source_type="text")],
        inlines=[Text(text="Figure 1: System")],
    )
    code = CodeBlock(
        id="code",
        sources=[SourceRef(page_idx=0, source_type="code")],
        text="print('system')",
    )
    raw_ir = BookIR(
        source=SourceDocument(page_count=1),
        blocks=[caption, code],
    )
    evidence = SemanticEvidenceBook(
        source_middle_sha256="middle",
        raw_bookir_sha256="raw",
        blocks=[
            SemanticEvidenceBlock(
                block_id="caption",
                current_kind="paragraph",
                source_type="text",
                plain_text="Figure 1: System",
            ),
            SemanticEvidenceBlock(
                block_id="code",
                current_kind="code",
                source_type="code",
                preformatted_text="print('system')",
            ),
        ],
    )
    draft = SemanticDraftBook(
        book_id="book",
        blocks=[
            DraftBlock(
                block_id="caption",
                current_kind="paragraph",
                source_type="text",
                text_preview="Figure 1: System",
                page_idx=0,
            ),
            DraftBlock(
                block_id="code",
                current_kind="code",
                source_type="code",
                page_idx=0,
            ),
        ],
    )
    return raw_ir, evidence, draft


def test_live_and_cache_hit_relation_paths_produce_same_semantic_ir(tmp_path: Path) -> None:
    raw_ir, evidence, draft = _fixture()
    cfg = JobConfig(
        app={"work_dir": tmp_path / ".work"},
        semantic=SemanticConfig(enabled=True, max_chunk_blocks=10),
    )
    provider = _RelationProvider()
    first_paths = create_job_paths(cfg.app.work_dir, job_id="job-a")
    first = run_semantic_reconstruction(raw_ir, evidence, draft, cfg, first_paths, provider)
    first_calls = provider.calls
    second = run_semantic_reconstruction(
        raw_ir, evidence, draft, cfg, create_job_paths(cfg.app.work_dir, job_id="job-b"), provider
    )

    assert first_calls > 0
    assert provider.calls == first_calls
    assert first.bookir.model_dump() == second.bookir.model_dump()
    assert first.bookir.blocks[0].kind == "code"
    assert second.bookir.blocks[0].kind == "code"
    assert len(first.relation_audits) == 2
    assert len(second.relation_audits) == 2
    assert [audit.model_dump() for audit in first.relation_audits] == [
        audit.model_dump() for audit in second.relation_audits
    ]
    assert sorted(audit.status for audit in second.relation_audits) == ["applied", "rejected"]

    from book2epub.ir.normalize import normalize_bookir

    normalized = normalize_bookir(first.bookir)
    render_result = run_conversion_m3(normalized, first_paths, cfg)
    package_result = run_conversion_m4(
        render_result,
        tmp_path / "relation.epub",
        first_paths,
        cfg,
    )
    assert package_result.epub_path.is_file()


def test_stage_callout_decision_and_group_relation_materialize_once(tmp_path: Path) -> None:
    raw_ir = BookIR(
        source=SourceDocument(page_count=1),
        blocks=[
            Paragraph(
                id="p1",
                sources=[SourceRef(page_idx=0, source_type="text")],
                inlines=[Text(text="Warning")],
            ),
            Paragraph(
                id="p2",
                sources=[SourceRef(page_idx=0, source_type="text")],
                inlines=[Text(text="Details")],
            ),
        ],
    )
    evidence = SemanticEvidenceBook(
        source_middle_sha256="middle-callout",
        raw_bookir_sha256="raw-callout",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                current_kind="paragraph",
                plain_text="Warning",
                allowed_targets=["callout_warning"],
            ),
            SemanticEvidenceBlock(
                block_id="p2",
                current_kind="paragraph",
                plain_text="Details",
            ),
        ],
    )
    draft = SemanticDraftBook(
        book_id="callout-book",
        blocks=[
            DraftBlock(block_id="p1", current_kind="paragraph", text_preview="Warning"),
            DraftBlock(block_id="p2", current_kind="paragraph", text_preview="Details"),
        ],
    )
    cfg = JobConfig(
        app={"work_dir": tmp_path / ".work"},
        semantic=SemanticConfig(enabled=True, max_chunk_blocks=10),
    )
    result = run_semantic_reconstruction(
        raw_ir,
        evidence,
        draft,
        cfg,
        create_job_paths(cfg.app.work_dir, job_id="callout-job"),
        _CalloutRelationProvider(),
    )
    assert len(result.bookir.blocks) == 1
    assert result.bookir.blocks[0].kind == "callout"
    assert result.bookir.blocks[0].subtype == "warning"  # type: ignore[union-attr]
    assert [child.id for child in result.bookir.blocks[0].blocks] == ["p1", "p2"]  # type: ignore[union-attr]


def _callout_safety_fixture(
    allowed_targets: list[str],
) -> tuple[BookIR, SemanticEvidenceBook, SemanticDraftBook]:
    blocks = [
        Paragraph(
            id=block_id,
            sources=[SourceRef(page_idx=0, source_type="text")],
            inlines=[Text(text=text)],
        )
        for block_id, text in [("p1", "Warning"), ("p2", "Details"), ("p3", "More")]
    ]
    raw_ir = BookIR(source=SourceDocument(page_count=1), blocks=blocks)
    evidence = SemanticEvidenceBook(
        source_middle_sha256="middle-callout-safety",
        raw_bookir_sha256="raw-callout-safety",
        blocks=[
            SemanticEvidenceBlock(
                block_id="p1",
                current_kind="paragraph",
                plain_text="Warning",
                allowed_targets=allowed_targets,
            ),
            SemanticEvidenceBlock(block_id="p2", current_kind="paragraph", plain_text="Details"),
            SemanticEvidenceBlock(block_id="p3", current_kind="paragraph", plain_text="More"),
        ],
    )
    draft = SemanticDraftBook(
        book_id="callout-safety-book",
        blocks=[
            DraftBlock(block_id=block_id, current_kind="paragraph", text_preview=text)
            for block_id, text in [("p1", "Warning"), ("p2", "Details"), ("p3", "More")]
        ],
    )
    return raw_ir, evidence, draft


def test_invalid_noncontiguous_relation_preserves_valid_standalone_callout(tmp_path: Path) -> None:
    raw_ir, evidence, draft = _callout_safety_fixture(["callout_warning"])
    cfg = JobConfig(
        app={"work_dir": tmp_path / ".work"},
        semantic=SemanticConfig(enabled=True, max_chunk_blocks=10),
    )
    result = run_semantic_reconstruction(
        raw_ir,
        evidence,
        draft,
        cfg,
        create_job_paths(cfg.app.work_dir, job_id="callout-noncontiguous"),
        _CalloutSafetyProvider(["p1", "p3"]),
    )
    assert [block.kind for block in result.bookir.blocks] == ["callout", "paragraph", "paragraph"]
    assert result.bookir.blocks[0].id == "semantic-callout-p1"
    assert result.bookir.blocks[0].blocks[0].id == "p1"  # type: ignore[union-attr]
    assert result.relation_audits[0].status == "rejected"


def test_callout_relation_cannot_bypass_allowed_target_gate(tmp_path: Path) -> None:
    raw_ir, evidence, draft = _callout_safety_fixture([])
    cfg = JobConfig(
        app={"work_dir": tmp_path / ".work"},
        semantic=SemanticConfig(enabled=True, max_chunk_blocks=10),
    )
    result = run_semantic_reconstruction(
        raw_ir,
        evidence,
        draft,
        cfg,
        create_job_paths(cfg.app.work_dir, job_id="callout-invalid-target"),
        _CalloutSafetyProvider(["p1", "p2"]),
    )
    assert [block.kind for block in result.bookir.blocks] == ["paragraph", "paragraph", "paragraph"]
    assert any(a.status == "rejected_invalid_target" for a in result.audits)
    assert result.relation_audits[0].status == "rejected"
