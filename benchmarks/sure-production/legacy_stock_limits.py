"""Versioned SURE equation correction; original v4 sources remain immutable.

Demolition/renovation reserve the existing building stock first. Heating and
PV transitions share the remaining stock proportionally. Every destination
uses the same corrected source flow. No integrated state is clamped.
"""
import ast
import copy
from dataclasses import dataclass
import re

REVISION = "nonnegative-flows-1"
D6 = ["District", "HS", "Performance", "Type", "PVpanel", "Battery"]
D4 = D6[:4]
D3 = ["District", "Performance", "Type"]
D2 = ["District", "Type"]
PV = [f"{who} adopting {kind}" for who in ("Owners", "Renters") for kind in ("PV", "RCP", "RCPv")]
RENOVATIONS = {
    "VeryLow": ["Res VeryLow Low renovation", "Res VeryLow Moderate renovation", "Res VeryLow High renovation", "Res VeryLow VeryHigh renovation"],
    "Low": ["Res Low to Moderate renovation", "Res Low High renovation", "Res Low VeryHigh renovation"],
    "Moderate": ["Res Moderate High renovation", "Res Moderate VeryHigh renovation"],
    "High": ["Res High VeryHigh renovation"],
}
REQUESTED = PV + ["Res VeryLow demolition"] + [n for rows in RENOVATIONS.values() for n in rows]


def identifier(name):
    return name.lower().replace(" ", "_")


def ref(name, dims):
    return name + "[" + ",".join(dims) + "]"


def mdl_limit(budget, demand):
    # The inner conditional keeps the denominator nonzero even in engines
    # that evaluate both array branches. There is no small-value cutoff.
    return f"IF THEN ELSE(({demand})>0, MIN(1, ({budget})/IF THEN ELSE(({demand})>0, ({demand}), 1)), 1)"


@dataclass
class Equation:
    name: str
    dims: list
    python: str
    vensim: str


def equations():
    rows = []
    def add(name, dims, py, mdl):
        rows.append(Equation(name, dims, py, mdl))
    stock = ref("Bounded housing stock", D6)
    total = ref("Bounded housing total", D3)
    pool = ref("Bounded PVno pool", D3)
    add("Bounded housing stock", D6, "return np.maximum(heating_solution(), 0.0)", f"MAX(0, {ref('Heating Solution', D6)})")
    add("Bounded housing total", D3,
        "return bounded_housing_stock().sum(dim=['HS','PVpanel','Battery']).transpose('District','Performance','Type')",
        "SUM(Bounded housing stock[District,HS!,Performance,Type,PVpanel!,Battery!])")
    add("Bounded PVno pool", D3,
        "return bounded_housing_stock().sel(PVpanel='PVno', Battery='Bno', drop=True).sum(dim='HS').transpose('District','Performance','Type')",
        "SUM(Bounded housing stock[District,HS!,Performance,Type,PVno,Bno])")
    add("Bounded demolition demand", D2,
        "return np.minimum(np.maximum(requested_res_verylow_demolition(), 0.0), bounded_pvno_pool().sel(Performance='VeryLow', drop=True)/time_step())",
        "MIN(MAX(0, Requested Res VeryLow demolition[District,Type]), Bounded PVno pool[District,VeryLow,Type]/TIME STEP)")
    for perf, transfers in RENOVATIONS.items():
        demand = f"Bounded renovation demand {perf}"
        factor = f"Bounded demographic factor {perf}"
        add(demand, D2,
            "return " + " + ".join(f"np.maximum(requested_{identifier(n)}(), 0.0)" for n in transfers),
            " + ".join(f"MAX(0, {ref('Requested '+n, D2)})" for n in transfers))
        h, r = f"Bounded housing total[District,{perf},Type]", ref(demand, D2)
        coarse = f"Res {perf} Buildings[District,Type]"
        py_h = f"bounded_housing_total().sel(Performance='{perf}', drop=True)"
        py_r = identifier(demand) + "()"
        if perf == "VeryLow":
            d = "Bounded demolition demand[District,Type]"
            mdl = mdl_limit(f"MAX(0,MIN({h},{coarse}))/TIME STEP", f"{r}+{d}")
            py = f"h = {py_h}\nr = {py_r}\nd = bounded_demolition_demand()\nreturn _sure_flow_limit(np.maximum(np.minimum(h,res_verylow_buildings()),0.0)/time_step(),r+d)"
        else:
            mdl = mdl_limit(f"MAX(0,MIN({h},{coarse}))/TIME STEP", r)
            py = f"return _sure_flow_limit(np.maximum(np.minimum({py_h},res_{perf.lower()}_buildings()),0.0)/time_step(),{py_r})"
        add(factor, D2, py, mdl)
        for name in transfers:
            add(name, D2,
                f"return np.maximum(requested_{identifier(name)}(),0.0)*{identifier(factor)}()",
                f"MAX(0,{ref('Requested '+name,D2)})*{ref(factor,D2)}")
    add("Res VeryLow demolition", D2,
        "h = bounded_housing_total().sel(Performance='VeryLow',drop=True)\np = bounded_pvno_pool().sel(Performance='VeryLow',drop=True)\nf = bounded_demographic_factor_verylow()\nr = bounded_renovation_demand_verylow()*f\nreturn np.minimum(bounded_demolition_demand()*f,np.maximum(p/time_step()-r*p/xr.where(h>0,h,1.0),0.0))",
        "MIN(Bounded demolition demand[District,Type]*Bounded demographic factor VeryLow[District,Type], MAX(0,Bounded PVno pool[District,VeryLow,Type]/TIME STEP-Bounded renovation demand VeryLow[District,Type]*Bounded demographic factor VeryLow[District,Type]*Bounded PVno pool[District,VeryLow,Type]/IF THEN ELSE(Bounded housing total[District,VeryLow,Type]>0,Bounded housing total[District,VeryLow,Type],1)))")
    add("Share HS by archetype", D6,
        "h = bounded_housing_total()\nreturn (bounded_housing_stock()/xr.where(h>0,h,1.0)).transpose('District','HS','Performance','Type','PVpanel','Battery')",
        f"{stock}/IF THEN ELSE({total}>0,{total},1)")
    add("Building demolition by archetype", D6,
        "s = bounded_housing_stock()\np = bounded_pvno_pool().sel(Performance='VeryLow',drop=True)\nvalue = xr.zeros_like(s)\nvalue.loc[dict(Performance='VeryLow',PVpanel='PVno',Battery='Bno')] = (res_verylow_demolition()*s.sel(Performance='VeryLow',PVpanel='PVno',Battery='Bno',drop=True)/xr.where(p>0,p,1.0)).transpose('District','HS','Type')\nreturn value",
        # Explicit clauses retain the original eligible demolition category.
        "@CLAUSES@Building demolition by archetype[District,HS,VeryLow,Type,PVno,Bno] = Res VeryLow demolition[District,Type]*Bounded housing stock[District,HS,VeryLow,Type,PVno,Bno]/IF THEN ELSE(Bounded PVno pool[District,VeryLow,Type]>0,Bounded PVno pool[District,VeryLow,Type],1)\n~ building/year ~ Eligible source shares. |\nBuilding demolition by archetype[District,HS,Performance,Type,PVpanel,Battery] :EXCEPT: [District,HS,VeryLow,Type,PVno,Bno] = 0")
    pv_sum_py = " + ".join(f"np.maximum(requested_{identifier(n)}(),0.0)" for n in PV)
    pv_sum_mdl = " + ".join(f"MAX(0,{ref('Requested '+n,D4)})" for n in PV)
    add("Bounded PV demand", D6,
        f"value = xr.zeros_like(bounded_housing_stock())\nvalue.loc[dict(PVpanel='PVno',Battery='Bno')] = ({pv_sum_py}).transpose('District','HS','Performance','Type')\nreturn value",
        f"@CLAUSES@Bounded PV demand[District,HS,Performance,Type,PVno,Bno] = {pv_sum_mdl}\n~ building/year ~ Requested nonnegative PV transfers. |\nBounded PV demand[District,HS,Performance,Type,PVpanel,Battery] :EXCEPT: [District,HS,Performance,Type,PVno,Bno] = 0")
    add("Bounded technology budget", D6,
        "return np.maximum(bounded_housing_stock()/time_step()-building_demolition_by_archetype()-buildings_hs_renovation_from(),0.0)",
        f"MAX(0,{stock}/TIME STEP-{ref('Building demolition by archetype',D6)}-{ref('Buildings HS Renovation From',D6)})")
    add("Bounded technology demand", D6,
        "return bounded_housing_stock()/equivalent_lifetime()+bounded_pv_demand()",
        f"{stock}/Equivalent Lifetime[HS]+{ref('Bounded PV demand',D6)}")
    add("Bounded technology factor", D6,
        "return _sure_flow_limit(bounded_technology_budget(),bounded_technology_demand())",
        mdl_limit(ref("Bounded technology budget",D6),ref("Bounded technology demand",D6)))
    add("Consumers leaving HS for old age", D6,
        "return bounded_housing_stock()/equivalent_lifetime()*bounded_technology_factor()",
        f"{stock}/Equivalent Lifetime[HS]*{ref('Bounded technology factor',D6)}")
    for name in PV:
        add(name, D4,
            f"return np.maximum(requested_{identifier(name)}(),0.0)*bounded_technology_factor().sel(PVpanel='PVno',Battery='Bno',drop=True)",
            f"MAX(0,{ref('Requested '+name,D4)})*Bounded technology factor[District,HS,Performance,Type,PVno,Bno]")
    return rows


def python_source(source):
    tree = ast.parse(source)
    functions = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'add':
                    fields = {k.arg: ast.literal_eval(k.value) for k in dec.keywords if k.arg in {'name', 'subscripts'}}
                    functions[fields['name']] = (node, fields)
    replacements, additions = [], []
    for name in REQUESTED:
        original, _ = functions[name]
        clone = copy.deepcopy(original)
        clone.name = 'requested_' + original.name
        for kw in clone.decorator_list[0].keywords:
            if kw.arg == 'name':
                kw.value = ast.Constant('Requested ' + name)
        additions.append(ast.unparse(clone))
    specs = equations()
    known = {n.name for n, _ in functions.values()} | {identifier(e.name) for e in specs} | {'requested_'+functions[n][0].name for n in REQUESTED}
    for eq in specs:
        name = functions[eq.name][0].name if eq.name in functions else identifier(eq.name)
        definition = f"def {name}():\n" + '\n'.join('    '+line for line in eq.python.splitlines()) + '\n'
        parsed = ast.parse(definition)
        dependencies = {}
        for node in ast.walk(parsed):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in known:
                dependencies[node.func.id] = dependencies.get(node.func.id, 0) + 1
        decorated = f"@component.add(name={eq.name!r}, subscripts={eq.dims!r}, comp_type='Auxiliary', comp_subtype='Normal', depends_on={dependencies!r})\n" + definition
        if eq.name in functions:
            original = functions[eq.name][0]
            replacements.append((original.decorator_list[0].lineno-1, original.end_lineno, decorated))
        else:
            additions.append(decorated)
    lines = source.splitlines(keepends=True)
    for start, end, text in sorted(replacements, reverse=True):
        lines[start:end] = [text]
    helper = "\ndef _sure_flow_limit(budget, demand):\n    return xr.where(demand>0, np.minimum(1.0, budget/xr.where(demand>0,demand,1.0)), 1.0)\n"
    return ''.join(lines) + helper + '\n\n' + '\n\n'.join(additions) + '\n'


def vensim_source(source):
    # Sketch/settings records also contain pipes (for example font settings).
    # Never split those as equations or append equations after the sketch.
    model, marker, trailer = source.partition("\\\\\\---///")
    if not marker:
        raise ValueError('Expected Vensim sketch boundary')
    specs = equations()
    replaced = {e.name for e in specs}
    found = {name: 0 for name in replaced}
    additions, kept = [], []
    for block in model.split('|'):
        match = re.match(r'\s*([^\[=]+?)(?:\[|=)', block)
        name = match.group(1).strip() if match else None
        if name in replaced:
            found[name] += 1
            if name in REQUESTED:
                additions.append(block.replace(name, 'Requested '+name, 1))
        else:
            kept.append(block)
    original_names = {e.name for e in specs if not e.name.startswith('Bounded ')}
    if {name for name, count in found.items() if count} != original_names:
        raise ValueError(f'Original Vensim correction targets differ: {found}')
    for eq in specs:
        body = eq.vensim.removeprefix('@CLAUSES@') if eq.vensim.startswith('@CLAUSES@') else ref(eq.name,eq.dims)+' = '+eq.vensim
        additions.append('\n'+body+'\n~\n~ SURE '+REVISION+'\n')
    # Insert before the preserved sketch/settings trailer, after all equations.
    return '|'.join(kept[:-1]) + '|\n' + '|\n'.join(additions) + '|\n' + kept[-1] + marker + trailer
