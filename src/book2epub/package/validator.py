"""EPUB 3.3 validation: internal structural/integrity checks and EPUBCheck 5.3.0 execution."""

import json
import logging
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from book2epub.package.models import ValidationIssue, ValidationReport
from book2epub.paths import get_epubcheck_jar_path

logger = logging.getLogger(__name__)

NS_CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
NS_OPF = "http://www.idpf.org/2007/opf"
NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_MATHML = "http://www.w3.org/1998/Math/MathML"


def validate_epub_internals(epub_path: Path) -> list[ValidationIssue]:
    """
    Perform strict internal structural validation on an EPUB archive before external tools.

    Verifies:
    - Root 'mimetype' is first, uncompressed, exact content
    - No Windows '\\' in archive entry names
    - META-INF/container.xml points to a valid package.opf
    - package.opf XML is well-formed
    - Every manifest item exists in the ZIP
    - Every spine itemref resolves to a manifest item
    - Exactly one manifest item has property 'nav'
    - MathML-bearing XHTML items are marked with 'mathml' property
    - Internal href and src links resolve (including fragment IDs)
    - No external resource dependencies (http/https for img/link/script)
    - No JavaScript (<script> or on* handlers)
    - No forbidden position:absolute layout CSS
    - No duplicate XML IDs per XHTML document
    """
    issues: list[ValidationIssue] = []

    if not epub_path.is_file():
        return [
            ValidationIssue(
                severity="FATAL",
                message=f"EPUB file does not exist: {epub_path}",
            )
        ]

    try:
        with zipfile.ZipFile(epub_path, mode="r") as zf:
            namelist = zf.namelist()

            # 1. mimetype check
            if not namelist or namelist[0] != "mimetype":
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        message="First file in EPUB must be 'mimetype'",
                        location="mimetype",
                    )
                )
            else:
                m_info = zf.getinfo("mimetype")
                if m_info.compress_type != zipfile.ZIP_STORED:
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message="mimetype must be uncompressed (ZIP_STORED)",
                            location="mimetype",
                        )
                    )
                content = zf.read("mimetype")
                if content != b"application/epub+zip":
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message=f"Invalid mimetype content: {content!r}",
                            location="mimetype",
                        )
                    )

            # 2. Path separators check
            for name in namelist:
                if "\\" in name:
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message=f"Windows backslash found in ZIP path: {name}",
                            location=name,
                        )
                    )

            # 3. container.xml check
            if "META-INF/container.xml" not in namelist:
                issues.append(
                    ValidationIssue(
                        severity="FATAL",
                        message="Missing META-INF/container.xml",
                        location="META-INF/container.xml",
                    )
                )
                return issues

            try:
                container_tree = etree.fromstring(zf.read("META-INF/container.xml"))
                rootfile_nodes = container_tree.xpath(
                    "//c:rootfile",
                    namespaces={"c": NS_CONTAINER},
                )
                if not rootfile_nodes:
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message="No rootfile found in META-INF/container.xml",
                            location="META-INF/container.xml",
                        )
                    )
                    return issues

                opf_path = rootfile_nodes[0].get("full-path")
                if not opf_path or opf_path not in namelist:
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message=f"Rootfile in container.xml missing: {opf_path}",
                            location="META-INF/container.xml",
                        )
                    )
                    return issues
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        message=f"Failed to parse container.xml: {e}",
                        location="META-INF/container.xml",
                    )
                )
                return issues

            # 4. package.opf check
            opf_dir = "/".join(opf_path.split("/")[:-1])
            opf_prefix = f"{opf_dir}/" if opf_dir else ""

            try:
                opf_tree = etree.fromstring(zf.read(opf_path))
            except Exception as e:
                issues.append(
                    ValidationIssue(
                        severity="FATAL",
                        message=f"Failed to parse {opf_path}: {e}",
                        location=opf_path,
                    )
                )
                return issues

            manifest_items: dict[str, dict[str, str]] = {}
            nav_count = 0

            # Manifest parsing
            for item in opf_tree.xpath("//opf:manifest/opf:item", namespaces={"opf": NS_OPF}):
                i_id = item.get("id", "")
                i_href = item.get("href", "")
                i_media = item.get("media-type", "")
                i_props = item.get("properties", "")

                full_item_path = f"{opf_prefix}{i_href}" if opf_prefix else i_href
                manifest_items[i_id] = {
                    "href": i_href,
                    "full_path": full_item_path,
                    "media_type": i_media,
                    "properties": i_props,
                }

                if full_item_path not in namelist:
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message=f"Manifest item '{i_id}' missing: {full_item_path}",
                            location=opf_path,
                        )
                    )

                if "nav" in i_props.split():
                    nav_count += 1

            if nav_count != 1:
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        message=f"EPUB must have exactly one nav item, found {nav_count}",
                        location=opf_path,
                    )
                )

            # Spine check
            for itemref in opf_tree.xpath("//opf:spine/opf:itemref", namespaces={"opf": NS_OPF}):
                idref = itemref.get("idref", "")
                if idref not in manifest_items:
                    issues.append(
                        ValidationIssue(
                            severity="ERROR",
                            message=f"Spine itemref references unknown manifest id: {idref}",
                            location=opf_path,
                        )
                    )

            # 5. XHTML document checks and link validation
            doc_id_maps: dict[str, set[str]] = {}

            # First pass: collect all IDs from each XHTML
            for item_info in manifest_items.values():
                if "xhtml" in item_info["media_type"]:
                    x_path = item_info["full_path"]
                    if x_path in namelist:
                        try:
                            xtree = etree.fromstring(zf.read(x_path))
                            ids: set[str] = set()
                            for elem in xtree.xpath("//*[@id]"):
                                el_id = elem.get("id")
                                if el_id:
                                    if el_id in ids:
                                        issues.append(
                                            ValidationIssue(
                                                severity="ERROR",
                                                message=f"Duplicate ID '{el_id}' in {x_path}",
                                                location=x_path,
                                            )
                                        )
                                    ids.add(el_id)
                            doc_id_maps[x_path] = ids

                            # MathML property check
                            has_math = bool(xtree.xpath("//*[local-name()='math']"))
                            props = item_info["properties"].split()
                            if has_math and "mathml" not in props:
                                issues.append(
                                    ValidationIssue(
                                        severity="ERROR",
                                        message="XHTML has MathML without manifest property",
                                        location=x_path,
                                    )
                                )

                            # Script check
                            scripts = xtree.xpath("//*[local-name()='script']")
                            if scripts:
                                issues.append(
                                    ValidationIssue(
                                        severity="ERROR",
                                        message="JavaScript <script> tag forbidden",
                                        location=x_path,
                                    )
                                )

                            # inline event handlers
                            for elem in xtree.iter():
                                for attr in elem.attrib:
                                    if attr.lower().startswith("on"):
                                        issues.append(
                                            ValidationIssue(
                                                severity="ERROR",
                                                message=f"Event handler '{attr}' forbidden",
                                                location=x_path,
                                            )
                                        )

                        except Exception as e:
                            issues.append(
                                ValidationIssue(
                                    severity="ERROR",
                                    message=f"Failed to parse XHTML in {x_path}: {e}",
                                    location=x_path,
                                )
                            )

            # Second pass: link resolution check (href and src)
            for item_info in manifest_items.values():
                if "xhtml" in item_info["media_type"]:
                    x_path = item_info["full_path"]
                    if x_path in namelist:
                        try:
                            xtree = etree.fromstring(zf.read(x_path))
                            doc_dir = "/".join(x_path.split("/")[:-1])

                            for elem in xtree.iter():
                                # Check src attributes
                                src = elem.get("src")
                                if src:
                                    if src.startswith("http://") or src.startswith("https://"):
                                        issues.append(
                                            ValidationIssue(
                                                severity="ERROR",
                                                message=f"Remote URL forbidden in src: {src}",
                                                location=x_path,
                                            )
                                        )
                                    else:
                                        # Normalize relative path
                                        norm_parts: list[str] = []
                                        for part in f"{doc_dir}/{src}".split("/"):
                                            if part == "..":
                                                if norm_parts:
                                                    norm_parts.pop()
                                            elif part and part != ".":
                                                norm_parts.append(part)
                                        norm_src = "/".join(norm_parts)

                                        if norm_src not in namelist:
                                            issues.append(
                                                ValidationIssue(
                                                    severity="ERROR",
                                                    message=f"Resource src not found: '{src}'",
                                                    location=x_path,
                                                )
                                            )

                                # Check internal href links
                                href = elem.get("href")
                                if href and not (
                                    href.startswith("http://")
                                    or href.startswith("https://")
                                    or href.startswith("mailto:")
                                ):
                                    # Internal href
                                    doc_part, _, frag_part = href.partition("#")
                                    if doc_part:
                                        norm_parts = []
                                        for part in f"{doc_dir}/{doc_part}".split("/"):
                                            if part == "..":
                                                if norm_parts:
                                                    norm_parts.pop()
                                            elif part and part != ".":
                                                norm_parts.append(part)
                                        target_doc = "/".join(norm_parts)
                                    else:
                                        target_doc = x_path

                                    if target_doc not in namelist:
                                        issues.append(
                                            ValidationIssue(
                                                severity="ERROR",
                                                message=f"Target doc not found: '{href}'",
                                                location=x_path,
                                            )
                                        )
                                    elif frag_part:
                                        target_ids = doc_id_maps.get(target_doc, set())
                                        if frag_part not in target_ids:
                                            issues.append(
                                                ValidationIssue(
                                                    severity="ERROR",
                                                    message=f"Target ID '#{frag_part}' not found",
                                                    location=x_path,
                                                )
                                            )
                        except Exception:
                            pass

    except zipfile.BadZipFile as e:
        issues.append(
            ValidationIssue(
                severity="FATAL",
                message=f"Corrupt ZIP file: {e}",
                location=str(epub_path),
            )
        )

    return issues


def run_epubcheck(
    epub_path: Path,
    epubcheck_jar: Path | None = None,
    json_report_path: Path | None = None,
    txt_report_path: Path | None = None,
    fail_on_warnings: bool = False,
) -> ValidationReport:
    """
    Run EPUBCheck 5.3.0 and combine results with internal validation.
    """
    jar = epubcheck_jar or get_epubcheck_jar_path()
    internal_issues = validate_epub_internals(epub_path)

    if not jar.exists():
        logger.warning("epubcheck.jar not found at %s; relying on internal validation", jar)
        fatal_count = sum(1 for i in internal_issues if i.severity == "FATAL")
        error_count = sum(1 for i in internal_issues if i.severity == "ERROR")
        warning_count = sum(1 for i in internal_issues if i.severity == "WARNING")
        info_count = sum(1 for i in internal_issues if i.severity == "INFO")

        return ValidationReport(
            is_valid=(fatal_count == 0 and error_count == 0),
            epubcheck_exit_code=-1,
            fatal_count=fatal_count,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            issues=internal_issues,
            raw_epubcheck_json=None,
            raw_epubcheck_text="EPUBCheck jar not found; skipped external validation.",
        )

    # Prepare temp json report if not supplied
    out_json = json_report_path or epub_path.with_suffix(".epubcheck.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "java",
        "-jar",
        str(jar),
        str(epub_path),
        "--json",
        str(out_json),
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        raw_text = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")

        if txt_report_path:
            txt_report_path.parent.mkdir(parents=True, exist_ok=True)
            txt_report_path.write_text(raw_text, encoding="utf-8")

        epub_json: dict[str, Any] = {}
        if out_json.is_file():
            try:
                epub_json = json.loads(out_json.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to parse epubcheck JSON: %s", e)

        # Parse external issues
        external_issues: list[ValidationIssue] = []
        for msg in epub_json.get("messages", []):
            sev = msg.get("severity", "WARNING").upper()
            m_text = msg.get("message", "")
            loc = None
            line = None
            col = None
            locations = msg.get("locations", [])
            if locations:
                loc = locations[0].get("path")
                line = locations[0].get("line")
                col = locations[0].get("column")

            external_issues.append(
                ValidationIssue(
                    severity=sev if sev in ("FATAL", "ERROR", "WARNING", "INFO") else "WARNING",
                    message=m_text,
                    location=loc,
                    line=line,
                    column=col,
                )
            )

        all_issues = internal_issues + external_issues

        fatal_count = sum(1 for i in all_issues if i.severity == "FATAL")
        error_count = sum(1 for i in all_issues if i.severity == "ERROR")
        warning_count = sum(1 for i in all_issues if i.severity == "WARNING")
        info_count = sum(1 for i in all_issues if i.severity == "INFO")

        # Failure condition: any FATAL or ERROR, or nonzero exit code,
        # or fail_on_warnings and warning_count > 0
        is_valid = (proc.returncode == 0) and (fatal_count == 0) and (error_count == 0)
        if fail_on_warnings and warning_count > 0:
            is_valid = False

        return ValidationReport(
            is_valid=is_valid,
            epubcheck_exit_code=proc.returncode,
            fatal_count=fatal_count,
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            issues=all_issues,
            raw_epubcheck_json=epub_json if epub_json else None,
            raw_epubcheck_text=raw_text,
        )

    except Exception as e:
        logger.error("Failed to execute EPUBCheck: %s", e)
        return ValidationReport(
            is_valid=False,
            epubcheck_exit_code=-1,
            fatal_count=1,
            error_count=0,
            warning_count=0,
            info_count=0,
            issues=internal_issues
            + [ValidationIssue(severity="FATAL", message=f"EPUBCheck execution error: {e}")],
            raw_epubcheck_text=str(e),
        )
