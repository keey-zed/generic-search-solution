"""
app/core/config/loader.py

The one function a project's startup code should call:
`load_use_case_config(path)`. Fails loudly, with a clear message, at
every stage that can go wrong — missing file, invalid YAML syntax, wrong
root shape, missing/unsupported schema_version, and full Pydantic
validation — rather than letting a bad config surface as a confusing
error deep inside search or filtering code at query time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import yaml
from pydantic import ValidationError

from app.core.config.models import UseCaseConfig


class ConfigLoadError(Exception):
    """Raised for any problem loading or validating a use-case config.
    Always carries a human-readable message naming the file and the
    specific problem — never a bare stack trace from PyYAML or Pydantic."""


def load_use_case_config(path: Union[str, Path]) -> UseCaseConfig:
    path = Path(path)

    if not path.exists():
        raise ConfigLoadError(f"config file not found: {path}")
    if not path.is_file():
        raise ConfigLoadError(f"config path is not a file: {path}")

    try:
        raw_text = path.read_text()
    except OSError as exc:
        raise ConfigLoadError(f"could not read config file {path}: {exc}") from exc

    try:
        # safe_load, deliberately never yaml.load()/unsafe_load() —
        # config files may originate from a project fork someone else
        # authored; arbitrary tag execution is not an acceptable risk
        # for something loaded at every process boot.
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"invalid YAML syntax in {path}: {exc}") from exc

    if raw is None:
        raise ConfigLoadError(f"config file {path} is empty")
    if not isinstance(raw, dict):
        raise ConfigLoadError(
            f"config file {path} must have a mapping (key: value pairs) at the root, "
            f"got {type(raw).__name__}"
        )

    if "schema_version" not in raw:
        raise ConfigLoadError(
            f"config file {path} is missing the required top-level key 'schema_version'"
        )

    try:
        return UseCaseConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigLoadError(f"config file {path} failed validation:\n{exc}") from exc
