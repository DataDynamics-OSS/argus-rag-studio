"""Application configuration.

Configuration is loaded from two files in the config directory:

1. config.properties - Java-style key=value variable definitions
2. config.yml - Main YAML config using Spring Boot style ${variable:default}

Variable resolution order:
  1. Lookup variable in config.properties
  2. If not found, use the default value specified after ':'
  3. If no default, the placeholder is left as-is

Default config directory: /etc/argus-rag-studio-agent
Override with ARGUS_CONFIG_DIR environment variable.
Override individual files with --config-yaml / --config-properties CLI arguments.
"""

import logging
import os
from pathlib import Path

from app.core.config_loader import load_config

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(os.environ.get("ARGUS_CONFIG_DIR", "/etc/argus-rag-studio-agent"))
_yaml_path: Path = _CONFIG_DIR / "config.yml"
_properties_path: Path = _CONFIG_DIR / "config.properties"
_server_properties_path: Path = _CONFIG_DIR / "server.properties"
_raw: dict = load_config(config_dir=_CONFIG_DIR)


def _get(section: str, key: str, default=None):
    """Get a value from the loaded config dict."""
    return _raw.get(section, {}).get(key, default)


def _get_nested(section: str, subsection: str, key: str, default=None):
    """Get a nested value from the loaded config dict."""
    return _raw.get(section, {}).get(subsection, {}).get(key, default)


def _to_bool(value) -> bool:
    """Convert a value to bool (handles string 'true'/'false')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


class Settings:
    """Global application settings loaded from config.yml + config.properties."""

    def __init__(self) -> None:
        # App
        self.app_name: str = _get("app", "name", "argus-rag-studio-agent")
        self.app_version: str = _get("app", "version", "0.1.0")
        self.debug: bool = _get("app", "debug", False)

        # Server
        self.host: str = _get("server", "host", "0.0.0.0")
        self.port: int = int(_get("server", "port", 4501))

        # Logging
        self.log_level: str = _get("logging", "level", "INFO")
        self.log_dir: Path = Path(_get("logging", "dir", "logs"))
        self.log_filename: str = _get("logging", "filename", "agent.log")
        self.log_rolling_type: str = _get_nested("logging", "rolling", "type", "daily")
        self.log_rolling_backup_count: int = int(
            _get_nested("logging", "rolling", "backup_count", 30)
        )

        # Data
        self.data_dir: Path = Path(_get("data", "dir", "/var/lib/argus-rag-studio-agent"))

        # Config
        self.config_dir: Path = _CONFIG_DIR
        self.config_yaml_path: Path = _yaml_path
        self.config_properties_path: Path = _properties_path
        self.config_server_properties_path: Path = _server_properties_path

        # Backup
        self.backup_dir: Path = Path(_get("backup", "dir", "backups"))

        # Command execution
        self.command_timeout: int = int(_get("command", "timeout", 300))
        self.command_max_output: int = int(_get("command", "max_output", 1024 * 1024))

        # Monitor
        self.monitor_interval: int = int(_get("monitor", "interval", 5))

        # Terminal
        self.terminal_shell: str = _get("terminal", "shell", os.environ.get("SHELL", "/bin/bash"))
        self.terminal_max_sessions: int = int(_get("terminal", "max_sessions", 10))
        self.terminal_home_dir: str = _get("terminal", "home_dir", "/root")

        # Certificate
        self.cert_days: int = int(_get("certificate", "days", 825))
        self.cert_key_bits: int = int(_get("certificate", "key_bits", 2048))
        self.cert_base_dir: Path = Path(_get("certificate", "dir", "certificates"))

        # Heartbeat
        self.heartbeat_interval: int = int(_get("heartbeat", "interval", 60))

        # File manager
        self.filemgr_exec_timeout: int = int(_get("filemgr", "exec_timeout", 60))

        # Insight Server (loaded from server.properties in config directory)
        _server_props = self._load_server_properties()
        self.studio_server_ip: str = _server_props.get("server.ip", "localhost")
        self.studio_server_port: int = int(_server_props.get("server.port", 4700))

        # Prometheus
        self.prometheus_enable_push: bool = _to_bool(_get("prometheus", "enable-push", True))
        self.prometheus_pushgateway_host: str = _get_nested(
            "prometheus", "pushgateway", "host", "localhost"
        )
        self.prometheus_pushgateway_port: int = int(
            _get_nested("prometheus", "pushgateway", "port", 9091)
        )
        self.prometheus_push_cron: str = _get("prometheus", "push-cron", "* * * * *")

    def update_prometheus(
        self,
        enable_push: str,
        push_cron: str,
        pushgateway_host: str,
        pushgateway_port: str,
    ) -> None:
        """Update Prometheus settings in memory."""
        logger.info(
            "Updating in-memory Prometheus settings: "
            "enable_push=%s -> %s, cron='%s' -> '%s', host=%s -> %s, port=%s -> %s",
            self.prometheus_enable_push, _to_bool(enable_push),
            self.prometheus_push_cron, push_cron,
            self.prometheus_pushgateway_host, pushgateway_host,
            self.prometheus_pushgateway_port, pushgateway_port,
        )
        self.prometheus_enable_push = _to_bool(enable_push)
        self.prometheus_push_cron = push_cron
        self.prometheus_pushgateway_host = pushgateway_host
        self.prometheus_pushgateway_port = int(pushgateway_port)

    def _load_server_properties(self) -> dict[str, str]:
        """Load server.properties from the configured path."""
        from app.core.config_loader import load_properties

        return load_properties(self.config_server_properties_path)


def init_settings(
    yaml_path: str | None = None,
    properties_path: str | None = None,
    server_properties_path: str | None = None,
) -> None:
    """Re-initialize settings with custom config file paths.

    Call this before the application starts to override default config locations.
    If not called, settings are loaded from the default config directory.

    Args:
        yaml_path: Absolute path to YAML config file.
        properties_path: Absolute path to properties file.
        server_properties_path: Absolute path to server properties file.
    """
    global _raw, _yaml_path, _properties_path, _server_properties_path
    if yaml_path:
        _yaml_path = Path(yaml_path)
    if properties_path:
        _properties_path = Path(properties_path)
    if server_properties_path:
        _server_properties_path = Path(server_properties_path)
    _raw = load_config(
        config_dir=_CONFIG_DIR,
        yaml_path=yaml_path,
        properties_path=properties_path,
    )
    settings.__init__()


settings = Settings()
