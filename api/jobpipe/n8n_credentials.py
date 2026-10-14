"""Print n8n's credentials import file, built from the settings in .env.

scripts/n8n-setup.sh runs this inside the api container and pipes it straight into n8n, so the
secrets never touch the disk and n8n sends exactly the API key intake-api checks:

    docker compose exec -T api python -m jobpipe.n8n_credentials \\
      | docker compose exec -T n8n n8n import:credentials --input=/dev/stdin

The ids are fixed, so the workflows in n8n/workflows/ can refer to them, and importing again updates
the same credentials.
"""

import json
import sys

from jobpipe.settings import Settings

API_KEY_ID = "jobpipeApiKey001"
WEBHOOK_SECRET_ID = "jobpipeWebhook01"
SMTP_ID = "jobpipeSmtp00001"


def n8n_credentials(settings: Settings) -> list[dict]:
    required = [("MACHINE_API_KEY", settings.machine_api_key), ("WEBHOOK_SECRET", settings.webhook_secret)]
    missing = [name for name, value in required if not value]
    if missing:
        raise ValueError(f"{' and '.join(missing)} not set. Run make env, then make up.")
    return [
        {"id": API_KEY_ID, "name": "intake-api key", "type": "httpHeaderAuth",
         "data": {"name": "X-API-Key", "value": settings.machine_api_key}},
        {"id": WEBHOOK_SECRET_ID, "name": "Job link webhook secret", "type": "httpHeaderAuth",
         "data": {"name": "X-Webhook-Secret", "value": settings.webhook_secret}},
        # No login when user and password are empty. STARTTLS is used when the server offers it.
        {"id": SMTP_ID, "name": "Outgoing email", "type": "smtp",
         "data": {"host": settings.smtp_host, "port": settings.smtp_port, "user": settings.smtp_user,
                  "password": settings.smtp_password, "secure": settings.smtp_secure, "disableStartTls": False}},
    ]


def main() -> None:
    try:
        credentials = n8n_credentials(Settings())
    except ValueError as exc:
        sys.exit(str(exc))
    json.dump(credentials, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
