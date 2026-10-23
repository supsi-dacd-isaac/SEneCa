"""Session-local gettext presentation; never translates model identifiers or values."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import gettext
import textwrap
from pathlib import Path

import streamlit as st

LOCALES = Path(__file__).resolve().parents[1] / "locales"
LANGUAGES = {"it": "Italiano", "en": "English"}


def language() -> str:
    selected = st.session_state.get("ui_language", "it")
    return selected if selected in LANGUAGES else "it"


@lru_cache(maxsize=2)
def catalog(lang: str):
    # Do not install a process-global translator: users may choose different languages.
    if lang == "it":
        return gettext.NullTranslations()
    return gettext.translation("seneca", localedir=LOCALES, languages=[lang], fallback=True)


def tr(message, **values):
    if message is None:
        return None
    translated = catalog(language()).gettext(message)
    return translated.format(**values) if values else translated


def language_selector():
    st.sidebar.selectbox("Lingua / Language", list(LANGUAGES),
                         format_func=LANGUAGES.get, key="ui_language")


def chart_text(value):
    """Translate composed display labels after all data matching and colour choices."""
    if not isinstance(value, str):
        return value
    translated = tr(value)
    if translated != value:
        return translated
    for suffix in (" (Base)", " (storico: incremento netto)", " (storico)"):
        if value.endswith(suffix):
            return chart_text(value[:-len(suffix)]) + tr(suffix)
    if " — " in value:
        return " — ".join(chart_text(part) for part in value.split(" — "))
    if value.endswith("/anno"):
        return chart_text(value[:-5]) + tr("/anno")
    return value


def chart_options(options):
    """Copy and localize ECharts presentation only; numeric arrays stay identical."""
    result = deepcopy(options)
    def labels(item):
        if isinstance(item, dict):
            for k, v in item.items():
                if k == "name" and isinstance(v, str):
                    item[k] = chart_text(v)
                elif k in ("data", "indicator") and isinstance(v, list):
                    item[k] = [chart_text(x) if isinstance(x, str) else x for x in v]
                    for x in item[k]:
                        labels(x)
                elif isinstance(v, (dict, list)):
                    labels(v)
        elif isinstance(item, list):
            for v in item:
                labels(v)
    labels(result)
    if "grid" in result:
        result["grid"].setdefault("containLabel", True)
    for indicator in result.get("radar", {}).get("indicator", []):
        name = indicator.get("name", "")
        if "\n" not in name:
            indicator["name"] = "\n".join(textwrap.wrap(name, width=20, break_long_words=False))
    features = result.get("toolbox", {}).get("feature", {})
    for key, label in (("saveAsImage", "Salva immagine"), ("restore", "Ripristina")):
        if key in features:
            features[key]["title"] = tr(label)
    if "dataView" in features:
        features["dataView"].update(title=tr("Dati"),
                                  lang=[tr("Dati"), tr("Chiudi"), tr("Aggiorna")])
    if "magicType" in features:
        features["magicType"]["title"] = {"line": tr("Linee"), "bar": tr("Barre")}
    return result
