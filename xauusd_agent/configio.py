"""Load/save an ``AgentConfig`` from a YAML (or JSON) file.

Lets you describe a whole run declaratively instead of in code::

    # config.yaml
    mode: backtest
    starting_equity: 10000
    strategy: {swing_length: 6, window: 200, require_fvg: false}
    management: {partial_enabled: true, partial_at_r: 1.0, trailing_enabled: true}
    news: {enabled: true, before_min: 30, after_min: 30}

``load_config`` maps the file onto the nested config dataclasses; unknown keys are
ignored and omitted keys keep their defaults, so partial configs are fine.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict

from .config import (
    AgentConfig, InstrumentSpec, RiskConfig, StrategyConfig, ManagementConfig,
    NewsConfig, Mode,
)

_SECTIONS = {
    "instrument": InstrumentSpec,
    "risk": RiskConfig,
    "strategy": StrategyConfig,
    "management": ManagementConfig,
    "news": NewsConfig,
}


def _build_section(cls, data: Dict[str, Any]):
    """Construct a dataclass from a dict, ignoring unknown keys."""
    if not isinstance(data, dict):
        return data
    valid = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def config_from_dict(d: Dict[str, Any]) -> AgentConfig:
    cfg = AgentConfig()
    for key, value in (d or {}).items():
        if key == "mode":
            cfg.mode = Mode(str(value).lower())
        elif key == "starting_equity":
            cfg.starting_equity = float(value)
        elif key in _SECTIONS and isinstance(value, dict):
            setattr(cfg, key, _build_section(_SECTIONS[key], value))
    return cfg


def config_to_dict(cfg: AgentConfig) -> Dict[str, Any]:
    d = dataclasses.asdict(cfg)
    d["mode"] = cfg.mode.value
    return d


def load_config(path: str) -> AgentConfig:
    """Load an AgentConfig from a .yaml/.yml/.json file."""
    with open(path) as fh:
        if path.lower().endswith((".yaml", ".yml")):
            import yaml
            data = yaml.safe_load(fh)
        else:
            data = json.load(fh)
    return config_from_dict(data or {})


def save_config(cfg: AgentConfig, path: str) -> None:
    """Write an AgentConfig to a .yaml/.yml/.json file."""
    data = config_to_dict(cfg)
    with open(path, "w") as fh:
        if path.lower().endswith((".yaml", ".yml")):
            import yaml
            yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
        else:
            json.dump(data, fh, indent=2)
