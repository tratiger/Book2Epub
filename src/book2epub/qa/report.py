"""Generation of offline diagnostic reports (qa/report.json and qa/report.html)."""

import json
import logging
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from book2epub.config import JobConfig
from book2epub.ir.models import (
    BookIR,
    Chart,
    Figure,
    Heading,
    UnknownBlock,
)
from book2epub.package.models import PackagingResult
from book2epub.qa.checks import run_structural_checks
from book2epub.qa.models import (
    OCRQAMetrics,
    PageQASummary,
    PresentationQAMetrics,
    PreservationLedgerEntry,
    QAReportData,
    SemanticQAMetrics,
)
from book2epub.render.models import RenderResult
from book2epub.version import __version__

logger = logging.getLogger(__name__)


def generate_qa_report(
    job_id: str,
    raw_middle_data: dict[str, Any],
    book_ir: BookIR,
    render_result: RenderResult,
    packaging_result: PackagingResult,
    cfg: JobConfig,
    report_json_path: Path,
    report_html_path: Path,
    manifest_data: dict[str, Any] | None = None,
    preservation_ledger: list[PreservationLedgerEntry] | None = None,
    semantic_metrics: SemanticQAMetrics | None = None,
    ocr_metrics: OCRQAMetrics | None = None,
    presentation_metrics: PresentationQAMetrics | None = None,
    violations: list[Any] | None = None,
) -> QAReportData:
    """Generate comprehensive JSON and standalone HTML QA reports for a conversion job."""
    # 1. Environment & Dependency info
    env_info = {
        "book2epub_version": __version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "mineru_pinned_version": "3.4.5",
        "epubcheck_version": "5.3.0",
    }

    # 2. Block counts by type
    block_counts: dict[str, int] = {}
    for b in book_ir.blocks:
        k = b.kind
        block_counts[k] = block_counts.get(k, 0) + 1

    # 3. Heading level distribution
    level_dist: dict[str, int] = {}
    for b in book_ir.blocks:
        if isinstance(b, Heading):
            lvl_key = f"h{b.level}" if b.level else "h_unspecified"
            level_dist[lvl_key] = level_dist.get(lvl_key, 0) + 1

    # 4. Page number table
    page_table: list[dict[str, Any]] = []
    for sp in book_ir.source.pages:
        page_table.append(
            {
                "page_idx": sp.page_idx,
                "raw_text": sp.printed_label or "",
                "parsed_label": sp.printed_label or str(sp.page_idx + 1),
                "confidence": round(sp.printed_label_confidence, 2),
                "scheme": "numeric",
            }
        )

    # 5. Page-level QA entries
    pages_qa: list[PageQASummary] = []
    # Map blocks to pages
    page_blocks_map: dict[int, list[str]] = {}
    for b in book_ir.blocks:
        p_idx = b.sources[0].page_idx if b.sources else 0
        page_blocks_map.setdefault(p_idx, []).append(b.id)

    # Map render targets
    render_targets_map: dict[int, list[str]] = {}
    for pm in render_result.manifest.page_map:
        render_targets_map.setdefault(pm.page_idx, []).append(f"{pm.xhtml_path}#{pm.fragment_id}")

    for idx, p_info in enumerate(raw_middle_data.get("pdf_info", [])):
        p_idx = p_info.get("page_idx", idx)
        lbl = (
            book_ir.source.pages[p_idx].printed_label
            if p_idx < len(book_ir.source.pages) and book_ir.source.pages[p_idx].printed_label
            else str(p_idx + 1)
        )
        b_types = [b.get("type", "unknown") for b in p_info.get("para_blocks", [])]

        pages_qa.append(
            PageQASummary(
                page_idx=p_idx,
                printed_label=lbl,
                source_image_rel=f"input/page_{p_idx+1:04d}.jpg",
                source_blocks_count=len(b_types),
                source_block_types=b_types[:10],
                bookir_block_ids=page_blocks_map.get(p_idx, []),
                rendered_target_hrefs=render_targets_map.get(p_idx, []),
                warnings=[],
            )
        )

    # 6. Structural quality checks & metrics
    checks, metrics = run_structural_checks(
        raw_middle_data=raw_middle_data,
        book_ir=book_ir,
        render_result=render_result,
        packaging_result=packaging_result,
        preservation_ledger=preservation_ledger,
        is_semantic=cfg.semantic.enabled,
    )

    # 7. Collect warnings
    missing_caps = [
        f"Block {b.id} missing caption/alt"
        for b in book_ir.blocks
        if isinstance(b, (Figure, Chart)) and not b.caption
    ]
    unknown_blocks = [
        f"Unknown block {b.id} (type: {b.source_type})"
        for b in book_ir.blocks
        if isinstance(b, UnknownBlock)
    ]

    qa_data = QAReportData(
        job_id=job_id,
        timestamp_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        environment=env_info,
        input_manifest=manifest_data or {"total_pages": len(book_ir.source.pages)},
        mineru_config={
            "version": cfg.mineru.version,
            "backend": cfg.mineru.backend,
            "effort": cfg.mineru.effort,
            "method": cfg.mineru.method,
        },
        bookir_block_counts=block_counts,
        fallback_counts={
            "math_fallbacks": render_result.fallback_count,
            "table_fallbacks": 0,
        },
        title_level_distribution=level_dist,
        page_number_table=page_table,
        missing_caption_warnings=missing_caps,
        unknown_block_warnings=unknown_blocks,
        cross_page_merges_count=0,
        dehyphenations_count=0,
        table_sanitizer_fallbacks_count=0,
        math_conversion_fallbacks_count=render_result.fallback_count,
        epub_internal_validation={
            "passed": packaging_result.validation_report.fatal_count == 0
            and packaging_result.validation_report.error_count == 0,
            "issues_count": len(packaging_result.validation_report.issues),
        },
        epubcheck_validation={
            "exit_code": packaging_result.validation_report.epubcheck_exit_code,
            "error_count": packaging_result.validation_report.error_count,
            "warning_count": packaging_result.validation_report.warning_count,
            "passed": packaging_result.validation_report.is_valid,
        },
        structural_checks=checks,
        metrics=metrics,
        pages=pages_qa,
        preservation_ledger=preservation_ledger or [],
        violations=violations or [],
        semantic_metrics=semantic_metrics,
        ocr_metrics=ocr_metrics,
        presentation_metrics=presentation_metrics,
    )

    # Write report.json
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(qa_data.to_dict(), indent=2), encoding="utf-8")

    # Render standalone report.html
    html_content = _render_qa_html(qa_data)
    report_html_path.parent.mkdir(parents=True, exist_ok=True)
    report_html_path.write_text(html_content, encoding="utf-8")

    logger.info("Generated QA reports at %s and %s", report_json_path, report_html_path)
    return qa_data


def _render_qa_html(qa: QAReportData) -> str:
    checks_rows_list: list[str] = []
    for c in qa.structural_checks:
        badge_cls = "badge-pass" if c.passed else "badge-fail"
        badge_txt = "PASS" if c.passed else "FAIL"
        checks_rows_list.append(
            f"<tr><td><strong>{c.name}</strong></td>"
            f'<td><span class="badge {badge_cls}">{badge_txt}</span></td>'
            f"<td>{c.source_count}</td><td>{c.target_count}</td>"
            f"<td>{c.details}</td></tr>"
        )
    checks_rows = "".join(checks_rows_list)

    pages_rows = "".join(
        f"""
        <tr>
          <td>{p.page_idx + 1}</td>
          <td><strong>{p.printed_label}</strong></td>
          <td>{p.source_blocks_count}</td>
          <td><code>{', '.join(p.source_block_types[:6])}</code></td>
          <td>{len(p.bookir_block_ids)} blocks</td>
          <td>{'<br/>'.join(p.rendered_target_hrefs)}</td>
        </tr>
        """
        for p in qa.pages
    )

    epubcheck_color = "#16a34a" if qa.epubcheck_validation.get("passed") else "#dc2626"
    epubcheck_status = "PASS" if qa.epubcheck_validation.get("passed") else "FAIL"

    semantic_section = ""
    if qa.semantic_metrics:
        trans_rows = "".join(
            f"<tr><td><code>{k}</code></td><td>{v}</td></tr>"
            for k, v in qa.semantic_metrics.type_transitions.items()
        )
        semantic_section = f"""
    <h2>Semantic Reconstruction & Type Transitions</h2>
    <div class="grid">
      <div class="card">
        <div class="metric-lbl">Change Rate</div>
        <div class="metric-val">{qa.semantic_metrics.semantic_change_rate * 100:.1f}%</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Auto-Apply Rate</div>
        <div class="metric-val">{qa.semantic_metrics.semantic_auto_apply_rate * 100:.1f}%</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Conflict Rate</div>
        <div class="metric-val">{qa.semantic_metrics.semantic_conflict_rate * 100:.1f}%</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Heading Level Known</div>
        <div class="metric-val">{qa.semantic_metrics.heading_level_known_rate * 100:.1f}%</div>
      </div>
    </div>
    <table>
      <thead>
        <tr><th>Transition (Old -> New)</th><th>Count</th></tr>
      </thead>
      <tbody>
        {trans_rows or "<tr><td colspan='2'>No type transitions recorded.</td></tr>"}
      </tbody>
    </table>
    """

    ocr_section = ""
    if qa.ocr_metrics and qa.ocr_metrics.ocr_mode != "off":
        ocr_section = f"""
    <h2>Multimodal OCR Correction</h2>
    <div class="grid">
      <div class="card">
        <div class="metric-lbl">OCR Mode</div>
        <div class="metric-val" style="font-size: 1.25rem;">{qa.ocr_metrics.ocr_mode}</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Applied Edits</div>
        <div class="metric-val">{qa.ocr_metrics.ocr_applied_count}</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Changed Codepoints</div>
        <div class="metric-val">{qa.ocr_metrics.ocr_changed_codepoints}</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Sensitive Confirmed</div>
        <div class="metric-val">{qa.ocr_metrics.ocr_sensitive_confirmation_count}</div>
      </div>
    </div>
    """

    pres_section = ""
    if qa.presentation_metrics:
        pres_section = f"""
    <h2>Presentation & Typography Quality</h2>
    <div class="grid">
      <div class="card">
        <div class="metric-lbl">Presentation Mode</div>
        <div class="metric-val" style="font-size: 1.25rem;">
          {qa.presentation_metrics.presentation_mode}
        </div>
      </div>
      <div class="card">
        <div class="metric-lbl">Duplicate List Markers</div>
        <div class="metric-val" style="color: {
            '#16a34a' if qa.presentation_metrics.list_duplicate_marker_count == 0 else '#dc2626'
        };">
          {qa.presentation_metrics.list_duplicate_marker_count}
        </div>
      </div>
      <div class="card">
        <div class="metric-lbl">Components Rendered</div>
        <div class="metric-val">{sum(qa.presentation_metrics.component_counts.values())}</div>
      </div>
    </div>
    """

    violations_section = ""
    if qa.violations:
        viol_rows = []
        for v in qa.violations:
            sev = getattr(v, "severity", "warning").lower()
            sev_cls = "badge-fail" if sev in ("fatal", "error") else "badge-warn"
            block_id = getattr(v, "block_id", None)
            page_idx = getattr(v, "page_idx", None)
            scope = f"Block: {block_id or 'N/A'}"
            if page_idx is not None:
                scope += f" (p.{page_idx + 1})"
            viol_rows.append(
                f"<tr>"
                f'<td><span class="badge {sev_cls}">{sev.upper()}</span></td>'
                f"<td><code>{getattr(v, 'category', '')}</code></td>"
                f"<td><strong>{getattr(v, 'code', '')}</strong></td>"
                f"<td>{scope}</td>"
                f"<td>{getattr(v, 'message', '')}</td>"
                f"</tr>"
            )
        violations_section = f"""
    <h2>QA Safety & Release Invariant Violations</h2>
    <table>
      <thead>
        <tr><th>Severity</th><th>Category</th><th>Code</th><th>Scope</th><th>Reason</th></tr>
      </thead>
      <tbody>
        {''.join(viol_rows)}
      </tbody>
    </table>
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Book2Epub QA Diagnostic Report - {qa.job_id}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0; padding: 2rem; background: #f8fafc; color: #1e293b; line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    h1, h2, h3 {{ color: #0f172a; margin-top: 1.5rem; }}
    .header {{ border-bottom: 2px solid #e2e8f0; padding-bottom: 1rem; margin-bottom: 2rem; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .card {{
      background: white;
      padding: 1.25rem;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      border: 1px solid #e2e8f0;
    }}
    .metric-val {{ font-size: 1.75rem; font-weight: 700; color: #2563eb; margin-top: 0.25rem; }}
    .metric-lbl {{
      font-size: 0.875rem;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      margin-bottom: 2rem;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    th, td {{
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid #e2e8f0;
      font-size: 0.9rem;
    }}
    th {{ background: #f1f5f9; font-weight: 600; color: #475569; }}
    .badge {{
      display: inline-block;
      padding: 0.25rem 0.5rem;
      border-radius: 4px;
      font-weight: 600;
      font-size: 0.75rem;
    }}
    .badge-pass {{ background: #dcfce7; color: #166534; }}
    .badge-fail {{ background: #fee2e2; color: #991b1b; }}
    .badge-warn {{ background: #fef08a; color: #854d0e; }}
    .badge-info {{ background: #e0f2fe; color: #0369a1; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Book2Epub QA Diagnostic Report</h1>
      <p>Job ID: <code>{qa.job_id}</code> | Generated: {qa.timestamp_utc} (UTC)</p>
    </div>

    {violations_section}

    <h2>Structural Quality & Losslessness Metrics</h2>
    <div class="grid">
      <div class="card">
        <div class="metric-lbl">Block Coverage</div>
        <div class="metric-val">{qa.metrics.block_coverage * 100:.1f}%</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Math Semantic Rate</div>
        <div class="metric-val">{qa.metrics.math_semantic_rate * 100:.1f}%</div>
      </div>
      <div class="card">
        <div class="metric-lbl">Table Semantic Rate</div>
        <div class="metric-val">{qa.metrics.table_semantic_rate * 100:.1f}%</div>
      </div>
      <div class="card">
        <div class="metric-lbl">EPUBCheck Status</div>
        <div class="metric-val" style="color: {epubcheck_color};">
          {epubcheck_status}
        </div>
      </div>
    </div>

    {semantic_section}
    {ocr_section}
    {pres_section}

    <h2>Reconciliation Checks</h2>
    <table>
      <thead>
        <tr>
          <th>Check</th>
          <th>Status</th>
          <th>Source Count</th>
          <th>Target Count</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {checks_rows}
      </tbody>
    </table>

    <h2>Source Page Diagnostics</h2>
    <table>
      <thead>
        <tr>
          <th>Page</th>
          <th>Label</th>
          <th>Source Blocks</th>
          <th>Block Types</th>
          <th>BookIR Blocks</th>
          <th>Render Targets</th>
        </tr>
      </thead>
      <tbody>
        {pages_rows}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
