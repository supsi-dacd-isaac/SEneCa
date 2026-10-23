"""Session-local gettext presentation; never translates model identifiers or values."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import gettext
import re
import textwrap
from pathlib import Path

import streamlit as st

LOCALES = Path(__file__).resolve().parents[1] / "locales"
LANGUAGES = {"it": "Italiano", "en": "English", "fr": "Français", "de": "Deutsch"}


def language() -> str:
    selected = st.session_state.get("ui_language", "it")
    return selected if selected in LANGUAGES else "it"


@lru_cache(maxsize=4)
def catalog(lang: str):
    # Do not install a process-global translator: users may choose different languages.
    if lang == "it":
        return gettext.NullTranslations()
    return gettext.translation("seneca", localedir=LOCALES, languages=[lang], fallback=True)


def tr(message, **values):
    if message is None:
        return None
    translated = catalog(language()).gettext(message)
    return translated.format(**{
        key: chart_text(value) if isinstance(value, str) else value
        for key, value in values.items()
    }) if values else translated


def display_frame(frame):
    """Localize a presentation copy, leaving calculation/export schemas intact."""
    return frame.rename(columns=chart_text).map(
        lambda value: chart_text(value) if isinstance(value, str) else value
    )


def _preserve_choices_on_language_change():
    # Streamlit's browser keeps formatted option labels. When those labels
    # change language, explicitly resend the canonical selection; otherwise
    # an existing radio/selectbox can briefly submit None on the next action.
    # Only string selections need this; button states must never be assigned.
    for key in list(st.session_state):
        value = st.session_state[key]
        if key != "ui_language" and isinstance(value, str):
            st.session_state[key] = value


def language_selector():
    # Keep this in the shared entrypoint so language persists across pages.
    # All four language names are shown in their own language.
    # Streamlit has no public API for adding widgets to its toolbar. Position
    # our own keyed container there, reserving a lane in the native toolbar so
    # its running indicator, Stop control and menu cannot overlap the selector.
    # Only the stable semantic toolbar class is used, never generated classes.
    st.html("""<style>
        .stAppToolbar { padding-right: 2.5rem; }
        .st-key-language_toolbar {
            position: fixed;
            top: 0;
            right: 1.25rem;
            height: 3.75rem;
            align-items: center;
            width: max-content;
            z-index: 1000000;
        }
    </style>""")
    with st.container(key="language_toolbar", horizontal=True, horizontal_alignment="right"):
        with st.popover(
            ":material/language:", help="Lingua / Language / Langue / Sprache", type="tertiary", key="language_menu",
        ):
            with st.container(width=200):
                st.radio(
                    "Lingua / Language / Langue / Sprache", list(LANGUAGES),
                    format_func=LANGUAGES.get, key="ui_language",
                    on_change=_preserve_choices_on_language_change,
                )


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
    if " | " in value:
        return " | ".join(chart_text(part) for part in value.split(" | "))
    for pattern, template in (
        (r"cumulato dal (\d{4})", "cumulato dal {year}"),
        (r"cumulato dal (\d{4}) per supplier", "cumulato dal {year} per supplier"),
        (r"Ripartizione (\d{4})", "Ripartizione {year}"),
        (r"Preparazione dei risultati: anno (\d{4}) \(fase 3/4\)",
         "Preparazione dei risultati: anno {year} (fase 3/4)"),
    ):
        if match := re.fullmatch(pattern, value):
            return tr(template, year=match.group(1))
    if match := re.fullmatch(r"(.+) \(([^()]*)\)", value):
        return f"{chart_text(match.group(1))} ({chart_text(match.group(2))})"
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
