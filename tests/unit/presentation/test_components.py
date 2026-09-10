"""Unit tests for ComponentDocumentRenderer and legacy compatibility bridge (M10)."""

import pytest

from book2epub.ir.assets import AssetRegistry
from book2epub.ir.models import (
    BlockQuote,
    Callout,
    CodeBlock,
    DefinitionItem,
    DefinitionList,
    ExampleBlock,
    Heading,
    Paragraph,
    PreformattedBlock,
    Text,
)
from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE
from book2epub.render.components import ComponentDocumentRenderer
from book2epub.render.xhtml import DocumentRenderer


def test_component_document_renderer_structure() -> None:
    """Verify ComponentDocumentRenderer emits semantic HTML elements with profile classes."""
    registry = AssetRegistry()
    renderer = ComponentDocumentRenderer(
        doc_href="text/part-0001.xhtml",
        doc_id="part-0001",
        title="Test Doc",
        language="ja",
        registry=registry,
        profile=DEFAULT_ENHANCED_PROFILE,
    )

    blocks = [
        Heading(id="b1", level=1, inlines=[Text(text="Chapter 1")]),
        Heading(id="b2", level=2, inlines=[Text(text="Section 1.1")]),
        Paragraph(id="b3", inlines=[Text(text="First paragraph text.")]),
        CodeBlock(id="b4", text="let x = 1;", language="rust"),
        PreformattedBlock(id="b5", text="$ cargo run\nDone.", subtype="terminal_output"),
        Callout(
            id="b6",
            subtype="warning",
            blocks=[Paragraph(id="b6-p", inlines=[Text(text="Be careful!")])],
        ),
        DefinitionList(
            id="b7",
            items=[
                DefinitionItem(
                    term=[Text(text="Term 1")],
                    definitions=[[Text(text="Definition 1")]],
                )
            ],
        ),
        BlockQuote(
            id="b8",
            blocks=[Paragraph(id="b8-p", inlines=[Text(text="Quote text")])],
        ),
        ExampleBlock(
            id="b9",
            blocks=[Paragraph(id="b9-p", inlines=[Text(text="Example contents")])],
        ),
    ]

    for blk in blocks:
        renderer.render_block(blk)

    xhtml_bytes = renderer.serialize()
    xhtml_text = xhtml_bytes.decode("utf-8")

    # 1. Heading structure
    assert '<h1 id="h-1-chapter-1" class="heading heading-1">Chapter 1</h1>' in xhtml_text
    assert '<h2 id="h-2-section-1-1" class="heading heading-2">Section 1.1</h2>' in xhtml_text

    # 2. Paragraph
    assert "<p>First paragraph text.</p>" in xhtml_text

    # 3. Source code and terminal distinctions
    assert '<pre class="preformatted source-code">' in xhtml_text
    assert '<code class="language-rust">let x = 1;</code>' in xhtml_text
    assert '<pre class="preformatted terminal-output">' in xhtml_text
    assert "<code>$ cargo run\nDone.</code>" in xhtml_text

    # 4. Callout aside with subtype class
    assert '<aside class="callout callout-warning">' in xhtml_text

    # 5. Definition list dl/dt/dd
    assert '<dl class="def-list">' in xhtml_text
    assert "<dt>Term 1</dt>" in xhtml_text
    assert "<dd>Definition 1</dd>" in xhtml_text

    # 6. BlockQuote
    assert '<blockquote class="quote quote-accent_left">' in xhtml_text

    # 7. Example container
    assert '<section class="example">' in xhtml_text

    # 8. Absolute prohibition on inline styles
    assert 'style="' not in xhtml_text

    # 9. Component counts recorded
    assert renderer.component_counts["heading"] == 2
    assert renderer.component_counts["paragraph"] == 4
    assert renderer.component_counts["code_block"] == 1
    assert renderer.component_counts["preformatted_terminal_output"] == 1
    assert renderer.component_counts["callout_warning"] == 1
    assert renderer.component_counts["definition_list"] == 1


def test_terminal_remains_text_not_table() -> None:
    """Verify terminal output is rendered as pre/code text and never rasterized or tabulated."""
    registry = AssetRegistry()
    renderer = ComponentDocumentRenderer(
        doc_href="text/part-0001.xhtml",
        doc_id="part-0001",
        title="Terminal Test",
        language="ja",
        registry=registry,
        profile=DEFAULT_ENHANCED_PROFILE,
    )
    blk = PreformattedBlock(
        id="term-01",
        text="root@server:~# systemctl status\nactive (running)",
        subtype="terminal_session",
    )
    renderer.render_block(blk)
    text = renderer.serialize().decode("utf-8")

    assert "<table" not in text
    assert "<img" not in text
    assert "systemctl status" in text
    assert '<pre class="preformatted terminal-session">' in text


@pytest.mark.parametrize(
    "subtype",
    [
        "source_code",
        "shell_command",
        "terminal_output",
        "terminal_session",
        "repl_session",
        "log_output",
        "config_file",
        "generic_preformatted",
    ],
)
def test_component_counts_preserve_every_canonical_preformatted_subtype(subtype: str) -> None:
    renderer = ComponentDocumentRenderer(
        doc_href="text/part-0001.xhtml",
        doc_id="part-0001",
        title="Subtype Test",
        language="en",
        registry=AssetRegistry(),
        profile=DEFAULT_ENHANCED_PROFILE,
    )
    renderer.render_block(PreformattedBlock(id=f"pre-{subtype}", text="x", subtype=subtype))

    assert renderer.component_counts[f"preformatted_{subtype}"] == 1


def test_legacy_bridge_compatibility() -> None:
    """Verify legacy DocumentRenderer renders new M8/M10 blocks via semantic compatibility bridge.
    """
    registry = AssetRegistry()
    legacy_renderer = DocumentRenderer(
        doc_href="text/part-0001.xhtml",
        doc_id="part-0001",
        title="Legacy Test",
        language="ja",
        registry=registry,
    )

    blocks = [
        PreformattedBlock(id="term-1", text="$ echo hello", subtype="terminal_output"),
        Callout(
            id="cal-1",
            subtype="tip",
            blocks=[Paragraph(id="cal-1-p", inlines=[Text(text="Tip text")])],
        ),
        DefinitionList(
            id="def-1",
            items=[
                DefinitionItem(
                    term=[Text(text="Key")],
                    definitions=[[Text(text="Value")]],
                )
            ],
        ),
    ]

    for blk in blocks:
        legacy_renderer.render_block(blk)

    text = legacy_renderer.serialize().decode("utf-8")
    # Generic pre without enhanced classes
    assert "<pre>" in text
    assert "<code>$ echo hello</code>" in text
    # Conservative aside without new theme dependency
    assert '<aside class="aside aside-tip">' in text
    assert "<p>Tip text</p>" in text
    # Conservative dl/dt/dd
    assert "<dl>" in text
    assert "<dt>Key</dt>" in text
    assert "<dd>Value</dd>" in text
