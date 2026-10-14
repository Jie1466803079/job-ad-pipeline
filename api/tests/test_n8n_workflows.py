"""The workflows in n8n/workflows/. CI does not run n8n, so these pin what must not drift: triggers and
times, error handling, retries and timeouts, credentials, and that no secret or address is in a file."""

import json
import re

from helpers import REPO_ROOT
from jobpipe.n8n_credentials import API_KEY_ID, SMTP_ID, WEBHOOK_SECRET_ID, n8n_credentials
from jobpipe.settings import Settings

WORKFLOW_DIR = REPO_ROOT / "n8n" / "workflows"
IDS = {"daily-ingest": "wfDailyIngest001", "submit-link": "wfSubmitLink0001", "daily-digest": "wfDailyDigest001",
       "maintenance": "wfMaintenance001", "error-alert": "wfErrorAlert0001"}
SCHEDULES = {"daily-ingest": "0 7 * * *", "daily-digest": "0 8 * * *", "maintenance": "0 2 * * *"}
API = "http://api:8000/"
TWO_HOURS_MS = 2 * 60 * 60 * 1000


def load(name: str) -> dict:
    return json.loads((WORKFLOW_DIR / f"{name}.json").read_text(encoding="utf-8"))


WORKFLOWS = {name: load(name) for name in IDS}


def nodes(workflow: dict, node_type: str) -> list[dict]:
    return [node for node in workflow["nodes"] if node["type"] == f"n8n-nodes-base.{node_type}"]


def node(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def targets(workflow: dict, name: str) -> list[list[str]]:
    """For each output of a node, the names of the nodes it leads to."""
    return [[link["node"] for link in output] for output in workflow["connections"].get(name, {}).get("main", [])]


def test_five_workflows_with_fixed_ids_that_start_unpublished():
    assert sorted(path.stem for path in WORKFLOW_DIR.glob("*.json")) == sorted(IDS)
    for name, workflow in WORKFLOWS.items():
        assert (workflow["id"], workflow["name"], workflow["active"]) == (IDS[name], name, False)


def test_every_workflow_runs_in_sydney_time_and_reports_failures():
    for name, workflow in WORKFLOWS.items():
        settings = workflow["settings"]
        assert (settings["timezone"], settings["executionOrder"]) == ("Australia/Sydney", "v1")
        assert settings.get("errorWorkflow") == (None if name == "error-alert" else IDS["error-alert"])


def test_schedules_and_a_manual_trigger_for_runs_on_demand():
    for name, cron in SCHEDULES.items():
        workflow = WORKFLOWS[name]
        [schedule] = nodes(workflow, "scheduleTrigger")
        assert schedule["parameters"]["rule"]["interval"] == [{"field": "cronExpression", "expression": cron}]
        [manual] = nodes(workflow, "manualTrigger")
        assert targets(workflow, manual["name"]) == targets(workflow, schedule["name"])


def test_connections_join_existing_nodes_and_leave_none_out():
    for workflow in WORKFLOWS.values():
        names = {n["name"] for n in workflow["nodes"]}
        triggers = {n["name"] for n in workflow["nodes"]
                    if n["type"].endswith("Trigger") or n["type"] == "n8n-nodes-base.webhook"}
        linked = {link["node"] for outputs in workflow["connections"].values()
                  for output in outputs["main"] for link in output}
        assert set(workflow["connections"]) <= names and linked <= names
        assert names - triggers <= linked


def test_http_nodes_retry_and_have_explicit_timeouts():
    for workflow in WORKFLOWS.values():
        for http in nodes(workflow, "httpRequest"):
            assert (http["retryOnFail"], http["maxTries"], http["waitBetweenTries"]) == (True, 3, 5000)
            timeout = http["parameters"]["options"]["timeout"]  # n8n's default would be 5 minutes
            if http["parameters"]["url"] == API + "machine/ingest":
                assert timeout == TWO_HOURS_MS
            else:
                assert 0 < timeout <= 10 * 60 * 1000


def test_only_calls_to_intake_api_carry_the_api_key():
    for workflow in WORKFLOWS.values():
        for http in nodes(workflow, "httpRequest"):
            url = http["parameters"]["url"]
            if url.startswith(API):
                assert http["parameters"]["genericAuthType"] == "httpHeaderAuth"
                assert http["credentials"]["httpHeaderAuth"]["id"] == API_KEY_ID
            else:  # a board address that intake-api built
                assert url in ("={{ $json.api_url }}", "={{ $json.body.api_url }}")
                assert "credentials" not in http


def test_credentials_are_the_ones_the_setup_script_imports():
    known = {c["id"]: c for c in n8n_credentials(Settings(machine_api_key="k", webhook_secret="s"))}
    for workflow in WORKFLOWS.values():
        for n in workflow["nodes"]:
            for kind, credential in n.get("credentials", {}).items():
                expected = known[credential["id"]]
                assert (kind, credential["name"]) == (expected["type"], expected["name"])


def test_no_secret_or_email_address_is_written_into_a_workflow():
    for name in IDS:
        text = (WORKFLOW_DIR / f"{name}.json").read_text(encoding="utf-8")
        assert not re.search(r"[0-9a-fA-F]{32}", text)  # make env's secrets are 64 hex characters
        assert "X-API-Key" not in text and "X-Webhook-Secret" not in text
        assert "@" not in text  # addresses come from $env


def test_emails_use_addresses_from_env_without_an_n8n_footer():
    sends = [send for workflow in WORKFLOWS.values() for send in nodes(workflow, "emailSend")]
    assert sorted(send["parameters"]["toEmail"] for send in sends) == ["={{ $env.ALERT_TO }}",
                                                                       "={{ $env.DIGEST_TO }}"]
    for send in sends:
        assert send["parameters"]["fromEmail"] == "={{ $env.MAIL_FROM }}"
        assert send["parameters"]["options"]["appendAttribution"] is False
        assert send["credentials"]["smtp"]["id"] == SMTP_ID


def test_a_failed_board_is_noted_and_the_loop_goes_on():
    ingest = WORKFLOWS["daily-ingest"]
    assert node(ingest, "Fetch board")["onError"] == "continueErrorOutput"
    assert targets(ingest, "Fetch board") == [["Post to ingest"], ["Note failed board"]]
    assert targets(ingest, "Note failed board") == [["Loop over companies"]]
    assert targets(ingest, "Post to ingest") == [["Loop over companies"]]
    assert "onError" not in node(ingest, "Post to ingest")  # intake-api failing stops the run
    assert targets(ingest, "Loop over companies") == [["Fail if a board failed"], ["Fetch board"]]
    assert "throw new Error" in node(ingest, "Fail if a board failed")["parameters"]["jsCode"]


def test_daily_ingest_can_be_limited_to_some_companies():
    query = node(WORKFLOWS["daily-ingest"], "Get companies")["parameters"]["queryParameters"]
    assert query == {"parameters": [{"name": "names", "value": "={{ $env.INGEST_COMPANIES ?? '' }}"}]}


def test_ingest_calls_say_whether_the_batch_is_complete():
    daily = node(WORKFLOWS["daily-ingest"], "Post to ingest")["parameters"]["jsonBody"]
    link = node(WORKFLOWS["submit-link"], "Ingest link")["parameters"]["jsonBody"]
    assert "complete: true" in daily and "only_source_id" not in daily
    assert "complete: false" in link and "only_source_id: $('Resolve link').item.json.body.job_id" in link


def test_submit_link_answers_every_outcome():
    link = WORKFLOWS["submit-link"]
    [hook] = nodes(link, "webhook")
    params = hook["parameters"]
    assert (params["httpMethod"], params["path"], params["authentication"], params["responseMode"]) == (
        "POST", "job-link", "headerAuth", "responseNode")
    assert hook["credentials"]["httpHeaderAuth"]["id"] == WEBHOOK_SECRET_ID
    codes = {n["name"]: n["parameters"]["options"]["responseCode"] for n in nodes(link, "respondToWebhook")}
    assert codes == {"Respond with result": 200, "Respond rejected": 400, "Respond not on board": 404,
                     "Respond board error": "={{ $json.statusCode === 404 ? 404 : 502 }}"}
    assert targets(link, "Link allowed?") == [["Fetch posting"], ["Respond rejected"]]
    assert targets(link, "Board has the job?") == [["Ingest link"], ["Respond board error"]]
    assert targets(link, "Job in the response?") == [["Respond with result"], ["Respond not on board"]]
    for name in ["Resolve link", "Fetch posting"]:  # their 4xx answers are outcomes, not failures
        assert node(link, name)["parameters"]["options"]["response"]["response"]["neverError"] is True


def test_an_intake_api_error_on_the_link_check_fails_the_run():
    """Only 200, 400 and 422 are answers for the person. Any other status from intake-api (a 500, or a 401
    after MACHINE_API_KEY changes) fails the run, so the caller gets 500 and the error workflow sends an alert."""
    link = WORKFLOWS["submit-link"]
    assert targets(link, "Resolve link") == [["Link check answered?"]]
    check = node(link, "Link check answered?")["parameters"]["conditions"]["conditions"][0]["leftValue"]
    assert check == "={{ [200, 400, 422].includes($json.statusCode) }}"
    assert targets(link, "Link check answered?") == [["Link allowed?"], ["Fail on an intake-api error"]]
    assert node(link, "Fail on an intake-api error")["type"] == "n8n-nodes-base.stopAndError"
