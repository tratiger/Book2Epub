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
        self.last_request: StructuredInferenceRequest | None = None

    @property
    def supports_vision(self) -> bool:
        return True

    def infer[TBaseModel: Any](
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        self.last_request = request
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


def test_infer_only_attached_pages_are_valid_evidence(tmp_path: Path, monkeypatch) -> None:
    """A rasterization failure must remove that page from prompt/evidence scope."""
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    for page_idx in range(3):
        Image.new("RGB", (600, 800), color="white").save(
            pages_dir / f"page_{page_idx + 1:03d}.png"
        )

    source = VisualSource(images_dir=pages_dir)
    paths = create_job_paths(tmp_path / ".work")
    paths.semantic_visual_pages_dir.mkdir(parents=True, exist_ok=True)
    bookir = BookIR(
        source=SourceDocument(
            page_count=3,
            pages=[SourcePage(page_idx=i, width=600, height=800) for i in range(3)],
        ),
        blocks=[],
    )
    monkeypatch.setattr(
        "book2epub.presentation.infer.select_representative_pages",
        lambda bookir, max_pages: [0, 1, 2],
    )

    def fake_rasterize(self, page_idx: int, max_edge: int):
        if page_idx == 1:
            raise OSError("synthetic raster failure")
        return pages_dir / f"page_{page_idx + 1:03d}.png", (600, 800)

    monkeypatch.setattr(
        "book2epub.presentation.infer.PageRasterCache.get_page_image",
        fake_rasterize,
    )
    provider = MockStyleProvider(
        decision=BookStyleProfileDecision(
            schema_version="1.0",
            profile=DEFAULT_ENHANCED_PROFILE,
            confidence=0.95,
            evidence_page_indices=[1],
        )
    )

    profile, warnings = infer_style_profile(bookir, paths, source, provider)

    assert profile.mode_source == "enhanced_default"
    assert "STYLE_INFERENCE_FALLBACK" in warnings
    assert provider.last_request is not None
    assert "indices: [0, 2]" in provider.last_request.user_text
    assert "indices: [0, 1, 2]" not in provider.last_request.user_text
    assert [image.label for image in provider.last_request.images] == ["Page 1", "Page 3"]


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
