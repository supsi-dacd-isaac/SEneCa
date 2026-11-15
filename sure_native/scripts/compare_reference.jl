# Uso: julia --project=sure_native compare_reference.jl GENERATED.jl INPUTS_DIR REF_DIR CHANGES.out FINAL_TIME [report.tsv]
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl"))     # normname
include(joinpath(SRC, "runtime.jl"))
using .SureRuntime
gen, inputs, refdir, changes, ftime = abspath.(ARGS[1:4])..., ARGS[5]
report = length(ARGS) >= 6 ? abspath(ARGS[6]) : ""
t_load = @elapsed include(gen)
const G = SUREGenerated
include(joinpath(SRC, "simulate.jl"))
println("caricamento e compilazione del modulo: $(round(t_load, digits=1)) s")
ch = read_changes(changes)
names, rtimes, V, status = read_series_dir(refdir)
# INJECT_ALLOC=1: l'uscita dell'allocazione è sostituita con i valori di Vensim
inject = nothing
if get(ENV, "INJECT_ALLOC", "0") == "1"
    sl = slot_index(G)
    inject = Pair{Int,Vector{Float64}}[]
    for (i, nm) in enumerate(names)
        startswith(nm, "Electricity dispatched[") || continue
        push!(inject, sl[parse_key(nm)] => V[i, :])
    end
    println("allocazione sostituita con Vensim: $(length(inject)) celle")
end
t1 = @elapsed (times, out, slots) = simulate(G, inputs; changes=ch, final_time=parse(Float64, ftime), inject=inject)
t2 = @elapsed simulate(G, inputs; changes=ch, final_time=parse(Float64, ftime), record=false)
println("prima simulazione $(round(t1, digits=1)) s, seconda $(round(t2, digits=2)) s")

rtimes == times || error("istanti diversi dal riferimento")
rtol64, atol64 = 1e-8, 1e-10
rtol6, atol6 = 1e-5, 1e-6
nomatch = String[]
rows = []
nbad = 0; ncmp = 0; maxrel = 0.0
for (i, nm) in enumerate(names)
    key = parse_key(nm)
    if !haskey(slots, key)
        push!(nomatch, nm); continue
    end
    jl = out[slots[key], :]
    ref = V[i, :]
    rt, at = status[i] == 0 ? (rtol64, atol64) : (rtol6, atol6)
    scale = maximum(abs, filter(!isnan, ref); init=0.0)
    bad = 0; first = 0; worst = 0.0; wk = 0
    for k in eachindex(ref)
        isnan(ref[k]) && continue      # istante senza valore nel riferimento
        a, b = jl[k], ref[k]
        global ncmp += 1
        ok = abs(a - b) <= at * scale + rt * abs(b) + 1e-12 || (a <= -1e33 && b <= -1e33)
        rel = abs(a - b) / max(abs(b), at * scale, 1e-300)
        if !ok
            bad += 1; first == 0 && (first = k)
        end
        if rel > worst && !(a <= -1e33 && b <= -1e33)
            worst = rel; wk = k
        end
    end
    global maxrel = max(maxrel, worst)
    if bad > 0
        global nbad += 1
        push!(rows, (nm, status[i], first, bad, worst, wk == 0 ? NaN : jl[wk], wk == 0 ? NaN : ref[wk], wk))
    end
end
println("serie confrontate: $(length(names) - length(nomatch)), valori: $ncmp, serie fuori tolleranza: $nbad")
println("serie del riferimento senza corrispondenza: $(length(nomatch)) ", first(nomatch, 10))
sort!(rows; by = r -> (r[3], -r[5]))
for r in first(rows, 40)
    println(join(string.(r), "\t"))
end
if !isempty(report)
    open(report, "w") do io
        println(io, "serie\tstato\tprimo_istante\tvalori_fuori\tmax_scarto_rel\tjulia\tvensim\tistante")
        for r in rows; println(io, join(string.(r), "\t")); end
    end
end

# Uscita Julia allineata al riferimento, per le analisi
if length(ARGS) >= 7
    dir = abspath(ARGS[7]); mkpath(dir)
    M = fill(NaN, length(times), length(names))
    for (i, nm) in enumerate(names)
        key = parse_key(nm)
        haskey(slots, key) && (M[:, i] = out[slots[key], :])
    end
    write(joinpath(dir, "values.f64"), vec(M))
    cp(joinpath(refdir, "names.txt"), joinpath(dir, "names.txt"); force=true)
    cp(joinpath(refdir, "times.f64"), joinpath(dir, "times.f64"); force=true)
    write(joinpath(dir, "status.u8"), zeros(UInt8, length(names)))
    println("uscita Julia in $dir")
end
