"""Presentation style profile inference using multimodal Structured Outputs (M10/Appendix L15)."""

import logging

from book2epub.ir.models import BookIR
from book2epub.paths import JobPaths
from book2epub.providers.base import StructuredProvider
from book2epub.providers.models import ImageInput, StructuredInferenceRequest
from book2epub.providers.usage import record_provider_usage
from book2epub.semantic.schemas import build_provider_schema
from book2epub.visual.raster import PageRasterCache
from book2epub.visual.source import VisualSource

from .defaults import DEFAULT_ENHANCED_PROFILE
from .models import BookStyleProfile, BookStyleProfileDecision
from .representative_pages import select_representative_pages

logger = logging.getLogger(__name__)

STYLE_INFERENCE_SYSTEM_INSTRUCTION = """\
You are an expert technical book typographer and EPUB design specialist.
Analyze the provided representative book page images to reconstruct the publication's
visual grammar into a reflowable EPUB styling profile.

Rules:
1. Select only finite tokens and enums defined in the response schema.
2. Infer typographic rhythm and visual hierarchy, NOT fixed pixel coordinates or layouts.
3. Distinguish heading scales, weights, and rules (e.g. underline rule on section headings).
4. Distinguish prose rhythms, preformatted themes, callout accents, tables, and list markers.
5. NEVER output CSS code, HTML tags, hex color codes, font filenames, or raw prose text.
6. Return high confidence only when visual conventions are clearly identifiable.
"""

STYLE_INFERENCE_USER_PROMPT = """\
Examine the attached {page_count} representative book pages (indices: {page_indices}).
Determine the consistent BookStyleProfile matching the source book's visual grammar.
"""


def infer_style_profile(
    bookir: BookIR,
    paths: JobPaths,
    visual_source: VisualSource,
    provider: StructuredProvider,
) -> tuple[BookStyleProfile, list[str]]:
    """
    Infer a BookStyleProfile from representative source pages using the multimodal provider.
    Falls back safely to DEFAULT_ENHANCED_PROFILE on low confidence (< 0.70) or failure.
    Returns (resolved_profile, warning_codes).
    """
    warning_codes: list[str] = []

    # 1. Select representative pages
    rep_pages = select_representative_pages(bookir, max_pages=8)
    if not rep_pages:
        logger.warning(
            "No representative pages could be selected. Falling back to enhanced profile."
        )
        warning_codes.append("STYLE_INFERENCE_FALLBACK")
        return DEFAULT_ENHANCED_PROFILE, warning_codes

    # 2. Rasterize representative pages (longest edge <= 1600 px)
    raster_cache = PageRasterCache(paths.semantic_visual_pages_dir, visual_source)
    image_inputs: list[ImageInput] = []

    for pidx in rep_pages:
        try:
            page_path, _ = raster_cache.get_page_image(pidx, max_edge=1600)
            image_inputs.append(
                ImageInput(
                    path=page_path,
                    media_type="image/jpeg",
                    label=f"Page {pidx + 1}",
                )
            )
        except Exception as exc:
            logger.warning("Failed to rasterize representative page %d: %s", pidx, exc)

    if not image_inputs:
        logger.warning("No page images could be rendered. Falling back to enhanced profile.")
        warning_codes.append("STYLE_INFERENCE_FALLBACK")
        return DEFAULT_ENHANCED_PROFILE, warning_codes

    # 3. Build Structured Output inference request
    req_id = f"style-infer-{paths.job_id}"
    user_prompt = STYLE_INFERENCE_USER_PROMPT.format(
        page_count=len(image_inputs),
        page_indices=rep_pages,
    )

    req = StructuredInferenceRequest(
        request_id=req_id,
        system_instruction=STYLE_INFERENCE_SYSTEM_INSTRUCTION,
        user_text=user_prompt,
        response_model_name="BookStyleProfileDecision",
        response_schema=build_provider_schema(BookStyleProfileDecision),
        images=image_inputs,
    )

    # 4. Invoke provider
    try:
        decision, result = provider.infer(req, response_model=BookStyleProfileDecision)
        record_provider_usage(
            paths,
            {
                "request_id": result.request_id,
                "requested_request_id": req.request_id,
                "provider": provider.name,
                "model": provider.model,
                "pass": "presentation_infer",
                "latency_ms": result.latency_ms,
                "attempt_count": result.attempt_count,
                "transport_attempt_count": result.transport_attempt_count,
                "schema_retry_count": result.schema_retry_count,
                "provider_request_ids": result.provider_request_ids,
                "usage": result.usage.model_dump(),
            },
        )
    except Exception as exc:
        logger.warning(
            "Style inference provider call failed: %s. Falling back to enhanced profile.", exc
        )
        warning_codes.append("STYLE_INFERENCE_FALLBACK")
        return DEFAULT_ENHANCED_PROFILE, warning_codes

    # 5. Validate decision
    if decision.confidence < 0.70:
        logger.info(
            "Style inference confidence %.2f < 0.70. Falling back to enhanced profile.",
            decision.confidence,
        )
        warning_codes.append("STYLE_INFERENCE_FALLBACK")
        return DEFAULT_ENHANCED_PROFILE, warning_codes

    # Verify returned page indices are valid subset
    valid_indices = set(rep_pages)
    for idx in decision.evidence_page_indices:
        if idx not in valid_indices:
            logger.warning("Style inference returned unprovided page index %d. Rejecting.", idx)
            warning_codes.append("STYLE_INFERENCE_FALLBACK")
            return DEFAULT_ENHANCED_PROFILE, warning_codes

    # Populate profile metadata
    inferred_profile = decision.profile.model_copy(
        update={
            "mode_source": "inferred",
            "provider": provider.name,
            "model": provider.model,
            "request_id": req_id,
            "confidence": decision.confidence,
            "representative_page_indices": rep_pages,
        }
    )

    logger.info("Successfully inferred BookStyleProfile with confidence %.2f", decision.confidence)
    return inferred_profile, warning_codes
