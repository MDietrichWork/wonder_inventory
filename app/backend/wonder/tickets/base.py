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
