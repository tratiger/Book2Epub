"""Abstract interface for structured LLM/VLM providers."""

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from book2epub.providers.models import (
    StructuredInferenceRequest,
    StructuredInferenceResult,
)

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


@runtime_checkable
class StructuredProvider(Protocol):
    """Protocol for providers supporting strict structured outputs (M7 spec Section 4)."""

    name: str
    model: str

    @property
    def supports_vision(self) -> bool:
        """Return True if this provider/model configuration supports image input."""
        ...

    def infer[TBaseModel: BaseModel](
        self,
        request: StructuredInferenceRequest,
        response_model: type[TBaseModel],
    ) -> tuple[TBaseModel, StructuredInferenceResult]:
        """
        Execute structured inference, returning the Pydantic-validated response model
        and full execution audit metadata.
        """
        ...
