"""Regression tests for dynamic BookState propagation through Pass B."""

import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from book2epub.config import JobConfig, SemanticConfig
from book2epub.ir.models import BookIR, Paragraph, SourceDocument, Text
from book2epub.paths import create_job_paths
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.semantic.book_state import BookStateObservationBatch, DomainTermObservation
from book2epub.semantic.decisions import SemanticDecisionBatch
from book2epub.semantic.models import (
    DraftBlock,
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
)
from book2epub.semantic.stage import run_semantic_reconstruction
from book2epub.semantic.structure import StructureDecisionBatch

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


class _StateCapturingProvider:
    name = "mock-provider"
    model = "mock-model"

    def __init__(self) -> None:
        self.pass_b_prompts: list[str] = []
        self.pass_b_calls = 0

    def infer(
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        chunk_id = re.search(r"CHUNK_ID: (\S+)", request.user_text)
        assert chunk_id is not None
        if response_model == StructureDecisionBatch:
            batch: BaseModel = StructureDecisionBatch(chunk_id=chunk_id.group(1))
        else:
            self.pass_b_calls += 1
            self.pass_b_prompts.append(request.user_text)
            observations = []
            if self.pass_b_calls == 1:
                observations = [
                    BookStateObservationBatch(
                        chunk_id=chunk_id.group(1),
                        domain_terms=[
                            DomainTermObservation(
                                term="TERM", source_block_id="b1", confidence=0.95
                            )
                        ],
                    )
                ]
            batch = SemanticDecisionBatch(
                chunk_id=chunk_id.group(1), observations=observations
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


def test_book_state_observation_reaches_next_chunk_prompt(tmp_path: Path) -> None:
    raw_ir = BookIR(
        source=SourceDocument(page_count=1),
        blocks=[
            Paragraph(id="b1", inlines=[Text(text="TERM appears here")]),
            Paragraph(id="b2", inlines=[Text(text="later paragraph")]),
        ],
    )
    evidence = SemanticEvidenceBook(
        source_middle_sha256="middle",
        raw_bookir_sha256="raw",
        blocks=[
            SemanticEvidenceBlock(block_id="b1", plain_text="TERM appears here"),
            SemanticEvidenceBlock(block_id="b2", plain_text="later paragraph"),
        ],
    )
    draft = SemanticDraftBook(
        book_id="book",
        blocks=[
            DraftBlock(block_id="b1", current_kind="paragraph", text_preview="TERM appears here"),
            DraftBlock(block_id="b2", current_kind="paragraph", text_preview="later paragraph"),
        ],
    )
    cfg = JobConfig(
        app={"work_dir": tmp_path / ".work", "force_semantic": True},
        semantic=SemanticConfig(
            enabled=True,
            max_chunk_blocks=1,
            max_chunk_chars=10000,
            overlap_blocks=0,
        ),
    )
    provider = _StateCapturingProvider()
    result = run_semantic_reconstruction(
        raw_ir,
        evidence,
        draft,
        cfg,
        create_job_paths(cfg.app.work_dir, job_id="semantic-state"),
        provider=provider,
    )

    assert provider.pass_b_calls == 2
    assert '"term"' not in provider.pass_b_prompts[0]
    assert '"term"' in provider.pass_b_prompts[1]
    assert any(term.normalized_key == "term" for term in result.book_state.domain_terms)
