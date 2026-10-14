"""scripts/make_env.py, loaded from its file because scripts/ is not a package."""

import importlib.util

from helpers import REPO_ROOT

spec = importlib.util.spec_from_file_location("make_env", REPO_ROOT / "scripts" / "make_env.py")
make_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_env)

EXAMPLE = "# A comment\nMACHINE_API_KEY=\nWEBHOOK_SECRET=\nLLM_PROVIDER=fake\nDIGEST_TO=you@example.com\n"


def values(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))


def test_a_new_env_copies_the_example_with_random_secrets():
    text, added, generated = make_env.update_env(EXAMPLE, None)
    env = values(text)
    assert text.startswith("# A comment\n")
    assert env["LLM_PROVIDER"] == "fake" and env["DIGEST_TO"] == "you@example.com"
    assert len(env["MACHINE_API_KEY"]) == 64 and len(env["WEBHOOK_SECRET"]) == 64
    assert env["MACHINE_API_KEY"] != env["WEBHOOK_SECRET"]
    assert added == [] and generated == ["MACHINE_API_KEY", "WEBHOOK_SECRET"]


def test_an_existing_env_keeps_every_value_and_gets_the_missing_keys():
    current = "MACHINE_API_KEY=kept-key\nLLM_PROVIDER=gemini\n"
    text, added, generated = make_env.update_env(EXAMPLE, current)
    env = values(text)
    assert text.startswith(current)
    assert env["MACHINE_API_KEY"] == "kept-key" and env["LLM_PROVIDER"] == "gemini"
    assert added == ["WEBHOOK_SECRET", "DIGEST_TO"] and generated == ["WEBHOOK_SECRET"]
    assert len(env["WEBHOOK_SECRET"]) == 64


def test_an_empty_secret_is_filled_where_it_is():
    current = "WEBHOOK_SECRET=\nMACHINE_API_KEY=k\nLLM_PROVIDER=fake\nDIGEST_TO=a@b.test\n"
    text, added, generated = make_env.update_env(EXAMPLE, current)
    assert added == [] and generated == ["WEBHOOK_SECRET"]
    assert text.splitlines()[0].startswith("WEBHOOK_SECRET=") and len(values(text)["WEBHOOK_SECRET"]) == 64


def test_a_second_run_changes_nothing():
    first, _, _ = make_env.update_env(EXAMPLE, None)
    assert make_env.update_env(EXAMPLE, first) == (first, [], [])


def test_main_writes_a_private_file_and_prints_names_not_values(tmp_path, capsys):
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    make_env.main(tmp_path)
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr().out == (
        "Created .env from .env.example.\nNew random values for: MACHINE_API_KEY, WEBHOOK_SECRET.\n")
    make_env.main(tmp_path)
    assert capsys.readouterr().out == ".env already has every key in .env.example.\n"
