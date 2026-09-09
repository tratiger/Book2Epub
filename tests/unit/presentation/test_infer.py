"""Unit tests for presentation style inference and fallback mechanisms (M10)."""

from pathlib import Path
from typing import Any

from PIL import Image

from book2epub.ir.models import BookIR, SourceDocument, SourcePage
from book2epub.paths import create_job_paths
from book2epub.presentation.defaults import DEFAULT_ENHANCED_PROFILE
from book2epub.presentation.infer import infer_style_profile
from book2epub.presentation.models import BookStyleProfileDecision
from book2epub.providers.base import StructuredProvider
from book2epub.providers.models import (
    ProviderUsage,
    StructuredInferenceRequest,
    StructuredInferenceResult,
)
from book2epub.visual.source import VisualSource


class MockStyleProvider(StructuredProvider):
    def __init__(self, decision: BookStyleProfileDecision | None = None, raise_error: bool = False):
        self._decision = decision
        self._raise_error = raise_error
        self.name = "mock-style"
        self.model = "mock-style-model"

    @property
    def supports_vision(self) -> bool:
        return True

    def infer[TBaseModel: Any](
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        if self._raise_error:
            raise RuntimeError("Vision model error")
        audit = StructuredInferenceResult(
            request_id=request.request_id,
            provider=self.name,
            model=self.model,
            raw_text="{}",
            parsed_json={},
            usage=ProviderUsage(),
            latency_ms=100,
        )
        return self._decision, audit  # type: ignore[return-value]


def test_infer_high_confidence_applied(tmp_path: Path) -> None:
    """Verify high-confidence inferred profile is accepted and returned."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(pages_dir / "page_001.png")

    source = VisualSource(images_dir=pages_dir)
    paths = create_job_paths(tmp_path / ".work")
    paths.semantic_visual_pages_dir.mkdir(parents=True, exist_ok=True)

    bookir = BookIR(
        source=SourceDocument(
            page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]
        ),
        blocks=[],
    )

    custom_profile = DEFAULT_ENHANCED_PROFILE.model_copy(
        update={"body": DEFAULT_ENHANCED_PROFILE.body.model_copy(update={"page_margin": "compact"})}
    )
    decision = BookStyleProfileDecision(
        schema_version="1.0",
        profile=custom_profile,
        confidence=0.92,
        evidence_page_indices=[0],
    )
    provider = MockStyleProvider(decision=decision)

    profile, warnings = infer_style_profile(bookir, paths, source, provider)
    assert len(warnings) == 0
    assert profile.confidence == 0.92
    assert profile.mode_source == "inferred"
    assert profile.body.page_margin == "compact"


def test_infer_low_confidence_fallback(tmp_path: Path) -> None:
    """Verify low-confidence inference falls back to DEFAULT_ENHANCED_PROFILE with warning."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(pages_dir / "page_001.png")

    source = VisualSource(images_dir=pages_dir)
    paths = create_job_paths(tmp_path / ".work")
    paths.semantic_visual_pages_dir.mkdir(parents=True, exist_ok=True)

    bookir = BookIR(
        source=SourceDocument(
            page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]
        ),
        blocks=[],
    )

    decision = BookStyleProfileDecision(
        schema_version="1.0",
        profile=DEFAULT_ENHANCED_PROFILE,
        confidence=0.55,  # Below 0.70 threshold
        evidence_page_indices=[0],
    )
    provider = MockStyleProvider(decision=decision)

    profile, warnings = infer_style_profile(bookir, paths, source, provider)
    assert "STYLE_INFERENCE_FALLBACK" in warnings
    assert profile.mode_source == "enhanced_default"


def test_infer_provider_error_fallback(tmp_path: Path) -> None:
    """Verify provider exception safely falls back to DEFAULT_ENHANCED_PROFILE."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    Image.new("RGB", (600, 800), color="white").save(pages_dir / "page_001.png")

    source = VisualSource(images_dir=pages_dir)
    paths = create_job_paths(tmp_path / ".work")
    paths.semantic_visual_pages_dir.mkdir(parents=True, exist_ok=True)

    bookir = BookIR(
        source=SourceDocument(
            page_count=1, pages=[SourcePage(page_idx=0, width=600, height=800)]
        ),
        blocks=[],
    )

    provider = MockStyleProvider(raise_error=True)
    profile, warnings = infer_style_profile(bookir, paths, source, provider)
    assert "STYLE_INFERENCE_FALLBACK" in warnings
    assert profile.mode_source == "enhanced_default"
