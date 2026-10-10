"""
test_alerts.py — alert generation for key assets and scenarios.
"""
import pytest
from datetime import datetime, timezone
from app.routers.alerts import refresh_alerts


class TestEQX1002Alerts:
    """EQX1002 is intentionally missing site, operator, with zero engine / all idle."""

    def test_no_site_alert(self, client):
        resp = client.get("/alerts?asset_id=EQX1002&alert_type=no_site")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_no_operator_alert(self, client):
        resp = client.get("/alerts?asset_id=EQX1002&alert_type=no_operator")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_high_idle_alert(self, client):
        resp = client.get("/alerts?asset_id=EQX1002&alert_type=high_idle")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestEQX1007Alerts:
    """EQX1007 is also unassigned with 12h/day idle."""

    def test_no_site_alert(self, client):
        resp = client.get("/alerts?asset_id=EQX1007&alert_type=no_site")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_high_idle_alert(self, client):
        resp = client.get("/alerts?asset_id=EQX1007&alert_type=high_idle")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestOverdueAlerts:
    """
    Regression test for a seed bug: every asset was seeded with
    status="available" regardless of checkout_date, so the overdue rule
    (which requires status=="checked_out") never fired on a fresh seed —
    EQX1002's headline 43-days-overdue scenario silently never triggered.
    """

    def test_eqx1002_seeded_as_checked_out(self, db_session):
        from app.models import Asset
        asset = db_session.get(Asset, "EQX1002")
        assert asset.status == "checked_out"

    def test_eqx1002_overdue_alert_on_fresh_seed(self, client):
        resp = client.get("/alerts?asset_id=EQX1002&alert_type=overdue")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_eqx1007_overdue_alert_on_fresh_seed(self, client):
        resp = client.get("/alerts?asset_id=EQX1007&alert_type=overdue")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_eqx1004_checked_out_but_not_yet_overdue(self, client, db_session):
        """EQX1004's expected_return_date (2025-05-15) is after DEMO_NOW (2025-05-12)."""
        from app.models import Asset
        asset = db_session.get(Asset, "EQX1004")
        assert asset.status == "checked_out"
        resp = client.get("/alerts?asset_id=EQX1004&alert_type=overdue")
        assert resp.json() == []

    def test_returned_assets_not_checked_out(self, db_session):
        from app.models import Asset
        for asset_id in ("EQX1001", "EQX1003", "EQX1005", "EQX1006"):
            asset = db_session.get(Asset, asset_id)
            assert asset.status == "available", f"{asset_id} should be available (already returned)"


class TestAlertRefresh:
    def test_refresh_post_endpoint(self, client):
        resp = client.post("/alerts/refresh")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_refresh_preserves_active_alerts(self, client, db_session):
        """Intentional change: refresh reconciles stable episodes, preserving history."""
        before = client.get("/alerts").json()
        count_before = len(before)

        # Refresh again
        client.post("/alerts/refresh")
        after = client.get("/alerts").json()
        # Repeated evaluation cannot create another active episode.
        assert len(after) == count_before
        assert {(a["id"], a["created_at"]) for a in after} == {(a["id"], a["created_at"]) for a in before}

    def test_alert_list_filter_by_severity(self, client):
        resp = client.get("/alerts?severity=HIGH")
        assert resp.status_code == 200
        for alert in resp.json():
            assert alert["severity"] == "HIGH"

    def test_resolved_filter(self, client):
        # By default only unresolved
        resp = client.get("/alerts")
        for alert in resp.json():
            assert alert["resolved"] is False

        resp_all = client.get("/alerts?resolved=true")
        assert resp_all.status_code == 200


class TestSimulatedScenarioAlerts:
    def test_engine_overheat_generates_alert(self, client, db_session):
        client.post("/assets/EQX1001/simulate", json={"scenario": "engine_overheat", "readings": 8})
        from app.routers.alerts import refresh_alerts
        refresh_alerts(db_session)

        resp = client.get("/alerts?asset_id=EQX1001&alert_type=engine_overheat")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_seatbelt_generates_alert(self, client, db_session):
        client.post("/assets/EQX1003/simulate", json={"scenario": "seatbelt_violation", "readings": 8})
        refresh_alerts(db_session)

        resp = client.get("/alerts?asset_id=EQX1003&alert_type=seatbelt_violation")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
