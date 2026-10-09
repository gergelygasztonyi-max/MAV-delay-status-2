# MÁV delay status — Biatorbágy → Budapest

Scheduled GitHub Actions prototype for departures from Biatorbágy between 05:55 and 07:10 toward Budapest-Kelenföld and Budapest-Déli.

## Status: NOT YET VALIDATED

The first live workflow run must confirm that the upstream MÁVPlusz/EMMA endpoint responds from GitHub-hosted runners and exposes explicit live departure estimates. An HTTP 200 response alone is not sufficient proof.

## How it works

- Calls the public community proxy used by the open-source regi-elvira project, which fronts the MÁVPlusz/EMMA OpenTripPlanner GraphQL API.
- Filters railway legs that originate at Biatorbágy and fall within the requested time window.
- Reports a delay only when the API explicitly supplies a realtime departure delay. Missing data is never treated as zero delay.
- Writes Markdown and JSON output as a workflow artifact and into the GitHub Actions job summary.

The endpoint/proxy is unofficial and can change or rate-limit requests. It is not a supported public MÁV developer API.

## Required first validation

1. Open Actions → MÁV morning status.
2. Select Run workflow and choose the validate mode.
3. Open the run logs. A valid test must show API_VALIDATION: PASS and a sample containing real_time=true.
4. If it fails, the project is not ready for automatic reporting. Inspect the error and adjust the API request before relying on it.

The initial workflow also runs a validation on push.

## Scheduled report

The workflow is scheduled for weekdays at 04:30 UTC, which is 06:30 in Hungary during summer time. GitHub Actions cron uses UTC and does not adjust for daylight saving time; in winter, change the cron to 05:30 UTC to keep the report at 06:30 local time.

The report is attached to each workflow run as an artifact and appears in the job summary. GitHub Actions cannot send a message directly into a ChatGPT conversation. The report can be opened from GitHub and then referenced in ChatGPT, but automatic ChatGPT delivery is not implemented by this prototype.

## Run locally

No extra Python packages are required (Python 3.11+):
- Validate current live data: REPORT_MODE=validate python mav_report.py
- Generate the morning report: python mav_report.py

Optional environment variables:
- REPORT_MODE=validate
- REPORT_DATE=YYYY-MM-DD
- MAV_API_URL=https://regi-elvira.kajc10.deno.net
