"""Jira Cloud REST v3 ticket sink (used only when TICKET_SINK=jira).

create() opens an issue with the error detail + offending snapshot and tags it with the
fingerprint (custom field if configured, else a label) so re-runs can find it. close()
performs the configured Done transition for auto-close. Failures are logged and swallowed
so a Jira hiccup never breaks the validation run.
"""
import logging
from typing import Optional

import httpx

from .base import TicketSink
from ..config import settings

log = logging.getLogger("wonder.jira")

# Map our severity model onto Jira's default priority scheme.
SEVERITY_TO_PRIORITY = {"Urgent": "Highest", "High": "High", "Medium": "Medium", "Low": "Low"}


def _adf(text: str) -> dict:
    """Minimal Atlassian Document Format wrapper (v3 requires ADF for plain comments)."""
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
        return "%s // %s" % (error.error_type, error.entity_key)

    def _description_adf(self, error) -> dict:
        """A clean, human-readable issue body (no raw JSON) for anyone working it in Jira."""
        snap = error.data_snapshot or {}

        def para(text, label=None):
            content = []
            if label is not None:
                content.append({"type": "text", "text": label, "marks": [{"type": "strong"}]})
            content.append({"type": "text", "text": text})
            return {"type": "paragraph", "content": content}

        body = [
            para("Auto-created by the Wonder Inventory Data-Quality validator."),
            para("%s · severity %s · run %s" % (error.error_type, error.severity, error.first_run_date)),
            para("Routed to %s / %s." % (error.routed_team, error.routed_assignee)),
            {"type": "heading", "attrs": {"level": 4}, "content": [{"type": "text", "text": "What was flagged"}]},
        ]
        HIDE = {"tolerance_pct", "uom_match", "ordered_uom", "received_uom", "implausible_quantity"}
        shown, rows = set(), []

        def add(label, val, *keys):
            rows.append((label, "NULL" if val is None else str(val)))
            shown.update(keys)

        if "po" in snap: add("PO", snap["po"], "po")
        if "consumable_sku" in snap: add("Consumable SKU", snap["consumable_sku"], "consumable_sku")
        if "item_name" in snap: add("Item", snap["item_name"], "item_name")
        if "ordered_qty" in snap:
            add("Ordered", ("%s %s" % (snap["ordered_qty"], snap.get("ordered_uom", ""))).strip(), "ordered_qty")
        if "received_qty" in snap:
            add("Received", ("%s %s" % (snap["received_qty"], snap.get("received_uom", ""))).strip(), "received_qty")
        if "over_by_pct" in snap: add("Over ordered by", "%s%%" % snap["over_by_pct"], "over_by_pct")
        for k, v in snap.items():  # any remaining fields, generically
            if k in shown or k in HIDE:
                continue
            add(k.replace("_", " ").capitalize(), v)
        if snap.get("implausible_quantity"):
            rows.append(("Flag", "Implausible quantity — received is more than 2x ordered"))

        body.append({"type": "bulletList", "content": [
            {"type": "listItem", "content": [para(v, label + ": ")]} for label, v in rows]})
        body.append(para("Fingerprint %s" % error.fingerprint))
        return {"type": "doc", "version": 1, "content": body}

    def create(self, error) -> Optional[str]:
        base = {
            "project": {"key": settings.jira_project_key},
            "summary": self._summary(error),
            "description": self._description_adf(error),
            "issuetype": {"name": settings.jira_issue_type},
            "labels": ["wonder-dq", "fp-" + error.fingerprint[:16]],
        }
        if settings.jira_fingerprint_field:
            base[settings.jira_fingerprint_field] = error.fingerprint
        optional = {"priority": {"name": SEVERITY_TO_PRIORITY.get(error.severity, "Medium")}}
        if error.routed_team:
            optional["components"] = [{"name": error.routed_team}]
        # Try with priority + components; if the project rejects either, fall back (priority first).
        last = None
        for drop in ((), ("components",), ("components", "priority")):
            fields = dict(base, **{k: v for k, v in optional.items() if k not in drop})
            try:
                r = self.client.post(self.base + "/rest/api/3/issue", json={"fields": fields})
                r.raise_for_status()
                if drop:
                    log.warning("Jira create for %s dropped fields %s", error.entity_key, drop)
                return r.json().get("key")
            except Exception as e:  # pragma: no cover - network
                last = e
        log.warning("Jira create failed for %s: %s", error.entity_key, last)
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
