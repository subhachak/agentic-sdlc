from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class SettingOverride(Base, TimestampMixin):
    """A configuration value set through the control plane rather than the
    environment.

    Overrides, not replacements: the environment still supplies the default,
    and deleting a row restores it. Secrets are never stored here — they stay
    in the environment, and this layer only reports whether they are present.
    """

    __tablename__ = "setting_overrides"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String, default="console")


class SettingChange(Base, UUIDPKMixin, TimestampMixin):
    """What was changed, from what, by whom.

    A separate record rather than a row in the run audit log: that log is
    keyed to a run, and a configuration change belongs to no run. Switching
    the model provider mid-programme still has to be accountable afterwards,
    so it gets its own trail.
    """

    __tablename__ = "setting_changes"

    key: Mapped[str] = mapped_column(String, index=True)
    previous: Mapped[Any] = mapped_column(JSON, nullable=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    changed_by: Mapped[str] = mapped_column(String, default="console")
