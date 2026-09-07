# Appendix B - EPUB 3.3 Packaging Contract

Implementation must follow this appendix and the EPUBCheck gate. It is a practical subset of EPUB 3.3 needed by Book2Epub.

Primary source: https://www.w3.org/TR/epub-33/

## B1. Reflow is the product mode

EPUB publications are reflowable by default. Book2Epub does not set fixed-layout (`pre-paginated`) metadata.

## B2. OCF container

The `.epub` file is a ZIP-based OCF container.

Required root `mimetype` constraints:

- first ZIP entry;
- exact ASCII content `application/epub+zip`;
- no whitespace/BOM;
- stored/uncompressed;
- not encrypted.

Container also has `/META-INF/container.xml`, pointing to package document.

## B3. Core package components

Book2Epub writes:

- package document `OEBPS/package.opf`;
- mandatory navigation document `OEBPS/nav.xhtml`;
- content documents under `OEBPS/text/`;
- CSS under `OEBPS/styles/`;
- content images under `OEBPS/images/`.

Do not list `mimetype` or `META-INF` files in the publication manifest.

## B4. Package metadata

Required practical metadata:

```xml
<dc:identifier id="pub-id">urn:uuid:...</dc:identifier>
<dc:title>...</dc:title>
<dc:language>...</dc:language>
<meta property="dcterms:modified">2026-09-08T00:00:00Z</meta>
```

Use package `unique-identifier="pub-id"`.

## B5. Manifest

Exactly one item must be identified as nav with `properties="nav"`.

Example:

```xml
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
```

An XHTML resource containing MathML must declare manifest property `mathml`.

Example from spec conceptually:

```xml
<item id="c2" href="text/c2.xhtml" media-type="application/xhtml+xml" properties="mathml"/>
```

If a cover image exists, `cover-image` property is recommended/used by this product.

## B6. Spine

Spine references content-document manifest ids in default reading order.

Book2Epub nav document is not required to be in spine.

## B7. Navigation document

Mandatory EPUB nav document must contain exactly one TOC nav:

```xml
<nav epub:type="toc">
  <ol>...</ol>
</nav>
```

Special nav content rules:

- `nav` has optional heading then exactly one ol;
- each li begins with exactly one `a` or `span`, then optionally a nested ol;
- TOC/page-list/landmarks hrefs resolve to top-level content document or a fragment within it.

Book2Epub also writes one `page-list` nav. EPUB spec makes page-list optional, but the product requires it to preserve source pagination.

Reading Systems spec says systems SHOULD provide navigation to page-list boundaries when present.

## B8. Page boundaries

Targets may use EPUB structural semantic `pagebreak`.

Book2Epub uses:

```xml
<span id="page-137" epub:type="pagebreak" role="doc-pagebreak" aria-label="137"/>
```

Page-list href resolves to that fragment.

## B9. XHTML and MathML

Content is XHTML, not tag-soup HTML. Generate well-formed XML.

MathML is embedded in XHTML with MathML namespace and presentation markup produced by the frozen local converter.

No script-based rendering is required or allowed.

## B10. Paths

All internal URLs are relative POSIX-style paths. Resources should be at or below the package document directory for interoperability.

Do not emit Windows drive letters or backslashes.

## B11. ZIP constraints

Book2Epub uses only Stored and Deflate methods, no encryption, and UTF-8 filenames. Python `zipfile` supports `ZIP_STORED`, `ZIP_DEFLATED`, and ZIP64. `allowZip64=True` is acceptable for very large EPUBs.

## B12. EPUBCheck

EPUBCheck 5.3.0 is the frozen production checker. W3C/DAISY state it is the latest production-ready release and checks EPUB 3 publications against EPUB 3.3.

Source:
https://www.w3.org/publishing/epubcheck/releases/

A generated EPUB is not successful until EPUBCheck passes.
