"""Unit tests for EPUB 3.3 packaging, OPF, NAV, ZIP, and validation."""

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from book2epub.package.container import generate_container_xml
from book2epub.package.models import ManifestItem, SpineItem
from book2epub.package.nav import generate_nav_xhtml
from book2epub.package.opf import generate_package_opf
from book2epub.package.validator import validate_epub_internals
from book2epub.package.zip import MIMETYPE_BYTES, create_epub_zip
from book2epub.render.models import PageMapEntry, TocEntry


def test_container_xml() -> None:
    content = generate_container_xml()
    tree = etree.fromstring(content.encode("utf-8"))
    rootfiles = tree.xpath(
        "//c:rootfile",
        namespaces={"c": "urn:oasis:names:tc:opendocument:xmlns:container"},
    )
    assert len(rootfiles) == 1
    assert rootfiles[0].get("full-path") == "OEBPS/package.opf"
    assert rootfiles[0].get("media-type") == "application/oebps-package+xml"


def test_package_opf_generation() -> None:
    manifest_items = [
        ManifestItem(
            id="nav", href="nav.xhtml", media_type="application/xhtml+xml", properties="nav"
        ),
        ManifestItem(id="style", href="styles/book.css", media_type="text/css"),
        ManifestItem(
            id="part1",
            href="text/part-0001.xhtml",
            media_type="application/xhtml+xml",
            properties="mathml",
        ),
        ManifestItem(id="fig1", href="images/fig1.png", media_type="image/png"),
    ]
    spine_items = [SpineItem(idref="part1")]

    opf_bytes = generate_package_opf(
        title="Test Technical Book",
        language="en",
        identifier="urn:uuid:12345678-1234-5678-1234-567812345678",
        manifest_items=manifest_items,
        spine_items=spine_items,
        authors=["Author One", "Author Two"],
        publisher="Test Publisher",
        modified_utc="2026-09-08T00:00:00Z",
    )

    tree = etree.fromstring(opf_bytes)
    ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}

    assert tree.get("version") == "3.0"
    assert tree.get("unique-identifier") == "pub-id"

    # Metadata
    assert tree.xpath("//dc:title", namespaces=ns)[0].text == "Test Technical Book"
    assert tree.xpath("//dc:language", namespaces=ns)[0].text == "en"
    creators = [el.text for el in tree.xpath("//dc:creator", namespaces=ns)]
    assert creators == ["Author One", "Author Two"]
    assert tree.xpath("//dc:publisher", namespaces=ns)[0].text == "Test Publisher"

    # Manifest
    items = tree.xpath("//opf:manifest/opf:item", namespaces=ns)
    assert len(items) == 4
    item_map = {item.get("id"): item for item in items}
    assert item_map["nav"].get("properties") == "nav"
    assert item_map["part1"].get("properties") == "mathml"
    assert item_map["fig1"].get("media-type") == "image/png"

    # Spine
    itemrefs = tree.xpath("//opf:spine/opf:itemref", namespaces=ns)
    assert len(itemrefs) == 1
    assert itemrefs[0].get("idref") == "part1"


def test_nav_xhtml_nesting_and_shape() -> None:
    toc = [
        TocEntry(
            title="Chapter 1",
            href="text/part-0001.xhtml#h1",
            level=1,
            children=[
                TocEntry(
                    title="Section 1.1",
                    href="text/part-0001.xhtml#h1-1",
                    level=2,
                )
            ],
        ),
        TocEntry(
            title="Chapter 2",
            href="text/part-0002.xhtml#h2",
            level=1,
        ),
    ]
    page_map = [
        PageMapEntry(
            page_idx=0,
            label="1",
            printed_label_confidence="high",
            xhtml_path="text/part-0001.xhtml",
            fragment_id="page-1",
        ),
        PageMapEntry(
            page_idx=1,
            label="2",
            printed_label_confidence="high",
            xhtml_path="text/part-0002.xhtml",
            fragment_id="page-2",
        ),
    ]

    nav_bytes = generate_nav_xhtml(
        title="Test Book",
        language="en",
        toc_entries=toc,
        page_map_entries=page_map,
        first_doc_href="text/part-0001.xhtml",
    )

    tree = etree.fromstring(nav_bytes)
    ns = {"h": "http://www.w3.org/1999/xhtml", "epub": "http://www.idpf.org/2007/ops"}

    # Check TOC nav
    toc_nav = tree.xpath("//h:nav[@epub:type='toc']", namespaces=ns)
    assert len(toc_nav) == 1
    toc_ol = toc_nav[0].xpath("./h:ol", namespaces=ns)[0]
    top_lis = toc_ol.xpath("./h:li", namespaces=ns)
    assert len(top_lis) == 2

    # Check nested list rule: each li starts with exactly one a, then optional ol
    first_li = top_lis[0]
    first_li_children = list(first_li)
    assert first_li_children[0].tag == "{http://www.w3.org/1999/xhtml}a"
    assert first_li_children[0].attrib["href"] == "text/part-0001.xhtml#h1"
    assert first_li_children[1].tag == "{http://www.w3.org/1999/xhtml}ol"

    # Check page-list nav
    pagelist_nav = tree.xpath("//h:nav[@epub:type='page-list']", namespaces=ns)
    assert len(pagelist_nav) == 1
    page_lis = pagelist_nav[0].xpath("./h:ol/h:li", namespaces=ns)
    assert len(page_lis) == 2
    assert page_lis[0].xpath("./h:a/@href", namespaces=ns)[0] == "text/part-0001.xhtml#page-1"
    assert page_lis[0].xpath("./h:a/text()", namespaces=ns)[0] == "1"

    # Check landmarks nav
    landmarks_nav = tree.xpath("//h:nav[@epub:type='landmarks']", namespaces=ns)
    assert len(landmarks_nav) == 1
    assert landmarks_nav[0].get("hidden") == "hidden"
    bodymatter = landmarks_nav[0].xpath(".//h:a[@epub:type='bodymatter']", namespaces=ns)
    assert len(bodymatter) == 1
    assert bodymatter[0].get("href") == "text/part-0001.xhtml"


def test_zip_archiver_mimetype_order_and_compression(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()

    # 1. Create files in staging
    (staging / "mimetype").write_bytes(MIMETYPE_BYTES)
    meta_inf = staging / "META-INF"
    meta_inf.mkdir()
    (meta_inf / "container.xml").write_text(generate_container_xml(), encoding="utf-8")

    oebps = staging / "OEBPS"
    oebps.mkdir()
    (oebps / "content.xhtml").write_text("<html><body>Hello</body></html>", encoding="utf-8")

    epub_target = tmp_path / "book.epub"
    create_epub_zip(staging, epub_target)

    assert epub_target.is_file()

    with zipfile.ZipFile(epub_target, "r") as zf:
        names = zf.namelist()
        # mimetype MUST be first
        assert names[0] == "mimetype"
        # mimetype MUST be ZIP_STORED (0)
        m_info = zf.getinfo("mimetype")
        assert m_info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == MIMETYPE_BYTES

        # Remaining files must be deflated
        c_info = zf.getinfo("META-INF/container.xml")
        assert c_info.compress_type == zipfile.ZIP_DEFLATED

        # No Windows backslashes
        for name in names:
            assert "\\" not in name


def test_internal_validator_detects_broken_href(tmp_path: Path) -> None:
    staging = tmp_path / "staging_broken"
    staging.mkdir()
    (staging / "mimetype").write_bytes(MIMETYPE_BYTES)

    meta_inf = staging / "META-INF"
    meta_inf.mkdir()
    (meta_inf / "container.xml").write_text(generate_container_xml(), encoding="utf-8")

    oebps = staging / "OEBPS"
    oebps.mkdir()

    # Part 1 references nonexistent fragment #nonexistent in part 2
    part1_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "  <head><title>P1</title></head>\n"
        '  <body><a href="part2.xhtml#nonexistent">Broken Link</a></body>\n'
        "</html>"
    )
    (oebps / "part1.xhtml").write_text(part1_xhtml, encoding="utf-8")

    # Part 2 exists with id="existing"
    part2_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "  <head><title>P2</title></head>\n"
        '  <body id="existing"><p>P2</p></body>\n'
        "</html>"
    )
    (oebps / "part2.xhtml").write_text(part2_xhtml, encoding="utf-8")

    # Nav
    nav_bytes = generate_nav_xhtml("Title", "en", [], [], "part1.xhtml")
    (oebps / "nav.xhtml").write_bytes(nav_bytes)

    # OPF
    manifest_items = [
        ManifestItem(
            id="nav", href="nav.xhtml", media_type="application/xhtml+xml", properties="nav"
        ),
        ManifestItem(id="p1", href="part1.xhtml", media_type="application/xhtml+xml"),
        ManifestItem(id="p2", href="part2.xhtml", media_type="application/xhtml+xml"),
    ]
    spine_items = [SpineItem(idref="p1"), SpineItem(idref="p2")]
    opf_bytes = generate_package_opf("Title", "en", "id-1", manifest_items, spine_items)
    (oebps / "package.opf").write_bytes(opf_bytes)

    epub_broken = tmp_path / "broken.epub"
    create_epub_zip(staging, epub_broken)

    issues = validate_epub_internals(epub_broken)
    broken_frag_issues = [i for i in issues if "Target ID '#nonexistent'" in i.message]
    assert len(broken_frag_issues) >= 1
    assert broken_frag_issues[0].severity == "ERROR"


def test_internal_validator_detects_forbidden_javascript(tmp_path: Path) -> None:
    staging = tmp_path / "staging_js"
    staging.mkdir()
    (staging / "mimetype").write_bytes(MIMETYPE_BYTES)

    meta_inf = staging / "META-INF"
    meta_inf.mkdir()
    (meta_inf / "container.xml").write_text(generate_container_xml(), encoding="utf-8")

    oebps = staging / "OEBPS"
    oebps.mkdir()

    # XHTML containing <script> tag
    part1_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "  <head><title>JS Test</title><script>alert(1);</script></head>\n"
        "  <body><p>Content</p></body>\n"
        "</html>"
    )
    (oebps / "part1.xhtml").write_text(part1_xhtml, encoding="utf-8")

    nav_bytes = generate_nav_xhtml("Title", "en", [], [], "part1.xhtml")
    (oebps / "nav.xhtml").write_bytes(nav_bytes)

    manifest_items = [
        ManifestItem(
            id="nav", href="nav.xhtml", media_type="application/xhtml+xml", properties="nav"
        ),
        ManifestItem(id="p1", href="part1.xhtml", media_type="application/xhtml+xml"),
    ]
    spine_items = [SpineItem(idref="p1")]
    opf_bytes = generate_package_opf("Title", "en", "id-1", manifest_items, spine_items)
    (oebps / "package.opf").write_bytes(opf_bytes)

    epub_js = tmp_path / "js.epub"
    create_epub_zip(staging, epub_js)

    issues = validate_epub_internals(epub_js)
    js_issues = [i for i in issues if "JavaScript <script> tag forbidden" in i.message]
    assert len(js_issues) >= 1
    assert js_issues[0].severity == "ERROR"


def test_internal_validator_detects_missing_mathml_property(tmp_path: Path) -> None:
    staging = tmp_path / "staging_math"
    staging.mkdir()
    (staging / "mimetype").write_bytes(MIMETYPE_BYTES)

    meta_inf = staging / "META-INF"
    meta_inf.mkdir()
    (meta_inf / "container.xml").write_text(generate_container_xml(), encoding="utf-8")

    oebps = staging / "OEBPS"
    oebps.mkdir()

    # XHTML containing MathML
    part1_xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "  <head><title>Math</title></head>\n"
        '  <body><p><math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math></p></body>\n'
        "</html>"
    )
    (oebps / "part1.xhtml").write_text(part1_xhtml, encoding="utf-8")

    nav_bytes = generate_nav_xhtml("Title", "en", [], [], "part1.xhtml")
    (oebps / "nav.xhtml").write_bytes(nav_bytes)

    # Manifest item intentionally missing properties="mathml"
    manifest_items = [
        ManifestItem(
            id="nav", href="nav.xhtml", media_type="application/xhtml+xml", properties="nav"
        ),
        ManifestItem(id="p1", href="part1.xhtml", media_type="application/xhtml+xml"),
    ]
    spine_items = [SpineItem(idref="p1")]
    opf_bytes = generate_package_opf("Title", "en", "id-1", manifest_items, spine_items)
    (oebps / "package.opf").write_bytes(opf_bytes)

    epub_math = tmp_path / "math.epub"
    create_epub_zip(staging, epub_math)

    issues = validate_epub_internals(epub_math)
    math_issues = [i for i in issues if "has MathML without manifest property" in i.message]
    assert len(math_issues) >= 1
    assert math_issues[0].severity == "ERROR"


def test_candidate_not_promoted_on_validation_failure(tmp_path: Path) -> None:
    from book2epub.errors import PackagingError
    from book2epub.package.packager import EpubPackager
    from book2epub.render.models import RenderedDocument, RenderManifest, RenderResult

    # Mock render result pointing to invalid XHTML with broken fragment
    oebps = tmp_path / "render" / "OEBPS"
    (oebps / "text").mkdir(parents=True)
    (oebps / "styles").mkdir(parents=True)
    (oebps / "styles" / "book.css").write_text("body {}", encoding="utf-8")

    broken_doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        "  <head><title>Broken</title></head>\n"
        '  <body><a href="part-0001.xhtml#missing">Link</a></body>\n'
        "</html>"
    )
    (oebps / "text" / "part-0001.xhtml").write_text(broken_doc, encoding="utf-8")

    manifest = RenderManifest(
        title="Fail Book",
        language="en",
        identifier="urn:uuid:11111111-1111-1111-1111-111111111111",
        documents=[RenderedDocument(href="text/part-0001.xhtml", id="part-0001", title="Part 1")],
        styles=[{"id": "css", "href": "styles/book.css", "media_type": "text/css"}],
        assets=[],
        toc=[],
        page_map=[],
    )

    render_result = RenderResult(
        oebps_dir=oebps,
        manifest=manifest,
        source_page_count=1,
        xhtml_part_count=1,
        figure_count=0,
        chart_count=0,
        table_count=0,
        code_count=0,
        math_count=0,
        fallback_count=0,
        warning_count=0,
    )

    packager = EpubPackager()
    output_epub = tmp_path / "out" / "final.epub"
    staging_dir = tmp_path / "staging"
    validation_dir = tmp_path / "val"

    with pytest.raises(PackagingError):
        packager.package(
            render_result=render_result,
            output_epub=output_epub,
            staging_dir=staging_dir,
            validation_dir=validation_dir,
        )

    # Assert candidate was NOT promoted to requested output path
    assert not output_epub.exists()
