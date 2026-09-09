# Appendix M — Japanese/Latin Typography, Whitespace, and List Normalization

This appendix is normative for M11. It fixes readability defects caused by OCR span/line joining while preserving authored text.

## M1. Scope

M11 may normalize:

- separators introduced at source span boundaries;
- printed line-wrap boundaries;
- conservative Latin dehyphenation;
- duplicate OCR list markers after semantic list recognition;
- print paragraph-indent characters when presentation replaces them.

M11 does NOT perform semantic OCR correction. That belongs only to M9.

## M2. Source-of-truth order

For enhanced/infer text reconstruction:

1. `SourceTextSegment.text` exact source span text;
2. `boundary_before` metadata;
3. span/line bbox gap;
4. language/punctuation boundary rules;
5. fallback to current joined `Text.text` only when segment evidence is absent.

Never re-tokenize code/math/table HTML with prose rules.

## M3. Character classes

Implement tested helper classes:

```text
CJK_HAN_KANA
LATIN_ASCII_WORD
DIGIT
OPEN_JP_PUNCT
CLOSE_JP_PUNCT
OPEN_ASCII_PUNCT
CLOSE_ASCII_PUNCT
WHITESPACE
OTHER
```

Japanese/CJK ranges may reuse the current `is_cjk()` ranges but punctuation should be classified separately.

Opening Japanese punctuation:

```text
（ ［ 【 〈 《 「 『 〔 〖〘〚
```

Closing Japanese punctuation:

```text
、 。 ， ． ！ ？ ： ； ） ］ 】 〉 》 」 』 〕 〗〙〛
```

## M4. Explicit whitespace

If a segment ends with ASCII whitespace or next segment begins with ASCII whitespace, preserve exactly one ordinary separator in prose unless punctuation rules remove it.

Do not infer multiple alignment spaces in prose.

Inside PreformattedBlock/CodeBlock preserve exact whitespace.

## M5. Same-line bbox gap

When no explicit source whitespace and both segments are on same line:

```text
gap = B.x0 - A.x1
estimated_char_width = median(
  bbox_width / count_nonspace_chars
  for valid adjacent segments
)
```

If:

```text
gap > 0.55 * estimated_char_width
```

candidate separator = one ASCII space; otherwise empty.

If char width cannot be estimated, use language boundary rules.

The threshold 0.55 is frozen for v1.

## M6. New-line rule matrix

Assuming no explicit whitespace:

| Left end | Right start | separator |
|---|---|---|
| CJK/Japanese | CJK/Japanese | empty |
| CJK/Japanese | Latin/digit | empty |
| Latin/digit | CJK/Japanese | empty |
| Latin word | Latin word | one space |
| any | closing JP punctuation | empty |
| opening JP punctuation | any | empty |
| opening ASCII punctuation | Latin/CJK | empty |
| Latin/CJK | closing ASCII punctuation | empty |

ASCII punctuation-specific sentence spacing is applied after this matrix.

Examples:

```text
これは + Linux       -> これはLinux
Linux + カーネル     -> Linuxカーネル
日本語 + 文章        -> 日本語文章
operating + system   -> operating system
「 + Linux           -> 「Linux
Linux + 」           -> Linux」
```

## M7. ASCII punctuation rules

No inserted space before:

```text
, . ; : ! ? ) ] }
```

No inserted space after:

```text
( [ {
```

At a printed line boundary, after `, ; : . ! ?` followed by an ASCII Latin word, use one space unless source punctuation is part of code/URL/path.

## M8. Latin dehyphenation

Apply only at NEW_LINE/PAGE_CONTINUATION prose boundary when:

- left trimmed ends `-`;
- character before `-` alphabetic;
- right begins lowercase ASCII Latin;
- previous token is not URL/path/code-like;
- neither segment is preformatted/math/link target.

Then remove only the terminal hyphen and concatenate.

Do not dehyphenate:

```text
UTF- + 8
pre- + 1990
foo- + Bar
http://...-
option --foo-
```

Record every dehyphenation.

## M9. Intra-segment spaces

Do not globally remove spaces inside a single source OCR segment. A space inside the span may be authored.

For ordinary prose only, a run of 2+ ASCII spaces inside one segment may be collapsed to one when it is not clearly alignment/preformatted material. This is legacy-compatible cleanup; record count.

NBSP is preserved.

## M10. Inline math boundaries

Do not insert a space merely because `InlineMath` separates Japanese text.

Examples:

```text
日本語 + InlineMath + です -> no automatic ASCII spaces
Latin word + InlineMath -> preserve explicit source boundary; do not guess if no segment evidence
```

LaTeX/MathML content is immutable.

## M11. Paragraph-start indentation

At beginning of Japanese Paragraph only:

- if one/two U+3000 IDEOGRAPHIC SPACE and BookStyleProfile first_line_indent != none, remove those leading U+3000 and rely on CSS indentation;
- if profile indent=none, preserve them;
- never strip internal U+3000.

Record normalization.

## M12. List marker recognition

Only operate inside a semantic `ListBlock`.

Unordered leading markers:

```text
• ● ○ ◦ ▪ ■ □ ‣ ・ * + - – —
```

Ordered families:

```text
1.  1)  (1)
a.  a)  A.  A)
①..⑳
一、 二、 三、 ...
```

A marker must occur at item start after optional indentation and normally be followed by whitespace or a clear item boundary.

## M13. Marker extraction model

Extend semantic list provenance:

```text
source_markers: list[str | None]
marker_style: auto|disc|circle|square|dash|decimal|alpha|roman
```

For each list item:

1. inspect first Text inline;
2. remove exactly recognized marker + immediate marker whitespace from rendered content;
3. store exact marker in source_markers;
4. leave remaining item content unchanged except normal text-boundary reconstruction;
5. never strip an internal marker.

Example:

```text
source: "- install package"
source_marker: "-"
rendered item text: "install package"
```

## M14. Marker-family mapping

```text
• ● ・ * +  -> disc
○ ◦         -> circle
▪ ■ □       -> square
- – —        -> dash
numeric      -> decimal
letter       -> alpha
roman        -> roman
```

Use majority family over list items. Tie/unknown -> auto.

Presentation profile may override visual style, but source marker provenance remains.

## M15. Double-marker invariant

Enhanced/infer renderer must never produce:

```text
• - item
• • item
1. (1) item
```

when the first symbol is a renderer marker and the second is an OCR source marker.

Exactly one marker mechanism per item.

## M16. Dash list rendering

Because portable list-style `dash` is not guaranteed, use explicit presentation span:

```html
<ul class="list list-dash">
  <li>
    <span class="list-marker" aria-hidden="true">–</span>
    <span class="list-content">item</span>
  </li>
</ul>
```

CSS:

```text
.list-dash { list-style:none; padding-left:<profile indent>; }
.list-dash .list-marker { display:inline-block; width:1.2em; margin-left:-1.2em; }
```

Do not depend on pseudo-elements for required visible content.

## M17. Normalization report

`presentation/normalization-report.json` includes counts plus bounded change records:

```text
source_segment_reconstructions
same_line_bbox_spaces_inserted
legacy_spaces_removed
newline_spaces_inserted
dehyphenations
leading_print_indents_normalized
list_markers_extracted
marker_style_distribution
fallback_text_nodes_without_segments
```

Change excerpts capped at 80 Unicode codepoints; never duplicate full book.

## M18. Exact regression cases

Required unit tests:

```text
こんにちは + 世界 -> こんにちは世界
これは + Linux -> これはLinux
Linux + カーネル -> Linuxカーネル
Unix + system -> Unix system
これは + 。 -> これは。
「 + Linux -> 「Linux
Linux + 」 -> Linux」
inter- + esting -> interesting
UTF- + 8 -> not dehyphenated
```

Lists:

```text
- foo in ListBlock -> one visible marker + foo
• foo -> one visible marker + foo
(1) foo -> ordered semantic marker only
Paragraph "-1 is negative" -> untouched
```

Exclusion:

- CodeBlock bytes unchanged.
- PreformattedBlock exact text unchanged.
- table HTML unchanged by typography normalizer.
- math unchanged.
- URL target unchanged.

## M19. Legacy compatibility

`presentation=legacy` keeps current `join_prose_texts()` behavior for existing Text output. New source-segment reconstruction is used by enhanced/infer mode and by OCR-correction rebuild logic as specified.

This separation makes visual quality improvements opt-in until M12 validates them.
