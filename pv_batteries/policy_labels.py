"""Shared presentation of policy levers; names and values stay in model units."""
from __future__ import annotations

BILL_SURCHARGE_EQUITY_LABEL = "Equità del supplemento in bolletta"
BILL_SURCHARGE_EQUITY_RADAR_LABEL = "Equità\nsupplemento\nin bolletta"
BILL_SURCHARGE_EQUITY_HELP = (
    "Il supplemento sulla bolletta elettrica finanzia gli incentivi e gli altri "
    "oneri rappresentati nel modello. L’indice confronta il saldo cumulato fra "
    "supplementi pagati e incentivi PV ricevuti dai diversi tipi di famiglia, "
    "ponderato per il numero di famiglie rappresentate."
)


POLICY_LABELS = {
    "PV rebate cantonal": {
        "label": "Contributo unico PV cantonale (FER)",
        "short_label": "Contributo PV cantonale",
        "unit": "% del costo", "scale": 100,
        "help": "Contributo unico cantonale per il PV finanziato dal FER. "
                "Nel modello è rappresentato come percentuale del costo d’investimento.",
    },
    "PV rebate federal": {
        "label": "Rimunerazione unica PV federale (RU)",
        "short_label": "Contributo PV federale",
        "unit": "% del costo", "scale": 100,
        "help": "Rimunerazione unica federale per il PV. Nel modello lo scenario "
                "è espresso come percentuale del costo d’investimento.",
    },
    "FiT": {
        "label": "Supplemento per l’elettricità PV immessa in rete",
        "control_label": "Supplemento PV per l’immissione in rete",
        "short_label": "Supplemento PV in rete",
        "unit": "ct./kWh", "scale": 100,
        "help": "Supplemento per l’elettricità PV non autoconsumata e immessa in rete, "
                "in aggiunta alla rimunerazione di base rappresentata nel modello.",
    },
    "Battery Rebate": {
        "label": "Contributo all’investimento in batterie",
        "control_label": "Contributo per le batterie",
        "short_label": "Contributo batterie",
        "unit": "% del costo", "scale": 100,
        "help": "Percentuale del costo d’investimento nelle batterie coperta dal contributo.",
    },
    "PV reg scenario": {
        "label": "Obbligo di installazione PV sui nuovi edifici",
        "control_label": "Obbligo PV sui nuovi edifici",
        "short_label": "Obbligo PV nuovi edifici",
        "kind": "binary",
        "help": "Attiva nel modello l’obbligo di installare impianti PV sui nuovi edifici.",
    },
    "Energy Community scenario": {
        "label": "Autoconsumo collettivo virtuale (RCPv)",
        "short_label": "Autoconsumo virtuale",
        "kind": "binary",
        "help": "Raggruppamento ai fini del consumo proprio virtuale (RCPv). "
                "Sì abilita questa possibilità nel modello; le adesioni sono simulate.",
    },
    "Grant share HP": {
        "label": "Contributo per pompe di calore",
        "short_label": "Contributo pompe di calore",
        "unit": "% del costo", "scale": 100,
        "help": "Percentuale del costo d’investimento nella pompa di calore coperta dal contributo.",
    },
    "Grant share PelletBoiler": {
        "label": "Contributo per caldaie a legna e pellet",
        "short_label": "Contributo legna e pellet",
        "unit": "% del costo", "scale": 100,
        "help": "Percentuale del costo d’investimento coperta dal contributo. "
                "La leva riguarda le caldaie a pellet e la componente a legna "
                "dei sistemi abbinati al solare termico.",
    },
    "Grant share DH": {
        "label": "Contributo per allacciamento a reti termiche",
        "control_label": "Contributo allacciamento a reti termiche",
        "short_label": "Contributo reti termiche",
        "unit": "% del costo", "scale": 100,
        "help": "Percentuale del costo d’investimento per l’allacciamento a una rete termica "
                "coperta dal contributo.",
    },
    "Retrofit incentive input": {
        "label": "Contributo base per il risanamento dell’involucro",
        "control_label": "Contributo base al risanamento dell’involucro",
        "short_label": "Contributo risanamento",
        "unit": "CHF/m²",
        "help": "Contributo base per metro quadrato di elemento dell’involucro risanato. "
                "Nel modello alimenta anche gli importi maggiorati secondo il livello "
                "di risanamento raggiunto (CECE e Minergie).",
    },
    "CO2 tax": {
        "label": "Tassa sul CO₂ dei combustibili",
        "short_label": "Tassa CO₂ combustibili",
        "unit": "CHF/tCO₂",
        "help": "Tassa per tonnellata di CO₂ dei combustibili. Nel modello incide "
                "sui costi del riscaldamento a olio e gas e sul finanziamento degli incentivi.",
    },
    "MuKEn scenario": {
        "label": "Requisiti energetici per il riscaldamento (MoPEC)",
        "control_label": "Requisiti per il riscaldamento (MoPEC)",
        "short_label": "Requisiti MoPEC",
        "kind": "muken",
        "choices": {0.0: "Nessuno", 1.0: "MoPEC 2014", 2.0: "MoPEC 2025"},
        "help": "Scenario di applicazione del Modello di prescrizioni energetiche dei Cantoni "
                "(MoPEC), con gli effetti sul riscaldamento rappresentati nel modello.",
    },
    "EV charger incentive input": {
        "label": "Contributo per un punto di ricarica privato",
        "control_label": "Contributo per la ricarica privata",
        "short_label": "Contributo ricarica privata",
        "unit": "CHF/punto",
        "help": "Contributo all’installazione di un punto di ricarica privato per veicoli elettrici.",
    },
    "CO2 coefficient ICE": {
        "label": "Coefficiente CO₂ della tassa di circolazione",
        "control_label": "Tassa di circolazione: coefficiente CO₂",
        "short_label": "Coefficiente tassa veicoli",
        "help": "Coefficiente applicato ai veicoli a combustione. Nel modello la tassa è "
                "0,1 × massa + coefficiente × potenza: la leva modifica il termine legato "
                "alla potenza e non moltiplica l’intero importo della tassa.",
    },
    "EV annual cost reduction input": {
        "label": "Riduzione annua del prezzo d’acquisto dei veicoli elettrici",
        "control_label": "Riduzione annua del prezzo dei veicoli elettrici",
        "short_label": "Riduzione prezzo elettriche",
        "unit": "%/anno", "scale": 100,
        "help": "Assunzione sulla riduzione annua del prezzo d’acquisto dei veicoli "
                "elettrici a batteria, applicata al prezzo dell’anno precedente.",
    },
    "ICE fuel price input": {
        "label": "Prezzo di benzina e diesel",
        "short_label": "Prezzo benzina e diesel",
        "unit": "CHF/l",
        "help": "Prezzo per litro assunto nel modello, uguale per benzina e diesel.",
    },
    "Provvedimento 1.2": {
        "label": "PECC P.1.2 – Rinnovo e ottimizzazione degli impianti idroelettrici esistenti",
        "control_label": "PECC P.1.2 – Rinnovo idroelettrico",
        "short_label": "PECC P.1.2 – Rinnovo",
        "kind": "binary",
        "help": "Rinnovo e ottimizzazione degli impianti idroelettrici esistenti. "
                "Nel modello aumenta l’apporto all’idroelettrico ad accumulo fino "
                "a 214 GWh annui aggiuntivi nel 2050 rispetto alla traiettoria di riferimento.",
    },
    "Provvedimento 1.3": {
        "label": "PECC P.1.3 – Nuovi impianti di pompaggio-turbinaggio",
        "control_label": "PECC P.1.3 – Pompaggio e turbinaggio",
        "short_label": "PECC P.1.3 – Pompaggio",
        "kind": "binary",
        "help": "Nuovi impianti di pompaggio-turbinaggio. Nel modello la produzione "
                "aggiuntiva arriva a 637 GWh nel 2050, con 430 GWh di consumo per il pompaggio.",
    },
    "Provvedimento 1.4": {
        "label": "PECC P.1.4 – Nuovi piccoli impianti idroelettrici",
        "control_label": "PECC P.1.4 – Piccolo idroelettrico",
        "short_label": "PECC P.1.4 – Piccoli impianti",
        "kind": "binary",
        "help": "Nuovi piccoli impianti idroelettrici, rappresentati nel modello "
                "come impianti ad acqua fluente. Aggiunge fino a 80 GWh annui nel 2050.",
    },
    "Provvedimento 1.7": {
        "label": "PECC P.1.7 – Aumento dell’accumulo invernale nei bacini idroelettrici",
        "control_label": "PECC P.1.7 – Accumulo invernale",
        "short_label": "PECC P.1.7 – Accumulo",
        "kind": "binary",
        "help": "Aumento della capacità di accumulazione invernale dei bacini idroelettrici "
                "esistenti. Nel modello trasferisce fino a 89 GWh dalla stagione estiva "
                "a quella invernale nel 2050.",
    },
    "Cantonal PV support": {
        "label": "Incentivi cantonali PV (investimento e immissione in rete)",
        "control_label": "Incentivi cantonali PV",
        "short_label": "Incentivi PV cantonali",
        "kind": "binary",
        "help": "Attiva insieme due componenti: contributo del 10% del costo d’investimento "
                "dal 2026 e supplemento di 5 ct./kWh sull’elettricità PV immessa in rete dal 2025, "
                "secondo le decorrenze del modello.",
    },
    "Renewable heating incentives": {
        "label": "Contributo per sistemi di riscaldamento rinnovabili",
        "control_label": "Contributo al riscaldamento rinnovabile",
        "short_label": "Contributo riscaldamento",
        "unit": "% del costo", "scale": 100,
        "help": "Percentuale del costo d’investimento coperta dal contributo. "
                "La leva comune comprende pompe di calore, caldaie a legna e pellet "
                "e allacciamenti alle reti termiche rappresentati nel modello.",
    },
}


def input_metadata(names):
    """Independent dictionaries for each section, all using the same wording."""
    return {name: {"unit": "-", "kind": "numeric", "scale": 1,
                   **POLICY_LABELS[name]} for name in names}


def control_label(meta, *, with_unit=True):
    label = meta.get("control_label", meta["label"])
    unit = meta.get("unit", "-")
    return f"{label} [{unit}]" if with_unit and unit != "-" else label


def format_value(meta, value, *, with_unit=True):
    if meta.get("kind") == "binary":
        return "Sì" if float(value) >= .5 else "No"
    if meta.get("choices"):
        return meta["choices"].get(float(value), f"{value:g}")
    text = f"{float(value) * meta.get('scale', 1):g}"
    unit = meta.get("unit", "-")
    if not with_unit or unit == "-":
        return text
    return text + ("" if unit.startswith("%") else " ") + unit
