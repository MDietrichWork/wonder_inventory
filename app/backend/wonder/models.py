"""ORM models for the DQ app: runs, rules, routing, errors, ticket events, SLA, audit."""
from typing import Optional
from sqlalchemy import String, Integer, Float, Boolean, JSON, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class ValidationRun(Base):
    __tablename__ = "validation_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[str] = mapped_column(String(10), index=True)   # YYYY-MM-DD
    started_at: Mapped[str] = mapped_column(String(32))
    finished_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    rows_scanned: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)   # reproduced this run
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    autoclosed_count: Mapped[int] = mapped_column(Integer, default=0)


class Rule(Base):
    __tablename__ = "rule"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)  # rule_key e.g. PO-01
    name: Mapped[str] = mapped_column(String(160))
    primitive: Mapped[str] = mapped_column(String(24))            # NOT_NULL, REFERENTIAL, RANGE, RECONCILIATION
    error_type: Mapped[str] = mapped_column(String(64), index=True)
    target_table: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(12))            # Urgent/High/Medium/Low (default if rule doesn't compute it)
    fail_type: Mapped[str] = mapped_column(String(8), default="Hard")  # Hard | Soft
    owner_group: Mapped[str] = mapped_column(String(48))
    expression: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RoutingMap(Base):
    __tablename__ = "routing_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    error_type: Mapped[str] = mapped_column(String(64), index=True)
    team: Mapped[str] = mapped_column(String(48))
    assignee: Mapped[str] = mapped_column(String(64))
    jira_project: Mapped[str] = mapped_column(String(16), default="WIQ")
    jira_component: Mapped[str] = mapped_column(String(48), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Error(Base):
    __tablename__ = "error"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # sha(rule_id + entity_key)
    rule_id: Mapped[str] = mapped_column(String(24))
    error_type: Mapped[str] = mapped_column(String(64), index=True)
    source_table: Mapped[str] = mapped_column(String(64))
    entity_key: Mapped[str] = mapped_column(String(96))
    data_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(12), index=True)
    routed_team: Mapped[str] = mapped_column(String(48))
    routed_assignee: Mapped[str] = mapped_column(String(64))
    # ownership transfer (sub-assignment) — primary owner stays accountable
    sub_team: Mapped[Optional[str]] = mapped_column(String(48), nullable=True)
    sub_assignee: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sub_assigned_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="Open", index=True)
    detected_at: Mapped[str] = mapped_column(String(32))      # ISO UTC, first seen
    first_run_date: Mapped[str] = mapped_column(String(10))
    last_seen_run: Mapped[str] = mapped_column(String(10), index=True)
    resolved_at: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    recurrence: Mapped[int] = mapped_column(Integer, default=1)  # times seen in trailing 30d
    jira_issue_key: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)

    events: Mapped[list["TicketEvent"]] = relationship(back_populates="error", cascade="all, delete-orphan")


class TicketEvent(Base):
    __tablename__ = "ticket_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    error_id: Mapped[int] = mapped_column(ForeignKey("error.id"))
    jira_issue_key: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    from_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(48))
    occurred_at: Mapped[str] = mapped_column(String(32))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    error: Mapped["Error"] = relationship(back_populates="events")


class SlaTarget(Base):
    __tablename__ = "sla_target"
    severity: Mapped[str] = mapped_column(String(12), primary_key=True)
    resolution_days: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(48))
    action: Mapped[str] = mapped_column(String(48))
    entity: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str] = mapped_column(String(48))
    before: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    at: Mapped[str] = mapped_column(String(32))
