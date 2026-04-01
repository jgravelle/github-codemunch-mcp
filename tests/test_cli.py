"""CLI behavior tests."""

import pytest

from jcodemunch_mcp.server import main


def test_config_init_creates_template(monkeypatch, tmp_path, capsys):
    """config --init should create a template config.jsonc file."""
    from jcodemunch_mcp import config as config_module

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.jsonc"

    monkeypatch.setenv("CODE_INDEX_PATH", str(config_dir))
    monkeypatch.setattr("sys.argv", ["jcodemunch-mcp", "config", "--init"])

    main(["config", "--init"])

    assert config_path.exists()

    # Should be valid JSONC (parseable after stripping comments)
    content = config_path.read_text()
    assert "// jcodemunch-mcp configuration" in content
    from jcodemunch_mcp.config import _strip_jsonc
    import json
    stripped = _strip_jsonc(content)
    parsed = json.loads(stripped)  # Should not raise
    assert "languages" in parsed
    assert "disabled_tools" in parsed


def test_config_init_refuses_overwrite(monkeypatch, tmp_path, capsys):
    """config --init should refuse to overwrite existing config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.jsonc"
    config_path.write_text('{"already": "exists"}')

    monkeypatch.setenv("CODE_INDEX_PATH", str(config_dir))
    monkeypatch.setattr("sys.argv", ["jcodemunch-mcp", "config", "--init"])

    main(["config", "--init"])

    out = capsys.readouterr().out
    # Should refuse to overwrite
    assert "already exists" in out.lower() or "exists" in out.lower()


def test_config_upgrade_no_config(monkeypatch, tmp_path, capsys):
    """config --upgrade should report missing config and suggest --init."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    monkeypatch.setenv("CODE_INDEX_PATH", str(config_dir))
    main(["config", "--upgrade"])

    out = capsys.readouterr().out
    assert "no config" in out.lower() or "not found" in out.lower()


def test_config_upgrade_already_current(monkeypatch, tmp_path, capsys):
    """config --upgrade on a current config reports 'up to date'."""
    from jcodemunch_mcp.config import generate_template

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.jsonc"
    config_path.write_text(generate_template(), encoding="utf-8")

    monkeypatch.setenv("CODE_INDEX_PATH", str(config_dir))
    main(["config", "--upgrade"])

    out = capsys.readouterr().out
    assert "up to date" in out.lower()


def test_config_upgrade_adds_missing_keys(monkeypatch, tmp_path, capsys):
    """config --upgrade should inject keys absent from an old config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.jsonc"

    # Write a minimal old-style config missing most keys
    config_path.write_text(
        '{\n  "version": "1.0.0"\n}\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("CODE_INDEX_PATH", str(config_dir))
    main(["config", "--upgrade"])

    out = capsys.readouterr().out
    assert "added" in out.lower() or "+" in out

    # The upgraded file should now be parseable and contain expected keys
    from jcodemunch_mcp.config import _strip_jsonc
    import json
    content = config_path.read_text(encoding="utf-8")
    parsed = json.loads(_strip_jsonc(content))
    assert "languages" in parsed
    assert "disabled_tools" in parsed


def test_config_upgrade_preserves_user_values(monkeypatch, tmp_path, capsys):
    """config --upgrade must not overwrite existing user values."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_path = config_dir / "config.jsonc"

    config_path.write_text(
        '{\n  "version": "1.0.0",\n  "max_folder_files": 9999\n}\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("CODE_INDEX_PATH", str(config_dir))
    main(["config", "--upgrade"])

    from jcodemunch_mcp.config import _strip_jsonc
    import json
    content = config_path.read_text(encoding="utf-8")
    parsed = json.loads(_strip_jsonc(content))
    assert parsed["max_folder_files"] == 9999


def test_main_help_exits_without_starting_server(capsys):
    """`--help` should print usage and exit cleanly."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "jcodemunch-mcp" in out
    assert "jCodeMunch MCP server" in out


def test_main_version_exits_with_version(capsys):
    """`--version` should print package version and exit cleanly."""
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("jcodemunch-mcp ")
