# M11 — Japanese Typography, Whitespace Reconstruction, and List Normalization

## Objective

Fix deterministic readability defects that semantic LLMs should not solve:

- artificial spaces inserted at OCR span/line boundaries;
- unnatural Japanese + Latin spacing;
- line-wrap artifacts and safe dehyphenation;
- duplicated list markers such as `• - item`;
- inconsistent unordered-list marker appearance;
- punctuation/bracket spacing.

M11 runs only for `presentation.mode in {enhanced, infer}` by default. Legacy mode retains the existing `join_prose_texts()` output for compatibility.

## 1. Required modules

```text
src/book2epub/typography/
  __init__.py
  models.py
  spacing.py
  japanese.py
  boundaries.py
  dehyphenation.py
  lists.py
  normalize.py
  report.py
```

Tests:

```text
tests/unit/typography/test_spacing.py
tests/unit/typography/test_japanese.py
tests/unit/typography/test_lists.py
tests/unit/typography/test_normalize.py
```

## 2. Pipeline position

Final high-quality order:

```text
M8/M9 Semantic BookIR
    -> existing normalize_bookir (page labels/cross-page structure/layout hints)
    -> M11 typography_normalize_bookir
    -> M10 component renderer using selected BookStyleProfile
```

Although M10 is implemented before M11 as a milestone, M11 inserts its normalized IR immediately before rendering in the final pipeline.

Write:

```text
ir/bookir.typography.json
presentation/normalization-report.json
```

Legacy mode may omit these.

## 3. Core rule: reconstruct from source segments

For a `Text` node with nonempty `source_segments`, enhanced typography MUST reconstruct visible prose from those exact raw span texts and boundary metadata. Do not normalize the already-joined `Text.text`, because it may contain spaces inserted by the old joining heuristic.

If `source_segments` is empty, leave `Text.text` unchanged except list-marker handling on a known ListBlock item.

Never run prose spacing normalization over:

- CodeBlock body;
- PreformattedBlock body;
- LaTeX/MathML;
- URLs/href targets;
- raw Table HTML.

## 4. Boundary classes

For adjacent SourceTextSegments A/B:

```text
START
SAME_LINE
NEW_LINE
PAGE_CONTINUATION
UNKNOWN
```

`boundary_before` from M6 supplies same/new line when available. PageBoundary in normalized IR identifies page continuation.

## 5. Explicit source whitespace

Before deciding an inter-segment separator:

- if A ends with ordinary ASCII whitespace or B begins with it, treat one space as explicitly observed by OCR/source content;
- strip duplicate boundary whitespace down to one in prose;
- do not infer multiple alignment spaces in prose;
- inside a single segment’s text, do not remove arbitrary Latin spaces.

A source whitespace inside a code/preformatted segment is never collapsed.

## 6. Same-line bbox gap inference

When no explicit boundary whitespace exists and both segment bboxes are available on the same line:

```text
gap = B.x0 - A.x1
char_width_A = A.bbox.width / max(1, count_nonspace_chars(A.text))
char_width_B = B.bbox.width / max(1, count_nonspace_chars(B.text))
estimated_char_width = median(valid positive char widths)
```

If:

```text
gap > 0.55 * estimated_char_width
```

then a visual word gap probably exists; separator candidate is one ASCII space.

If gap <= threshold, separator candidate is empty.

If bbox overlaps/invalid, fall back to language/punctuation boundary rules.

This threshold is frozen for v1 and unit-tested. Do not make it model-selected.

## 7. New-line reconstruction rules

A printed line break is normally not an EPUB line break.

Given trimmed A/B:

### 7.1 Latin dehyphenation

If A ends in `-`, previous character is alphabetic, B begins lowercase ASCII Latin, and the previous token does not look like URL/path/code (`http`, `/`, `\\`, `=`, common identifier operators), remove the terminal hyphen and concatenate.

Record dehyphenation.

Do not dehyphenate:

```text
UTF-
8
pre-
1990
foo-
Bar
```

unless exact existing legacy rule conditions are met.

### 7.2 CJK boundaries

If either boundary side is Japanese/CJK and there is no explicit source-space evidence, default separator is empty, subject to punctuation rules.

Examples expected:

```text
"Linux" + newline + "カーネル" -> "Linuxカーネル"
"これは" + newline + "Linux" -> "これはLinux"
"日本語" + newline + "文章" -> "日本語文章"
```

### 7.3 Latin-to-Latin

If both sides are Latin-like word characters and no hyphenation applies, insert one space.

```text
"operating" + newline + "system" -> "operating system"
```

### 7.4 Punctuation

Never insert a space before Japanese closing punctuation:

```text
、 。 ， ． ！ ？ ： ；
） ］ 】 〉 》 」 』
```

Never insert a space immediately after Japanese opening punctuation:

```text
（ ［ 【 〈 《 「 『
```

For ASCII punctuation in Latin prose:

- no space before `, . ; : ! ? ) ] }`;
- no space after `( [ {`;
- after comma/semicolon/colon/sentence punctuation followed by a Latin word at a line boundary, one space.

## 8. Japanese paragraph-start indentation

For Japanese-language enhanced/infer output, source leading print indentation should be represented by CSS/profile rather than literal fullwidth spaces where safely identifiable.

At the very beginning of a Paragraph only:

- if source starts with one or two U+3000 IDEOGRAPHIC SPACE characters and BookStyleProfile `first_line_indent != none`, remove those leading characters from rendered Text and record `LEADING_PRINT_INDENT_NORMALIZED`;
- if profile first_line_indent is none, preserve them because the style layer has no replacement indent;
- do not strip U+3000 inside paragraph text.

This is deterministic presentation normalization, not OCR correction.

## 9. Internal CJK spaces

Do **not** globally remove all spaces between Japanese/Latin characters inside a source segment. Such spaces may be authored.

The main fix comes from reconstructing **inter-span/inter-line boundaries** from source segments rather than using the current “anything non-CJK gets one space” rule.

Within a single source segment, only collapse obvious repeated ASCII whitespace in prose when it is not a preformatted/code context:

```text
2+ ordinary spaces -> 1 space
```

Preserve NBSP unless a later explicit rule handles it.

## 10. Inline node boundaries

Text adjacent to InlineMath/Hyperlink must not get arbitrary spaces.

Rules:

- preserve source Text segment boundaries on each side;
- do not insert ASCII space solely because an InlineMath node separates Japanese text;
- for Latin prose around inline math, add a normal word space only if existing source evidence/segment whitespace indicates it or punctuation logic demands it;
- hyperlink display text is normalized using its own Text source segments, but URL target is immutable.

## 11. List marker parsing

M11 normalizes markers only inside semantic `ListBlock`; it never turns ordinary paragraphs into lists. Classification belongs to MinerU/M8.

### Unordered marker regex family

Accept at item start:

```text
• ● ○ ◦ ▪ ■ □ ‣ ・ * + - – —
```

Require marker at beginning after optional indentation. A marker-like symbol later in text is untouched.

### Ordered marker families

Recognize at item start:

```text
1.  1)  (1)
a.  a)  A.  A)
①..⑳
一、 二、 三、 ...
```

Conservative regex only. Do not parse arbitrary dotted version numbers as list marker unless the block is already ListBlock and every/most item begins with the same family.

## 12. Marker extraction

For each ListBlock item:

1. inspect first Text inline;
2. if a recognized leading marker is present, remove exactly marker + immediate following marker whitespace from the rendered item content;
3. store the exact removed marker in `source_markers[index]`;
4. never remove a second marker-like character later in the item;
5. compute canonical preservation record containing both removed marker and remaining item text.

Thus:

```text
source item text: "- install package"
semantic list item: "install package"
source_marker: "-"
```

and the renderer supplies exactly one visual marker.

## 13. Marker style inference

Derive `ListBlock.marker_style` from the majority recognized source-marker family unless Semantic/Presentation profile explicitly sets a rendering preference.

Map:

```text
• ● ・ * +  -> disc
○ ◦         -> circle
▪ ■ □       -> square
- – —        -> dash
numeric      -> decimal
letter       -> alpha
roman source -> roman
```

Tie/unknown -> `auto`.

Final presentation may standardize unordered markers using `BookStyleProfile.list.unordered_marker`. Source marker remains provenance only.

## 14. No duplicated marker invariant

For every rendered semantic list item in enhanced/infer mode:

- source-leading marker is not present as literal duplicate text when renderer provides a marker;
- exactly one visual list marker mechanism is used.

If profile chooses `dash`, renderer may use either:

1. CSS list-style/pseudo-element if proven valid by EPUBCheck/reader-compatible tests; or
2. an explicit `<span class="list-marker" aria-hidden="true">–</span>` inside `<li>` while setting `list-style:none`.

For v1 prefer explicit marker span for dash because standard CSS has no portable `list-style-type: dash`. Standard disc/circle/square/decimal use native list semantics.

## 15. Normalization report

Write counts and exact block/segment references, not whole duplicated book text:

```text
source_segment_reconstructions
spaces_inserted_same_line_bbox
spaces_removed_vs_legacy_join
new_line_spaces_inserted
dehyphenations
leading_print_indents_normalized
list_markers_extracted
list_marker_styles
fallback_text_nodes_without_segments
```

For debugging, each change record may include short before/after excerpts capped at 80 codepoints.

## 16. Interaction with OCR correction

If M9 correction changed SourceTextSegment text:

- M11 consumes corrected segment text;
- bbox/boundary metadata remains original;
- normalization is run after corrections;
- M11 never second-guesses or edits a corrected glyph beyond deterministic spacing/marker rules.

OCR correction audit and typography audit remain separate.

## 17. Interaction with presentation

`BookStyleProfile` owns:

- line-height;
- paragraph gaps;
- first-line indentation;
- list marker visual style.

M11 owns textual cleanup/reconstruction.

Do not hard-code paragraph CSS inside typography code.

## 18. Tests

Required exact cases:

### Japanese/Latin

```text
["これは", "Linux"] on new line -> "これはLinux"
["Linux", "カーネル"] -> "Linuxカーネル"
["Unix", "system"] Latin-Latin -> "Unix system"
```

### Same-line bbox

- tiny gap -> no artificial space;
- gap > .55 estimated char width -> one space.

### Punctuation

```text
"これは" + "。" -> "これは。"
"「" + "Linux" -> "「Linux"
"Linux" + "」" -> "Linux」"
```

### Source-explicit space

A span ending with a real space followed by Latin word keeps one space.

### Dehyphenation

- `inter-` + `esting` -> `interesting`;
- `UTF-` + `8` remains `UTF- 8`/source-preserving non-dehyphenated form according to separator rules;
- URL/path not dehyphenated.

### Lists

- `- foo` in ListBlock does not render `• - foo`;
- `• foo` removes source bullet and renders one marker;
- `(1) foo` ordered list;
- ordinary Paragraph beginning `-1` is untouched;
- item text containing internal hyphen remains.

### Exclusions

Code/preformatted byte text unchanged by typography normalization.

## 19. Acceptance gate

M11 complete when:

- enhanced/infer Japanese output no longer relies on legacy non-CJK boundary space insertion;
- list duplicate marker regression tests pass;
- source-segment absent fallback is safe;
- legacy mode preserves existing text_join behavior;
- code/math/URL exclusions hold;
- ruff/mypy/pytest pass.
