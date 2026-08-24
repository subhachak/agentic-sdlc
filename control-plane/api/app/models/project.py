from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    """One client engagement: a codebase, where changes go, and where they ship.

    A real record rather than a filter key. A project has a name someone
    typed, a date it started, and the handful of settings that differ between
    engagements — which is exactly the "this engagement" section of the
    configuration page. Keeping them here instead of in the global settings
    table is what lets two teams hold different answers at the same time.

    The id doubles as the graph's scoping key, so it is constrained the same
    way: it ends up inside node identity and cannot contain the separator.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(String, default="")
    # The engagement fields, stored together rather than as columns: which
    # ones matter is a property of the adapters in use, and a client with a
    # different stack needs different ones without a migration.
    engagement: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(default=False)
