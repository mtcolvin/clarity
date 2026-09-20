"""env_local.py — the .env.local loader that scopes the provider API key to
the backend process. The invariants that matter: existing environment always
wins (a deliberate shell override is never clobbered), the shipped blank
placeholder (KEY=) sets nothing, and a missing file is a normal no-op."""

import os

from env_local import load_env_local


def test_missing_file_is_a_noop(tmp_path):
    assert load_env_local(str(tmp_path / "nope.env")) == 0


def test_loads_key_value(tmp_path, monkeypatch):
    monkeypatch.delenv("HT_TEST_KEY", raising=False)
    p = tmp_path / ".env.local"
    p.write_text("HT_TEST_KEY=abc123\n", encoding="utf-8")
    assert load_env_local(str(p)) == 1
    assert os.environ["HT_TEST_KEY"] == "abc123"
    monkeypatch.delenv("HT_TEST_KEY", raising=False)


def test_existing_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_TEST_KEY", "from-shell")
    p = tmp_path / ".env.local"
    p.write_text("HT_TEST_KEY=from-file\n", encoding="utf-8")
    assert load_env_local(str(p)) == 0
    assert os.environ["HT_TEST_KEY"] == "from-shell"


def test_blank_placeholder_sets_nothing(tmp_path, monkeypatch):
    # The checked-in-shape placeholder line ("ANTHROPIC_API_KEY=") must not
    # plant an empty-string key — gateway's "not set" guard tests falsiness,
    # but an empty env var would still read as "configured" to a human.
    monkeypatch.delenv("HT_TEST_KEY", raising=False)
    p = tmp_path / ".env.local"
    p.write_text("HT_TEST_KEY=\n", encoding="utf-8")
    assert load_env_local(str(p)) == 0
    assert "HT_TEST_KEY" not in os.environ


def test_comments_junk_and_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("HT_TEST_KEY", raising=False)
    monkeypatch.delenv("HT_TEST_KEY2", raising=False)
    p = tmp_path / ".env.local"
    p.write_text(
        "# a comment\n"
        "\n"
        "not a key=value line at all!\n"  # bad key name -> skipped
        "no_equals_line\n"
        'HT_TEST_KEY="quoted value"\n'
        "HT_TEST_KEY2 = spaced \n",
        encoding="utf-8",
    )
    assert load_env_local(str(p)) == 2
    assert os.environ["HT_TEST_KEY"] == "quoted value"
    assert os.environ["HT_TEST_KEY2"] == "spaced"
    monkeypatch.delenv("HT_TEST_KEY", raising=False)
    monkeypatch.delenv("HT_TEST_KEY2", raising=False)
