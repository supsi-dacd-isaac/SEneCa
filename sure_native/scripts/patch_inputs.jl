# Completa le serie di input rimaste a 6 cifre (blocchi .vdfx ambigui) con i valori
# che Vensim ha usato nella corsa di riferimento, dove le variabili di dati sono in Float64.
# Uso: julia patch_inputs.jl GENERATED.jl INPUTS_DIR REF_DIR
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl")); include(joinpath(SRC, "runtime.jl")); using .SureRuntime
gen, inputs, refdir, mdl = abspath.(ARGS)
include(gen); const G = SUREGenerated
include(joinpath(SRC, "simulate.jl"))
include(joinpath(SRC, "model.jl"))

# Copie dei dati nel modello (X[...] = Dato[...], anche a catena e come valore iniziale
# di uno stock): cella del dato => (cella della copia, solo il primo istante?)
m = build_model(mdl)
cellkey(v, c) = isempty(v.dims) ? v.name : v.name * "[" * join([v.dims[p].elements[c[p]] for p in eachindex(c)], ",") * "]"
rootof = Dict{String,Tuple{String,Bool}}()      # copia => (cella del dato, solo primo istante)
for d in m.defs, c in eachcol(d.cells)
    d.kind == :data && (rootof[cellkey(d.var, c)] = (cellkey(d.var, c), false))
end
changed = true
while changed
    global changed = false
    for d in m.defs
        src = d.kind == :aux ? d.expr : d.kind == :stock ? d.init : nothing
        src isa VRef || continue
        w = m.vars[src.name]
        _, binds = bind_ref(m, d, src, String[])
        any(b -> b.kind == :bang, binds) && continue
        for c in eachcol(d.cells)
            wk = cellkey(w, [b.kind == :const ? b.k : b.map[c[b.p]] for b in binds])
            haskey(rootof, wk) || continue
            me = cellkey(d.var, c)
            haskey(rootof, me) && continue
            root, f = rootof[wk]
            rootof[me] = (root, f || d.kind == :stock)
            global changed = true
        end
    end
end
copies = Dict{String,Vector{Tuple{String,Bool}}}()
for (k, (root, f)) in rootof
    push!(get!(copies, root, Tuple{String,Bool}[]), (k, f))
end
rn, rt, RV, rst = read_series_dir(refdir)
ridx = Dict(parse_key(n) => i for (i, n) in enumerate(rn))
dirs = Dict{String,Any}()
for (j, file, names, mode, lhskeys) in G.DATA_SPECS
    stem = splitext(file)[1]
    d = get!(dirs, stem) do
        n, ts, V, st = read_series_dir(joinpath(inputs, stem))
        Dict(:names => n, :idx => Dict(parse_key(x) => i for (i, x) in enumerate(n)), :t => ts, :V => V, :st => st, :fixed => 0, :left => 0)
    end
    for (c, nm) in enumerate(names)
        i = d[:idx][nm]
        d[:st][i] == 0 && continue
        r = get(ridx, lhskeys[c], 0)
        if r == 0 || rst[r] != 0
            # la variabile di dati è ambigua anche nel riferimento: si usa una sua copia
            r = 0
            vals = filter(!isnan, d[:V][i, :])
            constant = all(==(vals[1]), vals)
            for (ck, firstonly) in get(copies, lhskeys[c], Tuple{String,Bool}[])
                rr = get(ridx, ck, 0)
                if rr != 0 && rst[rr] == 0 && (!firstonly || constant)
                    r = rr; firstonly && (r = -rr); break
                end
            end
        end
        if r == 0
            d[:left] += 1; continue
        end
        if r < 0      # valore iniziale di uno stock: dato costante, vale il primo istante
            v0 = RV[-r, 1]
            if abs(v0 - filter(!isnan, d[:V][i, :])[1]) <= 5e-6 * abs(v0)
                d[:V][i, :] = [isnan(x) ? x : v0 for x in d[:V][i, :]]; d[:st][i] = 0; d[:fixed] += 1
            else
                d[:left] += 1
            end
            continue
        end
        ok = true; newv = copy(d[:V][i, :])
        for (k, t) in enumerate(d[:t])
            isnan(newv[k]) && continue
            kk = findfirst(==(t), rt)
            if kk === nothing || isnan(RV[r, kk]) || abs(RV[r, kk] - newv[k]) > 5e-6 * abs(newv[k]) + 1e-300
                ok = false; break
            end
            newv[k] = RV[r, kk]
        end
        if ok
            d[:V][i, :] = newv; d[:st][i] = 0; d[:fixed] += 1
        else
            d[:left] += 1
        end
    end
end
for (stem, d) in dirs
    dir = joinpath(inputs, stem)
    write(joinpath(dir, "values.f64"), vec(permutedims(d[:V])))
    write(joinpath(dir, "status.u8"), d[:st])
    println("$stem: completate $(d[:fixed]) serie dalla corsa di riferimento, restano $(count(!=(0), d[:st])) a 6 cifre")
end
