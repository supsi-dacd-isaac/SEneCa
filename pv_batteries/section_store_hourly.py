"""Loader store orario (formato long) per la sezione Elettricità."""

from __future__ import annotations



import pandas as pd



from section_store import combo_key



_DEFAULT_EXCLUDE_SUPPLIERS = {

    "Hourly available supply by Supplier": ["Import"],

}



ALL_MONTHS_ORDER = [f"M{i}" for i in range(1, 13)]

HOURS_ORDER = [f"H{h}" for h in range(1, 25)]


# Il modello simula un solo giorno tipo per mese (subscript Month x Hour): la
# somma sulle 24 ore vale quindi un giorno, non un mese. Per i totali mensili e
# annuali si scala sui giorni di un mese medio, come fa il modello Vensim stesso
# (es. "SUM(Hourly exported electricity[Month,Hour!,Supplier]) * 365 / 12").
DAYS_PER_MONTH = 365 / 12





def _parquet_filters(months: list[str] | None, years: list[int] | None) -> list:

    filters = []

    if months:

        filters.append(("month", "in", list(months)))

    if years:

        filters.append(("year", "in", [int(y) for y in years]))

    return filters





def _combo_parquet_filters(cfg, values) -> list:

    return [

        (col, "==", val)

        for col, val in zip(cfg.INPUT_ORDER, values)

    ]





def _apply_filters(df: pd.DataFrame, months: list[str] | None,

                   years: list[int] | None) -> pd.DataFrame:

    if df.empty:

        return df

    if months:

        df = df[df["month"].isin(months)]

    if years:

        df = df[df["year"].isin(years)]

    return df





def load_hourly_df(cfg, months: list[str] | None = None,

                   years: list[int] | None = None) -> pd.DataFrame:

    """Carica lo store long, filtrato per mesi/anni display (default: cfg)."""

    months = list(months if months is not None else cfg.DISPLAY_MONTHS)

    years = list(years if years is not None else cfg.DISPLAY_YEARS)

    filters = _parquet_filters(months, years) or None



    if cfg.CONSOLIDATED_HOURLY.exists():

        return pd.read_parquet(cfg.CONSOLIDATED_HOURLY, filters=filters)



    hourly_dir = cfg.STORE_DIR / "hourly"

    if not hourly_dir.exists():

        return pd.DataFrame()

    files = sorted(hourly_dir.glob("*.parquet"))

    if not files:

        return pd.DataFrame()

    df = pd.concat([pd.read_parquet(fp) for fp in files], ignore_index=True)

    return _apply_filters(df, months, years)





def load_combo_hourly_df(cfg, values) -> pd.DataFrame:

    """Carica tutti mesi/anni/ore per la combinazione input corrente."""

    key = combo_key(values)

    hourly_dir = cfg.STORE_DIR / "hourly"

    per_combo = hourly_dir / f"{key}.parquet"

    if per_combo.exists():

        return pd.read_parquet(per_combo)



    if cfg.CONSOLIDATED_HOURLY.exists():

        filters = _combo_parquet_filters(cfg, values)

        return pd.read_parquet(cfg.CONSOLIDATED_HOURLY, filters=filters)



    return pd.DataFrame()





def available_combo_keys(cfg, df: pd.DataFrame) -> set[str]:

    if df.empty:

        return set()

    keys = set()

    for _, row in df[cfg.INPUT_ORDER].drop_duplicates().iterrows():

        keys.add(combo_key([row[c] for c in cfg.INPUT_ORDER]))

    return keys





def load_combo_keys(cfg, df: pd.DataFrame | None = None) -> set[str]:

    """Combo disponibili: indice leggero, file per-combo, o dedup su df filtrato."""

    index_path = getattr(cfg, "CONSOLIDATED_COMBO_INDEX", None)

    if index_path is not None and index_path.exists():

        raw = pd.read_parquet(index_path)

        return {

            combo_key([row[c] for c in cfg.INPUT_ORDER])

            for _, row in raw.iterrows()

        }



    hourly_dir = cfg.STORE_DIR / "hourly"

    if hourly_dir.exists():

        stems = {fp.stem for fp in hourly_dir.glob("*.parquet")}

        if stems:

            return stems



    if df is None:

        df = load_hourly_df(cfg)

    return available_combo_keys(cfg, df)





def _resolve_exclude_suppliers(

    variable: str, exclude_suppliers: list[str] | None,

) -> list[str] | None:

    if exclude_suppliers is None:

        return _DEFAULT_EXCLUDE_SUPPLIERS.get(variable)

    return exclude_suppliers





def _slice_variable(

    df: pd.DataFrame, variable: str,

    exclude_suppliers: list[str] | None = None,

) -> pd.DataFrame:

    sub = df.loc[df["variable"] == variable].copy()

    exclude = _resolve_exclude_suppliers(variable, exclude_suppliers)

    if exclude and not sub.empty:

        sub = sub[~sub["supplier"].isin(exclude)]

    return sub





def aggregate_annual_supplier(

    df: pd.DataFrame, variable: str,

    exclude_suppliers: list[str] | None = None,

) -> pd.DataFrame:

    """Totale annuo GWh per supplier (somma su mesi e ore), indice = year."""

    sub = _slice_variable(df, variable, exclude_suppliers)

    if sub.empty:

        return pd.DataFrame()

    agg = sub.groupby(["year", "supplier"], as_index=False)["value"].sum()

    pivot = agg.pivot(index="year", columns="supplier", values="value")

    return pivot.sort_index().fillna(0.0) * DAYS_PER_MONTH





def aggregate_monthly_supplier(

    df: pd.DataFrame, variable: str, year: int,

    exclude_suppliers: list[str] | None = None,

    months: list[str] | None = None,

) -> pd.DataFrame:

    """Totale mensile GWh per supplier (somma su ore), indice = M1..M12."""

    months = months or ALL_MONTHS_ORDER

    sub = _slice_variable(df, variable, exclude_suppliers)

    sub = sub.loc[sub["year"] == year]

    if sub.empty:

        return pd.DataFrame()

    agg = sub.groupby(["month", "supplier"], as_index=False)["value"].sum()

    pivot = agg.pivot(index="month", columns="supplier", values="value")

    return pivot.reindex(months, fill_value=0.0).fillna(0.0) * DAYS_PER_MONTH





def hourly_snapshot(

    df: pd.DataFrame, variable: str, month: str, year: int,

    has_supplier: bool,

    exclude_suppliers: list[str] | None = None,

) -> pd.DataFrame:

    """Pivot hour x supplier (o hour solo) per combo gia' filtrata."""

    sub = _slice_variable(df, variable, exclude_suppliers)

    sub = sub.loc[(sub["month"] == month) & (sub["year"] == year)]

    if sub.empty:

        return pd.DataFrame()



    if has_supplier:

        pivot = sub.pivot_table(

            index="hour", columns="supplier", values="value", aggfunc="first",

        )

        pivot = pivot.reindex(HOURS_ORDER, fill_value=0.0).fillna(0.0)

        exclude = _resolve_exclude_suppliers(variable, exclude_suppliers)

        if exclude:

            pivot = pivot.drop(columns=exclude, errors="ignore")

        return pivot



    out = sub.set_index("hour")["value"]

    return out.reindex(HOURS_ORDER, fill_value=0.0).to_frame(name=variable).fillna(0.0)





def filter_snapshot(df: pd.DataFrame, cfg, values, variable: str,

                    month: str, year: int, has_supplier: bool,

                    exclude_suppliers: list[str] | None = None) -> pd.DataFrame:

    """Pivot hour x supplier con filtro combo (store multi-combo)."""

    mask = pd.Series(True, index=df.index)

    for name, val in zip(cfg.INPUT_ORDER, values):

        mask &= df[name] == val

    mask &= df["variable"] == variable

    mask &= df["month"] == month

    mask &= df["year"] == year

    combo_df = df.loc[mask]

    if combo_df.empty:

        return pd.DataFrame()

    return hourly_snapshot(

        combo_df, variable, month, year, has_supplier, exclude_suppliers,

    )


