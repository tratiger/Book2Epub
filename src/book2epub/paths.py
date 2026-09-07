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
    def ir_normalized_json(self) -> Path:
        return self.ir_dir / "bookir.normalized.json"

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
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "book2epub.log"

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
        ):
            directory.mkdir(parents=True, exist_ok=True)


def create_job_paths(work_dir: Path, job_id: str | None = None) -> JobPaths:
    """Create a JobPaths object and initialize directories."""
    jid = job_id or generate_job_id()
    root = work_dir / "jobs" / jid
    paths = JobPaths(job_id=jid, root=root)
    paths.ensure_directories()
    return paths
