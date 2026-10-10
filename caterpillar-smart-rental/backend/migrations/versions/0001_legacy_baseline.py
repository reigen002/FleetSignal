"""Frozen schema of the original six tables; does not import application models."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def legacy_metadata():
    metadata = sa.MetaData()
    sa.Table("sites", metadata,
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("latitude", sa.Float), sa.Column("longitude", sa.Float),
        sa.Column("address", sa.String(200)))
    sa.Table("operators", metadata,
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("license_class", sa.String(20)), sa.Column("contact", sa.String(100)))
    sa.Table("assets", metadata,
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("equipment_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("site_id", sa.String(20), sa.ForeignKey("sites.id")),
        sa.Column("operator_id", sa.String(20), sa.ForeignKey("operators.id")),
        sa.Column("checkout_date", sa.DateTime), sa.Column("expected_return_date", sa.DateTime),
        sa.Column("engine_hrs_per_day", sa.Float, nullable=False),
        sa.Column("idle_hrs_per_day", sa.Float, nullable=False),
        sa.Column("operating_days", sa.Integer, nullable=False),
        sa.Column("customer_name", sa.String(100)), sa.Column("qr_code", sa.String(200)),
        sa.Column("rfid_tag", sa.String(100)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False))
    sa.Table("rental_events", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(20), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("operator_id", sa.String(20)), sa.Column("site_id", sa.String(20)),
        sa.Column("customer_name", sa.String(100)), sa.Column("expected_return_date", sa.DateTime),
        sa.Column("notes", sa.Text), sa.Column("performed_by", sa.String(100)),
        sa.Column("identifier_method", sa.String(20)))
    telemetry = sa.Table("telemetry", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(20), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("latitude", sa.Float), sa.Column("longitude", sa.Float),
        sa.Column("engine_temp_c", sa.Float), sa.Column("engine_hours", sa.Float),
        sa.Column("fuel_level_pct", sa.Float), sa.Column("fuel_consumption_lph", sa.Float),
        sa.Column("idle_time_hours", sa.Float), sa.Column("seatbelt_on", sa.Boolean),
        sa.Column("fault_code", sa.String(50)), sa.Column("fault_description", sa.String(200)),
        sa.Column("scenario", sa.String(50)))
    sa.Index("ix_telemetry_timestamp", telemetry.c.timestamp)
    sa.Table("alerts", metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.String(20), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("message", sa.Text, nullable=False), sa.Column("evidence", sa.Text),
        sa.Column("resolved", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False), sa.Column("resolved_at", sa.DateTime))
    return metadata


def upgrade():
    for table in legacy_metadata().sorted_tables:
        op.execute(sa.schema.CreateTable(table))
        for index in table.indexes:
            op.execute(sa.schema.CreateIndex(index))


def downgrade():
    for table in reversed(legacy_metadata().sorted_tables):
        op.drop_table(table.name)
