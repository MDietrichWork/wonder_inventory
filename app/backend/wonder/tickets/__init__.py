"""Ticket sink adapters. Swap memory <-> jira via TICKET_SINK in .env."""
from ..config import settings
from .base import TicketSink
from .memory import MemoryTicketSink


def get_ticket_sink() -> TicketSink:
    if settings.ticket_sink == "jira":
        from .jira import JiraTicketSink
        return JiraTicketSink()
    return MemoryTicketSink()
