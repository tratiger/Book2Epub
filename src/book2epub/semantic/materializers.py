"""Canonical Pass B materializer registry.

The evidence builder and application layer deliberately share this registry.
That keeps an advertised ``allowed_targets`` value backed by a deterministic
materializer, rather than by a broad semantic whitelist.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from book2epub.ir.models import (
    Aside,
    Block,
    BlockQuote,
    Callout,
    Chart,
    CodeBlock,
    DisplayMath,
    Figure,
    Heading,
    Inline,
    ListBlock,
    Paragraph,
    PreformattedBlock,
    Table,
    Text,
)
from book2epub.semantic.models import SemanticEvidenceBlock, SemanticTarget
from book2epub.semantic.reconcile import ReconciledSemanticDecision

MaterializerApply = Callable[
    [Block, SemanticEvidenceBlock, ReconciledSemanticDecision], Block | list[Block]
]
MaterializerSupports = Callable[[Block, SemanticEvidenceBlock], bool]


@dataclass(frozen=True)
class SemanticMaterializer:
    target: SemanticTarget
    supports: MaterializerSupports
    apply: MaterializerApply


_PREFORMATTED_TARGETS: tuple[SemanticTarget, ...] = (
    "source_code",
    "shell_command",
    "terminal_output",
    "terminal_session",
    "repl_session",
    "log_output",
    "config_file",
    "generic_preformatted",
)
_CALLOUT_TARGETS: tuple[SemanticTarget, ...] = (
    "callout_note",
    "callout_tip",
    "callout_warning",
    "callout_caution",
    "callout_important",
    "sidebar",
)
_LIST_TARGETS: tuple[SemanticTarget, ...] = ("list", "unordered_list", "ordered_list")


def _inline_text(inlines: list[Inline]) -> str:
    parts: list[str] = []
    for inline in inlines:
        if isinstance(inline, Text):
            parts.append(inline.text)
        elif hasattr(inline, "children"):
            parts.append(_inline_text(inline.children))
        elif hasattr(inline, "latex"):
            parts.append(inline.latex)
        elif inline.kind == "line_break":
            parts.append("\n")
    return "".join(parts)


def _source_text(block: Block) -> str:
    if isinstance(block, (Paragraph, Heading, Aside)):
        return _inline_text(block.inlines)
    if isinstance(block, CodeBlock):
        return block.text
    if isinstance(block, PreformattedBlock):
        return block.text
    return ""


def _supports_identity(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, (Paragraph, Heading, Aside))


def _supports_heading(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, (Paragraph, Heading, Aside))


def _supports_table_identity(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, Table)


def _supports_display_math_identity(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, DisplayMath)


def _supports_figure_identity(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, Figure)


def _supports_chart_identity(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, Chart)


def _identity(
    block: Block, _evidence: SemanticEvidenceBlock, _decision: ReconciledSemanticDecision
) -> Block:
    return block.model_copy()


def _supports_preformatted(block: Block, evidence: SemanticEvidenceBlock) -> bool:
    if isinstance(block, (CodeBlock, PreformattedBlock)):
        return True
    if isinstance(block, Table):
        return bool(evidence.preformatted_text and evidence.preformatted_text.strip())
    if isinstance(block, (Paragraph, Heading, Aside)):
        return bool(
            evidence.preformatted_text
            and _source_text(block) == evidence.preformatted_text
        )
    return False


def _supports_callout(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    return isinstance(block, (Paragraph, Aside))


def _supports_list(block: Block, _evidence: SemanticEvidenceBlock) -> bool:
    if not isinstance(block, (Paragraph, Heading, Aside)):
        return False
    return len([line for line in _source_text(block).strip().splitlines() if line.strip()]) >= 2


def _supports_table(block: Block, evidence: SemanticEvidenceBlock) -> bool:
    return (
        isinstance(block, (Paragraph, Heading, Aside))
        and evidence.table_html_available
        and bool(evidence.table_html)
    )


def _to_paragraph(
    block: Block, _evidence: SemanticEvidenceBlock, _decision: ReconciledSemanticDecision
) -> Block:
    if isinstance(block, Paragraph):
        return block.model_copy()
    if isinstance(block, (Heading, Aside)):
        return Paragraph(id=block.id, sources=list(block.sources), inlines=list(block.inlines))
    raise ValueError("paragraph materializer received an unsupported source block")


def _to_heading(
    block: Block, _evidence: SemanticEvidenceBlock, decision: ReconciledSemanticDecision
) -> Block:
    if isinstance(block, Heading):
        return block.model_copy(update={"level": decision.heading_level or block.level or 1})
    if isinstance(block, (Paragraph, Aside)):
        return Heading(
            id=block.id,
            sources=list(block.sources),
            level=decision.heading_level or 1,
            inlines=list(block.inlines),
        )
    raise ValueError("heading materializer received an unsupported source block")


def _to_preformatted(
    block: Block, evidence: SemanticEvidenceBlock, decision: ReconciledSemanticDecision
) -> Block:
    target = decision.target
    if target not in _PREFORMATTED_TARGETS:
        raise ValueError("invalid preformatted target")
    text = evidence.preformatted_text if isinstance(block, Table) else _source_text(block)
    if isinstance(block, (Paragraph, Heading, Aside)):
        if evidence.preformatted_text is None or text != evidence.preformatted_text:
            raise ValueError("preformatted evidence does not preserve source text")
        text = evidence.preformatted_text
    if text is None:
        raise ValueError("missing preformatted evidence")
    subtype = cast(
        Literal[
            "source_code",
            "shell_command",
            "terminal_output",
            "terminal_session",
            "repl_session",
            "log_output",
            "config_file",
            "generic_preformatted",
        ],
        target,
    )
    if isinstance(block, (CodeBlock, PreformattedBlock)):
        return PreformattedBlock(
            id=block.id,
            sources=list(block.sources),
            subtype=subtype,
            text=text,
            language=block.language,
            caption=list(block.caption),
            footnotes=list(block.footnotes),
        )
    if isinstance(block, Table):
        return PreformattedBlock(
            id=block.id,
            sources=list(block.sources),
            subtype=subtype,
            text=text,
            caption=list(block.caption),
            footnotes=list(block.footnotes),
        )
    if isinstance(block, (Paragraph, Heading, Aside)):
        return PreformattedBlock(
            id=block.id,
            sources=list(block.sources),
            subtype=subtype,
            text=text,
        )
    raise ValueError("preformatted materializer received an unsupported source block")


def _to_callout(
    block: Block, _evidence: SemanticEvidenceBlock, decision: ReconciledSemanticDecision
) -> Block:
    subtype = (
        "sidebar"
        if decision.target == "sidebar"
        else decision.target.removeprefix("callout_")
    )
    if subtype not in {"note", "tip", "warning", "caution", "important", "sidebar"}:
        raise ValueError("invalid callout subtype")
    if not isinstance(block, (Paragraph, Aside)):
        raise ValueError("callout materializer received an unsupported source block")
    callout_subtype = cast(
        Literal["note", "tip", "warning", "caution", "important", "sidebar"],
        subtype,
    )
    return Callout(
        id=f"semantic-callout-{block.id}",
        sources=list(block.sources),
        subtype=callout_subtype,
        blocks=[block],
    )


def _to_block_quote(
    block: Block, _evidence: SemanticEvidenceBlock, _decision: ReconciledSemanticDecision
) -> Block:
    if not isinstance(block, (Paragraph, Aside)):
        raise ValueError("block quote materializer received an unsupported source block")
    return BlockQuote(
        id=f"semantic-block-quote-{block.id}",
        sources=list(block.sources),
        blocks=[block],
    )


def _to_list(
    block: Block, _evidence: SemanticEvidenceBlock, decision: ReconciledSemanticDecision
) -> Block:
    text = _source_text(block)
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError("list materializer requires at least two source lines")
    return ListBlock(
        id=block.id,
        sources=list(block.sources),
        ordered=decision.target == "ordered_list",
        items=[[Text(text=line)] for line in lines],
    )


def _to_table(
    block: Block, evidence: SemanticEvidenceBlock, _decision: ReconciledSemanticDecision
) -> Block:
    if not isinstance(block, (Paragraph, Heading, Aside)) or not evidence.table_html:
        raise ValueError("table materializer requires valid table HTML evidence")
    return Table(id=block.id, sources=list(block.sources), html=evidence.table_html)


def _build_registry() -> tuple[SemanticMaterializer, ...]:
    entries: list[SemanticMaterializer] = [
        SemanticMaterializer("paragraph", _supports_identity, _to_paragraph),
        SemanticMaterializer("heading", _supports_heading, _to_heading),
        SemanticMaterializer("table", _supports_table_identity, _identity),
        SemanticMaterializer("display_math", _supports_display_math_identity, _identity),
        SemanticMaterializer("figure", _supports_figure_identity, _identity),
        SemanticMaterializer("chart", _supports_chart_identity, _identity),
    ]
    entries.extend(
        SemanticMaterializer(target, _supports_preformatted, _to_preformatted)
        for target in _PREFORMATTED_TARGETS
    )
    entries.extend(
        SemanticMaterializer(target, _supports_callout, _to_callout)
        for target in _CALLOUT_TARGETS
    )
    entries.extend(
        SemanticMaterializer(target, _supports_list, _to_list) for target in _LIST_TARGETS
    )
    entries.extend(
        [
            SemanticMaterializer("quote", _supports_callout, _to_block_quote),
            SemanticMaterializer("block_quote", _supports_callout, _to_block_quote),
            SemanticMaterializer("table", _supports_table, _to_table),
        ]
    )
    return tuple(entries)


MATERIALIZER_REGISTRY: tuple[SemanticMaterializer, ...] = _build_registry()


def materializer_for(
    block: Block, target: str, evidence: SemanticEvidenceBlock
) -> SemanticMaterializer | None:
    for materializer in MATERIALIZER_REGISTRY:
        if materializer.target == target and materializer.supports(block, evidence):
            return materializer
    return None


def allowed_targets_for(
    block: Block, evidence: SemanticEvidenceBlock
) -> list[SemanticTarget]:
    targets: list[SemanticTarget] = ["keep", "keep_original"]
    targets.extend(
        materializer.target
        for materializer in MATERIALIZER_REGISTRY
        if materializer.supports(block, evidence)
    )
    return list(dict.fromkeys(targets))


__all__ = [
    "MATERIALIZER_REGISTRY",
    "SemanticMaterializer",
    "allowed_targets_for",
    "materializer_for",
]
