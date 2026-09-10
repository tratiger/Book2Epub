"""Document-level BookState representation, deterministic statistics,
and bounded observation merging (Appendix J)."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from book2epub.ir.models import (
    Block,
    CodeBlock,
    ExampleBlock,
    ExerciseBlock,
    Figure,
    Heading,
    Table,
)
from book2epub.semantic.models import SemanticEvidenceBlock


class HeadingPattern(BaseModel):
    """Observed heading numbering pattern across chapters/sections."""

    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    numbering_family: Literal[
        "chapter_japanese",
        "chapter_english",
        "decimal",
        "roman",
        "unnumbered",
        "other",
    ]
    example_block_ids: list[str] = Field(default_factory=list)
    likely_level: int = Field(ge=1, le=6)
    confidence: float = Field(ge=0.0, le=1.0)


class PreformattedConvention(BaseModel):
    """Observed preformatted subtype and language conventions."""

    model_config = ConfigDict(extra="forbid")

    convention_id: str
    subtype: Literal[
        "source_code",
        "shell_command",
        "terminal_output",
        "terminal_session",
        "repl_session",
        "log_output",
        "config_file",
    ]
    language_or_shell: str | None = None
    example_block_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class CalloutConvention(BaseModel):
    """Observed callout/note patterns with textual prefix cues."""

    model_config = ConfigDict(extra="forbid")

    convention_id: str
    subtype: Literal["note", "tip", "warning", "caution", "important", "sidebar"]
    textual_cues: list[str] = Field(default_factory=list)
    example_block_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class NumberingConvention(BaseModel):
    """Observed numbering conventions for figures, tables, and code listings."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["figure", "table", "listing", "example", "exercise"]
    family: Literal["chapter-hyphen", "chapter-dot", "global", "roman", "other"]
    example_labels: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class DomainTerm(BaseModel):
    """Normalized technical term or API symbol observed verbatim in source."""

    model_config = ConfigDict(extra="forbid")

    normalized_key: str
    source_forms: list[str] = Field(default_factory=list)
    example_block_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class BookState(BaseModel):
    """Bounded, document-level state tracking recurring conventions (Appendix J2)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    heading_patterns: list[HeadingPattern] = Field(default_factory=list)
    preformatted_conventions: list[PreformattedConvention] = Field(default_factory=list)
    callout_conventions: list[CalloutConvention] = Field(default_factory=list)
    numbering_conventions: list[NumberingConvention] = Field(default_factory=list)
    domain_terms: list[DomainTerm] = Field(default_factory=list)
    confirmed_code_languages: list[str] = Field(default_factory=list)
    revision: int = 0


# Observation Models returned by Provider (Appendix J4)
class HeadingPatternObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numbering_family: Literal[
        "chapter_japanese",
        "chapter_english",
        "decimal",
        "roman",
        "unnumbered",
        "other",
    ]
    likely_level: int = Field(ge=1, le=6)
    example_block_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class PreformattedConventionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtype: Literal[
        "source_code",
        "shell_command",
        "terminal_output",
        "terminal_session",
        "repl_session",
        "log_output",
        "config_file",
    ]
    language_or_shell: str | None = None
    example_block_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CalloutConventionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtype: Literal["note", "tip", "warning", "caution", "important", "sidebar"]
    textual_cues: list[str] = Field(default_factory=list)
    example_block_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class NumberingConventionExample(BaseModel):
    """Source-grounded numbering example returned by the provider."""

    model_config = ConfigDict(extra="forbid")

    block_id: str
    label: str = Field(min_length=1)


class NumberingConventionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["figure", "table", "listing", "example", "exercise"]
    family: Literal["chapter-hyphen", "chapter-dot", "global", "roman", "other"]
    examples: list[NumberingConventionExample] = Field(default_factory=list)
    # Kept for backward-compatible provider fixtures. Runtime validation only
    # accepts labels that can be matched verbatim to a scoped source block.
    example_labels: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class DomainTermObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str
    source_block_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class BookStateObservationBatch(BaseModel):
    """Batch of bounded observations returned during document-level passes."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    chunk_id: str
    heading_patterns: list[HeadingPatternObservation] = Field(default_factory=list)
    preformatted_conventions: list[PreformattedConventionObservation] = Field(
        default_factory=list
    )
    callout_conventions: list[CalloutConventionObservation] = Field(default_factory=list)
    numbering_conventions: list[NumberingConventionObservation] = Field(default_factory=list)
    domain_terms: list[DomainTermObservation] = Field(default_factory=list)


def detect_numbering_family(
    text: str,
) -> tuple[str, Literal["chapter-hyphen", "chapter-dot", "global", "roman", "other"]]:
    """Detect numbering family from label text (e.g. '1-2', '3.4', '15')."""
    if re.search(r"(?<!\d)\d+-\d+(?!\d)", text):
        return text, "chapter-hyphen"
    if re.search(r"(?<!\d)\d+\.\d+(?!\d)", text):
        return text, "chapter-dot"
    if re.search(r"(?<!\d)\d+(?!\d)", text):
        return text, "global"
    if re.search(r"(?<![A-Za-z])[IVXLCDM]+(?![A-Za-z])", text, re.IGNORECASE):
        return text, "roman"
    return text, "other"


def _observe_numbering(
    kind: str,
    label_text: str,
    numbering_map: dict[tuple[str, str], list[str]],
) -> None:
    """
    Observe a verbatim caption/label text and record its numbering family.
    Stores only verbatim labels — never generates numbers.
    """
    label_stripped = label_text.strip()
    if not label_stripped:
        return
    _, family = detect_numbering_family(label_stripped)
    key = (kind, family)
    if key not in numbering_map:
        numbering_map[key] = []
    if len(numbering_map[key]) < 8 and label_stripped not in numbering_map[key]:
        numbering_map[key].append(label_stripped)


def compute_initial_book_state(
    blocks: list[Block],
    evidence_blocks: list[SemanticEvidenceBlock] | None = None,
) -> BookState:
    """
    Compute initial deterministic BookState fields without an LLM (M8 spec Section 9).

    Numbering conventions are observed from verbatim source caption/label text only.
    Numbers are never generated.
    """
    from book2epub.semantic.apply import extract_inlines_text

    code_languages: set[str] = set()
    # (kind, family) -> list[verbatim label strings]
    numbering_map: dict[tuple[str, str], list[str]] = {}
    heading_pattern_map: dict[tuple[str, int], list[str]] = {}

    for blk in blocks:
        if isinstance(blk, CodeBlock) and blk.language:
            lang_clean = blk.language.strip().lower()
            if lang_clean:
                code_languages.add(lang_clean)

        if isinstance(blk, Heading):
            text = extract_inlines_text(blk.inlines).strip()
            lvl_raw = blk.level if blk.level is not None else 1
            level = max(1, min(6, lvl_raw))
            if re.match(r"^第[0-9一二三四五六七八九十百]+[章節]", text):
                fam = "chapter_japanese"
            elif re.match(r"^(?:Chapter|Section|Part)\s+\d+", text, re.IGNORECASE):
                fam = "chapter_english"
            elif re.match(r"^\d+(\.\d+)*\b", text):
                fam = "decimal"
            elif re.match(r"^[IVXLCDM]+\b", text):
                fam = "roman"
            else:
                fam = "other"

            key = (fam, level)
            if key not in heading_pattern_map:
                heading_pattern_map[key] = []
            if len(heading_pattern_map[key]) < 8:
                heading_pattern_map[key].append(blk.id)

        elif isinstance(blk, Figure):
            # Caption prefix (e.g. "Figure 1-2: ..." or "図1.3 ...")
            if blk.caption:
                cap_text = extract_inlines_text(blk.caption)
                _observe_numbering("figure", cap_text, numbering_map)

        elif isinstance(blk, Table):
            # Caption prefix (e.g. "Table 3.1: ..." or "表2-5 ...")
            if blk.caption:
                cap_text = extract_inlines_text(blk.caption)
                _observe_numbering("table", cap_text, numbering_map)

        elif isinstance(blk, CodeBlock):
            # Caption prefix for listings (e.g. "Listing 2-3: ..." or "リスト1.4 ...")
            if blk.caption:
                cap_text = extract_inlines_text(blk.caption)
                _observe_numbering("listing", cap_text, numbering_map)

        elif isinstance(blk, ExampleBlock):
            # Label prefix (e.g. "Example 5.2" or "例1-3")
            if blk.label:
                lbl_text = extract_inlines_text(blk.label)
                _observe_numbering("example", lbl_text, numbering_map)

        elif isinstance(blk, ExerciseBlock):
            # Label prefix (e.g. "Exercise 4.1" or "練習1-2")
            if blk.label:
                lbl_text = extract_inlines_text(blk.label)
                _observe_numbering("exercise", lbl_text, numbering_map)

    heading_patterns: list[HeadingPattern] = []
    for (fam, lvl), ex_ids in heading_pattern_map.items():
        heading_patterns.append(
            HeadingPattern(
                pattern_id=f"hp-{fam}-{lvl}",
                numbering_family=fam,  # type: ignore[arg-type]
                likely_level=lvl,
                example_block_ids=ex_ids[:8],
                confidence=0.9,
            )
        )

    numbering_conventions: list[NumberingConvention] = []
    for (kind, fam), labels in numbering_map.items():
        numbering_conventions.append(
            NumberingConvention(
                kind=kind,  # type: ignore[arg-type]
                family=fam,  # type: ignore[arg-type]
                example_labels=labels[:8],
                confidence=0.9,
            )
        )

    # Sort code languages deterministically
    confirmed_langs = sorted(list(code_languages))[:16]

    return BookState(
        schema_version="1.0",
        heading_patterns=heading_patterns[:16],
        numbering_conventions=numbering_conventions[:12],
        confirmed_code_languages=confirmed_langs,
        revision=0,
    )


def merge_book_state_observations(
    state: BookState,
    obs: BookStateObservationBatch,
    evidence_lookup: dict[str, SemanticEvidenceBlock],
) -> BookState:
    """
    Deterministically merge observations into BookState enforcing hard limits
    and verbatim evidence rules (Appendix J3, J5).
    """
    updated = state.model_copy(deep=True)
    updated.revision += 1
    known_block_ids = set(evidence_lookup)

    def valid_examples(ids: list[str]) -> list[str]:
        # Empty evidence maps are useful in isolated unit tests; production
        # merges always receive the complete evidence lookup.
        if not known_block_ids:
            return ids[:8]
        return [block_id for block_id in ids if block_id in known_block_ids][:8]

    def source_grounded_numbering_labels(num_obs: NumberingConventionObservation) -> list[str]:
        labels_by_block = {example.block_id: example.label for example in num_obs.examples}
        labels = list(labels_by_block.values()) + list(num_obs.example_labels)
        if not known_block_ids:
            return labels[:8]

        kind_aliases = {
            "figure": {"figure"},
            "table": {"table"},
            "listing": {"code", "preformatted"},
            "example": {"example"},
            "exercise": {"exercise"},
        }
        allowed_kinds = kind_aliases[num_obs.kind]
        grounded: list[str] = []
        for label in labels:
            explicit_example = next(
                (example for example in num_obs.examples if example.label == label),
                None,
            )
            matching_blocks = (
                [evidence_lookup.get(explicit_example.block_id)]
                if explicit_example is not None
                else list(evidence_lookup.values())
            )
            if any(
                evidence is not None
                and evidence.current_kind in allowed_kinds
                and label
                in " ".join(
                    part
                    for part in (
                        evidence.plain_text,
                        evidence.caption_text,
                        evidence.caption_plain_text,
                    )
                    if part
                )
                for evidence in matching_blocks
            ):
                if label not in grounded:
                    grounded.append(label)
        return grounded[:8]

    # 1. Merge heading patterns (merge on family + likely_level)
    for hp_obs in obs.heading_patterns:
        existing = next(
            (
                p
                for p in updated.heading_patterns
                if p.numbering_family == hp_obs.numbering_family
                and p.likely_level == hp_obs.likely_level
            ),
            None,
        )
        if existing:
            # Weighted average confidence
            existing.confidence = round((existing.confidence + hp_obs.confidence) / 2.0, 3)
            for ex in valid_examples(hp_obs.example_block_ids):
                if ex not in existing.example_block_ids and len(existing.example_block_ids) < 8:
                    existing.example_block_ids.append(ex)
        else:
            if len(updated.heading_patterns) < 16:
                updated.heading_patterns.append(
                    HeadingPattern(
                        pattern_id=f"hp-{hp_obs.numbering_family}-{hp_obs.likely_level}",
                        numbering_family=hp_obs.numbering_family,
                        likely_level=hp_obs.likely_level,
                        example_block_ids=valid_examples(hp_obs.example_block_ids),
                        confidence=hp_obs.confidence,
                    )
                )

    # 2. Merge preformatted conventions (merge on subtype + language_or_shell)
    for pf_obs in obs.preformatted_conventions:
        norm_lang = pf_obs.language_or_shell.lower().strip() if pf_obs.language_or_shell else None
        existing_pf = next(
            (
                p
                for p in updated.preformatted_conventions
                if p.subtype == pf_obs.subtype and p.language_or_shell == norm_lang
            ),
            None,
        )
        if existing_pf:
            existing_pf.confidence = round((existing_pf.confidence + pf_obs.confidence) / 2.0, 3)
            for ex in valid_examples(pf_obs.example_block_ids):
                if (
                    ex not in existing_pf.example_block_ids
                    and len(existing_pf.example_block_ids) < 8
                ):
                    existing_pf.example_block_ids.append(ex)
        else:
            if len(updated.preformatted_conventions) < 20:
                updated.preformatted_conventions.append(
                    PreformattedConvention(
                        convention_id=f"pfc-{pf_obs.subtype}-{norm_lang or 'none'}",
                        subtype=pf_obs.subtype,
                        language_or_shell=norm_lang,
                        example_block_ids=valid_examples(pf_obs.example_block_ids),
                        confidence=pf_obs.confidence,
                    )
                )

    # 3. Merge callout conventions (merge on subtype)
    for co_obs in obs.callout_conventions:
        existing_co = next(
            (c for c in updated.callout_conventions if c.subtype == co_obs.subtype),
            None,
        )
        if existing_co:
            existing_co.confidence = round((existing_co.confidence + co_obs.confidence) / 2.0, 3)
            for cue in co_obs.textual_cues:
                if cue not in existing_co.textual_cues and len(existing_co.textual_cues) < 8:
                    existing_co.textual_cues.append(cue)
            for ex in valid_examples(co_obs.example_block_ids):
                if (
                    ex not in existing_co.example_block_ids
                    and len(existing_co.example_block_ids) < 8
                ):
                    existing_co.example_block_ids.append(ex)
        else:
            if len(updated.callout_conventions) < 12:
                updated.callout_conventions.append(
                    CalloutConvention(
                        convention_id=f"coc-{co_obs.subtype}",
                        subtype=co_obs.subtype,
                        textual_cues=co_obs.textual_cues[:8],
                        example_block_ids=valid_examples(co_obs.example_block_ids),
                        confidence=co_obs.confidence,
                    )
                )

    # 4. Merge numbering conventions on kind + family. Labels are kept exactly
    # as supplied by source evidence; no numbering is generated here.
    for num_obs in obs.numbering_conventions:
        labels = source_grounded_numbering_labels(num_obs)
        deterministic_families = {detect_numbering_family(label)[1] for label in labels}
        if len(deterministic_families) != 1:
            continue
        deterministic_family = next(iter(deterministic_families))
        existing_num = next(
            (
                item
                for item in updated.numbering_conventions
                if item.kind == num_obs.kind and item.family == deterministic_family
            ),
            None,
        )
        if existing_num:
            existing_num.confidence = round(
                (existing_num.confidence + num_obs.confidence) / 2.0, 3
            )
            for label in labels:
                if (
                    label not in existing_num.example_labels
                    and len(existing_num.example_labels) < 8
                ):
                    existing_num.example_labels.append(label)
        elif len(updated.numbering_conventions) < 12:
            updated.numbering_conventions.append(
                NumberingConvention(
                    kind=num_obs.kind,
                    family=deterministic_family,
                    example_labels=labels[:8],
                    confidence=num_obs.confidence,
                )
            )

    # 5. Merge domain terms (enforcing verbatim check in source block)
    for dt_obs in obs.domain_terms:
        term = dt_obs.term.strip()
        if not term:
            continue
        # Verbatim check against evidence block (M8 Section 9 / Appendix J5)
        ev_blk = evidence_lookup.get(dt_obs.source_block_id)
        if not ev_blk or (ev_blk.plain_text and term not in ev_blk.plain_text):
            # Term not present verbatim; discard observation
            continue

        norm_key = term.lower()
        existing_dt = next(
            (d for d in updated.domain_terms if d.normalized_key == norm_key),
            None,
        )
        if existing_dt:
            if term not in existing_dt.source_forms and len(existing_dt.source_forms) < 8:
                existing_dt.source_forms.append(term)
            if (
                dt_obs.source_block_id not in existing_dt.example_block_ids
                and len(existing_dt.example_block_ids) < 8
            ):
                existing_dt.example_block_ids.append(dt_obs.source_block_id)
        else:
            if len(updated.domain_terms) < 80:
                updated.domain_terms.append(
                    DomainTerm(
                        normalized_key=norm_key,
                        source_forms=[term],
                        example_block_ids=[dt_obs.source_block_id],
                        confidence=dt_obs.confidence,
                    )
                )

    return updated


def get_book_state_prompt_view(state: BookState) -> dict[str, Any]:
    """
    Produce a compact, JSON-serializable prompt view of BookState (Appendix J9).
    """
    return {
        "confirmed_code_languages": state.confirmed_code_languages[:16],
        "heading_patterns": [
            {
                "family": hp.numbering_family,
                "level": hp.likely_level,
                "confidence": hp.confidence,
            }
            for hp in state.heading_patterns[:8]
        ],
        "preformatted_conventions": [
            {
                "subtype": pc.subtype,
                "language": pc.language_or_shell,
            }
            for pc in state.preformatted_conventions[:10]
        ],
        "callout_conventions": [
            {
                "subtype": cc.subtype,
                "cues": cc.textual_cues[:4],
            }
            for cc in state.callout_conventions[:6]
        ],
        "numbering_conventions": [
            {
                "kind": nc.kind,
                "family": nc.family,
                "example_labels": nc.example_labels[:4],
            }
            for nc in state.numbering_conventions[:12]
        ],
        "domain_terms": [t.normalized_key for t in state.domain_terms[:20]],
    }
