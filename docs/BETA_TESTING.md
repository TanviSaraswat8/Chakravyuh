# Alpha and beta testing

The goal of testing is to answer two questions the simulator can't: do real people find the alerts useful, and how often do alerts land on genuine activity?

## Phases

| Phase | Who | Setup | What we measure |
| --- | --- | --- | --- |
| Alpha | The team and 5–10 friends | `ALLOW_REGISTRATION=true`; demo scenarios plus live sessions under their own accounts | Bugs, confusing copy, whether alerts are understood |
| Closed beta | 30–100 invited testers, ideally some fraud analysts | `ALLOW_REGISTRATION=false`; an admin creates accounts (`python -m app.manage create-user`) | False alerts, missed scams, alert usefulness ratings |
| Analyst beta | Fraud or risk teams | ANALYST accounts; campaign review | Whether campaign cards and draft rules are worth acting on |

## Running it

1. Deploy (see `DEPLOY.md`) and share the web app link.
2. Testers create an account on the **Account** page (or are given one). Their live sessions are private to that account. The **Beta** page's tester key is optional: it is shown once, never stored by the browser, and only links feedback to the tester.
3. Testers try the live session demo and report through the **Report something** form. Reports have a kind: false alert, missed scam, bug or general.
4. Alert responses ("This is a scam, end it" or "I know this person") are stored against each alert, so you can measure usefulness without asking.

## Reading the results

Feedback and the tester list need an ADMIN account (the old shared admin key is retired). Sign in,
then send the session cookie:

```bash
curl -c jar -H "Content-Type: application/json" -d '{"email":"admin@example.com","password":"..."}' https://<api>/v1/auth/login
curl -b jar https://<api>/v1/beta/feedback      # all reports
curl -b jar https://<api>/v1/beta/testers       # who signed up
curl https://<api>/v1/metrics                   # sessions, alerts, responses by level (aggregate, public)
```

Numbers worth tracking each week:

- **Alerts per 1,000 sessions**, split by level. Watch for growth in levels 3–4.
- **"I know this person" rate** on alerts: this is the false-alert rate as users experience it.
- **False alert and missed scam reports**, read one by one. Each missed scam is a candidate for the next simulator run.
- **Usefulness ratings** (1–5) on warnings.

## Exit criteria for the beta

- Fewer than 1 in 100 legitimate sessions gets any alert, and none gets a hold.
- Testers rate warnings useful (4 or 5) at least 70% of the time.
- Every missed scam report is reproduced in the simulator and caught after retraining.

## Privacy during testing

Keep `STORE_MESSAGE_TEXT=false` for anything beyond the alpha. Ask testers not to paste real personal or banking details into the demo. Delete test data at the end of the beta.
