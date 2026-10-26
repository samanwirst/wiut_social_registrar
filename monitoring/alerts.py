"""Page only for confirmed outages, with persistent deduplication and stable recovery."""

POLICY_VERSION = 2
RECOVERY_SECONDS = 60
MAX_CHECK_GAP = 120
AVAILABILITY_KEYS = (
    "process:bot",
    "process:postgres",
    "process:caddy",
    "database",
    "polling",
    "heartbeat",
    "http",
    "public_https",
)
CONFIRM_SECONDS = {
    "availability": 30,
    "outlook": 180,
    "broadcasts": 180,
    "cleanup": 180,
    "supervisor": 180,
    "backup": 300,
    "disk": 300,
    "tls": 300,
}
RECOVERY_TEXT = {
    "availability": "The bot and Mini App are available again",
    "outlook": "Outlook is available again",
    "broadcasts": "The message delivery worker is available again",
    "cleanup": "The answer cleanup worker is available again",
    "supervisor": "Monitoring checks are working again",
    "backup": "Database backups are healthy again",
    "disk": "Disk space is sufficient again",
    "tls": "The HTTPS certificate is healthy again",
}


def actionable_issues(issues):
    """Group service symptoms; isolated exceptions/restarts are diagnostic signals only."""
    selected = {key: value for key, value in issues.items() if key in CONFIRM_SECONDS}
    unavailable = list(dict.fromkeys(issues[key] for key in AVAILABILITY_KEYS if key in issues))
    if unavailable:
        selected["availability"] = "; ".join(unavailable)
    return selected


def observe(state, issues, recipients, *, now, name, complete=True):
    if state.get("alert_policy") != POLICY_VERSION:
        # Never replay queued messages from the old, per-error notification policy.
        # Process metadata and the automatic-repair budget remain untouched.
        state["records"] = {}
        state["alert_policy"] = POLICY_VERSION
        state.pop("next_delivery", None)
        state.pop("delivery_failures", None)
    issues = actionable_issues(issues)
    records = state.setdefault("records", {})
    for key in set(records) | set(issues):
        record = records.setdefault(
            key,
            {
                "open": False,
                "first_failed_at": None,
                "healthy_since": None,
                "notified": [],
                "pending": [],
            },
        )
        record["notified"] = [value for value in record["notified"] if value in recipients]
        previous = record.get("last_observed_at", now)
        record["last_observed_at"] = now
        if (not complete and key != "supervisor") or (
            key in {"outlook", "broadcasts", "cleanup"} and "availability" in issues
        ):
            # An unavailable observer/service cannot establish dependency recovery.
            # The service alert also replaces its downstream symptom notifications.
            record["first_failed_at"] = None
            record["healthy_since"] = None
            record["pending"] = []
            continue
        if now < previous or now - previous > MAX_CHECK_GAP:
            # An unobserved interval cannot establish continued failure or recovery.
            record["first_failed_at"] = None
            record["healthy_since"] = None
        if key in issues:
            record["healthy_since"] = None
            if record["first_failed_at"] is None:
                record["first_failed_at"] = now
            if now - record["first_failed_at"] >= CONFIRM_SECONDS[key]:
                record["open"] = True
            remaining = [value for value in recipients if value not in record["notified"]]
            duration = CONFIRM_SECONDS[key]
            message = (
                f"Social Registrar · {name}\nAlert: {issues[key]}\n"
                f"Confirmed for at least {duration} seconds"
            )
            kind = "alert"
        else:
            record["first_failed_at"] = None
            if record["healthy_since"] is None:
                record["healthy_since"] = now
            stable = now - record["healthy_since"] >= RECOVERY_SECONDS
            if stable:
                record["open"] = False
                record["first_failed_at"] = None
            # A brief recovery never produces a second alert when the issue returns.
            remaining = record["notified"][:] if stable else []
            message = f"Social Registrar · {name}\nRecovered: {RECOVERY_TEXT[key]}"
            kind = "recovery"
        # Replace stale deliveries with current state. If an unsent outage recovers,
        # neither its old alert nor an unsolicited recovery can be delivered later.
        record["pending"] = (
            [{"kind": kind, "text": message, "remaining": remaining}]
            if remaining and (kind == "recovery" or record["open"])
            else []
        )


def deliver(state, send, *, now):
    if now < state.get("next_delivery", 0):
        return
    failed = False
    deliveries = []
    for record in state.get("records", {}).values():
        for pending in record["pending"]:
            deliveries.extend((record, pending, recipient) for recipient in pending["remaining"])
    for record, pending, recipient in deliveries[:3]:
        if send(recipient, pending["text"]):
            pending["remaining"].remove(recipient)
            if pending["kind"] == "alert":
                if recipient not in record["notified"]:
                    record["notified"].append(recipient)
            elif recipient in record["notified"]:
                record["notified"].remove(recipient)
        else:
            failed = True
    for record in state.get("records", {}).values():
        record["pending"] = [item for item in record["pending"] if item["remaining"]]
    state["delivery_failures"] = min(5, state.get("delivery_failures", 0) + 1) if failed else 0
    state["next_delivery"] = now + min(300, 10 * 2 ** state["delivery_failures"]) if failed else now
