"""Observed input years shared by charts and calibration-curve export."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_INPUTS = {
    "Fotovoltaico": ("PVinput.csv", [f"Adoption PV Type[{t}]" for t in ("SFH", "DFH", "MFH")]),
    "Pompe di calore": ("HPinput.csv", [f"Adoption HP Type[{t}]" for t in ("SFH", "DFH", "MFH")]),
    "Accumulatori": ("PVinput.csv", [f"Adoption Battery Type[{t}]" for t in ("SFH", "DFH", "MFH")]),
    "Veicoli elettrici": ("EVinput.csv", ["Adoption Vehicles[BEV]"]),
}


def available_history(raw: pd.DataFrame, rows: list[str]) -> pd.DataFrame:
    """Trim empty ends, retain partial values and missing years inside the range."""
    years = sorted((c for c in raw if str(c).strip().isdigit() and int(c) >= 2011), key=int)
    frame = raw.loc[rows, years].apply(pd.to_numeric, errors="coerce").T
    frame.index = frame.index.astype(int)
    valid = frame.dropna(how="all")
    if valid.empty:
        return frame.iloc[:0]
    return frame.reindex(range(int(valid.index.min()), int(valid.index.max()) + 1))


def calibration_observations(technology: str) -> pd.Series:
    filename, rows = CALIBRATION_INPUTS[technology]
    history = available_history(pd.read_csv(ROOT / "Vensim" / filename, index_col=0), rows)
    # An aggregate requires every component; a missing type is not a zero.
    total = history.sum(axis=1, min_count=len(rows))
    valid = total.dropna()
    return total.loc[valid.index.min():valid.index.max()] if not valid.empty else total.iloc[:0]
