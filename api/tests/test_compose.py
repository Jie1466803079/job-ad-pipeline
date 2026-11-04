"""docker-compose.yml and .env.example: what keeps the stack private and n8n's environment free of keys."""

import re

import yaml

from helpers import REPO_ROOT
from jobpipe.settings import Settings

COMPOSE_TEXT = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
SERVICES = yaml.safe_load(COMPOSE_TEXT)["services"]


def example_keys() -> set[str]:
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return {line.split("=", 1)[0] for line in lines if "=" in line and not line.startswith("#")}


def test_ports_are_published_on_localhost_only():
    ports = sorted(port for service in SERVICES.values() for port in service.get("ports", []))
    assert ports == ["127.0.0.1:5433:5432", "127.0.0.1:5678:5678", "127.0.0.1:8000:8000", "127.0.0.1:8025:8025"]


def test_images_are_pinned():
    images = {name: service["image"] for name, service in SERVICES.items() if "image" in service}
    assert images == {"db": "postgres:16", "mailpit": "axllent/mailpit:v1.31.4",
                      "n8n": "docker.n8n.io/n8nio/n8n:2.42.5"}


def test_n8n_never_sees_api_keys():
    n8n = SERVICES["n8n"]
    assert "env_file" not in n8n  # workflows can read n8n's environment with $env
    secrets = {"MACHINE_API_KEY", "WEBHOOK_SECRET", "SESSION_SECRET", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
               "SMTP_PASSWORD"}
    assert not secrets & set(n8n["environment"])


def test_n8n_settings():
    n8n = SERVICES["n8n"]
    env = n8n["environment"]
    assert env["GENERIC_TIMEZONE"] == env["TZ"] == "Australia/Sydney"
    assert env["DB_POSTGRESDB_DATABASE"] == "n8n"
    assert env["N8N_ENCRYPTION_KEY"].startswith("${N8N_ENCRYPTION_KEY:?")  # n8n never starts with its own key
    assert env["N8N_BLOCK_ENV_ACCESS_IN_NODE"] == "false"
    assert {"MAIL_FROM", "DIGEST_TO", "ALERT_TO"} <= set(env)
    assert "./n8n/workflows:/opt/n8n-import/workflows:ro" in n8n["volumes"]


def test_api_and_n8n_report_when_they_are_ready():
    assert "http://127.0.0.1:8000/health" in str(SERVICES["api"]["healthcheck"]["test"])
    assert "http://127.0.0.1:5678/healthz/readiness" in str(SERVICES["n8n"]["healthcheck"]["test"])


def test_every_variable_compose_reads_is_in_env_example():
    assert set(re.findall(r"\$\{([A-Z0-9_]+)", COMPOSE_TEXT)) <= example_keys()


def test_every_setting_read_from_env_is_in_env_example():
    set_by_compose_or_the_image = {"database_url", "config_dir", "web_dir"}
    names = {name.upper() for name in Settings.model_fields if name not in set_by_compose_or_the_image}
    assert names <= example_keys()


def test_services_come_back_when_docker_restarts():
    # Without this, a reboot leaves the stack stopped and the daily schedules stop with it, with no alert.
    assert {name: service.get("restart") for name, service in SERVICES.items()} == dict.fromkeys(
        SERVICES, "unless-stopped")
