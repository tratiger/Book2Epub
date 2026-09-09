"""CSS token mappings and design constants for BookStyleProfile (M10/Appendix L)."""

# Frozen color palette tokens (Appendix L3)
PALETTE: dict[str, str] = {
    "text": "currentColor",
    "subtle_bg": "#f5f5f5",
    "subtle_border": "#d6d6d6",
    "neutral_accent": "#6b7280",
    "blue_accent": "#2563eb",
    "teal_accent": "#0f766e",
    "amber_accent": "#b45309",
    "red_accent": "#b91c1c",
}

CALLOUT_ACCENTS: dict[str, str] = {
    "neutral": PALETTE["neutral_accent"],
    "blue": PALETTE["blue_accent"],
    "teal": PALETTE["teal_accent"],
    "amber": PALETTE["amber_accent"],
    "red": PALETTE["red_accent"],
}

BODY_PAGE_MARGIN: dict[str, str] = {
    "compact": "3%",
    "standard": "5%",
    "generous": "8%",
}

BODY_LINE_HEIGHT: dict[str, str] = {
    "compact": "1.40",
    "normal": "1.55",
    "relaxed": "1.70",
}

BODY_PARAGRAPH_GAP: dict[str, str] = {
    "none": "0",
    "tight": "0.35em",
    "normal": "0.65em",
    "open": "1.0em",
}

BODY_FIRST_LINE_INDENT: dict[str, str] = {
    "none": "0",
    "small": "1em",
    "medium": "2em",
}

HEADING_SCALE: dict[str, str] = {
    "s": "1.05em",
    "m": "1.20em",
    "l": "1.40em",
    "xl": "1.70em",
    "xxl": "2.00em",
}

HEADING_WEIGHT: dict[str, str] = {
    "semibold": "600",
    "bold": "700",
}

HEADING_SPACE_BEFORE: dict[str, str] = {
    "m": "0.9em",
    "l": "1.3em",
    "xl": "1.8em",
    "xxl": "2.4em",
}

HEADING_SPACE_AFTER: dict[str, str] = {
    "s": "0.35em",
    "m": "0.65em",
    "l": "0.95em",
    "xl": "1.3em",
}

PRE_PADDING: dict[str, str] = {
    "s": "0.55em",
    "m": "0.85em",
    "l": "1.10em",
}

PRE_RADIUS: dict[str, str] = {
    "none": "0",
    "small": "4px",
}

PRE_FONT_SCALE: dict[str, str] = {
    "small": "0.88em",
    "normal": "0.95em",
}

PRE_LINE_HEIGHT: dict[str, str] = {
    "compact": "1.30",
    "normal": "1.45",
}

INLINE_CODE_FONT_SCALE: dict[str, str] = {
    "normal": "1.0em",
    "small": "0.92em",
}

TABLE_CELL_PADDING: dict[str, str] = {
    "compact": "0.20em 0.30em",
    "normal": "0.35em 0.50em",
    "generous": "0.55em 0.70em",
}

TABLE_FONT_SCALE: dict[str, str] = {
    "small": "0.90em",
    "normal": "1.0em",
}

FIGURE_SPACING: dict[str, str] = {
    "tight": "0.8em",
    "normal": "1.2em",
    "open": "1.8em",
}

FIGURE_CAPTION_SCALE: dict[str, str] = {
    "small": "0.88em",
    "normal": "0.95em",
}

LIST_INDENT: dict[str, str] = {
    "compact": "1.2em",
    "normal": "1.8em",
    "generous": "2.4em",
}

LIST_ITEM_SPACING: dict[str, str] = {
    "compact": "0.15em",
    "normal": "0.35em",
    "open": "0.65em",
}

CALLOUT_SPACING: dict[str, str] = {
    "tight": "0.5em",
    "normal": "1.0em",
    "open": "1.5em",
}

QUOTE_SPACING: dict[str, str] = {
    "normal": "0.8em",
    "open": "1.4em",
}
