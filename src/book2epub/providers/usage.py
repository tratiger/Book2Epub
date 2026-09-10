"""Provider token usage and metrics tracking."""

import json
from typing import Any

from book2epub.paths import JobPaths


def record_provider_usage(paths: JobPaths, usage_dict: dict[str, Any]) -> None:
    """Append a token usage record to semantic/provider-usage.json."""
    usage_file = paths.semantic_provider_usage_json
    usage_list: list[dict[str, Any]] = []
    if usage_file.is_file():
        try:
            loaded = json.loads(usage_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                usage_list = loaded
        except Exception:
            pass
    usage_list.append(usage_dict)
    usage_file.parent.mkdir(parents=True, exist_ok=True)
    usage_file.write_text(json.dumps(usage_list, indent=2), encoding="utf-8")
