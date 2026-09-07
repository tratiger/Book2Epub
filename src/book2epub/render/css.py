"""Default stylesheet for reflowable EPUB 3.3 content documents."""

BOOK_CSS_CONTENT = """/* Book2Epub base stylesheet - reader-compatible reflowable EPUB 3.3 */

html {
  line-height: 1.5;
}

body {
  margin: 0 5%;
}

img {
  max-width: 100%;
  height: auto;
}

figure {
  margin: 1.2em auto;
  break-inside: avoid;
}

figcaption {
  font-size: 0.9em;
  margin-top: 0.5em;
  text-align: center;
}

pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background-color: #f6f8fa;
  padding: 0.8em;
  border-radius: 4px;
}

code {
  font-family: monospace;
  font-size: 0.9em;
}

table {
  border-collapse: collapse;
  max-width: 100%;
  margin: 0.8em 0;
}

th, td {
  vertical-align: top;
  padding: 0.25em 0.4em;
  border: 1px solid #ddd;
}

th {
  background-color: #f2f2f2;
}

.table-wrap {
  max-width: 100%;
  overflow-x: auto;
}

.math.display {
  text-align: center;
  margin: 1em 0;
  overflow-x: auto;
}

.size-small {
  width: 36%;
  max-width: 100%;
}

.size-medium {
  width: 72%;
  max-width: 100%;
}

.size-large {
  width: 100%;
}

.align-left {
  margin-left: 0;
  margin-right: auto;
}

.align-center {
  margin-left: auto;
  margin-right: auto;
}

.align-right {
  margin-left: auto;
  margin-right: 0;
}

.code-listing {
  margin: 1.2em auto;
}

.figure-note, .table-note {
  font-size: 0.85em;
  color: #555;
  margin-top: 0.4em;
}

.page-footnote {
  font-size: 0.85em;
  border-top: 1px solid #ccc;
  margin-top: 1.5em;
  padding-top: 0.5em;
}

.list-marker-preserved {
  list-style-type: none;
  padding-left: 1.2em;
}

.math-fallback {
  max-width: 100%;
  height: auto;
  display: inline-block;
}

.math-unconverted {
  font-family: monospace;
  background-color: #fff3cd;
  padding: 0.1em 0.3em;
}

.unknown-block {
  border: 1px dashed #999;
  padding: 0.5em;
  margin: 1em 0;
  font-size: 0.9em;
}

aside.aside {
  margin: 1em 0;
  padding: 0.8em;
  background-color: #f9f9f9;
  border-left: 4px solid #007acc;
}

/* Narrow-screen media query promoting small/medium elements to full width */
@media screen and (max-width: 40em) {
  .size-small,
  .size-medium {
    width: 100%;
  }
}
"""
