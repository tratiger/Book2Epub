"""Synthetic MinerU middle.json fixture generator."""

from typing import Any


def sample_middle_dict(
    version: str = "3.4.5",
    backend: str = "hybrid",
    effort: str = "high",
    page_count: int = 1,
) -> dict[str, Any]:
    """Generate a valid mock MinerU middle.json dictionary."""
    pages: list[dict[str, Any]] = []
    for i in range(page_count):
        pages.append(
            {
                "page_idx": i,
                "page_size": [600, 800],
                "para_blocks": [
                    {
                        "type": "title",
                        "level": 1,
                        "lines": [{"spans": [{"type": "text", "content": f"Title {i+1}"}]}],
                    },
                    {
                        "type": "text",
                        "lines": [
                            {"spans": [{"type": "text", "content": "Paragraph content."}]}
                        ],
                    },
                ],
                "discarded_blocks": [
                    {
                        "type": "page_number",
                        "lines": [{"spans": [{"type": "text", "content": str(i + 1)}]}],
                    }
                ],
            }
        )

    return {
        "_version_name": version,
        "_backend": backend,
        "_effort": effort,
        "_ocr_enable": True,
        "pdf_info": pages,
    }
