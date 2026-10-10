"""
test_seed.py — seed data correctness and reset idempotency.
"""
import pytest
from app.models import Asset, Site, Operator
from app.seed import reset_database, seed_database


class TestSeedData:
    def test_all_7_assets_present(self, db_session):
        assets = db_session.query(Asset).all()
        ids = {a.id for a in assets}
        expected = {"EQX1001", "EQX1002", "EQX1003", "EQX1004", "EQX1005", "EQX1006", "EQX1007"}
        assert ids == expected

    def test_equip_type_spelling_preserved(self, db_session):
        """EQX1002 must be "Cater" (not "Caterpillar")."""
        a = db_session.get(Asset, "EQX1002")
        assert a.equipment_type == "Cater"

    def test_null_site_operator_preserved(self, db_session):
        for asset_id in ("EQX1002", "EQX1007"):
            a = db_session.get(Asset, asset_id)
            assert a.site_id is None, f"{asset_id} site_id should be NULL"
            assert a.operator_id is None, f"{asset_id} operator_id should be NULL"

    def test_seed_is_idempotent(self, db_session):
        counts = seed_database(db_session)
        # Second call: everything already exists, inserts should be 0
        assert counts["assets"] == 0
        assert counts["sites"] == 0
        assert counts["operators"] == 0

    def test_sites_seeded(self, db_session):
        sites = db_session.query(Site).all()
        assert len(sites) == 5

    def test_operators_seeded(self, db_session):
        ops = db_session.query(Operator).all()
        assert len(ops) == 5


class TestReset:
    def test_reset_clears_then_reseeds(self, db_session):
        """After reset the asset count should be back to 7."""
        counts = reset_database(db_session)
        assets = db_session.query(Asset).all()
        assert len(assets) == 7

    def test_reset_clears_telemetry(self, db_session):
        from app.models import Telemetry, Asset
        from app.simulator import simulate

        asset = db_session.get(Asset, "EQX1001")
        simulate(db_session, asset, "normal", 5)
        before = db_session.query(Telemetry).count()
        assert before > 0

        reset_database(db_session)
        after = db_session.query(Telemetry).count()
        assert after == 0

    def test_reset_clears_alerts(self, db_session):
        from app.models import Alert

        before = db_session.query(Alert).count()
        assert before >= 0  # may or may not have alerts

        reset_database(db_session)
        after = db_session.query(Alert).count()
        assert after == 0
