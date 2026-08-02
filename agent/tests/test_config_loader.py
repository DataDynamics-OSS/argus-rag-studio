"""Tests for config loader."""

import pytest

from app.core.config_loader import _resolve_value, load_config, load_properties


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp config directory with sample files."""
    props_content = """# Comment line
server.host=127.0.0.1
server.port=9090
log.level=DEBUG
"""
    yml_content = """server:
  host: ${server.host:0.0.0.0}
  port: ${server.port:4501}
logging:
  level: ${log.level:INFO}
app:
  name: test-agent
"""
    (tmp_path / "config.properties").write_text(props_content)
    (tmp_path / "config.yml").write_text(yml_content)
    return tmp_path


def test_load_properties(config_dir):
    """Test Java-style properties file parsing."""
    props = load_properties(config_dir / "config.properties")
    assert props["server.host"] == "127.0.0.1"
    assert props["server.port"] == "9090"
    assert props["log.level"] == "DEBUG"


def test_load_properties_missing_file(tmp_path):
    """Test that missing properties file returns empty dict."""
    props = load_properties(tmp_path / "nonexistent.properties")
    assert props == {}


def test_load_config_resolves_variables(config_dir):
    """Test that ${var:default} in YAML is resolved from properties."""
    config = load_config(config_dir=config_dir)
    assert config["server"]["host"] == "127.0.0.1"
    assert config["server"]["port"] == "9090"
    assert config["logging"]["level"] == "DEBUG"
    assert config["app"]["name"] == "test-agent"


def test_load_config_missing_dir(tmp_path):
    """Test that missing config dir returns empty dict."""
    config = load_config(config_dir=tmp_path / "nonexistent")
    assert config == {}


def test_default_value_used_when_property_missing(tmp_path):
    """Test that ${var:default} uses default when property is not defined."""
    (tmp_path / "config.properties").write_text("")
    (tmp_path / "config.yml").write_text(
        "server:\n  host: ${server.host:0.0.0.0}\n  port: ${server.port:4501}\n"
    )
    config = load_config(config_dir=tmp_path)
    assert config["server"]["host"] == "0.0.0.0"
    assert config["server"]["port"] == "4501"


def test_property_overrides_default(tmp_path):
    """Test that property value takes precedence over default."""
    (tmp_path / "config.properties").write_text("server.host=10.0.0.1\n")
    (tmp_path / "config.yml").write_text("server:\n  host: ${server.host:0.0.0.0}\n")
    config = load_config(config_dir=tmp_path)
    assert config["server"]["host"] == "10.0.0.1"


def test_no_default_unresolved_left_as_is(tmp_path):
    """Test that ${var} without default is left as-is when not found."""
    (tmp_path / "config.properties").write_text("")
    (tmp_path / "config.yml").write_text("key: ${undefined.var}\n")
    config = load_config(config_dir=tmp_path)
    assert config["key"] == "${undefined.var}"


def test_empty_default_value(tmp_path):
    """Test that ${var:} resolves to empty string when property missing."""
    (tmp_path / "config.properties").write_text("")
    (tmp_path / "config.yml").write_text("key: ${some.var:}\n")
    config = load_config(config_dir=tmp_path)
    assert config["key"] == ""


def test_default_with_special_characters(tmp_path):
    """Test default values containing paths and special chars."""
    (tmp_path / "config.properties").write_text("")
    (tmp_path / "config.yml").write_text("log:\n  dir: ${log.dir:/var/log/argus-rag-studio-agent}\n")
    config = load_config(config_dir=tmp_path)
    assert config["log"]["dir"] == "/var/log/argus-rag-studio-agent"


def test_resolve_value_directly():
    """Test _resolve_value with various patterns."""
    props = {"db.host": "localhost"}

    # Property found - ignore default
    assert _resolve_value("${db.host:remotehost}", props) == "localhost"

    # Property not found - use default
    assert _resolve_value("${db.port:5432}", props) == "5432"

    # Property not found, no default - left as-is
    assert _resolve_value("${db.name}", props) == "${db.name}"

    # Mixed text with variable
    assert _resolve_value("jdbc://${db.host:remotehost}:${db.port:5432}", props) == (
        "jdbc://localhost:5432"
    )


def test_no_properties_file_uses_defaults(tmp_path):
    """Test that config works with only config.yml (no properties file)."""
    (tmp_path / "config.yml").write_text(
        "server:\n  host: ${server.host:0.0.0.0}\n  port: ${server.port:4501}\n"
    )
    config = load_config(config_dir=tmp_path)
    assert config["server"]["host"] == "0.0.0.0"
    assert config["server"]["port"] == "4501"
