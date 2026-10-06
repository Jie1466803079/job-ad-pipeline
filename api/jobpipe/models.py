"""The standard record that every job board's response is converted into."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Source = Literal["greenhouse", "lever", "ashby"]
WorkMode = Literal["onsite", "hybrid", "remote"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship", "graduate_program"]
SalaryPeriod = Literal["year", "month", "day", "hour"]


class BoardFields(BaseModel):
    """Values the job board itself supplies. The checks compare the extraction against them."""

    model_config = ConfigDict(frozen=True)

    locations: list[str] = []
    country: str | None = None
    work_mode: WorkMode | None = None
    employment_type: EmploymentType | None = None
    deadline: date | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: SalaryPeriod | None = None


class Posting(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Source
    source_id: str
    company: str
    title: str
    url: str
    posted_at: datetime | None
    text: str
    text_hash: str
    board: BoardFields

    @property
    def full_text(self) -> str:
        """Title and body: what the LLM reads and what quotes are checked against."""
        return f"{self.title}\n\n{self.text}"
