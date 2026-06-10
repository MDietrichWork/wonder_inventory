"""Jira Cloud REST v3 ticket sink (used only when TICKET_SINK=jira).

create() opens an issue with the error detail + offending snapshot and tags it with the
fingerprint (custom field if configured, else a label) so re-runs can find it. close()
performs the configured Done transition for auto-close. Failures are logged and swallowed
so a Jira hiccup never breaks the validation run.
"""
import json
import logging
from typing import Optional

import httpx

from .base import TicketSink
from ..config import settings

log = logging.getLogger("wonder.jira")


def _adf(text: str) -> dict:
    """Minimal Atlassian Document Format wrapper (v3 requires ADF for description)."""
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    ]}


class JiraTicketSink(TicketSink):
    def __init__(self):
        for req in ("jira_base_url", "jira_email", "jira_api_token"):
            if not getattr(settings, req):
                raise RuntimeError("TICKET_SINK=jira requires %s in .env" % req.upper())
        self.base = settings.jira_base_url.rstrip("/")
        self.client = httpx.Client(
            auth=httpx.BasicAuth(settings.jira_email, settings.jira_api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=20.0,
        )

    def _summary(self, error) -> str:
        return "[%s] %s @ %s (%s)" % (error.severity, error.error_type, error.entity_key, error.rule_id)

    def _description(self, error) -> str:
        snap = json.dumps(error.data_snapshot, indent=2)
        return ("Auto-created by Wonder DQ validator.\n"
                "Rule: %s  Severity: %s  Run: %s\n"
                "Routed: %s / %s\nFingerprint: %s\n\nOffending %s row:\n%s"
                % (error.rule_id, error.severity, error.first_run_date, error.routed_team,
                   error.routed_assignee, error.fingerprint, error.source_table, snap))

    def create(self, error) -> Optional[str]:
        fields = {
            "project": {"key": settings.jira_project_key},
            "summary": self._summary(error),
            "description": _adf(self._description(error)),
            "issuetype": {"name": settings.jira_issue_type},
            "labels": ["wonder-dq", "fp-" + error.fingerprint[:16]],
        }
        if error.routed_team:
            fields["components"] = [{"name": error.routed_team}]
        if settings.jira_fingerprint_field:
            fields[settings.jira_fingerprint_field] = error.fingerprint
        try:
            r = self.client.post(self.base + "/rest/api/3/issue", json={"fields": fields})
            r.raise_for_status()
            return r.json().get("key")
        except Exception as e:  # pragma: no cover - network
            log.warning("Jira create failed for %s: %s", error.entity_key, e)
            return None

    def comment(self, error, text: str) -> None:
        if not error.jira_issue_key:
            return
        try:
            self.client.post(self.base + "/rest/api/3/issue/%s/comment" % error.jira_issue_key,
                             json={"body": _adf(text)}).raise_for_status()
        except Exception as e:  # pragma: no cover
            log.warning("Jira comment failed for %s: %s", error.jira_issue_key, e)

    def close(self, error, text: str) -> None:
        if not error.jira_issue_key:
            return
        try:
            self.comment(error, text)
            tr = self.client.get(self.base + "/rest/api/3/issue/%s/transitions" % error.jira_issue_key)
            tr.raise_for_status()
            target = settings.jira_done_transition.lower()
            tid = next((t["id"] for t in tr.json().get("transitions", [])
                        if t["name"].lower() == target), None)
            if tid:
                self.client.post(self.base + "/rest/api/3/issue/%s/transitions" % error.jira_issue_key,
                                 json={"transition": {"id": tid}}).raise_for_status()
        except Exception as e:  # pragma: no cover
            log.warning("Jira close failed for %s: %s", error.jira_issue_key, e)
