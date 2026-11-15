# Sceglie, per le serie di input ancora ambigue (stesso valore a 6 cifre, Float32 diversi),
# il candidato che riproduce la corsa di riferimento di Vensim.
# Uso: julia resolve_ambiguous.jl GENERATED.jl INPUTS_DIR REF_DIR CHANGES FINAL_TIME
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl")); include(joinpath(SRC, "runtime.jl")); using .SureRuntime
gen, inputs, refdir, changes = abspath.(ARGS[1:4]); ftime = parse(Float64, ARGS[5])
include(gen); const G = SUREGenerated
include(joinpath(SRC, "simulate.jl"))
using JSON3: JSON3
rn, rt, RV, rst = read_series_dir(refdir)
ch = read_changes(changes)
function score(out, slots)
    bad = 0
    for (i, nm) in enumerate(rn)
        s = get(slots, parse_key(nm), 0); s == 0 && continue
        rt_, at = rst[i] == 0 ? (1e-8, 1e-10) : (1e-5, 1e-6)
        sc = maximum(abs, filter(!isnan, RV[i, :]); init=0.0)
        for k in axes(RV, 2)
            b = RV[i, k]; isnan(b) && continue
            abs(out[s, k] - b) > rt_ * abs(b) + at * sc + 1e-12 && (bad += 1)
        end
    end
    bad
end
for stem in readdir(inputs)
    dir = joinpath(inputs, stem)
    f = joinpath(dir, "ambiguous.json")
    isfile(f) || continue
    amb = JSON3.read(read(f, String))
    n, ts, V, st = read_series_dir(dir)
    idx = Dict(x => i for (i, x) in enumerate(n))
    for (nm, cands) in pairs(amb)
        i = idx[String(nm)]
        st[i] == 0 && continue
        cs = [Float64.(collect(c)) for c in cands]
        distinct32 = unique([Float32.(c) for c in cs])
        if length(distinct32) == 1
            V[i, :] = [isnan(V[i, k]) ? NaN : cs[1][k] for k in axes(V, 2)]; st[i] = 0
            println("$nm: candidati uguali in Float32")
            continue
        end
        scores = Int[]
        for c in cs
            V[i, :] = [isnan(V[i, k]) ? NaN : c[k] for k in axes(V, 2)]
            write(joinpath(dir, "values.f64"), vec(permutedims(V)))
            _, out, slots = simulate(G, inputs; changes=ch, final_time=ftime, cache_data=false)
            push!(scores, score(out, slots))
        end
        b = argmin(scores)
        V[i, :] = [isnan(V[i, k]) ? NaN : cs[b][k] for k in axes(V, 2)]
        st[i] = 0
        println("$nm: valori fuori tolleranza per candidato $(scores) -> scelto $b")
    end
    write(joinpath(dir, "values.f64"), vec(permutedims(V)))
    write(joinpath(dir, "status.u8"), st)
end
