"""
Pydantic schemas — the API contract.

These are stable shapes that the frontend can depend on.
Internal DB models may evolve without breaking these contracts.
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------

class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    license_class: Optional[str] = None
    contact: Optional[str] = None


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

class AssetSummary(BaseModel):
    """Lightweight representation for list endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    equipment_type: str
    status: str
    site_id: Optional[str] = None
    operator_id: Optional[str] = None
    checkout_date: Optional[datetime] = None
    expected_return_date: Optional[datetime] = None
    engine_hrs_per_day: float
    idle_hrs_per_day: float
    operating_days: int
    customer_name: Optional[str] = None
    qr_code: Optional[str] = None
    rfid_tag: Optional[str] = None


class AssetDetail(AssetSummary):
    """Full asset detail including nested site/operator objects."""
    site: Optional[SiteOut] = None
    operator: Optional[OperatorOut] = None
    utilization: Optional["UtilizationOut"] = None


class UtilizationOut(BaseModel):
    """
    Defensible utilization calculation:
      engine_hrs / (engine_hrs + idle_hrs) × 100  for productive-time ratio
      engine_hrs / (operating_days × 8h shift)     for shift-utilization
    """
    engine_hrs_total: float
    idle_hrs_total: float
    operating_days: int
    productive_ratio_pct: float   # engine / (engine + idle) × 100
    shift_utilization_pct: float  # engine / (days × 8h) × 100  (capped at 100)
    label: str                    # human-readable explanation


# ---------------------------------------------------------------------------
# Rental Events
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    operator_id: Optional[str] = None
    site_id: Optional[str] = None
    customer_name: Optional[str] = None
    expected_return_date: Optional[datetime] = None
    notes: Optional[str] = None
    performed_by: Optional[str] = None
    identifier_method: Optional[str] = "manual"  # "qr" | "rfid" | "manual"


class CheckinRequest(BaseModel):
    notes: Optional[str] = None
    performed_by: Optional[str] = None
    identifier_method: Optional[str] = "manual"


class RentalEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: str
    event_type: str
    timestamp: datetime
    operator_id: Optional[str] = None
    site_id: Optional[str] = None
    customer_name: Optional[str] = None
    expected_return_date: Optional[datetime] = None
    notes: Optional[str] = None
    performed_by: Optional[str] = None
    identifier_method: Optional[str] = None


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

class TelemetryEventIn(BaseModel):
    """Validated semantic event. Server identity, receipt and scenario stay private."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    event_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=20)
    timestamp: AwareDatetime
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    engine_temp_c: Optional[float] = None
    engine_hours: Optional[float] = Field(default=None, ge=0)
    fuel_level_pct: Optional[float] = Field(default=None, ge=0, le=100)
    fuel_consumption_lph: Optional[float] = Field(default=None, ge=0)
    idle_time_hours: Optional[float] = Field(default=None, ge=0)
    seatbelt_on: Optional[bool] = None
    fault_code: Optional[str] = Field(default=None, max_length=50)
    fault_description: Optional[str] = Field(default=None, max_length=200)

    @field_validator("event_id")
    @classmethod
    def no_whitespace(cls, value):
        if any(character.isspace() for character in value):
            raise ValueError("event_id cannot contain whitespace")
        return value

    @field_validator("timestamp")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def sensor_payload(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        sensors = self.model_dump(exclude={"event_id", "asset_id", "timestamp"})
        if all(value is None for value in sensors.values()):
            raise ValueError("at least one sensor or fault field is required")
        return self


class TelemetryEventResult(BaseModel):
    event_id: str
    telemetry_id: int
    asset_id: str
    duplicate: bool


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: str
    timestamp: datetime
    event_id: Optional[str] = None
    received_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    engine_temp_c: Optional[float] = None
    engine_hours: Optional[float] = None
    fuel_level_pct: Optional[float] = None
    fuel_consumption_lph: Optional[float] = None
    idle_time_hours: Optional[float] = None
    seatbelt_on: Optional[bool] = None
    fault_code: Optional[str] = None
    fault_description: Optional[str] = None
    scenario: Optional[str] = None


class SimulateRequest(BaseModel):
    """
    Trigger a deterministic telemetry scenario for a given asset.
    scenario values:
      "normal" | "engine_overheat" | "location_mismatch"
      | "seatbelt_violation" | "high_idle" | "abnormal_fuel"
    """
    scenario: str = "normal"
    readings: int = Field(default=10, ge=1, le=100)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: str
    alert_type: str
    severity: str
    message: str
    evidence: Optional[str] = None
    resolved: bool
    created_at: datetime
    resolved_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

class RecommendationOut(BaseModel):
    asset: str
    issue: str
    severity: str      # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    evidence: str
    recommendation: str


# ---------------------------------------------------------------------------
# Forecasts
# ---------------------------------------------------------------------------

class ForecastDataPoint(BaseModel):
    period: str          # e.g. "2025-05", "Week 18"
    demand: float        # historical or predicted asset-days
    is_forecast: bool    # False = historical, True = predicted


class ExpectedReturn(BaseModel):
    asset_id: str
    equipment_type: str
    expected_return_date: Optional[datetime]


class AllocationCandidate(BaseModel):
    """An asset identified as a recoverable/reallocatable candidate for a demand gap."""
    asset_id: str
    equipment_type: str
    current_status: str                       # "available" | "recoverable" | "returning"
    current_site_id: Optional[str] = None
    destination_site_id: str
    reason: str                               # why this asset is a candidate
    action: str                               # e.g. "Recover and redeploy to S003"


class ForecastOut(BaseModel):
    equipment_type: str
    site_id: Optional[str] = None
    history: list[ForecastDataPoint]
    forecast: list[ForecastDataPoint]
    expected_returning: list[ExpectedReturn]
    recommended_allocation: int   # suggested fleet size for next period
    allocation_rationale: str
    # --- Site-level supply/gap fields (populated when site_id is set) ---
    supply_available: Optional[int] = None    # assets of this type currently available
    supply_recoverable: Optional[int] = None  # assets that can be reallocated to this site
    supply_total_known: Optional[int] = None  # available + recoverable
    peak_forecast_demand: Optional[int] = None  # peak monthly unit count from forecast
    projected_gap: Optional[int] = None      # peak_demand - supply_total_known (>=0)
    allocation_candidates: Optional[list[AllocationCandidate]] = None
