"""Load synthetic demand from a configured directory without process-wide state."""
import json
from pathlib import Path

from app.settings import Settings


def _load_raw(data_dir: Path | None = None) -> dict:
    directory = Path(data_dir) if data_dir is not None else Settings().data_dir
    path = directory / "scenarios" / "demand_history_supplement.json"
    # Ordinary deployments can start without optional demo demand history.
    # Demo startup validates this file before opening its database.
    if not path.is_file():
        return {"demand_history": []}
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid demand history JSON: {path}") from error


def get_demand_history(site_id: str, equipment_type: str, data_dir: Path | None = None) -> list[dict]:
    """Return periods for a site and equipment type from this data directory."""
    data = _load_raw(data_dir)
    for entry in data.get("demand_history", []):
        if entry.get("site_id") == site_id and entry.get("equipment_type") == equipment_type:
            return list(entry.get("periods", []))
    return []


def all_supplement_segments(data_dir: Path | None = None) -> list[dict]:
    """Return every site and equipment segment from this data directory."""
    return [
        {
            "site_id": entry["site_id"], "equipment_type": entry["equipment_type"],
            "periods": list(entry.get("periods", [])),
        }
        for entry in _load_raw(data_dir).get("demand_history", [])
    ]
