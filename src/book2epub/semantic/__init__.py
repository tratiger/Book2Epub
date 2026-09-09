"""Semantic reconstruction, evidence preservation, and document adjudication module."""

from book2epub.semantic.draft import build_semantic_draft
from book2epub.semantic.evidence import build_semantic_evidence
from book2epub.semantic.hashing import (
    compute_content_sha256,
    compute_file_sha256,
    compute_text_sha256,
)
from book2epub.semantic.models import (
    SemanticDraftBook,
    SemanticEvidenceBlock,
    SemanticEvidenceBook,
    SemanticTarget,
)

__all__ = [
    "build_semantic_draft",
    "build_semantic_evidence",
    "compute_content_sha256",
    "compute_file_sha256",
    "compute_text_sha256",
    "SemanticDraftBook",
    "SemanticEvidenceBlock",
    "SemanticEvidenceBook",
    "SemanticTarget",
]
