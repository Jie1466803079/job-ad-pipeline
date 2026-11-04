import csv
from datetime import date

from helpers import REPO_ROOT
from jobpipe.eval.labels import CHOICES, COLUMNS, Labels, Salary, main, read_labels
from jobpipe.llm.schema import ROUTING_FIELDS

FILLED = {"work_rights": "not_stated", "security_clearance": "not_stated", "closing_date": "not_stated",
          "locations": "Sydney", "work_mode": "hybrid", "seniority": "mid", "employment_type": "full_time",
          "salary": "not_stated"}


def row(ad_id: str, **cells) -> list[str]:
    values = FILLED | cells
    return [ad_id, "Example", "Data Engineer", f"https://example.test/{ad_id}",
            *[values[name] for name in ROUTING_FIELDS], ""]


def blank_row(ad_id: str) -> list[str]:
    return [ad_id, "Example", "Data Engineer", f"https://example.test/{ad_id}", *[""] * len(ROUTING_FIELDS), ""]


def write_rows(path, rows, header=COLUMNS, encoding="utf-8", line_end="\n"):
    with open(path, "w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, lineterminator=line_end)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_reads_a_labelled_row_and_skips_one_not_labelled_yet(tmp_path):
    path = write_rows(tmp_path / "labels.csv", [
        row("ad001", work_rights="citizen_or_pr", closing_date="2026-10-31", locations="Sydney; Melbourne",
            salary="120000-140000 AUD year"),
        blank_row("ad002"),
    ])
    labels, unlabelled, problems = read_labels(path)
    assert problems == []
    assert unlabelled == ["ad002"]
    assert labels == {"ad001": Labels(
        work_rights="citizen_or_pr", security_clearance="not_stated", closing_date=date(2026, 10, 31),
        locations=["Sydney", "Melbourne"], work_mode="hybrid", seniority="mid", employment_type="full_time",
        salary=Salary(min=120000, max=140000, currency="AUD", period="year"))}


def test_reads_what_a_spreadsheet_saves(tmp_path):
    # Excel and Numbers add a byte-order mark, end lines with CRLF and may rewrite a date as 31/10/2026.
    path = write_rows(tmp_path / "labels.csv", [
        row("ad001", work_rights=" Citizen_Only ", closing_date="31/10/2026", salary="120,000 - 140,000 aud year"),
        row("ad002", closing_date="7/11/26", locations="NOT_STATED", salary="95000 AUD hour"),
    ], encoding="utf-8-sig", line_end="\r\n")
    labels, _, problems = read_labels(path)
    assert problems == []
    assert labels["ad001"].work_rights == "citizen_only"
    assert labels["ad001"].closing_date == date(2026, 10, 31)
    assert labels["ad001"].salary == Salary(min=120000, max=140000, currency="AUD", period="year")
    assert labels["ad002"].closing_date == date(2026, 11, 7)
    assert labels["ad002"].locations == []
    assert labels["ad002"].salary == Salary(min=95000, max=95000, currency="AUD", period="hour")


def test_reads_a_sheet_saved_in_an_older_spreadsheet_encoding(tmp_path):
    # Excel's plain "CSV" format is not UTF-8, so the en dash in a title such as IMC's is saved as one byte.
    cells = row("ad001")
    cells[2] = "Commodities Analyst \u2013 China"
    path = write_rows(tmp_path / "labels.csv", [cells], encoding="cp1252")
    labels, unlabelled, problems = read_labels(path)
    assert (sorted(labels), unlabelled, problems) == (["ad001"], [], [])


def test_reports_every_cell_it_cannot_read_with_its_line(tmp_path):
    path = write_rows(tmp_path / "labels.csv", [
        row("ad001", work_rights="citizen"),
        row("ad002", closing_date="31 Oct"),
        row("ad003", salary="120k"),
        row("ad004", salary="140000-120000 AUD year"),
        row("ad005", seniority=""),
        row("ad001"),
    ])
    labels, unlabelled, problems = read_labels(path)
    assert labels == {} and unlabelled == []
    assert problems == [
        "line 2 (ad001): work_rights 'citizen' is not one of: citizen_only, citizen_or_pr, any_work_rights, "
        "sponsorship_available, not_stated",
        "line 3 (ad002): closing_date '31 Oct' is not a date such as 2026-10-31, or not_stated",
        "line 4 (ad003): salary '120k' is not a salary such as '120000-140000 AUD year', or not_stated",
        "line 5 (ad004): salary '140000-120000 AUD year' has a minimum above its maximum",
        "line 6 (ad005): seniority is blank",
        "line 7: ad001 appears twice",
    ]


def test_reports_a_missing_column(tmp_path):
    header = [column for column in COLUMNS if column != "salary"]
    path = write_rows(tmp_path / "labels.csv", [], header=header)
    assert read_labels(path) == ({}, [], ["labels.csv has no column called salary"])


def test_the_check_command_counts_labels_and_fails_on_a_problem(tmp_path, capsys):
    write_rows(tmp_path / "labels.csv", [row("ad001"), blank_row("ad002")])
    assert main(["--eval-dir", str(tmp_path)]) == 0
    assert "Labelled: 1. Not labelled yet: 1. Problems: 0." in capsys.readouterr().out
    write_rows(tmp_path / "labels.csv", [row("ad001", work_mode="sometimes")])
    assert main(["--eval-dir", str(tmp_path)]) == 1
    assert "work_mode 'sometimes' is not one of" in capsys.readouterr().out


def test_the_check_command_without_a_labels_file(tmp_path, capsys):
    assert main(["--eval-dir", str(tmp_path)]) == 1
    assert "Run make eval-sample first." in capsys.readouterr().out


def test_the_labelling_guide_names_every_value():
    guide = (REPO_ROOT / "eval" / "LABELLING.md").read_text(encoding="utf-8")
    for field, values in CHOICES.items():
        assert f"### {field}" in guide
        for value in values:
            assert f"`{value}`" in guide, (field, value)
    for field in ("closing_date", "locations", "salary"):
        assert f"### {field}" in guide
