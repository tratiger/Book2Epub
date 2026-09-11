"""Path management and job directory layout for Book2Epub."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


def get_repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parent.parent.parent


def get_default_tools_dir() -> Path:
    """Return the default .tools directory."""
    return get_repo_root() / ".tools"


def get_epubcheck_jar_path(tools_dir: Path | None = None) -> Path:
    """Return the path to epubcheck.jar."""
    base = tools_dir or get_default_tools_dir()
    return base / "epubcheck-5.3.0" / "epubcheck.jar"


def generate_job_id(prefix: str = "job") -> str:
    """Generate a unique, filename-safe job ID with UTC timestamp and UUID fragment."""
    now = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    sanitized_prefix = re.sub(r"[^a-zA-Z0-9_-]", "-", prefix).strip("-") or "job"
    return f"{sanitized_prefix}-{now}-{short_uuid}"


@dataclass(frozen=True)
class JobPaths:
    """Standard layout of directories and files for a single conversion job."""

    job_id: str
    root: Path

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def manifest_file(self) -> Path:
        return self.input_dir / "manifest.json"

    @property
    def source_pdf_file(self) -> Path:
        return self.input_dir / "source.pdf"

    @property
    def mineru_dir(self) -> Path:
        return self.root / "mineru"

    @property
    def mineru_raw_dir(self) -> Path:
        return self.mineru_dir / "raw"

    @property
    def mineru_canonical_dir(self) -> Path:
        return self.mineru_dir / "canonical"

    @property
    def mineru_canonical_middle_json(self) -> Path:
        return self.mineru_canonical_dir / "book_middle.json"

    @property
    def mineru_canonical_images_dir(self) -> Path:
        return self.mineru_canonical_dir / "images"

    @property
    def mineru_stage_file(self) -> Path:
        return self.mineru_dir / "stage.json"

    @property
    def ir_dir(self) -> Path:
        return self.root / "ir"

    @property
    def ir_raw_json(self) -> Path:
        return self.ir_dir / "bookir.raw.json"

    @property
    def ir_semantic_json(self) -> Path:
        return self.ir_dir / "bookir.semantic.json"

    @property
    def ir_corrected_json(self) -> Path:
        return self.ir_dir / "bookir.corrected.json"

    @property
    def ir_normalized_json(self) -> Path:
        return self.ir_dir / "bookir.normalized.json"

    @property
    def ir_typography_json(self) -> Path:
        return self.ir_dir / "bookir.typography.json"

    @property
    def normalization_report_file(self) -> Path:
        return self.presentation_dir / "normalization-report.json"

    @property
    def render_dir(self) -> Path:
        return self.root / "render"

    @property
    def render_oebps_dir(self) -> Path:
        return self.render_dir / "OEBPS"

    @property
    def validation_dir(self) -> Path:
        return self.root / "validation"

    @property
    def package_stage_json(self) -> Path:
        return self.root / "package-stage.json"

    @property
    def validate_stage_json(self) -> Path:
        return self.validation_dir / "stage.json"

    @property
    def epubcheck_json_file(self) -> Path:
        return self.validation_dir / "epubcheck.json"

    @property
    def epubcheck_txt_file(self) -> Path:
        return self.validation_dir / "epubcheck.txt"

    @property
    def structural_report_file(self) -> Path:
        return self.validation_dir / "structural-report.json"

    @property
    def qa_dir(self) -> Path:
        return self.root / "qa"

    @property
    def qa_report_html(self) -> Path:
        return self.qa_dir / "report.html"

    @property
    def qa_report_json(self) -> Path:
        return self.qa_dir / "report.json"

    @property
    def qa_stage_json(self) -> Path:
        return self.qa_dir / "stage.json"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "book2epub.log"

    @property
    def semantic_dir(self) -> Path:
        return self.root / "semantic"

    @property
    def semantic_evidence_json(self) -> Path:
        return self.semantic_dir / "evidence.json"

    @property
    def semantic_draft_json(self) -> Path:
        return self.semantic_dir / "draft.json"

    @property
    def semantic_stage_json(self) -> Path:
        return self.semantic_dir / "stage.json"

    @property
    def semantic_chunks_dir(self) -> Path:
        return self.semantic_dir / "chunks"

    @property
    def semantic_decisions_dir(self) -> Path:
        return self.semantic_dir / "decisions"

    @property
    def semantic_book_state_json(self) -> Path:
        return self.semantic_dir / "book_state.json"

    @property
    def semantic_outline_json(self) -> Path:
        return self.semantic_dir / "outline.json"

    @property
    def semantic_applied_json(self) -> Path:
        return self.semantic_dir / "applied.json"

    @property
    def semantic_applied_m8_json(self) -> Path:
        """Provisional M8-only audit artifact; written before M9 visual arbitration.
        The authoritative final artifact is semantic/applied.json (written by pipeline.py
        after M9 updates the audits)."""
        return self.semantic_dir / "applied.m8.json"

    @property
    def semantic_relations_json(self) -> Path:
        """Authoritative Pass B relation reconciliation/application audit."""
        return self.semantic_dir / "relations.json"

    @property
    def semantic_provider_usage_json(self) -> Path:
        return self.semantic_dir / "provider-usage.json"

    @property
    def semantic_visual_dir(self) -> Path:
        return self.semantic_dir / "visual"

    @property
    def semantic_visual_pages_dir(self) -> Path:
        return self.semantic_visual_dir / "pages"

    @property
    def semantic_visual_crops_dir(self) -> Path:
        return self.semantic_visual_dir / "crops"

    @property
    def semantic_visual_stage_json(self) -> Path:
        return self.semantic_visual_dir / "stage.json"

    @property
    def semantic_visual_ir_json(self) -> Path:
        return self.semantic_visual_dir / "bookir.json"

    @property
    def semantic_visual_audits_json(self) -> Path:
        return self.semantic_visual_dir / "audits.json"

    @property
    def semantic_ocr_corrections_json(self) -> Path:
        return self.semantic_dir / "ocr-corrections.json"

    @property
    def semantic_ocr_stage_json(self) -> Path:
        return self.semantic_dir / "ocr-stage.json"

    @property
    def presentation_dir(self) -> Path:
        return self.root / "presentation"

    @property
    def presentation_book_style_profile_json(self) -> Path:
        return self.presentation_dir / "book-style-profile.json"

    @property
    def presentation_style_pages_json(self) -> Path:
        return self.presentation_dir / "style-pages.json"

    @property
    def presentation_stage_json(self) -> Path:
        return self.presentation_dir / "stage.json"

    @property
    def typography_stage_json(self) -> Path:
        return self.presentation_dir / "typography-stage.json"

    @property
    def render_stage_json(self) -> Path:
        return self.render_dir / "stage.json"

    @property
    def presentation_normalization_report_json(self) -> Path:
        return self.presentation_dir / "normalization-report.json"

    def ensure_directories(self) -> None:
        """Create all job directory structure if not already present."""
        for directory in (
            self.input_dir,
            self.mineru_raw_dir,
            self.mineru_canonical_images_dir,
            self.ir_dir,
            self.render_oebps_dir,
            self.validation_dir,
            self.qa_dir,
            self.logs_dir,
            self.semantic_dir,
            self.presentation_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def create_job_paths(work_dir: Path, job_id: str | None = None) -> JobPaths:
    """Create a JobPaths object and initialize directories."""
    jid = job_id or generate_job_id()
    root = work_dir / "jobs" / jid
    paths = JobPaths(job_id=jid, root=root)
    paths.ensure_directories()
    return paths
