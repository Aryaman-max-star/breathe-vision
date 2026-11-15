"""Service actions per verdict. Tiers are POLICY PLACEHOLDERS - real limits come from the
cell maker and the OEM service manual."""
from __future__ import annotations

SEVERITY_ORDER = ["OK", "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


def action(verdict: str, slot: int | None = None, r_mm: float | None = None, t_alarm: float = 0.25,
           detail: str = "") -> tuple[str, str]:
    n = slot if slot is not None else "?"
    if verdict == "SWELL" and detail == "heat":
        return "HIGH", (f"Stop charging. Find and remove the heat source near cell {n} (check the cooling path), let "
                        f"the module cool below 35 °C, then scan again. If cell {n} is still swollen when cool, the "
                        f"damage is permanent: replace it.")
    if verdict == "SWELL" and detail == "permanent":
        return "CRITICAL", (f"Cell {n} stayed swollen after cooling: permanent heat damage. Do not charge. Isolate and "
                            f"replace cell {n}; fix the hotspot or cooling fault that caused it; inspect the neighbours; "
                            f"log for the battery passport.")
    if verdict == "SWELL":
        if r_mm is not None and r_mm >= 2 * t_alarm:
            return "CRITICAL", (f"Stop. Do not charge. Isolate cell {n}; quarantine the module in a fire-safe area; "
                                f"replace per OEM procedure; inspect neighbours; log for the battery passport.")
        return "HIGH", (f"Remove from service. Replace cell {n}; capacity/IR test the neighbours; review charge "
                        f"history for overcharge or cold fast-charge; limit charge rate.")
    table = {
        "RECOVERED": ("LOW", f"Cell {n} went back to normal after cooling: the swelling was heat-related and "
                             f"reversible. Inspect the cooling path near cell {n}, keep the module below 35 °C, and "
                             f"monitor cell {n} in the next scans."),
        "WATCH": ("MEDIUM", f"Monitor cell {n}. Retest in 7 days or after 10 cycles; check balancing of cell {n}."),
        "RESEAT": ("INFO", f"Reseat cell {n} (press it fully down) and scan again - confirmation required."),
        "MISSING": ("INFO", f"Insert a cell in slot {n} and scan again."),
        "THERMAL": ("MEDIUM", "Let the module cool below 35 C and retest; inspect the cooling path. "
                              "No geometric change."),
        "THERMAL_OK": ("MEDIUM", "Temperature event, geometry change within thermal expansion. Cool and retest."),
        "UNIFORM_RISE": ("MEDIUM", "All cells read higher by the same amount: check holder seating and debris, rescan."),
        "HOLDER_LIFTED": ("MEDIUM", "All cells higher with no temperature change: the holder is lifted or has debris under it."),
        "CONDENSATION": ("MEDIUM", "Surface within 3 C of the dew point: let the module equilibrate before opening."),
        "CAMERA_MOVED": ("INFO", "Station fault: the camera moved too far to correct automatically. Open the dashboard's "
                                 "Camera placement panel and follow it back to OK, or press Re-anchor (4 normal cells in "
                                 "place). No cell verdict."),
        "OBSTRUCTED": ("INFO", "Station fault: something is in the camera view. Clear it and rescan. No cell verdict."),
        "LIGHTING": ("INFO", "Station fault: the lighting changed. Restore lighting or recalibrate. No cell verdict."),
        "ANOMALY": ("LOW", "Unusual scan (AI anomaly score). Retest; flag for a technician."),
        "NOT_CALIBRATED": ("INFO", "Run the calibration first (dashboard, Calibration panel)."),
        "VISION_OFFLINE": ("INFO", "Camera / vision service not reachable."),
        "OK": ("OK", "No action needed."),
    }
    return table.get(verdict, ("INFO", verdict))
