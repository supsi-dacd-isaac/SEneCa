"""Percorsi asset statici per la pagina Approccio System Dynamics."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONTENT_ROOT = ROOT / "content" / "system_dynamics"
PLOTS_DATA = CONTENT_ROOT / "plots_data"
IMAGES = CONTENT_ROOT / "images"
MAP_HTML = CONTENT_ROOT / "map.html"
PV_INPUT_CSV = ROOT / "Vensim" / "PVinput.csv"
HP_INPUT_CSV = ROOT / "Vensim" / "HPinput.csv"
EV_INPUT_CSV = ROOT / "Vensim" / "EVinput.csv"
HOUR_FACTORS_CSV = ROOT / "Vensim" / "Input Hour Factors.csv"
# Canonical v7 baseline; export provenance is stored beside the CSV.
SIM_ADOPTIONS_CSV = PLOTS_DATA / "calibration_sim_adoptions_v7.csv"

IMAGE_WORKSHOP = IMAGES / "Image_1.png"
IMAGE_CLD = IMAGES / "Image_5.png"
IMAGE_ARCHITECTURE = IMAGES / "Image_3.png"
