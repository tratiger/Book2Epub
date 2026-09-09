"""Typed exception hierarchy for Book2Epub."""

from typing import Any


class Book2EpubError(Exception):
    """Base exception for all Book2Epub errors."""

    def __init__(
        self,
        message: str,
        stage: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.details = details or {}


class NotImplementedStageError(Book2EpubError):
    """Raised when a pipeline stage or CLI command is not yet implemented."""

    def __init__(
        self,
        message: str = "This stage is not yet implemented in the current milestone.",
    ) -> None:
        super().__init__(message, stage="unimplemented")


class SubprocessError(Book2EpubError):
    """Raised when an external subprocess execution fails."""

    def __init__(
        self,
        message: str,
        cmd: list[str],
        exit_code: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(
            message,
            stage="subprocess",
            details={
                "cmd": cmd,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            },
        )
        self.cmd = cmd
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class ConfigurationError(Book2EpubError):
    """Raised for invalid configuration or missing settings."""


class IngestError(Book2EpubError):
    """Raised when page image ingestion or source PDF creation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="ingest", details=details)


class MinerUError(Book2EpubError):
    """Raised when MinerU execution or output parsing fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="mineru", details=details)


class IRError(Book2EpubError):
    """Raised when BookIR normalization or parsing fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="ir", details=details)


class RenderError(Book2EpubError):
    """Raised during XHTML/MathML/CSS rendering."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="render", details=details)


class PackagingError(Book2EpubError):
    """Raised during EPUB 3.3 OCF ZIP or package document creation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="package", details=details)


class ValidationError(Book2EpubError):
    """Raised when internal EPUB validation or EPUBCheck fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="validate", details=details)


class SemanticError(Book2EpubError):
    """Raised during semantic document reconstruction and adjudication."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="semantic", details=details)


class ProviderError(Book2EpubError):
    """Raised when LLM/VLM provider invocation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="provider", details=details)


class VisualReviewError(Book2EpubError):
    """Raised during visual evidence arbitration."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="visual", details=details)


class OCRCorrectionError(Book2EpubError):
    """Raised during OCR correction proposal or validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="ocr_correction", details=details)


class PresentationError(Book2EpubError):
    """Raised during style profile inference or CSS generation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, stage="presentation", details=details)

