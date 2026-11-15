# Validazione Vensim–Julia sugli scenari di riferimento.
#
# Per ogni scenario con riferimento Vensim (cartella <id>.ref):
#   - corsa "full":   Julia completo, con il proprio ALLOCATE BY PRIORITY esatto;
#   - corsa "inject": Electricity dispatched sostituito a ogni passo con i valori di
#                     Vensim (isola la traduzione dallo scarto dell'allocatore).
# Criterio (piano, sezione 8): |d| <= rtol*|ref| + atol*max|serie| + 1e-12, con
# (rtol, atol) = (1e-8, 1e-10) per le serie Float64 e (1e-5, 1e-6) per quelle a 6 cifre.
#
# Uso: julia --project=sure_native validate_scenarios.jl GENERATED.jl INPUTS SCENARIOS.json REFS
#            CALIBRATION.out MDL OUTPUTS.json RESULTS_DIR [id,id,...]
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl"))
include(joinpath(SRC, "runtime.jl")); using .SureRuntime
gen, inputs, scenfile, refs, calib, mdl, outfile, resdir = abspath.(ARGS[1:8])
only = length(ARGS) >= 9 ? Set(split(ARGS[9], ',')) : nothing
include(gen); const G = SUREGenerated
include(joinpath(SRC, "simulate.jl"))
include(joinpath(SRC, "model.jl"))
using JSON3
mkpath(resdir)

# --- classificazione delle variabili dal modello
m = build_model(mdl)
disp(n) = m.vars[n].display
stocks = Set(disp(n) for (n, v) in m.vars if v.kind == :stock)
users = Dict{String,Set{String}}()
for d in m.defs
    refs_ = Tuple{VRef,Vector{String}}[]
    for e in (d.expr, d.init, d.extra)
        e isa Node && collect_refs!(refs_, e, String[])
    end
    for (r, _) in refs_
        push!(get!(users, r.name, Set{String}()), d.var.name)
    end
end
down = Set(n for (n, v) in m.vars if v.kind == :alloc); queue = collect(down)
while !isempty(queue)
    v = pop!(queue)
    for u in get(users, v, Set{String}())
        u in down || (push!(down, u); push!(queue, u))
    end
end
downstream = Set(disp(n) for n in down if !m.vars[n].hidden)
outs = JSON3.read(read(outfile, String))
webapp = Set(String.(outs.webapp_outputs)); equity = Set(String.(outs.equity_inputs))
expl = Set(String.(outs.exploratory_outputs))
ischeck(b) = occursin("check", lowercase(b)) || b in ("Electricity dispatch balance error", "Unserved hourly electricity")
basename_(n) = strip(split(n, '[')[1], '"')

spec = JSON3.read(read(scenfile, String))
calchanges = read_changes(calib)
slots = slot_index(G)

function compare(out, slotv, names, V, status, cands)
    T = size(V, 2)
    res = Dict{String,Any}()
    nbad = 0; ncmp = 0; nident = 0
    badseries = Tuple{String,Int,Float64}[]           # nome, primo istante, max scarto relativo
    groupmax = Dict{String,Float64}()                 # max |d|/max|serie| per gruppo
    varmax = Dict{String,Float64}()                   # per variabile (uscite e stock)
    for i in eachindex(names)
        s = slotv[i]; s == 0 && continue
        b = basename_(names[i])
        # stretta per i valori Float64 (anche scelti tra candidati); larga solo per le 6 cifre
        rt, at = (status[i] == 0 || haskey(cands, i)) ? (1e-8, 1e-10) : (1e-5, 1e-6)
        sc = 0.0
        for k in 1:T
            r = V[i, k]; isnan(r) || (sc = max(sc, abs(r)))
        end
        fk = 0; worst = 0.0; worstn = 0.0
        for k in 1:T
            r = V[i, k]; isnan(r) && continue
            a = out[s, k]
            (a <= -1e33 && r <= -1e33) && continue
            ncmp += 1
            d = abs(a - r)
            if haskey(cands, i)          # più candidati Float64 nel .vdfx: il più vicino
                for c in cands[i]
                    ck = c[k]; ck === nothing || (d = min(d, abs(a - ck)))
                end
            end
            d == 0 && (nident += 1)
            if d > rt * abs(r) + at * sc + 1e-12
                nbad += 1; fk == 0 && (fk = k)
                worst = max(worst, d / max(abs(r), 1e-300))
            end
            worstn = max(worstn, d / max(sc, 1e-12))
        end
        fk > 0 && push!(badseries, (String(names[i]), fk, worst))
        grp = ischeck(b) ? "controlli" : b in downstream ? "a_valle_allocazione" : "indipendenti_allocazione"
        groupmax[grp] = max(get(groupmax, grp, 0.0), worstn)
        if !ischeck(b) && (b in webapp || b in equity || b in expl || b in stocks)
            varmax[b] = max(get(varmax, b, 0.0), worstn)
        end
    end
    sort!(badseries; by = x -> -x[3])
    bygroup = Dict{String,Int}()
    for (n, _, _) in badseries
        b = basename_(n)
        g = ischeck(b) ? "controlli" : b in downstream ? "a_valle_allocazione" : "indipendenti_allocazione"
        bygroup[g] = get(bygroup, g, 0) + 1
    end
    Dict("values" => ncmp, "values_out" => nbad, "identical" => nident, "series_out" => length(badseries),
         "series_out_by_group" => bygroup, "max_norm_err_by_group" => groupmax,
         "worst_series" => [Dict("name" => n, "first_year" => 2010 + f, "max_rel" => w) for (n, f, w) in first(badseries, 25)],
         "outputs_max_norm_err" => Dict(k => v for (k, v) in varmax if k in webapp || k in equity || k in expl),
         "stocks_max_norm_err" => maximum(v for (k, v) in varmax if k in stocks; init=0.0))
end

function negatives(out, slotv, names, V, T)
    neg = Dict{String,Tuple{Int,Int,Float64,Float64}}()   # serie julia, serie vensim, min julia, min vensim
    for i in eachindex(names)
        b = basename_(names[i]); b in stocks || continue
        s = slotv[i]; s == 0 && continue
        mj = minimum(out[s, 1:T]); mv = minimum(x for x in V[i, :] if !isnan(x); init=Inf)
        (mj < -1e-10 || mv < -1e-10) || continue
        e = get(neg, b, (0, 0, Inf, Inf))
        neg[b] = (e[1] + (mj < -1e-10), e[2] + (mv < -1e-10), min(e[3], mj), min(e[4], mv))
    end
    Dict(k => Dict("series_julia" => v[1], "series_vensim" => v[2], "min_julia" => v[3], "min_vensim" => v[4]) for (k, v) in neg)
end

summary = []
for sc in spec.scenarios
    id = String(sc.id)
    only === nothing || id in only || continue
    refid = get(sc, :same_as_base, false) ? "base" : id
    refdir = joinpath(refs, refid * ".ref")
    # solo riferimenti completati (registrati da run_vensim_scenarios.py); salta i già validati
    done_refs = Set(String(JSON3.read(l).id) for l in eachline(joinpath(refs, "runs.jsonl")) if !isempty(strip(l)))
    (isdir(refdir) && refid in done_refs) || (println("$id: riferimento non ancora pronto"); continue)
    get(ENV, "REVALIDATE", "0") == "1" || !isfile(joinpath(resdir, id * ".json")) || continue
    names, rtimes, V, status = read_series_dir(refdir)
    cf = joinpath(refdir, "candidates.json")
    cands = isfile(cf) ? Dict(parse(Int, String(k)) + 1 => [collect(c) for c in v] for (k, v) in pairs(JSON3.read(read(cf, String)))) :
                         Dict{Int,Vector{Vector{Any}}}()
    settings = [parse_key(String(k)) => Float64(v) for (k, v) in pairs(sc.settings)]
    ch = calchanges
    slotv = [get(slots, parse_key(n), 0) for n in names]
    t1 = @elapsed (times, out, _) = simulate(G, inputs; changes=ch, setvals=settings, final_time=Float64(sc.final_time))
    truncated = rtimes != times
    if truncated
        # corsa Vensim interrotta: si confrontano gli anni completi prima dell'interruzione
        rtimes == times[1:length(rtimes)] || error("$id: istanti diversi")
        n = length(rtimes) - 1
        V = V[:, 1:n]; out = out[:, 1:n]
    end
    inj = Pair{Int,Vector{Float64}}[]
    for (i, n) in enumerate(names)
        startswith(n, "Electricity dispatched[") && push!(inj, slotv[i] => vcat(V[i, :], fill(NaN, length(times) - size(V, 2))))
    end
    (_, outi, _) = simulate(G, inputs; changes=ch, setvals=settings, final_time=Float64(sc.final_time), inject=inj)
    truncated && (outi = outi[:, 1:size(V, 2)])
    r = Dict("id" => id, "group" => String(sc.group), "reference" => refid, "seconds_full" => t1,
             "compared_years" => [Int(rtimes[1]), Int(rtimes[size(V, 2)])], "vensim_truncated_at" => truncated ? Int(rtimes[end]) : nothing,
             "unmatched_reference_series" => count(==(0), slotv) - 1,
             "full" => compare(out, slotv, names, V, status, cands),
             "inject" => compare(outi, slotv, names, V, status, cands),
             "negative_stocks" => negatives(out, slotv, names, V, size(V, 2)))
    open(joinpath(resdir, id * ".json"), "w") do io
        JSON3.pretty(io, r)
    end
    f, i_ = r["full"], r["inject"]
    println(rpad(id, 14), " inject: fuori $(i_["values_out"]) valori / $(i_["series_out"]) serie $(i_["series_out_by_group"])",
            " | full: $(f["series_out"]) serie, max dispatch $(round(get(f["max_norm_err_by_group"], "a_valle_allocazione", 0.0), sigdigits=2)),",
            " stock $(round(f["stocks_max_norm_err"], sigdigits=2)) | negativi: ", join(keys(r["negative_stocks"]), ", "))
    flush(stdout)
end
