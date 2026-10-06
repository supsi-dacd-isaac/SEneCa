"""Renderer condivisi per grafici stile pagine Risultati (PV groups + section_ui).

Usato da pages/1_PV_e_Batterie.py e pages/9_Esplora_SURE_PySD.py.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from echarts_charts import (
    render_echarts_bar_category,
    render_echarts_bar_grouped,
    render_echarts_line,
    render_echarts_line_composite,
)
from pv_batteries_config import CHART_ALIASES, FINAL_YEAR, OUTPUT_GROUPS, OUTPUTS
from section_ui import (
    chart_title,
    elem_label,
    match_cols,
    render_section,
    render_section_layout,
    render_section_nav,
    render_section_picker,
)
from ui_colors import SUPSI_BLUE

_LEGACY_PV_CAPACITY_BASES = {
    '"Capacity PV < 30 kW total"',
    '"Capacity PV 30 - 100 kW total"',
    '"Capacity PV > 100 kW total"',
}
_LEGACY_PV_ELECTRICITY_BASES = {
    "Total PV electricity production",
    "Total PV electricity injected in the grid",
    "Total PV electricity SC",
}
_LEGACY_BATTERY_CAPACITY_BASES = {
    '"Total Battery capacity < 100 kW"',
    '"Total Battery capacity > 100 kW"',
}
_LEGACY_LINE_BASES = (
    _LEGACY_PV_CAPACITY_BASES
    | _LEGACY_PV_ELECTRICITY_BASES
    | _LEGACY_BATTERY_CAPACITY_BASES
)

PV_NONRES_CAPACITY_CHART = {
    "kind": "line_composite",
    "unit": "kW",
    "title": "Potenza PV non residenziale",
    "desc": "Potenza installata PV edificio non residenziale",
    "series": [
        {"label": "< 100 kW", "bases": [
            '"Capacity PV < 30 kW total"',
            '"Capacity PV 30 - 100 kW total"',
        ]},
        {"label": "> 100 kW", "bases": ['"Capacity PV > 100 kW total"']},
    ],
}
PV_ELECTRICITY_CHART = {
    "kind": "line_composite",
    "unit": "GWh",
    "title": "Energia PV annuale",
    "desc": "Totale energia prodotta, iniettata in rete e autoconsumata",
    "series": [
        {"label": "Produzione", "bases": ["Total PV electricity production"]},
        {"label": "In rete", "bases": ["Total PV electricity injected in the grid"]},
        {"label": "Autoconsumo (SC)", "bases": ["Total PV electricity SC"]},
    ],
}
BATTERY_CAPACITY_CHART = {
    "kind": "line_composite",
    "unit": "MWh",
    "title": "Capacita' batterie non residenziale",
    "desc": "Capacita' batterie per segmento di potenza PV",
    "series": [
        {"label": "< 100 kW", "bases": ['"Total Battery capacity < 100 kW"']},
        {"label": "> 100 kW", "bases": ['"Total Battery capacity > 100 kW"']},
    ],
}


def clean_base(base: str) -> str:
    return base.strip('"')


def _chart_key(meta: dict) -> str:
    if meta.get("kind") in ("line_composite", "bar_grouped"):
        return meta["title"]
    return clean_base(meta["base"])


def _build_chart_index(outputs: list[dict] | None = None) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for o in (outputs if outputs is not None else OUTPUTS):
        if o.get("base") in _LEGACY_LINE_BASES:
            continue
        index[_chart_key(o)] = o
    for fb in (PV_NONRES_CAPACITY_CHART, BATTERY_CAPACITY_CHART, PV_ELECTRICITY_CHART):
        index.setdefault(fb["title"], fb)
    return index


def _resolve_chart(key: str, index: dict[str, dict]) -> dict | None:
    resolved = CHART_ALIASES.get(key, key)
    return index.get(resolved)


def _sort_by_type_order(cols: list[str], base: str, type_order: list[str]) -> list[str]:
    rank = {label: i for i, label in enumerate(type_order)}
    return sorted(cols, key=lambda c: rank.get(elem_label(c, base), len(type_order)))


def render_bar_fallback(df: pd.DataFrame, meta: dict) -> None:
    """Bar chart Streamlit nativo (fallback se meta senza echarts)."""
    base = meta["base"]
    title = chart_title(meta)
    year = meta.get("year", FINAL_YEAR)
    cols = match_cols(df, base)
    if not cols or year not in df.index:
        st.info(f"Nessun dato {year} per '{title}'.")
        return
    type_order = meta.get("type_order")
    if type_order:
        cols = _sort_by_type_order(cols, base, type_order)
    row = df.loc[year, cols]
    scale = meta.get("scale", 1.0)
    if scale != 1.0:
        row = row * scale
    labels = [elem_label(c, base) for c in cols]
    bar = pd.DataFrame({title: row.values}, index=labels)
    st.markdown(f"**{title}** ({meta['unit']}) - {year}")
    st.caption(meta.get("desc", ""))
    st.bar_chart(bar, color=SUPSI_BLUE, sort=False)


def render_chart(
    df: pd.DataFrame,
    meta: dict,
    *,
    df_base: pd.DataFrame | None = None,
    chart_key: str | None = None,
) -> None:
    kind = meta.get("kind")
    ck = chart_key or f"erc_{_chart_key(meta)}"
    if kind == "line_composite":
        render_echarts_line_composite(df, meta, df_base=df_base, chart_key=ck)
    elif kind == "line":
        render_echarts_line(df, meta, df_base=df_base, chart_key=ck)
    elif kind == "bar_grouped":
        render_echarts_bar_grouped(df, meta, df_base=df_base, chart_key=ck)
    elif kind == "bar":
        if meta.get("echarts"):
            render_echarts_bar_category(df, meta, df_base=df_base, chart_key=ck)
        else:
            render_bar_fallback(df, meta)
    else:
        st.info(f"Tipo grafico non supportato: {kind!r}.")


LEVY_SHARED = """
Il supplemento non è un parametro esogeno: il modello lo **ricalcola** in modo
che il gettito copra esattamente gli incentivi erogati, con la formula
`supplemento [CHF/kWh] = fondi necessari / domanda che paga il supplemento`.
Fondi e domanda sono mediati sui 5 anni precedenti per smorzare le oscillazioni.
"""

LEVY_FEDERAL = """
Finanzia:

- la **rimunerazione unica** per i grandi impianti PV (RUG, oltre 100 kW);
- la **rimunerazione unica** per i piccoli impianti PV (RUP, sotto 100 kW);
- i contratti della **vecchia RIC** ancora in essere;
- gli **altri costi Pronovo**, fissi a 59.4 Mio CHF all'anno.

La domanda al denominatore è quella **svizzera**, che si assume proporzionale a
quella ticinese.
"""

LEVY_CANTONAL = """
Finanzia:

- la quota ticinese della **RIC cantonale**;
- il **contributo unico cantonale** sugli impianti PV, residenziali e non;
- la **FiT cantonale**, attiva dal 2025 e pari all'energia PV immessa in rete
  moltiplicata per la tariffa FiT scelta nello scenario;
- l'**incentivo sulle batterie**, residenziali e non residenziali.

Da questa somma vengono sottratti gli oneri per la centrale a carbone di Lünen.
La domanda al denominatore è quella **ticinese che transita in rete**, cioè il
consumo totale meno l'autoconsumo fotovoltaico.

Da qui un effetto di retroazione importante: più fotovoltaico significa più
autoconsumo, quindi **meno kWh su cui ripartire gli incentivi** e un supplemento
unitario più alto, anche a parità di incentivi erogati.
"""

PRICE_EXPLANATION = """
Il prezzo pagato dal consumatore finale è la somma di più voci. Dal menu qui sotto
puoi vedere l'andamento del prezzo finale, dell'energia e della rete locale.

- ⚡ **Energia** — il costo di acquisto vero e proprio. Varia da distretto a distretto
  perché dipende dal portafoglio di approvvigionamento dell'azienda distributrice.
  Fino al 2026 sono i valori storici osservati; dal 2027 il modello li riscala sul
  prezzo medio di mercato che calcola nella simulazione oraria.
- 🏘️ **Rete di distribuzione (DSO)** — la rete locale. Fino al 2026 vale la tariffa
  storica; dal 2027 il modello la ricalcola come *(spese di base del distributore +
  costi di rinforzo rete) / kWh transitati in rete nel distretto*. I cinque distretti
  serviti dallo stesso distributore (Locarno, Vallemaggia, Leventina, Blenio e
  Riviera) condividono quindi la stessa tariffa.
- 🇨🇭 **Supplemento federale** e 🏛️ **supplemento cantonale** — finanziano gli
  incentivi; il dettaglio è nei riquadri dei due supplementi.
- 🧾 **Tasse cantonali e comunali** — voce fissa a 0.018 CHF/kWh.
"""

GRID_COST_EXPLANATION = """
È l'investimento annuo necessario a potenziare la rete a bassa tensione di ciascun
distretto, in milioni di franchi. Nasce da tre spinte che il modello segue
separatamente:

- 🔥 **pompe di calore**, che alzano i picchi di prelievo invernali;
- ☀️ **fotovoltaico**, che nelle ore centrali inverte il flusso verso la rete;
- 🚗 **ricarica dei veicoli elettrici**, che concentra domanda nelle ore serali.

Il valore mostrato è una media mobile su 5 anni, perché i potenziamenti di rete si
pianificano su più esercizi e non seguono le oscillazioni di un singolo anno.

⚠️ Questi costi confluiscono nella componente DSO del
prezzo. Un distretto che elettrifica in fretta vede quindi **aumentare la propria
tariffa di rete**, ed è uno dei motivi per cui le curve del prezzo finale divergono fra
distretti.
"""

EXPLANATIONS = {
    "levy_federal": (
        "Come viene calcolato il supplemento federale",
        LEVY_SHARED + LEVY_FEDERAL,
    ),
    "levy_cantonal": (
        "Come viene calcolato il supplemento cantonale",
        LEVY_SHARED + LEVY_CANTONAL,
    ),
    "prezzo": ("Da cosa è composto il prezzo", PRICE_EXPLANATION),
    "rinforzo": ("Che cosa sono questi costi", GRID_COST_EXPLANATION),
}


def _render_chart(df, meta, df_base, group_title) -> None:
    render_chart(
        df, meta, df_base=df_base,
        chart_key=f"pv_{group_title}_{_chart_key(meta)}",
    )


def _render_chart_grid(df, charts: list[dict], df_base, group_title: str) -> None:
    """Grafici a coppie, tranne quelli marcati full_width che occupano la riga."""
    pending: list[dict] = []

    def flush() -> None:
        while pending:
            row = [pending.pop(0)]
            if pending:
                row.append(pending.pop(0))
            if len(row) == 1:
                # un grafico spaiato a mezza larghezza lascia mezza riga vuota
                _render_chart(df, row[0], df_base, group_title)
                continue
            cols = st.columns(2)
            for col, meta in zip(cols, row):
                with col:
                    _render_chart(df, meta, df_base, group_title)

    for meta in charts:
        if meta.get("full_width"):
            flush()
            _render_chart(df, meta, df_base, group_title)
        else:
            pending.append(meta)
    flush()


def _group_name(group: dict) -> str:
    """Identificatore stabile del blocco, usato per le chiavi dei widget."""
    return group.get("title") or group.get("key") or group["charts"][0]


def _render_group_body(df, group: dict, index: dict, df_base, *, nested: bool) -> None:
    """Expander esplicativo, eventuale menu a tendina e griglia dei grafici."""
    if note := EXPLANATIONS.get(group.get("explain")):
        label, body = note
        with st.expander(label):
            st.markdown(body)

    name = _group_name(group)
    charts = [m for m in (_resolve_chart(k, index) for k in group["charts"]) if m]
    if not charts:
        st.info("Nessun grafico configurato per questa sezione.")
        return

    if selector := group.get("selector"):
        titles = [chart_title(m) for m in charts]
        sel_key = f"pv_sel_{name}"
        if st.session_state.get(sel_key) not in titles:
            st.session_state.pop(sel_key, None)
        chosen = st.selectbox(selector, titles, key=sel_key)
        charts = [m for m in charts if chart_title(m) == chosen]

    if nested:
        # gia' dentro una colonna: i grafici occupano tutta la larghezza disponibile
        for meta in charts:
            _render_chart(df, meta, df_base, name)
    else:
        _render_chart_grid(df, charts, df_base, name)


PV_SECTION_KEY = "pv_section"


def render_pv_topic_sections(
    df: pd.DataFrame,
    *,
    df_base: pd.DataFrame | None = None,
    section_selector: bool = False,
) -> None:
    """Stessi gruppi OUTPUT_GROUPS della pagina PV e Batterie.

    Un gruppo puo' avere `columns` (una riga di sotto-sezioni), `column_rows`
    (piu' righe di sotto-sezioni) e/o `charts` a tutta larghezza.

    Con `section_selector` si mostra un gruppo alla volta, scelto da un
    selettore con i tasti avanti/indietro.
    """
    index = _build_chart_index()
    groups = OUTPUT_GROUPS
    labels = active = None
    if section_selector:
        labels = [g.get("title") or _group_name(g) for g in OUTPUT_GROUPS]
        active = render_section_picker(labels, key=PV_SECTION_KEY)
        groups = [OUTPUT_GROUPS[labels.index(active)]]

    for i, group in enumerate(groups):
        if title := group.get("title"):
            st.subheader(title)

        column_rows = group.get("column_rows") or (
            [group["columns"]] if group.get("columns") else []
        )
        for subgroups in column_rows:
            for col, sub in zip(st.columns(len(subgroups)), subgroups):
                with col:
                    if sub_title := sub.get("title"):
                        st.subheader(sub_title)
                    _render_group_body(df, sub, index, df_base, nested=True)

        if group.get("charts"):
            _render_group_body(df, group, index, df_base, nested=False)

        if i < len(groups) - 1:
            st.divider()

    if labels:
        st.divider()
        render_section_nav(labels, active, key=PV_SECTION_KEY)


def render_risanamento_section(
    df: pd.DataFrame, outputs: list[dict], final_year: int,
    *, df_base: pd.DataFrame | None = None, explanations=None,
) -> None:
    render_section(
        df, outputs, final_year, df_base=df_base, explanations=explanations,
    )


def render_veicoli_section(
    df: pd.DataFrame, outputs: list[dict], layout: list[list[str]], final_year: int,
    *, df_base: pd.DataFrame | None = None,
) -> None:
    render_section_layout(df, outputs, layout, final_year, df_base=df_base)


def df_has_results_columns(df: pd.DataFrame) -> bool:
    """True se il DataFrame ha almeno un output tipico delle pagine Risultati."""
    probe = "PV residential power by Type"
    return any(c == probe or c.startswith(probe + "[") for c in df.columns)


def df_has_elec_columns(df: pd.DataFrame) -> bool:
    probe = "Electricity dispatched"
    return any(c == probe or c.startswith(probe + "[") for c in df.columns)


def pysd_wide_to_hourly_long(
    df: pd.DataFrame, bases: list[str] | None = None,
) -> pd.DataFrame:
    """Converte output PySD flatten (wide, indice=anno) nel long orario Risultati.

    Colonne attese: variable, month, hour, supplier, year, value
    (supplier NaN per variabili solo Month×Hour, es. PHS).
    """
    from elettricita_config import OUTPUT_BASES

    bases_set = set(bases if bases is not None else OUTPUT_BASES)
    years = [float(y) for y in df.index.tolist()]
    records: list[dict] = []

    for col in df.columns:
        if "[" not in col:
            continue
        name, bracket = col.split("[", 1)
        if name not in bases_set:
            continue
        parts = bracket.rstrip("]").split(",")
        if len(parts) == 3:
            month, hour, supplier = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            month, hour, supplier = parts[0], parts[1], None
        else:
            continue
        series = df[col].to_numpy(dtype=float, copy=False)
        for year, val in zip(years, series, strict=True):
            records.append({
                "variable": name,
                "month": month,
                "hour": hour,
                "supplier": supplier,
                "year": int(year),
                "value": float(val) if val == val else float("nan"),  # NaN-safe
            })

    if not records:
        return pd.DataFrame(
            columns=["variable", "month", "hour", "supplier", "year", "value"]
        )
    return pd.DataFrame.from_records(records)


def render_elettricita_from_pysd(
    df_wide: pd.DataFrame,
    *,
    df_base_wide: pd.DataFrame | None = None,
    section_selector: bool = False,
) -> None:
    """Render sezione Elettricità da DataFrame wide PySD (stessi chart Risultati)."""
    import elettricita_config as elec_cfg
    from section_ui_hourly import render_electricity_section

    if not df_has_elec_columns(df_wide):
        st.warning(
            "Colonne elettriche assenti nel DataFrame. "
            "Rilancia una simulazione live dopo l'aggiornamento del modello."
        )
        return

    long_df = pysd_wide_to_hourly_long(df_wide, elec_cfg.OUTPUT_BASES)
    long_base = None
    if df_base_wide is not None and df_has_elec_columns(df_base_wide):
        long_base = pysd_wide_to_hourly_long(df_base_wide, elec_cfg.OUTPUT_BASES)

    render_electricity_section(
        long_df, elec_cfg, values=None, df_base=long_base,
        section_selector=section_selector,
    )
