"""Telemetry identity and stable active alert episodes; keep all legacy rows."""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("telemetry", sa.Column("event_id", sa.String(128), nullable=True))
    op.add_column("telemetry", sa.Column("payload_hash", sa.String(64), nullable=True))
    op.add_column("telemetry", sa.Column("received_at", sa.DateTime, nullable=True))
    op.add_column("alerts", sa.Column("last_seen_at", sa.DateTime, nullable=True))
    op.create_index("uq_telemetry_event_id", "telemetry", ["event_id"], unique=True)
    op.create_index("ix_telemetry_asset_timestamp_id", "telemetry", ["asset_id", "timestamp", "id"])
    # Earliest creation wins; the lower id breaks ties. Preserve resolved history.
    op.get_bind().execute(sa.text("""UPDATE alerts SET resolved=1, resolved_at=:now
        WHERE resolved=0 AND id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY asset_id,alert_type ORDER BY created_at,id
                ) AS episode_rank FROM alerts WHERE resolved=0
            ) WHERE episode_rank > 1
        )"""), {"now": datetime.now(timezone.utc).replace(tzinfo=None)})
    op.create_index("uq_alerts_active_asset_type", "alerts", ["asset_id", "alert_type"],
        unique=True, sqlite_where=sa.text("resolved = 0"), postgresql_where=sa.text("resolved = false"))


def downgrade():
    op.drop_index("uq_alerts_active_asset_type", table_name="alerts")
    op.drop_column("alerts", "last_seen_at")
    op.drop_index("ix_telemetry_asset_timestamp_id", table_name="telemetry")
    op.drop_index("uq_telemetry_event_id", table_name="telemetry")
    for column in ("received_at", "payload_hash", "event_id"):
        op.drop_column("telemetry", column)
