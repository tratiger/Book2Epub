"""Native EPUB 3.3 packaging coordinator."""

import logging
import shutil
from collections.abc import Sequence
from pathlib import Path

from book2epub.errors import PackagingError
from book2epub.package.container import generate_container_xml
from book2epub.package.models import ManifestItem, PackagingResult, SpineItem
from book2epub.package.nav import generate_nav_xhtml
from book2epub.package.opf import generate_package_opf
from book2epub.package.validator import run_epubcheck
from book2epub.package.zip import create_epub_zip
from book2epub.render.models import RenderResult

logger = logging.getLogger(__name__)

MIMETYPE_CONTENT = b"application/epub+zip"


class EpubPackager:
    """Packages an unpacked M3 render tree into a verified EPUB 3.3 publication."""

    def __init__(
        self,
        epubcheck_jar: Path | None = None,
        strict: bool = True,
        reproducible: bool = False,
    ) -> None:
        self.epubcheck_jar = epubcheck_jar
        self.strict = strict
        self.reproducible = reproducible

    def package(
        self,
        render_result: RenderResult,
        output_epub: Path,
        staging_dir: Path,
        validation_dir: Path,
        authors: Sequence[str] | None = None,
        publisher: str | None = None,
        modified_utc: str | None = None,
        qa_report_path: Path | None = None,
    ) -> PackagingResult:
        """
        Assemble the EPUB staging tree, write container/opf/nav, package to ZIP,
        and validate with internal checks and EPUBCheck 5.3.0.
        """
        manifest_data = render_result.manifest

        # 1. Clean and initialize staging tree: render/epub-root/
        epub_root = staging_dir / "epub-root"
        if epub_root.exists():
            shutil.rmtree(epub_root)
        epub_root.mkdir(parents=True, exist_ok=True)

        meta_inf_dir = epub_root / "META-INF"
        meta_inf_dir.mkdir(parents=True, exist_ok=True)

        oebps_dest = epub_root / "OEBPS"
        oebps_dest.mkdir(parents=True, exist_ok=True)

        # 2. Write root 'mimetype'
        mimetype_path = epub_root / "mimetype"
        mimetype_path.write_bytes(MIMETYPE_CONTENT)

        # 3. Write 'META-INF/container.xml'
        container_path = meta_inf_dir / "container.xml"
        container_path.write_text(generate_container_xml(), encoding="utf-8")

        # 4. Copy text, styles, and images from render_result.oebps_dir to OEBPS/
        for sub_dir in ("text", "styles", "images"):
            src_sub = render_result.oebps_dir / sub_dir
            if src_sub.is_dir():
                dest_sub = oebps_dest / sub_dir
                shutil.copytree(src_sub, dest_sub, dirs_exist_ok=True)

        # 5. Generate and write OEBPS/nav.xhtml
        first_doc = (
            manifest_data.documents[0].href if manifest_data.documents else "text/part-0001.xhtml"
        )
        nav_bytes = generate_nav_xhtml(
            title=manifest_data.title,
            language=manifest_data.language,
            toc_entries=manifest_data.toc,
            page_map_entries=manifest_data.page_map,
            first_doc_href=first_doc,
        )
        nav_path = oebps_dest / "nav.xhtml"
        nav_path.write_bytes(nav_bytes)

        # 6. Build manifest items for package.opf
        manifest_items: list[ManifestItem] = [
            ManifestItem(
                id="nav",
                href="nav.xhtml",
                media_type="application/xhtml+xml",
                properties="nav",
            )
        ]

        # Stylesheets
        for style in manifest_data.styles:
            manifest_items.append(
                ManifestItem(
                    id=style["id"],
                    href=style["href"],
                    media_type=style["media_type"],
                )
            )

        # Content documents
        spine_items: list[SpineItem] = []
        for doc in manifest_data.documents:
            props = "mathml" if doc.contains_mathml else None
            manifest_items.append(
                ManifestItem(
                    id=doc.id,
                    href=doc.href,
                    media_type=doc.media_type,
                    properties=props,
                )
            )
            spine_items.append(SpineItem(idref=doc.id))

        # Assets (images)
        for asset in manifest_data.assets:
            manifest_items.append(
                ManifestItem(
                    id=asset["id"],
                    href=asset["href"],
                    media_type=asset["media_type"],
                    properties="cover-image" if asset["role"] == "cover" else None,
                )
            )

        mod_time = modified_utc
        if self.reproducible and not mod_time:
            mod_time = "1980-01-01T00:00:00Z"

        # 7. Generate and write OEBPS/package.opf
        opf_bytes = generate_package_opf(
            title=manifest_data.title,
            language=manifest_data.language,
            identifier=manifest_data.identifier,
            manifest_items=manifest_items,
            spine_items=spine_items,
            authors=authors,
            publisher=publisher,
            modified_utc=mod_time,
        )
        opf_path = oebps_dest / "package.opf"
        opf_path.write_bytes(opf_bytes)

        # 8. Create candidate EPUB archive in validation dir
        validation_dir.mkdir(parents=True, exist_ok=True)
        candidate_epub = validation_dir / "candidate.epub"
        if candidate_epub.exists():
            candidate_epub.unlink()

        create_epub_zip(
            staging_dir=epub_root,
            target_epub_path=candidate_epub,
            reproducible=self.reproducible,
        )

        # 9. Validate candidate with EPUBCheck 5.3.0 and internal checks
        json_report_path = validation_dir / "epubcheck.json"
        txt_report_path = validation_dir / "epubcheck.txt"

        report = run_epubcheck(
            candidate_epub,
            epubcheck_jar=self.epubcheck_jar,
            json_report_path=json_report_path,
            txt_report_path=txt_report_path,
            fail_on_warnings=self.strict,
        )

        if not report.is_valid:
            error_msgs = [f"[{i.severity}] {i.message} ({i.location or ''})" for i in report.issues]
            summary = "\n".join(error_msgs[:15])
            raise PackagingError(
                f"EPUBCheck validation failed with {report.error_count} errors, "
                f"{report.warning_count} warnings:\n{summary}\n"
                f"Full report saved to: {json_report_path}"
            )

        # 10. Atomically promote candidate to requested output path
        output_epub.parent.mkdir(parents=True, exist_ok=True)
        if output_epub.exists():
            output_epub.unlink()
        shutil.copy2(candidate_epub, output_epub)

        file_size = output_epub.stat().st_size

        return PackagingResult(
            epub_path=output_epub,
            file_size_bytes=file_size,
            source_page_count=render_result.source_page_count,
            xhtml_part_count=render_result.xhtml_part_count,
            figure_count=render_result.figure_count,
            chart_count=render_result.chart_count,
            table_count=render_result.table_count,
            code_count=render_result.code_count,
            math_count=render_result.math_count,
            fallback_count=render_result.fallback_count,
            warning_count=render_result.warning_count,
            validation_report=report,
            qa_report_path=qa_report_path or json_report_path,
        )
