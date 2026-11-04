from jobpipe.eval.report import render_run, render_summary
from jobpipe.eval.score import summarise_unlabelled
from jobpipe.llm.schema import ROUTING_FIELDS

VALUES = {"work_rights": "not_stated", "security_clearance": "not_stated", "closing_date": "not_stated",
          "locations": ["Sydney"], "work_mode": "not_stated", "seniority": "not_stated",
          "employment_type": "not_stated", "salary": "not_stated"}


def ad(ad_id, route="tracked", original=None, reasons=(), **values):
    return {"id": ad_id, "original": original, "route": route, "reasons": list(reasons), "failed": False,
            "values": VALUES | values, "correct": None, "cost_usd": 0.001, "latency_ms": 2000}


def label_free_doc(run, provider, model, ads):
    gemini = provider == "gemini"
    return {"run": run, "split": "all", "provider": provider, "model": model,
            "setting": "default" if gemini else None, "prompt": "abc123" if gemini else None,
            "date": "2026-10-25T01:00:00+00:00", "metrics": summarise_unlabelled(ads), "ads": ads}


def test_a_label_free_run_report_shows_routing_review_reasons_and_the_injected_copies():
    ads = [ad("a", "ineligible", work_rights="citizen_only"),
           ad("b", "review", reasons=["locations: quote not found in the ad"]),
           ad("a-inj", original="a", work_rights="any_work_rights")]
    text = render_run(label_free_doc("all_gemini_gemini-3.8-flash_default", "gemini", "gemini-3.8-flash", ads))
    assert ("gemini-3.8-flash (default) on all 2 ads, without labels, run on 2026-10-25. Prompt version abc123."
            in text)
    assert "These numbers do not measure accuracy: nobody has checked the values against the ads." in text
    assert "| locations | 1 |" in text
    assert "Followed the injected instruction: 1 of 1, routed automatically: 1." in text
    assert "| a-inj | ineligible | tracked | work_rights |" in text


def test_the_summary_ranks_label_free_runs_and_shows_how_often_methods_agree():
    rules = label_free_doc("all_rules", "rules", "rules-1",
                           [ad("a", "review", reasons=["seniority: no quote given"]), ad("b")])
    flash = label_free_doc("all_gemini_gemini-3.8-flash_default", "gemini", "gemini-3.8-flash", [ad("a"), ad("b")])
    labelled = {"run": "dev_rules", "split": "dev", "provider": "rules", "model": "rules-1", "setting": None,
                "prompt": None, "metrics": {
                    "ads": 2, "auto_routed": 2, "auto_routed_wrong": 0,
                    "routes": {"tracked": 2, "ineligible": 0, "review": 0}, "cost_per_1000_usd": 0.0,
                    "median_latency_ms": 0, "injected": 0, "injected_auto_wrong": 0,
                    "field_accuracy": dict.fromkeys(ROUTING_FIELDS, 2)}}
    text = render_summary([rules, labelled, flash])
    assert "## All ads, without labels (2 ads)" in text
    assert text.index("| gemini-3.8-flash (default) |") < text.index("| Rules baseline |")
    assert "| gemini-3.8-flash (default) vs Rules baseline | 2 | 1 | 2 |" in text
    assert "Agreement is not accuracy" in text
    assert "## Dev split (2 ads)" in text
