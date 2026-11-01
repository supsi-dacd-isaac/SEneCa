"""Export the observed non-residential PV capacity used by the PV page.

From v8 the 30-100 kW and >100 kW history is no longer in PVinput: SURE.mdl
holds the yearly register additions (``NR Observed kW``) and the stock up to
2010 (``NR Initial stock``). The model stock at the start of year t is the
initial stock plus the additions of the previous years, so the comparable
observed stock is ``NR Initial stock + sum(NR Observed kW, 2011..t-1)``.

    python scripts/export_nr_history.py          # write the CSV
    python scripts/export_nr_history.py --check  # verify it is current
"""
import argparse
import csv
import io
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Vensim/SURE.mdl"
TARGET = ROOT / "content/system_dynamics/plots_data/nr_capacity_history.csv"
CLASSES = {"NR Mid": '"Capacity PV 30 - 100 kW"', "NR Large": '"Capacity PV > 100 kW"'}


def equation(model, name):
    matches = re.findall(rf"(?m)^{re.escape(name)}\s*=(.*?)~", model, re.S)
    if len(matches) != 1:
        raise ValueError(f"Expected one equation for {name}, found {len(matches)}")
    return re.sub(r"\\\s*\n\s*", "", matches[0])


def history():
    model = SOURCE.read_text(encoding="latin-1").partition("\\\\\\---///")[0]
    rows = {}
    for element, label in CLASSES.items():
        stock = float(equation(model, f"NR Initial stock[{element}]"))
        lookup = equation(model, f"NR Observed kW[{element}]")
        points = [(int(float(t)), float(v)) for t, v in
                  re.findall(r"\(\s*([0-9.]+)\s*,\s*(-?[0-9.eE+]+)\s*\)", lookup.split("]", 1)[1])]
        years = [t for t, _ in points]
        if years != list(range(2011, years[-1] + 1)):
            raise ValueError(f"Unexpected observation years for {element}: {years}")
        series = {2011: stock}
        for year, added in points:
            stock += added
            series[year + 1] = stock
        rows[label] = series
    return rows


def render(rows):
    years = sorted({y for series in rows.values() for y in series})
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["Time", *years])
    for label, series in rows.items():
        writer.writerow([label, *(f"{series[y]:.10g}" if y in series else "" for y in years)])
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    text = render(history())
    if parser.parse_args().check:
        if TARGET.read_text(encoding="utf-8") != text:
            raise SystemExit(f"{TARGET.relative_to(ROOT)} is stale: rerun scripts/export_nr_history.py")
    else:
        TARGET.write_text(text, encoding="utf-8")
    print(f"{TARGET.relative_to(ROOT)}: {len(CLASSES)} classes")


if __name__ == "__main__":
    main()
