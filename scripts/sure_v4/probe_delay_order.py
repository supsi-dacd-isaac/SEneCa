"""Isolated counterfactual: stage fixed delays or vary one sequential update."""
from pathlib import Path
import sys

from scripts.julia_repro.common import dump, read, digest

MODES = {"before", "after", "unchanged", "staged-before", "staged-after", "staged-app"}


def main(original, target, mode, cases):
    if mode not in MODES:
        raise ValueError(mode)
    original, target = Path(original).resolve(), Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not (target / "source").exists():
        (target / "source").symlink_to(original / "source", target_is_directory=True)
        dump(target / "manifest.json", read(original / "manifest.json"))
    sys.path.insert(0, str(target / "source"))
    import sure_paths
    sure_paths.set_variant("v4")
    import sure_pysd as sp
    load = sp.load_model

    def reordered(*args, **kwargs):
        model = load(*args, **kwargs)
        objects = list(model._dynamicstateful_elements)
        before = [s.py_name for s in objects]
        delay = next(s for s in objects if s.py_name == "_delayfixed_hourly_imported_electricity")
        smooth = next(s for s in objects if s.py_name == "_smooth_hourly_imported_electricity")
        if mode not in {"unchanged", "staged-app"}:
            objects.remove(delay)
            objects.insert(objects.index(smooth) + (mode in {"after", "staged-after"}), delay)
            model._dynamicstateful_elements = objects
        if mode.startswith("staged-"):
            from scripts.sure_v4.synchronous_delays import install
            install(model)
        dump(target / (mode + "-order.json"), {"before": before, "after": [s.py_name for s in model._dynamicstateful_elements],
             "original_manifest_sha256": digest(original / "manifest.json"), "mode": mode})
        return model

    sp.load_model = reordered
    from scripts.sure_v4.reference import run
    run(target, "app" if mode == "staged-app" else mode, cases)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
