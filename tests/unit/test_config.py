"""Unit tests for configuration models and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from book2epub.config import AppConfig, JobConfig, MetadataConfig, MinerUConfig, RenderConfig


def test_default_configs_valid() -> None:
    job_cfg = JobConfig()
    assert job_cfg.app.strict is True
    assert job_cfg.app.work_dir == Path(".work")
    assert job_cfg.mineru.version == "3.4.5"
    assert job_cfg.mineru.backend == "hybrid-engine"
    assert job_cfg.mineru.effort == "high"
    assert job_cfg.render.math_mode == "mathml"
    assert job_cfg.metadata.language == "auto"


def test_mineru_version_must_be_frozen() -> None:
    with pytest.raises(ValidationError):
        MinerUConfig(version="4.0.0")

    with pytest.raises(ValidationError):
        MinerUConfig(version="3.4.4")

    # Valid
    cfg = MinerUConfig(version="3.4.5")
    assert cfg.version == "3.4.5"


def test_app_config_logging_level_validation() -> None:
    cfg = AppConfig(logging_level="debug")
    assert cfg.logging_level == "DEBUG"

    cfg_warn = AppConfig(logging_level="warn")
    assert cfg_warn.logging_level == "WARNING"

    with pytest.raises(ValidationError):
        AppConfig(logging_level="INVALID_LEVEL")


def test_render_config_thresholds() -> None:
    cfg = RenderConfig(max_xhtml_chars=50000, max_source_pages_per_xhtml=20)
    assert cfg.max_xhtml_chars == 50000
    assert cfg.max_source_pages_per_xhtml == 20

    with pytest.raises(ValidationError):
        RenderConfig(max_xhtml_chars=500)  # ge=1000 required

    with pytest.raises(ValidationError):
        RenderConfig(max_source_pages_per_xhtml=0)  # ge=1 required


def test_metadata_config_authors_default() -> None:
    meta = MetadataConfig()
    assert meta.authors == []
    meta2 = MetadataConfig(authors=["Author One", "Author Two"])
    assert len(meta2.authors) == 2
