# WIUT Social Registrar

A console tool for looking up students by ID, retrieving their name, email address, and account, and sending them email from your account. It uses the official Microsoft Graph v1.0 API and MSAL Python for authentication. Requests share a single `requests` HTTP session; browser automation is no longer required.

Sign-in and student profile lookup have been verified with the current account. The delegated permissions `User.Read`, `User.ReadBasic.All`, and `Mail.Send` were granted through user consent, without requesting approval from a university administrator. Email submission is tested with a mocked HTTP transport; no real test emails were sent.

## Getting started

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# For a new installation only: configure the application in .env.
test -f .env || cp .env.example .env
chmod 600 .env
python main.py
```

The application and sign-in are already configured in `.env` in this working copy. By default, the program prompts for student IDs in the terminal. A blank line or EOF exits the program. Leading zeroes are preserved. The first request reads your profile, then retrieves the student by their exact `userPrincipalName`, such as `00025208@wiut.uz`. This avoids ambiguity when selecting the first search result.

## Commands

```bash
python main.py                           # Enter student IDs interactively
python main.py --id 00025208              # Look up one profile
python main.py --id 00025208 --json       # JSON output for another script
python main.py --debug                    # Method, path, HTTP status, timing, cache hits
python main.py --login                    # Sign in again
python main.py --logout                   # Clear the local token cache
python main.py --env-file /path/to/.env
```

When sign-in is required, MSAL displays an official Microsoft URL and a one-time code. Open the URL in your browser, enter the code, and confirm sign-in to `WIUT Social Registrar`. The program never receives your password. MSAL refreshes tokens automatically.

Preview an email:

```bash
python main.py --id 00025208 --subject 'Email subject' --body 'Email body'
python main.py --id 00025208 --subject 'Email subject' --body-file letter.txt
```

Add **`--send`** to either command to send the email. Body files must use UTF-8 encoding. The student's profile is fetched from Graph again before sending. Emails are submitted through `/me/sendMail` from the signed-in account and saved in Sent Items. HTTP 202 means Microsoft accepted the email for sending; it does not confirm delivery. Submission is never retried automatically after a timeout or an ambiguous error: check Sent Items first.

The `--json` result contains `student_id`, `name`, `email`, `account`, `email_addresses`, and `source`. For emails, it also includes `message` with the sender, recipient, subject, body, and a status of `preview` or `accepted`. A missing student is represented as `null`. Results go to stdout; sign-in messages and network logs go to stderr. Authorization headers, tokens, and full error responses are excluded from logs.

Exit codes: `0` for success or a completed interactive session; `1` when no student is found; `2` for an error; `130` for Ctrl+C. HTTP 403 and network errors are reported as errors, not as missing students.

## Core API

```python
from registrar.config import Settings
from registrar.graph import GraphClient

with GraphClient(Settings.load()) as client:
    student = client.find_student("00025208")
    if student:
        print(student.to_dict())
        print(client.mail_preview(student, "Subject", "Body"))
        # Explicit submission: client.send_email(student, "Subject", "Body")
```

`find_student()` returns a `Student` or `None`, and raises `GraphError` on failure. The sender's profile is cached for the lifetime of the client. Student profiles are cached for 5 minutes, up to 256 entries. Repeated lookups use the cache without a network request. `refresh=True` fetches the student's profile again. GET requests receiving HTTP 429/503 honor `Retry-After` delays of up to 10 seconds, with at most three attempts. The core does not queue emails or automatically resubmit them.

## Application and configuration

Settings are listed in [.env.example](.env.example). A new environment requires your own Microsoft Entra application: a single organizational tenant, a public client, and `Allow public client flows` enabled. No client secret is used. Copy `GRAPH_CLIENT_ID` and `GRAPH_TENANT_ID` from the application's overview page. Delegated permissions are requested dynamically during sign-in; the application does not use application permissions. Policies may differ for other accounts or tenants.

`GRAPH_ACCOUNT` restricts sign-in to the specified UPN. The student account domain is inferred from your account's UPN and can be overridden with `GRAPH_STUDENT_DOMAIN`. Configure the HTTP read timeout and student profile cache lifetime through `GRAPH_TIMEOUT_SECONDS` and `GRAPH_CACHE_TTL_SECONDS`.

The MSAL cache, including refresh tokens, is stored in `GRAPH_TOKEN_CACHE_B64` inside `.env` with permissions set to `600`. The file is excluded from Git. Base64 does not encrypt secrets. Neither your Microsoft password nor a client secret is stored. `--logout` clears only the local cache. Use one process per `.env` file to avoid concurrent cache writes.

## Testing

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests run without an account or network access. They cover exact student IDs, caching, errors and access restrictions, token refresh, private `.env` storage, console JSON output, previews, email submission, and prevention of retries when submission status is unknown.

Microsoft documentation: [get a user](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0), [send email](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0), [authenticate with MSAL](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens).
