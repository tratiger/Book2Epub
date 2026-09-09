"""Preformatted and code block component rendering for EPUB 3.3 (M10/Appendix L6)."""

from collections.abc import Callable, Sequence

from lxml import etree

from book2epub.ir.models import CodeBlock, Inline, PreformattedBlock

from .base import LANG_PATTERN, NS_XHTML

SUBTYPE_TO_CLASS = {
    "source_code": "source-code",
    "shell_command": "shell-command",
    "terminal_output": "terminal-output",
    "terminal_session": "terminal-session",
    "repl_session": "repl-session",
    "log_output": "log-output",
    "config_file": "config-file",
    "generic": "generic-preformatted",
}


def render_code_block(
    parent: etree._Element,
    block: CodeBlock,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render a CodeBlock to semantic XHTML."""
    lang_attr = ""
    if block.language:
        clean_lang = LANG_PATTERN.sub("", block.language.lower())
        if clean_lang:
            lang_attr = f"language-{clean_lang}"

    has_caption = bool(block.caption)
    has_footnotes = bool(block.footnotes)

    if has_caption or has_footnotes:
        fig = etree.SubElement(
            parent,
            f"{{{NS_XHTML}}}figure",
            attrib={"class": "code-listing"},
        )
        if has_caption:
            fc = etree.SubElement(fig, f"{{{NS_XHTML}}}figcaption")
            render_inlines_func(fc, block.caption)

        pre = etree.SubElement(
            fig,
            f"{{{NS_XHTML}}}pre",
            attrib={"class": "preformatted source-code"},
        )
        c_attribs = {"class": lang_attr} if lang_attr else {}
        code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code", attrib=c_attribs)
        code_el.text = block.text

        if has_footnotes:
            fn_div = etree.SubElement(
                fig,
                f"{{{NS_XHTML}}}div",
                attrib={"class": "code-note"},
            )
            render_inlines_func(fn_div, block.footnotes)
    else:
        pre = etree.SubElement(
            parent,
            f"{{{NS_XHTML}}}pre",
            attrib={"class": "preformatted source-code"},
        )
        c_attribs = {"class": lang_attr} if lang_attr else {}
        code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code", attrib=c_attribs)
        code_el.text = block.text


def render_preformatted_block(
    parent: etree._Element,
    block: PreformattedBlock,
    render_inlines_func: Callable[[etree._Element, Sequence[Inline]], None],
) -> None:
    """Render a PreformattedBlock (terminal, shell, logs, config) to semantic XHTML."""
    subtype_cls = SUBTYPE_TO_CLASS.get(block.subtype, "generic-preformatted")
    lang_attr = ""
    if block.language:
        clean_lang = LANG_PATTERN.sub("", block.language.lower())
        if clean_lang:
            lang_attr = f"language-{clean_lang}"

    has_caption = bool(block.caption)
    has_footnotes = bool(block.footnotes)

    if has_caption or has_footnotes:
        fig = etree.SubElement(
            parent,
            f"{{{NS_XHTML}}}figure",
            attrib={"class": f"preformatted-listing {subtype_cls}"},
        )
        if has_caption:
            fc = etree.SubElement(fig, f"{{{NS_XHTML}}}figcaption")
            render_inlines_func(fc, block.caption)

        pre = etree.SubElement(
            fig,
            f"{{{NS_XHTML}}}pre",
            attrib={"class": f"preformatted {subtype_cls}"},
        )
        c_attribs = {"class": lang_attr} if lang_attr else {}
        code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code", attrib=c_attribs)
        code_el.text = block.text

        if has_footnotes:
            fn_div = etree.SubElement(
                fig,
                f"{{{NS_XHTML}}}div",
                attrib={"class": "preformatted-note"},
            )
            render_inlines_func(fn_div, block.footnotes)
    else:
        pre = etree.SubElement(
            parent,
            f"{{{NS_XHTML}}}pre",
            attrib={"class": f"preformatted {subtype_cls}"},
        )
        c_attribs = {"class": lang_attr} if lang_attr else {}
        code_el = etree.SubElement(pre, f"{{{NS_XHTML}}}code", attrib=c_attribs)
        code_el.text = block.text
