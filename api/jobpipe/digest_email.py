"""The daily digest as an email: a subject, a plain-text body and an HTML body.

n8n only sends what this returns. Titles and company names come from job ads, so the HTML escapes them.
"""

from dataclasses import dataclass
from datetime import date
from html import escape

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COUNT_LABELS = [("fetched", "fetched"), ("created", "new"), ("skipped", "skipped"), ("tracked", "tracked"),
                ("review", "to review"), ("ineligible", "not eligible"), ("closed", "closed"), ("failed", "failed")]
STYLE = "font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; color: #1f2933"


@dataclass(frozen=True)
class DigestEmail:
    subject: str
    text: str
    html: str


def day_label(day: date) -> str:
    """date(2026, 10, 31) becomes "31 Oct 2026", as on the review page."""
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _describe(ad: dict) -> str:
    """Everything after the title: company, status when it is not tracked, closing date and fit."""
    status = ad.get("status", "tracked")
    company = _one_line(ad["company"]) + ("" if status == "tracked" else f" ({status})")
    closes = f"Closes {day_label(ad['closing_date'])}." if ad["closing_date"] else "No closing date."
    fit = ad.get("fit") or {}
    fit_text = f" Fit {len(fit['matched'])} of {fit['total']}." if fit.get("total") else ""
    return f"at {company}. {closes}{fit_text}"


def render_digest(digest: dict, today: date, review_url: str) -> DigestEmail:
    base = review_url.rstrip("/")
    review_count = digest["review_count"]
    title = f"Job digest for {day_label(today)}"
    subject = (f"Job digest {day_label(today)}: {len(digest['tracked'])} new, "
               f"{len(digest['closing_soon'])} closing soon, {review_count} to review")
    counts = ", ".join(f"{digest['counts'][key]} {label}" for key, label in COUNT_LABELS)
    totals = f"Last 24 hours: {counts}. LLM cost: US${digest['llm_cost_usd']:.2f}."
    queue = f"{base}/#/queue/review"

    text, html = [title, ""], [f"<h2>{escape(title)}</h2>"]
    lists = [("New tracked ads", digest["tracked"]), ("Closing within 7 days", digest["closing_soon"])]
    for heading, ads in lists:
        text.append(f"{heading}: {len(ads)}")
        html.append(f"<h3>{heading}: {len(ads)}</h3>")
        items = []
        for ad in ads:
            link, ad_title, about = f"{base}/#/postings/{ad['id']}", _one_line(ad["title"]), _describe(ad)
            text += [f"- {ad_title} {about}", f"  {link}"]
            items.append(f'<li><a href="{escape(link)}">{escape(ad_title)}</a> {escape(about)}</li>')
        if items:
            html.append("<ul>\n" + "\n".join(items) + "\n</ul>")
        text.append("")
    text += [f"Waiting for review: {review_count}", queue, "", totals]
    html += [f"<h3>Waiting for review: {review_count}</h3>",
             f'<p><a href="{escape(queue)}">Open the review queue</a></p>', f"<p>{escape(totals)}</p>"]
    body = "\n".join(html)
    return DigestEmail(subject=subject, text="\n".join(text) + "\n",
                       html=f'<!doctype html>\n<html><body style="{STYLE}">\n{body}\n</body></html>\n')
