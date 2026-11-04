from datetime import date

from jobpipe.digest_email import day_label, render_digest

COUNTS = {"fetched": 120, "created": 6, "skipped": 80, "tracked": 2, "review": 3, "ineligible": 0, "closed": 1,
          "failed": 0}
TODAY = date(2026, 10, 9)
SITE = "http://127.0.0.1:8000"


def tracked_ad(**changes) -> dict:
    ad = {"id": 12, "company": "Canva", "title": "Data Engineer", "url": "https://example.test/12",
          "closing_date": date(2026, 10, 31), "fit": {"matched": ["Python", "SQL"], "missing": ["AWS"], "total": 3}}
    return ad | changes


def digest_with(**changes) -> dict:
    digest = {
        "tracked": [tracked_ad()],
        "closing_soon": [{"id": 7, "company": "Xero", "title": "ML Engineer", "url": "https://example.test/7",
                          "closing_date": date(2026, 10, 12), "status": "applied"}],
        "review_count": 4, "counts": COUNTS, "llm_cost_usd": 0.0712,
    }
    return digest | changes


def test_subject_gives_the_day_and_three_numbers():
    assert render_digest(digest_with(), TODAY, SITE).subject == (
        "Job digest 9 Oct 2026: 1 new, 1 closing soon, 4 to review")


def test_text_lists_each_ad_with_its_review_link():
    text = render_digest(digest_with(), TODAY, SITE + "/").text
    assert text.startswith("Job digest for 9 Oct 2026\n\nNew tracked ads: 1\n")
    assert "- Data Engineer at Canva. Closes 31 Oct 2026. Fit 2 of 3.\n  http://127.0.0.1:8000/#/postings/12\n" in text
    assert "- ML Engineer at Xero (applied). Closes 12 Oct 2026.\n  http://127.0.0.1:8000/#/postings/7\n" in text
    assert "Waiting for review: 4\nhttp://127.0.0.1:8000/#/queue/review\n" in text
    assert ("Last 24 hours: 120 fetched, 6 new, 80 skipped, 2 tracked, 3 to review, 0 not eligible, 1 closed, "
            "0 failed. LLM cost: US$0.07.") in text


def test_html_escapes_titles_and_company_names():
    hostile = tracked_ad(id=3, company="A&B <Pty>", title='<img src=x onerror="alert(1)">', closing_date=None,
                         fit=None)
    html = render_digest(digest_with(tracked=[hostile]), TODAY, SITE).html
    assert "<img" not in html
    assert '<a href="http://127.0.0.1:8000/#/postings/3">&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</a>' in html
    assert "at A&amp;B &lt;Pty&gt;. No closing date." in html


def test_a_quiet_day_still_says_what_happened():
    quiet = digest_with(tracked=[], closing_soon=[], review_count=0, counts=dict.fromkeys(COUNTS, 0),
                        llm_cost_usd=0.0)
    email = render_digest(quiet, TODAY, SITE)
    assert email.subject == "Job digest 9 Oct 2026: 0 new, 0 closing soon, 0 to review"
    assert "New tracked ads: 0\n\nClosing within 7 days: 0\n\nWaiting for review: 0\n" in email.text
    assert "LLM cost: US$0.00." in email.text
    assert "<ul>" not in email.html


def test_an_ad_without_a_closing_date_or_verified_skills():
    ad = tracked_ad(title="Analyst", closing_date=None, fit={"matched": [], "missing": [], "total": 0})
    assert "- Analyst at Canva. No closing date.\n" in render_digest(digest_with(tracked=[ad]), TODAY, SITE).text


def test_titles_are_kept_on_one_line():
    ad = tracked_ad(title="Data\n  Engineer\t(Sydney)")
    assert "- Data Engineer (Sydney) at Canva." in render_digest(digest_with(tracked=[ad]), TODAY, SITE).text


def test_day_label():
    assert day_label(date(2026, 1, 5)) == "5 Jan 2026"
