"""Presentation stage orchestrator for resolving BookStyleProfile (M10/Appendix L)."""

import json
import logging

from book2epub.cache import (
    compute_presentation_cache_key,
    hash_bookir_relevant,
    hash_model,
    materialize_global_stage_cache,
    persist_global_stage_cache,
    stage_cache_hit,
)
from book2epub.config import JobConfig
from book2epub.ir.models import BookIR
from book2epub.paths import JobPaths
from book2epub.qa.stage import StageState, record_stage_status

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
        record_stage_status(
            paths.presentation_stage_json,
            "presentation_profile",
            StageState.SKIPPED,
            reason="legacy presentation mode",
        )
        return None, []

    paths.presentation_dir.mkdir(parents=True, exist_ok=True)

    if mode == "enhanced":
        profile = DEFAULT_ENHANCED_PROFILE
        # Save profile
        paths.presentation_book_style_profile_json.write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8",
        )
        record_stage_status(
            paths.presentation_stage_json,
            "presentation_profile",
            StageState.COMPLETE,
            input_hash=hash_model(bookir),
            cache_key=hash_model(profile),
            output_artifact=str(paths.presentation_book_style_profile_json),
            reason="enhanced deterministic profile",
        )
        return profile, []

    if mode == "infer":
        from book2epub.presentation.infer import (
            STYLE_INFERENCE_SYSTEM_INSTRUCTION,
            STYLE_INFERENCE_USER_PROMPT,
        )
        from book2epub.presentation.models import BookStyleProfileDecision
        from book2epub.semantic.schemas import build_provider_schema
        from book2epub.visual.source import VisualSource

        visual_source = VisualSource.resolve(cfg, paths=paths)
        rep_pages = select_representative_pages(bookir, max_pages=8)
        provider = None
        provider_name = ""
        provider_model = ""
        if visual_source.has_visual:
            from book2epub.providers.factory import create_provider

            provider = create_provider(cfg, purpose="presentation")
            provider_name = provider.name
            provider_model = provider.model
        presentation_key = compute_presentation_cache_key(
            representative_pages=rep_pages,
            visual_hash=visual_source.source_hash,
            relevant_ir_hash=hash_bookir_relevant(bookir),
            provider=provider_name,
            model=provider_model,
            profile_schema=build_provider_schema(BookStyleProfileDecision),
            prompt=STYLE_INFERENCE_SYSTEM_INSTRUCTION + STYLE_INFERENCE_USER_PROMPT,
        )
        presentation_cache_artifacts = {
            "stage.json": paths.presentation_stage_json,
            "book-style-profile.json": paths.presentation_book_style_profile_json,
        }
        presentation_cache_hit = False
        if not cfg.app.force_presentation:
            presentation_cache_hit = materialize_global_stage_cache(
                cfg.app.work_dir,
                "presentation",
                presentation_key,
                presentation_cache_artifacts,
            ) or stage_cache_hit(
                paths.presentation_stage_json,
                presentation_key,
                (paths.presentation_book_style_profile_json,),
            )
        if presentation_cache_hit:
            profile = BookStyleProfile.model_validate_json(
                paths.presentation_book_style_profile_json.read_text(encoding="utf-8")
            )
            record_stage_status(
                paths.presentation_stage_json,
                "presentation_profile",
                StageState.CACHE_HIT,
                input_hash=presentation_key,
                cache_key=presentation_key,
                provider=provider_name or None,
                model=provider_model or None,
                output_artifact=str(paths.presentation_book_style_profile_json),
                reason="presentation profile cache hit",
            )
            persist_global_stage_cache(
                cfg.app.work_dir,
                "presentation",
                presentation_key,
                presentation_cache_artifacts,
            )
            return profile, []

        record_stage_status(
            paths.presentation_stage_json,
            "presentation_profile",
            StageState.RUNNING,
            input_hash=presentation_key,
            cache_key=presentation_key,
            provider=provider_name or None,
            model=provider_model or None,
            reason="presentation profile requested",
        )
        if not visual_source.has_visual:
            logger.warning(
                "Presentation mode 'infer' requested but no visual source available. "
                "Falling back to enhanced profile."
            )
            warnings.append("STYLE_INFERENCE_FALLBACK")
            profile = DEFAULT_ENHANCED_PROFILE
        else:
            # Write style-pages.json
            style_pages_file = paths.presentation_dir / "style-pages.json"
            style_pages_file.write_text(
                json.dumps({"representative_pages": rep_pages}, indent=2),
                encoding="utf-8",
            )

            try:
                assert provider is not None
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
        record_stage_status(
            paths.presentation_stage_json,
            "presentation_profile",
            StageState.COMPLETE,
            input_hash=presentation_key,
            cache_key=presentation_key,
            provider=provider_name or None,
            model=provider_model or None,
            output_artifact=str(paths.presentation_book_style_profile_json),
            reason="presentation profile complete",
        )
        persist_global_stage_cache(
            cfg.app.work_dir,
            "presentation",
            presentation_key,
            presentation_cache_artifacts,
        )
        return profile, warnings

    return None, []
