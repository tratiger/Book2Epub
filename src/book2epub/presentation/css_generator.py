"""Deterministic CSS generator for Book2Epub presentation profiles (M10/Appendix L16)."""

from hashlib import sha256

from .css_tokens import (
    BODY_FIRST_LINE_INDENT,
    BODY_LINE_HEIGHT,
    BODY_PAGE_MARGIN,
    BODY_PARAGRAPH_GAP,
    CALLOUT_ACCENTS,
    CALLOUT_SPACING,
    FIGURE_CAPTION_SCALE,
    FIGURE_SPACING,
    HEADING_SCALE,
    HEADING_SPACE_AFTER,
    HEADING_SPACE_BEFORE,
    HEADING_WEIGHT,
    INLINE_CODE_FONT_SCALE,
    LIST_INDENT,
    LIST_ITEM_SPACING,
    PRE_FONT_SCALE,
    PRE_LINE_HEIGHT,
    PRE_PADDING,
    PRE_RADIUS,
    QUOTE_SPACING,
    TABLE_CELL_PADDING,
    TABLE_FONT_SCALE,
)
from .models import BookStyleProfile, HeadingStyle, PreStyle


def _render_heading_rule_css(rule: str) -> str:
    """Map heading rule to CSS border declarations."""
    if rule == "bottom_thin":
        return "  border-bottom: 0.06em solid currentColor;\n  padding-bottom: 0.22em;\n"
    if rule == "bottom_medium":
        return "  border-bottom: 0.10em solid currentColor;\n  padding-bottom: 0.25em;\n"
    if rule == "accent_left":
        return "  border-left: 0.20em solid currentColor;\n  padding-left: 0.45em;\n"
    return ""


def _render_heading_css(tag: str, style: HeadingStyle, is_h1: bool = False) -> str:
    """Format single heading level CSS."""
    lines = [
        f"{tag}, .{tag} {{",
        f"  font-size: {HEADING_SCALE[style.scale]};",
        f"  font-weight: {HEADING_WEIGHT[style.weight]};",
        f"  text-align: {style.alignment};",
        f"  margin-block-start: {HEADING_SPACE_BEFORE[style.space_before]};",
        f"  margin-block-end: {HEADING_SPACE_AFTER[style.space_after]};",
        "  line-height: 1.25;",
        "  break-after: avoid;",
    ]
    rule_css = _render_heading_rule_css(style.rule)
    if rule_css:
        lines.append(rule_css.rstrip("\n"))
    if is_h1 and style.chapter_break_before:
        lines.append("  break-before: page;")
    lines.append("}")
    return "\n".join(lines)


def _render_pre_css(selector: str, s: PreStyle) -> str:
    """Format CSS block for preformatted component class."""
    lines = [
        f"{selector} {{",
        "  font-family: monospace;",
        f"  font-size: {PRE_FONT_SCALE[s.font_scale]};",
        f"  line-height: {PRE_LINE_HEIGHT[s.line_height]};",
        f"  padding: {PRE_PADDING[s.padding]};",
        "  margin-block: 0.8em;",
        "  box-sizing: border-box;",
    ]
    # Radius
    r = PRE_RADIUS[s.radius]
    if r != "0":
        lines.append(f"  border-radius: {r};")

    # Theme
    if s.theme == "subtle":
        lines.append("  background-color: #f5f5f5;")
    elif s.theme == "outline":
        lines.append("  background-color: transparent;")
        lines.append("  border: 1px solid #d6d6d6;")
    elif s.theme == "dark":
        lines.append("  background-color: #202124;")
        lines.append("  color: #f2f2f2;")
    else:  # plain
        lines.append("  background-color: transparent;")

    # Border
    if s.border == "thin" and s.theme != "outline":
        lines.append("  border: 1px solid #d6d6d6;")
    elif s.border == "accent_left":
        lines.append("  border-left: 0.22em solid currentColor;")
    elif s.border == "none" and s.theme != "outline":
        lines.append("  border: none;")

    # Wrap
    if s.wrap == "soft":
        lines.append("  white-space: pre-wrap;")
        lines.append("  overflow-wrap: break-word;")
    else:
        lines.append("  white-space: pre;")
        lines.append("  overflow-x: auto;")

    lines.append("}")
    return "\n".join(lines)


def generate_book_css(profile: BookStyleProfile) -> str:
    """
    Generate deterministic, pure CSS from a validated BookStyleProfile (M10/Appendix L).
    Produces strict EPUB 3.3 compatible CSS.
    """
    sections: list[str] = []

    # 1. Header
    sections.append('@charset "UTF-8";')

    # 2. Document & Body
    body = profile.body
    margin = BODY_PAGE_MARGIN[body.page_margin]
    lh = BODY_LINE_HEIGHT[body.line_height]
    align = body.text_align

    sections.append(
        "html {\n"
        "  font-family: serif;\n"
        "  color: currentColor;\n"
        "  background: transparent;\n"
        "}\n"
        "body {\n"
        f"  margin-inline: {margin};\n"
        f"  line-height: {lh};\n"
        f"  text-align: {align};\n"
        "  word-break: normal;\n"
        "  overflow-wrap: break-word;\n"
        "}"
    )

    # 3. Paragraphs
    gap = BODY_PARAGRAPH_GAP[body.paragraph_gap]
    indent = BODY_FIRST_LINE_INDENT[body.first_line_indent]

    sections.append(
        "p {\n"
        f"  margin-block-start: {gap};\n"
        f"  margin-block-end: {gap};\n"
        f"  text-indent: {indent};\n"
        "}"
    )

    # 4. Headings
    h = profile.headings
    sections.append(_render_heading_css("h1", h.h1, is_h1=True))
    sections.append(_render_heading_css("h2", h.h2))
    sections.append(_render_heading_css("h3", h.h3))
    sections.append(_render_heading_css("h4", h.h4))
    sections.append(_render_heading_css("h5", h.h5_6))
    sections.append(_render_heading_css("h6", h.h5_6))

    # 5. Inline Code
    ic = profile.inline_code
    ic_bg = "#f5f5f5" if ic.background == "subtle" else "transparent"
    ic_b = "1px solid #d6d6d6" if ic.border == "thin" else "none"
    ic_pad = "0.12em 0.28em" if ic.padding == "xs" else "0"
    ic_scale = INLINE_CODE_FONT_SCALE[ic.font_scale]

    sections.append(
        "code.inline-code, .inline-code {\n"
        "  font-family: monospace;\n"
        f"  font-size: {ic_scale};\n"
        f"  background-color: {ic_bg};\n"
        f"  border: {ic_b};\n"
        f"  padding: {ic_pad};\n"
        "  border-radius: 3px;\n"
        "}"
    )

    # 6. Preformatted & Code Blocks
    sections.append(
        "pre {\n"
        "  font-family: monospace;\n"
        "  margin-block: 0.8em;\n"
        "  box-sizing: border-box;\n"
        "}"
    )
    sections.append(
        _render_pre_css(
            "pre.source-code, .code-listing pre, .source-code",
            profile.source_code,
        )
    )
    sections.append(
        _render_pre_css(
            "pre.terminal-output, pre.terminal-session, pre.shell-command, pre.repl-session, "
            ".terminal-output, .terminal-session, .shell-command, .repl-session",
            profile.terminal,
        )
    )
    sections.append(
        _render_pre_css(
            "pre.log-output, .log-output",
            profile.log,
        )
    )
    sections.append(
        _render_pre_css(
            "pre.config-file, .config-file",
            profile.config,
        )
    )
    sections.append(
        _render_pre_css(
            "pre.generic-preformatted, .generic-preformatted",
            profile.source_code,
        )
    )

    # 7. Callouts
    sections.append(
        "aside.callout, .callout, aside.aside {\n"
        "  margin-block: 1.0em;\n"
        "  box-sizing: border-box;\n"
        "  break-inside: avoid;\n"
        "}"
    )

    callout_styles = {
        "note": profile.callout.note,
        "tip": profile.callout.tip,
        "warning": profile.callout.warning,
        "caution": profile.callout.caution,
        "important": profile.callout.important,
        "sidebar": profile.callout.sidebar,
    }

    for name, c_style in callout_styles.items():
        color = CALLOUT_ACCENTS[c_style.accent]
        c_gap = CALLOUT_SPACING[c_style.spacing]
        c_lines = [
            f"aside.callout-{name}, .callout-{name}, aside.aside-{name} {{",
            f"  margin-block: {c_gap};",
            "  box-sizing: border-box;",
            "  break-inside: avoid;",
        ]
        if c_style.variant == "plain":
            c_lines.append("  padding: 0.5em 0.8em;")
        elif c_style.variant == "boxed":
            c_lines.append(f"  border: 1px solid {color};")
            c_lines.append("  border-radius: 4px;")
            c_lines.append("  padding: 0.6em 0.9em;")
            c_lines.append("  background-color: #f5f5f5;")
        else:  # accent_left
            c_lines.append(f"  border-left: 0.25em solid {color};")
            c_lines.append("  padding: 0.6em 0.9em;")
            c_lines.append("  background-color: #f5f5f5;")
        c_lines.append("}")
        sections.append("\n".join(c_lines))

    # 8. Quotes
    q = profile.quote
    q_spacing = QUOTE_SPACING[q.spacing]
    q_lines = [
        "blockquote, blockquote.quote {",
        f"  margin-block: {q_spacing};",
        f"  font-style: {q.font_style};",
        "  box-sizing: border-box;",
    ]
    if q.variant == "indent":
        q_lines.append("  margin-inline: 1.5em;")
    elif q.variant == "boxed":
        q_lines.append("  border: 1px solid #d6d6d6;")
        q_lines.append("  padding: 0.8em;")
        q_lines.append("  margin-inline: 1.0em;")
    else:  # accent_left
        q_lines.append("  border-left: 0.18em solid currentColor;")
        q_lines.append("  padding-left: 0.8em;")
        q_lines.append("  margin-inline: 1.0em;")
    q_lines.append("}")
    sections.append("\n".join(q_lines))

    # 9. Lists
    lst = profile.list
    sections.append(
        "ul, ol {\n"
        f"  padding-inline-start: {LIST_INDENT[lst.indent]};\n"
        "  margin-block: 0.6em;\n"
        "}\n"
        "li {\n"
        f"  margin-block: {LIST_ITEM_SPACING[lst.item_spacing]};\n"
        "}\n"
        f"ul {{ list-style-type: {lst.unordered_marker}; }}\n"
        f"ol {{ list-style-type: {lst.ordered_marker}; }}\n"
        "ul.list-dash {\n"
        "  list-style: none;\n"
        "  padding-inline-start: 1.2em;\n"
        "}\n"
        "ul.list-dash li {\n"
        "  position: relative;\n"
        "}\n"
        "ul.list-dash .list-marker {\n"
        "  display: inline-block;\n"
        "  width: 1.0em;\n"
        "  margin-left: -1.0em;\n"
        "}"
    )

    # 10. Definition Lists
    sections.append(
        "dl {\n"
        "  margin-block: 0.8em;\n"
        "}\n"
        "dt {\n"
        "  font-weight: 600;\n"
        "  margin-top: 0.4em;\n"
        "}\n"
        "dd {\n"
        "  margin-inline-start: 1.5em;\n"
        "  margin-bottom: 0.4em;\n"
        "}"
    )

    # 11. Tables
    tbl = profile.table
    tbl_scale = TABLE_FONT_SCALE[tbl.font_scale]
    tbl_pad = TABLE_CELL_PADDING[tbl.cell_padding]
    tbl_align = tbl.caption_align

    sections.append(
        ".table-wrap {\n"
        "  overflow-x: auto;\n"
        "  margin-block: 1.0em;\n"
        "}\n"
        "table {\n"
        "  border-collapse: collapse;\n"
        "  width: 100%;\n"
        f"  font-size: {tbl_scale};\n"
        "}\n"
        "caption {\n"
        f"  text-align: {tbl_align};\n"
        "  caption-side: top;\n"
        "  font-weight: 600;\n"
        "  margin-bottom: 0.5em;\n"
        "}"
    )

    if tbl.rules == "full":
        sections.append(
            "th, td {\n"
            "  border: 1px solid #d6d6d6;\n"
            f"  padding: {tbl_pad};\n"
            "}"
        )
    elif tbl.rules == "horizontal":
        sections.append(
            "th, td {\n"
            "  border-bottom: 1px solid #d6d6d6;\n"
            f"  padding: {tbl_pad};\n"
            "}"
        )
    else:  # minimal
        sections.append(
            "table {\n"
            "  border-top: 1px solid currentColor;\n"
            "  border-bottom: 1px solid currentColor;\n"
            "}\n"
            "th {\n"
            "  border-bottom: 1px solid currentColor;\n"
            f"  padding: {tbl_pad};\n"
            "}\n"
            "td {\n"
            f"  padding: {tbl_pad};\n"
            "}"
        )

    if tbl.header_emphasis == "strong":
        sections.append("th {\n  font-weight: 700;\n  border-bottom: 0.12em solid currentColor;\n}")
    elif tbl.header_emphasis == "subtle":
        sections.append("th {\n  font-weight: 600;\n  background-color: #f5f5f5;\n}")
    else:
        sections.append("th {\n  font-weight: normal;\n}")

    # 12. Figures & Images
    fig = profile.figure
    fig_spacing = FIGURE_SPACING[fig.spacing]
    fig_scale = FIGURE_CAPTION_SCALE[fig.caption_scale]
    fig_align = fig.caption_align

    sections.append(
        "figure, .figure {\n"
        f"  margin-block: {fig_spacing};\n"
        "  margin-inline: 0;\n"
        "  text-align: center;\n"
        "}\n"
        "figure img, .figure img {\n"
        "  max-width: 100%;\n"
        "  height: auto;\n"
        "  display: block;\n"
        "  margin-inline: auto;\n"
        "}\n"
        "figcaption, .figure-caption {\n"
        f"  font-size: {fig_scale};\n"
        f"  text-align: {fig_align};\n"
        "  margin-block: 0.4em;\n"
        "  color: currentColor;\n"
        "}"
    )

    # 13. Math
    sections.append(
        "div.math, .math.display {\n"
        "  margin-block: 0.8em;\n"
        "  text-align: center;\n"
        "  overflow-x: auto;\n"
        "}\n"
        "math {\n"
        "  font-family: serif;\n"
        "}"
    )

    # 14. Footnotes
    sections.append(
        "aside.page-footnote, .footnote {\n"
        "  font-size: 0.85em;\n"
        "  border-top: 1px solid #d6d6d6;\n"
        "  margin-top: 1.5em;\n"
        "  padding-top: 0.5em;\n"
        "}"
    )

    # 15. Containers (Example & Exercise)
    sections.append(
        "section.example, div.example {\n"
        "  margin-block: 1.2em;\n"
        "  padding: 0.8em 1.0em;\n"
        "  border-left: 0.25em solid #0f766e;\n"
        "  background-color: #f5f5f5;\n"
        "}\n"
        "section.exercise, div.exercise {\n"
        "  margin-block: 1.2em;\n"
        "  padding: 0.8em 1.0em;\n"
        "  border: 1px solid #d6d6d6;\n"
        "  border-radius: 4px;\n"
        "}"
    )

    return "\n\n".join(sections) + "\n"


def compute_css_hash(css_content: str) -> str:
    """Compute deterministic SHA-256 hash of CSS content."""
    return sha256(css_content.encode("utf-8")).hexdigest()
