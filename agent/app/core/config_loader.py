"""Configuration loader with properties variable resolution.

Loads config.properties (Java-style key=value) and config.yml,
resolving ${variable} placeholders in YAML values using properties.
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Matches ${variable} or ${variable:default_value}
_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")

DEFAULT_CONFIG_DIR = Path("/etc/argus-rag-studio-agent")


def load_properties(path: Path) -> dict[str, str]:
    """Load a Java-style .properties file into a dict.

    Supports:
    - key=value and key: value syntax
    - Lines starting with # or ! are comments
    - Empty lines are skipped
    - Leading/trailing whitespace is trimmed from keys and values
    """
    props: dict[str, str] = {}

    if not path.is_file():
        logger.debug("Properties file not found: %s", path)
        return props

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue

            # Split on first '=' or ':'
            for sep in ("=", ":"):
                idx = line.find(sep)
                if idx >= 0:
                    key = line[:idx].strip()
                    value = line[idx + 1 :].strip()
                    props[key] = value
                    break

    return props


def update_properties(path: Path, updates: dict[str, str]) -> None:
    """Update specific keys in a .properties file, preserving comments and order.

    If a key exists, its value is replaced in-place.
    If a key does not exist, it is appended at the end of the file.
    """
    if not path.is_file():
        logger.warning("Properties file not found for update: %s", path)
        return

    lines: list[str] = []
    updated_keys: set[str] = set()

    with open(path, encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            stripped = raw.strip()

            if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
                for sep in ("=", ":"):
                    idx = stripped.find(sep)
                    if idx >= 0:
                        key = stripped[:idx].strip()
                        if key in updates:
                            lines.append(f"{key}={updates[key]}")
                            updated_keys.add(key)
                        else:
                            lines.append(raw)
                        break
                else:
                    lines.append(raw)
            else:
                lines.append(raw)

    # Append keys that were not found in the file
    for key, value in updates.items():
        if key not in updated_keys:
            lines.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info("Updated properties file %s: keys=%s", path, list(updates.keys()))


def _resolve_value(value: str, props: dict[str, str]) -> str:
    """Replace ${variable} or ${variable:default} placeholders.

    Spring Boot style resolution:
    - ${variable} : resolved from properties, left as-is if not found
    - ${variable:default} : resolved from properties, uses default if not found
    """

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default_value = match.group(2)  # None if no default specified

        if var_name in props:
            return props[var_name]

        if default_value is not None:
            return default_value

        logger.warning("Unresolved variable: ${%s}", var_name)
        return match.group(0)

    return _VAR_PATTERN.sub(replacer, value)


def _resolve_dict(data: dict[str, Any], props: dict[str, str]) -> dict[str, Any]:
    """Recursively resolve ${variable} placeholders in a dict."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = _resolve_value(value, props)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value, props)
        elif isinstance(value, list):
            resolved[key] = [
                _resolve_value(item, props) if isinstance(item, str) else item for item in value
            ]
        else:
            resolved[key] = value
    return resolved


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return as dict."""
    if not path.is_file():
        logger.debug("YAML config file not found: %s", path)
        return {}

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if isinstance(data, dict) else {}


def load_config(
    config_dir: Path | None = None,
    yaml_file: str = "config.yml",
    properties_file: str = "config.properties",
    yaml_path: Path | str | None = None,
    properties_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load configuration by resolving YAML with properties variables.

    1. Load config.properties from config_dir (or properties_path)
    2. Load config.yml from config_dir (or yaml_path)
    3. Resolve ${variable} placeholders in YAML using properties values

    Args:
        config_dir: Directory containing config files. Defaults to /etc/argus-rag-studio-agent.
        yaml_file: Name of the YAML config file (used with config_dir).
        properties_file: Name of the properties file (used with config_dir).
        yaml_path: Absolute path to YAML config file. Overrides config_dir/yaml_file.
        properties_path: Absolute path to properties file. Overrides config_dir/properties_file.

    Returns:
        Resolved configuration dict.
    """
    base_dir = config_dir or DEFAULT_CONFIG_DIR

    props_file = Path(properties_path) if properties_path else base_dir / properties_file
    yaml_config_file = Path(yaml_path) if yaml_path else base_dir / yaml_file

    props = load_properties(props_file)
    raw_config = load_yaml(yaml_config_file)

    if not raw_config:
        return {}

    return _resolve_dict(raw_config, props)
