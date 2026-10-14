"""Progress describes completed phases, not an estimate of remaining time."""
from .common import YEARS


def worker_event(event):
    phase = event.get("phase")
    completed, total, year = (event.get(k) for k in ("completed", "total", "year"))
    if any(type(v) is not int for v in (completed, total, year)):
        raise RuntimeError("Invalid Julia progress counters")
    if phase in {"initialize", "integrate"}:
        if (completed, total, year) != (0, 1, 0):
            raise RuntimeError("Invalid Julia phase progress")
        value = 0. if phase == "initialize" else .25
    elif phase == "extract":
        if total != len(YEARS) or not 0 <= completed <= total or year != (YEARS[completed-1] if completed else 0):
            raise RuntimeError("Invalid Julia extraction progress")
        value = .5 + .25 * completed / total
    else:
        raise RuntimeError("Unknown Julia progress phase")
    return {"phase": phase, "value": value, "year": year}


def label(event):
    phase = event["phase"]
    if phase == "extract" and event.get("year"):
        return f"Preparazione dei risultati: anno {event['year']} (fase 3/4)"
    return {"initialize": "Preparazione dello scenario (fase 1/4)",
            "integrate": "Simulazione 2011–2050 (fase 2/4)",
            "extract": "Preparazione dei risultati (fase 3/4)",
            "check": "Verifica dei risultati (fase 4/4)",
            "complete": "Simulazione completata"}[phase]
