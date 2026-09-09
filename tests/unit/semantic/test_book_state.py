"""Unit tests for BookState deterministic initialization, observation merging,
and hard limits (Appendix J)."""

from book2epub.ir.models import CodeBlock, Heading, Paragraph, Text
from book2epub.semantic.book_state import (
    BookState,
    BookStateObservationBatch,
    DomainTermObservation,
    HeadingPatternObservation,
    PreformattedConventionObservation,
    compute_initial_book_state,
    get_book_state_prompt_view,
    merge_book_state_observations,
)
from book2epub.semantic.models import SemanticEvidenceBlock


def test_compute_initial_book_state() -> None:
    h1 = Heading(id="h1", level=1, inlines=[Text(text="第1章 はじめに")])
    h2 = Heading(id="h2", level=2, inlines=[Text(text="1.1 概要")])
    code1 = CodeBlock(id="c1", text="print('hi')", language="python")
    code2 = CodeBlock(id="c2", text="SELECT 1;", language="sql")
    p = Paragraph(id="p1", inlines=[Text(text="Normal prose.")])

    state = compute_initial_book_state([h1, h2, code1, code2, p])

    assert "python" in state.confirmed_code_languages
    assert "sql" in state.confirmed_code_languages
    assert any(hp.numbering_family == "chapter_japanese" for hp in state.heading_patterns)
    assert any(hp.numbering_family == "decimal" for hp in state.heading_patterns)


def test_merge_book_state_verbatim_domain_term() -> None:
    state = BookState(schema_version="1.0")
    ev1 = SemanticEvidenceBlock(
        block_id="b1",
        plain_text="The fork() system call creates a new process with PID.",
        content_sha256="h1",
    )
    evidence_lookup = {"b1": ev1}

    # Observation 1: verbatim term "fork()"
    # Observation 2: hallucinated term "quantum_hypervisor" not in b1
    obs_batch = BookStateObservationBatch(
        schema_version="1.0",
        chunk_id="chk-1",
        domain_terms=[
            DomainTermObservation(term="fork()", source_block_id="b1", confidence=0.95),
            DomainTermObservation(term="quantum_hypervisor", source_block_id="b1", confidence=0.99),
        ],
    )

    merged = merge_book_state_observations(state, obs_batch, evidence_lookup)

    # fork() must be merged
    assert any(dt.normalized_key == "fork()" for dt in merged.domain_terms)
    # quantum_hypervisor must be discarded because it's not present verbatim in b1
    assert not any(dt.normalized_key == "quantum_hypervisor" for dt in merged.domain_terms)


def test_merge_book_state_conventions_and_limits() -> None:
    state = BookState(schema_version="1.0")
    evidence_lookup: dict[str, SemanticEvidenceBlock] = {}

    obs_batch = BookStateObservationBatch(
        schema_version="1.0",
        chunk_id="chk-1",
        heading_patterns=[
            HeadingPatternObservation(
                numbering_family="decimal",
                likely_level=2,
                example_block_ids=["h1", "h2"],
                confidence=0.90,
            )
        ],
        preformatted_conventions=[
            PreformattedConventionObservation(
                subtype="terminal_output",
                language_or_shell="bash",
                example_block_ids=["c1"],
                confidence=0.88,
            )
        ],
    )

    merged = merge_book_state_observations(state, obs_batch, evidence_lookup)
    assert len(merged.heading_patterns) == 1
    assert merged.heading_patterns[0].numbering_family == "decimal"
    assert len(merged.preformatted_conventions) == 1
    assert merged.preformatted_conventions[0].subtype == "terminal_output"

    # Verify prompt view can be generated
    prompt_view = get_book_state_prompt_view(merged)
    assert "heading_patterns" in prompt_view
    assert "preformatted_conventions" in prompt_view
