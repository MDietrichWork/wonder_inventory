"""TicketSink interface. The job calls create() once per new fingerprint, comment()
on recurrence, and close() when an issue stops reproducing (auto-close)."""
from typing import Optional


class TicketSink:
    def create(self, error) -> Optional[str]:
        """Create a ticket for the Error; return the issue key (e.g. WIQ-1042) or None."""
        raise NotImplementedError

    def comment(self, error, text: str) -> None:
        pass

    def close(self, error, text: str) -> None:
        """Transition the ticket to a resolved/closed state (used for auto-close)."""
        pass

    def set_assignee(self, error, query: str) -> bool:
        """Set the ticket assignee (resolve query=email/name). Returns True if applied."""
        return False

    def transition(self, error, status_name: str) -> bool:
        """Move the ticket to the named status/transition. Returns True if applied."""
        return False

    def fetch_issue_states(self) -> dict:
        """Return {issue_key: {status, assignee, resolutiondate}} for all tracked tickets.
        Used by the Jira -> app poller. Empty for non-external sinks."""
        return {}
