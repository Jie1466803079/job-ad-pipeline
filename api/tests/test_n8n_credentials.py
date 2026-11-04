import json

import pytest

from jobpipe.n8n_credentials import API_KEY_ID, SMTP_ID, WEBHOOK_SECRET_ID, main, n8n_credentials
from jobpipe.settings import Settings

SMTP_ENV = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_SECURE"]


@pytest.fixture(autouse=True)
def no_settings_from_the_shell(monkeypatch):
    for name in ["MACHINE_API_KEY", "WEBHOOK_SECRET", *SMTP_ENV]:
        monkeypatch.delenv(name, raising=False)


def credentials(**settings) -> dict[str, dict]:
    values = {"machine_api_key": "api-key", "webhook_secret": "hook-secret"} | settings
    return {credential["id"]: credential for credential in n8n_credentials(Settings(**values))}


def test_two_header_credentials_with_fixed_ids():
    by_id = credentials()
    assert by_id[API_KEY_ID]["type"] == by_id[WEBHOOK_SECRET_ID]["type"] == "httpHeaderAuth"
    assert by_id[API_KEY_ID]["data"] == {"name": "X-API-Key", "value": "api-key"}
    assert by_id[WEBHOOK_SECRET_ID]["data"] == {"name": "X-Webhook-Secret", "value": "hook-secret"}


def test_email_goes_to_mailpit_without_a_login_by_default():
    smtp = credentials()[SMTP_ID]
    assert smtp["type"] == "smtp"
    assert smtp["data"] == {"host": "mailpit", "port": 1025, "user": "", "password": "", "secure": False,
                            "disableStartTls": False}


def test_a_real_mail_server_can_be_set_in_the_environment(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_SECURE", "true")
    monkeypatch.setenv("SMTP_USER", "me")
    data = credentials()[SMTP_ID]["data"]
    assert (data["host"], data["port"], data["secure"], data["user"]) == ("smtp.example.com", 465, True, "me")


def test_missing_secrets_are_named():
    with pytest.raises(ValueError, match=r"^MACHINE_API_KEY and WEBHOOK_SECRET not set\. Run make env"):
        credentials(machine_api_key=None, webhook_secret="")
    with pytest.raises(ValueError, match=r"^WEBHOOK_SECRET not set\."):
        credentials(webhook_secret=None)


def test_main_prints_only_the_import_file(monkeypatch, capsys):
    monkeypatch.setenv("MACHINE_API_KEY", "api-key")
    monkeypatch.setenv("WEBHOOK_SECRET", "hook-secret")
    main()
    printed = capsys.readouterr()
    assert [credential["id"] for credential in json.loads(printed.out)] == [API_KEY_ID, WEBHOOK_SECRET_ID, SMTP_ID]
    assert printed.err == ""


def test_main_exits_with_the_reason_and_no_secret(monkeypatch, capsys):
    monkeypatch.setenv("MACHINE_API_KEY", "api-key")
    with pytest.raises(SystemExit) as stopped:
        main()
    assert str(stopped.value) == "WEBHOOK_SECRET not set. Run make env, then make up."
    assert capsys.readouterr().out == ""
