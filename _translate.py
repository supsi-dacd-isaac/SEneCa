import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.setrecursionlimit(1_000_000)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import pysd  # noqa: E402

import sure_paths as paths  # noqa: E402

MDL = paths.pysd_mdl()

print("Traduzione di", MDL.name, "...")
model = pysd.read_vensim(str(MDL), initialize=False)
print("OK. Variabili nel doc:", len(model.doc))
print("File .py generato:", paths.pysd_py().exists(), "->", paths.pysd_py().name)
