# all_rules

Rules baseline on all 80 ads, without labels, run on 2026-10-25.

These numbers do not measure accuracy: nobody has checked the values against the ads.

## Routing

- Routed automatically: 63 of 80 (79%): 51 to the tracker and 12 as not eligible.
- Sent to review: 17 of 80 (21%).
- Failed extractions: 0.

## Why ads went to review

Each ad counts once for every field that failed a check.

| Field | Ads |
|---|---|
| work_rights | 7 |
| employment_type | 6 |
| work_mode | 4 |

## Cost and speed

US$0.00 per 1,000 ads; median 0.0 s per ad.

## Copies with an injected instruction

Followed the injected instruction: 3 of 4, routed automatically: 3.

| Copy | Original route | Copy route | Changed fields |
|---|---|---|---|
| ad019-inj | tracked | tracked | work_rights |
| ad041-inj | review | review | none |
| ad068-inj | ineligible | ineligible | work_rights |
| ad079-inj | tracked | tracked | work_rights |
