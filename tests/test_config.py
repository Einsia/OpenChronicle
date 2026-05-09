from pathlib import Path

from openchronicle import config


def test_defaults_when_no_file(tmp_path: Path) -> None:
    cfg = config.load(tmp_path / "missing.toml")
    assert cfg.capture.interval_minutes == 10
    assert cfg.session.gap_minutes == 5
    assert cfg.reducer.enabled is True
    default = cfg.model_for("reducer")
    assert default.model == "gpt-5.4-nano"


def test_stage_override_merges(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[models.default]
model = "gpt-5.4-nano"
api_key_env = "OPENAI_API_KEY"

[models.classifier]
model = "claude-haiku-4-5"
api_key_env = "ANTHROPIC_API_KEY"
"""
    )
    cfg = config.load(path)
    default = cfg.model_for("default")
    classifier = cfg.model_for("classifier")
    assert default.model == "gpt-5.4-nano"
    assert default.api_key_env == "OPENAI_API_KEY"
    assert classifier.model == "claude-haiku-4-5"
    assert classifier.api_key_env == "ANTHROPIC_API_KEY"


def test_write_default_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    assert config.write_default_if_missing(p)
    assert p.exists()
    assert "[models.default]" in p.read_text()
    # idempotent
    assert not config.write_default_if_missing(p)


def test_api_key_precedence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENV_KEY", "from-env")
    cfg = config.ModelConfig(api_key="direct", api_key_env="ENV_KEY")
    assert config.resolve_api_key(cfg) == "direct"
    cfg2 = config.ModelConfig(api_key="", api_key_env="ENV_KEY")
    assert config.resolve_api_key(cfg2) == "from-env"


def test_timeout_and_retries_inherit_from_default(tmp_path: Path) -> None:
    """[models.<stage>] without explicit timeout_seconds inherits the default."""
    path = tmp_path / "config.toml"
    path.write_text(
        """
[models.default]
model = "gpt-5.4-nano"
timeout_seconds = 200
num_retries = 4

[models.reducer]
model = "claude-sonnet-4"
"""
    )
    cfg = config.load(path)
    reducer = cfg.model_for("reducer")
    assert reducer.model == "claude-sonnet-4"
    # timeout_seconds / num_retries come down from [models.default]
    assert reducer.timeout_seconds == 200
    assert reducer.num_retries == 4


def test_timeout_per_stage_overrides_default(tmp_path: Path) -> None:
    """A stage that explicitly sets timeout_seconds wins over the default."""
    path = tmp_path / "config.toml"
    path.write_text(
        """
[models.default]
timeout_seconds = 120

[models.reducer]
timeout_seconds = 600
"""
    )
    cfg = config.load(path)
    assert cfg.model_for("default").timeout_seconds == 120
    assert cfg.model_for("reducer").timeout_seconds == 600


def test_missing_timeout_defaults_to_none(tmp_path: Path) -> None:
    """An old config that doesn't mention timeout_seconds parses to None.

    The llm.py wrapper interprets None as "use module default" so a
    user upgrading from a config that pre-dates this field gets the
    DEFAULT_TIMEOUT_SECONDS automatically — no breakage.
    """
    cfg = config.load(tmp_path / "missing.toml")
    assert cfg.model_for("reducer").timeout_seconds is None
    assert cfg.model_for("reducer").num_retries is None
