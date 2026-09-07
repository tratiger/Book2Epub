# Appendix E - Test Matrix and Acceptance Fixtures

## E1. Test layers

### Unit

No MinerU/GPU/Java needed.

### Integration-render

Uses checked-in synthetic middle/BookIR fixtures. No GPU. Java optional except EPUBCheck marker.

### Integration-MinerU

Requires local MinerU models and GPU; excluded from default fast suite.

### Release

Requires target Windows GPU + EPUBCheck.

## E2. Comprehensive middle fixture

Fixture must cover at least these cases in one or several pages:

1. `title level=1`
2. `title level=2`
3. body text with `<`, `>`, `&`
4. Japanese prose
5. English hyphenated line continuation
6. inline equation
7. display equation with fallback image
8. Java/Python-like code with indentation and caption
9. algorithm subtype
10. figure with caption and footnote
11. chart with caption
12. table with rowspan/colspan
13. table with embedded local image path
14. list ordered
15. list unordered
16. reference-style list
17. index
18. header
19. footer
20. page number Arabic
21. page number Roman
22. aside text
23. page footnote
24. paragraph continuing across source page boundary
25. unknown harmless field
26. unknown content-bearing block for warning path

## E3. Formula corpus

At minimum test successful conversion of:

```text
x^2 + y^2 = z^2
\frac{a+b}{c}
\sqrt{x}
\sum_{i=1}^{n} i
\int_0^1 x^2\,dx
\alpha + \beta \leq \gamma
\begin{bmatrix}a & b \\ c & d\end{bmatrix}
\mathrm{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
```

Also include one deliberately unsupported/malformed LaTeX string to exercise fallback.

## E4. EPUB structural assertions

Unzip generated EPUB in tests and assert:

- first ZIP member is `mimetype`;
- mimetype stored and exact;
- container points to package;
- every manifest file exists;
- every spine idref resolves;
- nav property exactly once;
- toc nav exactly once;
- page-list exists;
- href/src internal resolution;
- MathML resource property;
- no `<script`;
- no `position:absolute`;
- no source page filenames in content resource list except explicit cover fixture;
- XHTML XML parse success;
- code text exact;
- tables remain `<table>`;
- formulas contain MathML namespace on success.

## E5. Real-book local evaluation set

Do not commit commercial book pages.

Recommended local evaluation selection: 20-30 pages intentionally containing:

- chapter opener;
- ordinary prose;
- multiple heading levels;
- dense code;
- code with long lines;
- inline math;
- display math;
- table simple;
- table wide/complex;
- diagram + caption;
- screenshot/photograph;
- sidebar/note;
- footnote;
- page transition in mid-paragraph;
- index/reference page if relevant.

Run all through one source PDF so cross-page behavior is exercised.

## E6. Manual pass criteria

On a real technical-book sample:

- font-size increase/decrease reflows text instead of zooming a page image;
- code can be selected/copied;
- ordinary formulas are crisp and scalable;
- figures resize to device width;
- table text remains selectable when structured HTML was available;
- TOC hierarchy is usable;
- original page navigation exists when reader exposes page-list;
- there is no scan-page background;
- no content appears twice because both semantic and image page representations were included.
