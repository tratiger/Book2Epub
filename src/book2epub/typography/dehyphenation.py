"""Safe Latin dehyphenation at line and page boundaries (M11/Appendix M8)."""

import re

# Tokens looking like URLs, paths, CLI options, code identifiers with symbols
_CODE_OR_URL_PATTERN = re.compile(r"(https?://|[/\\]|=|--|_\w+)")


def try_dehyphenate(
    text_a: str,
    text_b: str,
) -> tuple[str, str, bool]:
    """
    Attempt safe Latin dehyphenation across a newline / page boundary.

    Conditions required:
    - Left text ends with '-' after right-stripping whitespace.
    - Character preceding '-' is ASCII alphabetic ([a-zA-Z]).
    - Right text begins with lowercase ASCII Latin ([a-z]).
    - Left text does not look like a URL, file path, CLI option, or code expression.

    Returns:
    - (modified_a_without_hyphen, left_trimmed_b, True) if dehyphenated,
    - (text_a, text_b, False) otherwise.
    """
    trimmed_a = text_a.rstrip()
    if not trimmed_a.endswith("-") or len(trimmed_a) < 2:
        return text_a, text_b, False

    char_before = trimmed_a[-2]
    if not (char_before.isascii() and char_before.isalpha()):
        return text_a, text_b, False

    # Check for CLI flags or URLs/paths in the preceding token
    last_token = trimmed_a.split()[-1]
    if _CODE_OR_URL_PATTERN.search(last_token):
        return text_a, text_b, False
    if last_token.startswith("--"):
        return text_a, text_b, False

    trimmed_b = text_b.lstrip()
    if not trimmed_b:
        return text_a, text_b, False

    first_char_b = trimmed_b[0]
    # Right must begin with lowercase ASCII Latin: rejects digits (UTF-8, pre-1990)
    # and uppercase (foo-Bar)
    if not (first_char_b.isascii() and first_char_b.isalpha() and first_char_b.islower()):
        return text_a, text_b, False

    # Strip the trailing hyphen
    dehyphenated_a = trimmed_a[:-1]
    return dehyphenated_a, trimmed_b, True
