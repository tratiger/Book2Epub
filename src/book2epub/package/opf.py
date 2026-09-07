"""EPUB 3.3 package.opf (Package Document) generator."""

from collections.abc import Sequence
from datetime import UTC, datetime

from lxml import etree

from book2epub.package.models import ManifestItem, SpineItem

NS_OPF = "http://www.idpf.org/2007/opf"
NS_DC = "http://purl.org/dc/elements/1.1/"

OPF_NSMAP = {
    None: NS_OPF,
    "dc": NS_DC,
}


def generate_package_opf(
    title: str,
    language: str,
    identifier: str,
    manifest_items: Sequence[ManifestItem],
    spine_items: Sequence[SpineItem],
    authors: Sequence[str] | None = None,
    publisher: str | None = None,
    modified_utc: str | None = None,
) -> bytes:
    """
    Generate XML-serialized package.opf document for EPUB 3.3.
    """
    root = etree.Element(
        f"{{{NS_OPF}}}package",
        nsmap=OPF_NSMAP,
        attrib={
            "version": "3.0",
            "unique-identifier": "pub-id",
        },
    )

    # 1. Metadata
    metadata_el = etree.SubElement(root, f"{{{NS_OPF}}}metadata")

    # dc:identifier
    dc_id = etree.SubElement(metadata_el, f"{{{NS_DC}}}identifier", attrib={"id": "pub-id"})
    dc_id.text = identifier

    # dc:title
    dc_title = etree.SubElement(metadata_el, f"{{{NS_DC}}}title")
    dc_title.text = title

    # dc:language
    dc_lang = etree.SubElement(metadata_el, f"{{{NS_DC}}}language")
    dc_lang.text = language

    # dc:creator
    if authors:
        for author in authors:
            if author.strip():
                dc_creator = etree.SubElement(metadata_el, f"{{{NS_DC}}}creator")
                dc_creator.text = author.strip()

    # dc:publisher
    if publisher and publisher.strip():
        dc_pub = etree.SubElement(metadata_el, f"{{{NS_DC}}}publisher")
        dc_pub.text = publisher.strip()

    # dcterms:modified (UTC format: YYYY-MM-DDTHH:MM:SSZ)
    mod_val = modified_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta_mod = etree.SubElement(
        metadata_el,
        f"{{{NS_OPF}}}meta",
        attrib={"property": "dcterms:modified"},
    )
    meta_mod.text = mod_val

    # 2. Manifest
    manifest_el = etree.SubElement(root, f"{{{NS_OPF}}}manifest")
    for item in manifest_items:
        attribs: dict[str, str] = {
            "id": item.id,
            "href": item.href,
            "media-type": item.media_type,
        }
        if item.properties:
            attribs["properties"] = item.properties
        etree.SubElement(manifest_el, f"{{{NS_OPF}}}item", attrib=attribs)

    # 3. Spine
    spine_el = etree.SubElement(root, f"{{{NS_OPF}}}spine")
    for s in spine_items:
        s_attribs: dict[str, str] = {"idref": s.idref}
        if not s.linear:
            s_attribs["linear"] = "no"
        etree.SubElement(spine_el, f"{{{NS_OPF}}}itemref", attrib=s_attribs)

    return etree.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    )
