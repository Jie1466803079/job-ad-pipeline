# Labelling guide

This guide is for filling in `eval/labels.csv`: eight fields for each of the 80 ads in the evaluation. The labels
are the answers that the rules baseline and each model are scored against, so they need to follow the same rules
from the first ad to the last. Allow about two minutes an ad. You can stop at any point: a row left blank simply
counts as not labelled yet.

## Before you start

- Label from the text files in `eval/snapshots/`, for example `eval/snapshots/ad001.txt`. Each holds the ad's
  title and text as they were on the day the sample was drawn, which is what every method reads.
- Don't open these ads on the review page until all 80 are labelled. The review page shows what Gemini extracted,
  and the labels must not be influenced by any model's answers.
- Don't read `eval/results/` until all 80 are labelled either: the runs saved there hold each method's answers.
- The link in each file is for reference only. If the ad has changed or closed since, the text file is what
  counts.
- Label what the ad's text says, title included. Ignore the tags a job board shows beside an ad, such as a
  "Full-time" badge or the office location: the pipeline compares its answers with those tags in a separate check.

## Filling in labels.csv

- Open `eval/labels.csv` in Numbers, Excel or a text editor. Keep the header row and the `id`, `company`, `title`
  and `url` columns as they are, and fill in one row per ad.
- Write each value as this guide lists it, such as `citizen_or_pr`. Capital letters are fine.
- Once you start a row, fill in all eight fields. Use `not_stated` when the ad doesn't say.
- Write anything you were unsure about in `notes`. Notes are not scored.
- Save as CSV, then run `make eval-labels`. It lists every cell it can't read, with its line number, and counts the
  rows done.

## The fields

### work_rights

What the ad says about citizenship, residency or visas.

| Value | When |
|---|---|
| `citizen_only` | Only Australian citizens can apply. Also use it when the role needs an Australian security clearance, or the ability to get one, and the ad says nothing else about work rights: clearances are open to citizens only. |
| `citizen_or_pr` | Australian citizens or permanent residents can apply. |
| `any_work_rights` | Any valid right to work in Australia, visas included. "Full working rights in Australia" and "we are unable to sponsor visas" both count. |
| `sponsorship_available` | The employer offers visa sponsorship. |
| `not_stated` | None of the above. A statement that the employer doesn't discriminate on citizenship is not a requirement. |

### security_clearance

| Value | When |
|---|---|
| `baseline`, `nv1`, `nv2` or `pv` | The role needs that clearance or the ability to obtain it. If the ad names several levels as possibilities, such as "Baseline, NV1 or NV2", use the lowest one named. |
| `other` | A clearance is needed but no level is given. |
| `not_stated` | No clearance is mentioned, or the ad says none is needed. |

### closing_date

The date applications close, written like `2026-10-31`. If the ad gives a day and month but no year, use the first
such date on or after the posting date at the top of the text file. Use `not_stated` when there is no date, for
example when applications are reviewed as they arrive.

### locations

The places where the ad's text says the role can be based, separated by semicolons: `Sydney; Melbourne`. Write
`Remote, Australia` for a role that can be done from anywhere in Australia. Leave out the company's other offices
unless the ad says the role can be based there. Use `not_stated` when the text names no place.

### work_mode

| Value | When |
|---|---|
| `onsite` | Always at an office or site. |
| `hybrid` | Some days in an office and some elsewhere. |
| `remote` | Fully remote. |
| `not_stated` | The text doesn't say. |

### seniority

Use the title first. When it has more than one of these words, the first row that matches wins.

| Value | The title says |
|---|---|
| `graduate_or_entry` | intern, internship, graduate or entry level |
| `junior` | junior |
| `lead_or_above` | lead, staff, principal, head, manager or director |
| `senior` | senior |

If the title has none of these words, use the years of experience the ad asks for, taking the lower figure of a
range: under 1 year is `graduate_or_entry`, 1 to 2 years `junior`, 3 to 4 years `mid`, and 5 or more `senior`. If
the ad asks for neither, use `not_stated`.

### employment_type

| Value | When the text says |
|---|---|
| `full_time` | full-time or permanent |
| `part_time` | part-time |
| `contract` | contract, fixed-term, maximum-term or temporary |
| `internship` | internship |
| `graduate_program` | graduate program |
| `not_stated` | none of these. Don't assume full-time. |

### salary

The pay the text advertises, written as minimum, maximum, currency and period: `120000-140000 AUD year`. The period
is `year`, `month`, `day` or `hour`. Write plain numbers, so 120000 rather than 120k. When the ad gives one figure,
write it once: `95000 AUD year`. If it gives several ranges, use the one for an Australian location, or else the
first. Use `not_stated` when no pay is given.

## How answers are scored

- `work_rights`, `security_clearance`, `closing_date`, `work_mode`, `seniority` and `employment_type` must match
  exactly.
- `locations` are compared as sets of Australian cities, plus whether remote work is offered. Places outside
  Australia are ignored, and "Sydney, NSW" matches "Sydney".
- `salary` must have the same period, with the minimum and the maximum each within 1% of the label. The currency is
  not compared.
- An ad that a method routes automatically counts as an error if any of its eight fields is wrong.

## The test set

`eval/split.json` puts 20 ads in the dev set and 60 in the test set. The prompt is tuned on the dev set only. Once
the first method has been scored on the test set, leave the test labels as they are; if you find a mistake after
that, describe it in `notes` instead.
