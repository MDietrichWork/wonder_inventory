"""In-process ticket sink: assigns deterministic WIQ-#### keys; all lifecycle state is
tracked in the app DB by the job. Lets the whole loop run with no external Jira."""
from typing import Optional

from .base import TicketSink
from ..config import settings


class MemoryTicketSink(TicketSink):
    def create(self, error) -> Optional[str]:
        # Deterministic + unique from the DB primary key.
        return "%s-%d" % (settings.jira_project_key, 1000 + int(error.id))

    def comment(self, error, text: str) -> None:
        pass

    def close(self, error, text: str) -> None:
        pass
