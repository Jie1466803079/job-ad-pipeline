# Evaluation results

Written by `python -m jobpipe.eval.run` from the JSON files in this folder. Runs over all ads without labels are listed by the share sent to review, then cost. Runs on the dev and test splits, which are scored against hand labels, are listed in the order used to pick the daily model: the smallest share of ads with a wrong field among those routed automatically, then the fewest sent to review, then the lowest cost.

## All ads, without labels (80 ads)

These runs have no labels, so they say nothing about accuracy. They are listed by the share sent to review, then cost.

| Method | Routed automatically | Sent to review | Failed | Cost per 1,000 ads | Median time per ad | Injected instruction followed | Prompt |
|---|---|---|---|---|---|---|---|
| gemini-3.8-flash (default) | 73 of 80 (91%) | 7 of 80 (9%) | 1 | US$8.12 | 11.7 s | 0 of 4 (0 routed automatically) | f778ac5f5940 |
| Rules baseline | 63 of 80 (79%) | 17 of 80 (21%) | 0 | US$0.00 | 0.0 s | 3 of 4 (3 routed automatically) | - |

How often two methods route an ad the same way, and give the same value for each field where both extractions worked, compared by the scoring rules in eval/LABELLING.md. Agreement is not accuracy: two methods can agree and both be wrong.

| Methods | Ads | Same route | Values compared | work_rights | security_clearance | closing_date | locations | work_mode | seniority | employment_type | salary |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemini-3.8-flash (default) vs Rules baseline | 80 | 66 | 79 | 71 | 79 | 79 | 65 | 66 | 75 | 64 | 76 |
