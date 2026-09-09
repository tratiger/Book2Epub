"""Presentation stage orchestrator for resolving BookStyleProfile (M10/Appendix L)."""

import json
import logging

from book2epub.config import JobConfig
from book2epub.ir.models import BookIR
from book2epub.paths import JobPaths

from .defaults import DEFAULT_ENHANCED_PROFILE
from .infer import infer_style_profile
from .models import BookStyleProfile
from .representative_pages import select_representative_pages

logger = logging.getLogger(__name__)


def resolve_style_profile(
    bookir: BookIR,
    cfg: JobConfig,
    paths: JobPaths,
) -> tuple[BookStyleProfile | None, list[str]]:
    """
    Resolve BookStyleProfile according to cfg.presentation.mode ('legacy', 'enhanced', 'infer').

    Returns:
      (profile_or_none, warning_codes)
      - legacy: returns (None, [])
      - enhanced: returns (DEFAULT_ENHANCED_PROFILE, [])
      - infer: returns (inferred_profile, warnings) with fallback to enhanced on failure
    """
    mode = cfg.presentation.mode
    warnings: list[str] = []

    if mode == "legacy":
        # Legacy mode: no profile, existing M0-M5 path
        return None, []

    paths.presentation_dir.mkdir(parents=True, exist_ok=True)

    if mode == "enhanced":
        profile = DEFAULT_ENHANCED_PROFILE
        # Save profile
        paths.presentation_book_style_profile_json.write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return profile, []

    if mode == "infer":
        from book2epub.visual.source import VisualSource

        visual_source = VisualSource.resolve(cfg, paths=paths)
        if not visual_source.has_visual:
            logger.warning(
                "Presentation mode 'infer' requested but no visual source available. "
                "Falling back to enhanced profile."
            )
            warnings.append("STYLE_INFERENCE_FALLBACK")
            profile = DEFAULT_ENHANCED_PROFILE
        else:
            # Write style-pages.json
            rep_pages = select_representative_pages(bookir, max_pages=8)
            style_pages_file = paths.presentation_dir / "style-pages.json"
            style_pages_file.write_text(
                json.dumps({"representative_pages": rep_pages}, indent=2),
                encoding="utf-8",
            )

            try:
                from book2epub.providers.factory import create_provider

                provider = create_provider(cfg, purpose="presentation")
                profile, infer_warnings = infer_style_profile(
                    bookir=bookir,
                    paths=paths,
                    visual_source=visual_source,
                    provider=provider,
                )
                warnings.extend(infer_warnings)
            except Exception as exc:
                logger.warning(
                    "Presentation inference setup failed: %s. Falling back to enhanced.", exc
                )
                warnings.append("STYLE_INFERENCE_FALLBACK")
                profile = DEFAULT_ENHANCED_PROFILE

        # Save profile
        paths.presentation_book_style_profile_json.write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return profile, warnings

    return None, []
