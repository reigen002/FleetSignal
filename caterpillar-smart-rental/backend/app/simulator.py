"""
Deterministic telemetry simulator.

Each scenario produces a reproducible sequence of readings anchored
to the asset's seed parameters. Useful for demo / QA without needing
live hardware.

Scenarios
---------
normal              — baseline healthy readings
engine_overheat     — engine_temp_c climbs above 110°C threshold
location_mismatch   — GPS drifts far outside the registered site centroid
seatbelt_violation  — seatbelt_on toggles to False unexpectedly
high_idle           — idle_time_hours grows each reading (no engine use)
abnormal_fuel       — fuel_consumption_lph spikes 2-3× expected baseline
"""
import math
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Asset
from app.schemas import TelemetryEventIn

# Normal operation baselines
NORMAL_ENGINE_TEMP = 85.0       # °C
OVERHEAT_THRESHOLD = 110.0      # °C
NORMAL_FUEL_LPH = 12.0          # litres/hour baseline
SITE_RADIUS_KM = 2.0            # acceptable GPS drift from site centroid

# Default lat/lon when asset has no site (placed at CAT Manila office ~placeholder)
DEFAULT_LAT = 14.5547
DEFAULT_LON = 120.9930


def _site_coords(asset: Asset) -> tuple[float, float]:
    if asset.site and asset.site.latitude and asset.site.longitude:
        return asset.site.latitude, asset.site.longitude
    return DEFAULT_LAT, DEFAULT_LON


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def generate_readings(
    asset: Asset,
    scenario: str,
    readings: int = 10,
) -> list[TelemetryEventIn]:
    """
    Generate validated `readings` events for `asset` under `scenario`.
    This function generates values only; the ingestion service owns persistence.
    """
    scenario = scenario.lower()
    base_lat, base_lon = _site_coords(asset)
    base_time = datetime.now(tz=timezone.utc)
    cumulative_engine_hrs = asset.engine_hrs_per_day * asset.operating_days
    cumulative_idle_hrs = asset.idle_hrs_per_day * asset.operating_days

    rows: list[TelemetryEventIn] = []
    run_id = uuid4().hex

    for i in range(readings):
        ts = base_time + timedelta(minutes=i * 15)  # 15-min intervals
        progress = i / max(readings - 1, 1)          # 0.0 → 1.0

        # --- defaults ---
        lat, lon = base_lat, base_lon
        engine_temp = NORMAL_ENGINE_TEMP + (progress * 2)   # slight natural rise
        fuel_lph = NORMAL_FUEL_LPH
        idle_hrs = cumulative_idle_hrs + (i * 0.25)
        engine_hrs = cumulative_engine_hrs + (i * 0.25)
        seatbelt = True
        fault_code: Optional[str] = None
        fault_desc: Optional[str] = None
        fuel_level = max(95.0 - (i * 2.5), 20.0)

        # --- scenario overrides ---
        if scenario == "engine_overheat":
            # Temperature climbs through readings
            engine_temp = NORMAL_ENGINE_TEMP + (progress * 40.0)
            if engine_temp >= OVERHEAT_THRESHOLD:
                fault_code = "E001"
                fault_desc = f"Engine temperature critical: {engine_temp:.1f}°C"

        elif scenario == "location_mismatch":
            # Drift asset ~10 km north-east to simulate theft/mis-deployment
            lat = base_lat + (0.05 * progress)
            lon = base_lon + (0.05 * progress)
            if _haversine_km(base_lat, base_lon, lat, lon) > SITE_RADIUS_KM:
                fault_code = "L001"
                fault_desc = (
                    f"Asset {_haversine_km(base_lat, base_lon, lat, lon):.1f} km "
                    f"from registered site"
                )

        elif scenario == "seatbelt_violation":
            # Alternate on/off each reading
            seatbelt = (i % 2 == 0)
            if not seatbelt:
                fault_code = "S001"
                fault_desc = "Seatbelt not fastened during operation"

        elif scenario == "high_idle":
            # Engine not running; idle time piles up
            engine_hrs = cumulative_engine_hrs  # stays flat
            idle_hrs = cumulative_idle_hrs + (i * 1.0)  # grows fast
            engine_temp = 45.0  # cold — engine off
            fault_code = "I001" if i > 3 else None
            fault_desc = (
                f"Prolonged idle: {idle_hrs:.1f}h cumulative" if fault_code else None
            )

        elif scenario == "abnormal_fuel":
            # Fuel burns 2.5× faster than normal
            fuel_lph = NORMAL_FUEL_LPH * (2.0 + progress)
            fuel_level = max(95.0 - (i * 7.0), 5.0)
            if fuel_lph > NORMAL_FUEL_LPH * 2:
                fault_code = "F001"
                fault_desc = f"Fuel consumption {fuel_lph:.1f} L/h — {fuel_lph/NORMAL_FUEL_LPH:.1f}× baseline"

        row = TelemetryEventIn(
            event_id=f"sim-{run_id}-{i}",
            asset_id=asset.id,
            timestamp=ts,
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            engine_temp_c=round(engine_temp, 2),
            engine_hours=round(engine_hrs, 2),
            fuel_level_pct=round(fuel_level, 1),
            fuel_consumption_lph=round(fuel_lph, 2),
            idle_time_hours=round(idle_hrs, 2),
            seatbelt_on=seatbelt,
            fault_code=fault_code,
            fault_description=fault_desc,
        )
        rows.append(row)

    return rows


def simulate(db: Session, asset: Asset, scenario: str, readings: int = 10):
    """Compatibility entrypoint for trusted demo callers; the batch is atomic."""
    from app.services.telemetry import ingest_simulation
    return ingest_simulation(db, asset.id, scenario, readings)
