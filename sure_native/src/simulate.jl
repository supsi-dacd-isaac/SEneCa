# Esecuzione del modulo generato. Include runtime.jl e il file generato nel modulo Main.

const DelayBuf = Tuple{Matrix{Float64},Vector{Int},Vector{Int}}
mutable struct SimState
    dt::Float64
    delay::Vector{DelayBuf}
end

normkey(name::AbstractString, els) = isempty(els) ? normname(name) : normname(name) * "[" * join(normname.(els), ",") * "]"

function parse_key(s::AbstractString)
    s = replace(strip(s), "\"" => "")
    m = match(r"^([^\[]+)(\[(.*)\])?$", s)
    m === nothing && return normname(s)
    els = m[3] === nothing ? String[] : split(m[3], ',')
    normkey(m[1], els)
end

function read_series_dir(dir)
    names = filter(!isempty, readlines(joinpath(dir, "names.txt")))
    times = reinterpret(Float64, read(joinpath(dir, "times.f64"))) |> collect
    vals = reinterpret(Float64, read(joinpath(dir, "values.f64"))) |> collect
    V = permutedims(reshape(vals, length(times), length(names)))
    status = read(joinpath(dir, "status.u8"))
    return names, times, V, status
end

"""Tabelle dei dati per gli istanti del modello."""
const DATA_CACHE = Dict{Tuple{String,Vector{Float64}},Vector{Matrix{Float64}}}()
load_data_cached(G, inputs, times) = get!(() -> load_data(G, inputs, times), DATA_CACHE, (abspath(inputs), times))
function load_data(G, inputs::AbstractString, times::Vector{Float64})
    cache = Dict{String,Any}()
    tabs = Matrix{Float64}[]
    for (j, file, names, mode, _) in G.DATA_SPECS
        stem = splitext(file)[1]
        src = get!(cache, stem) do
            n, ts, V, _ = read_series_dir(joinpath(inputs, stem))
            (Dict(parse_key(x) => i for (i, x) in enumerate(n)), ts, V)
        end
        idx, ts, V = src
        tab = zeros(length(names), length(times))
        for (c, nm) in enumerate(names)
            haskey(idx, nm) || error("serie $nm non trovata in $file")
            sv = [isnan(v) ? v : Float64(Float32(v)) for v in V[idx[nm], :]]  # Vensim legge i dati in Float32
            tab[c, :] = SureRuntime.data_table(ts, sv, times, mode)
        end
        length(tabs) + 1 == j || error("ordine dei dati")
        push!(tabs, tab)
    end
    tabs
end

"""Mappa nome normalizzato della cella => posizione nel vettore di stato (memorizzata)."""
const SLOT_CACHE = IdDict{Module,Dict{String,Int}}()
slot_index(G::Module) = get!(() -> build_slot_index(G), SLOT_CACHE, G)
function build_slot_index(G)
    out = Dict{String,Int}()
    for (name, disp, off, els, kind) in G.VARS
        if isempty(els)
            out[name] = off
            continue
        end
        shape = length.(els)
        for (l, ci) in enumerate(CartesianIndices(Tuple(shape)))
            out[normkey(name, [els[k][ci[k]] for k in eachindex(els)])] = off + l - 1
        end
    end
    out
end

"""Assegnazioni di un file .out/.cin di Vensim: `lo <= Nome[e] = v <= hi` o `Nome = v`."""
function read_changes(path)
    out = Pair{String,Float64}[]
    for line in eachline(path)
        s = strip(line)
        (isempty(s) || startswith(s, ":")) && continue
        parts = split(s, "<=")
        body = length(parts) == 3 ? parts[2] : length(parts) == 2 ? (occursin('=', parts[1]) ? parts[1] : parts[2]) : s
        k = findlast('=', body)
        k === nothing && error("riga non riconosciuta: $s")
        push!(out, parse_key(body[1:k-1]) => parse(Float64, strip(body[k+1:end])))
    end
    out
end

function simulate(G, inputs; changes=Pair{String,Float64}[], final_time=nothing, record=true, inject=nothing, cache_data=true)
    slots = slot_index(G)
    x = zeros(G.NX); r = zeros(G.NR)
    G.init_constants!(x, 0.0, 1)
    for (k, v) in changes
        haskey(slots, k) || error("costante non trovata: $k")
        x[slots[k]] = Float64(Float32(v))  # come READCIN di Vensim
    end
    final_time === nothing || (x[slots["final time"]] = final_time)
    t0, dt, tf = x[slots["initial time"]], x[slots["time step"]], x[slots["final time"]]
    times = collect(t0:dt:tf)
    empty!(G.DATA); append!(G.DATA, cache_data ? load_data_cached(G, inputs, times) : load_data(G, inputs, times))
    st = SimState(dt, Vector{DelayBuf}(undef, G.NDELAY))
    # inject: slot => valori per istante, scritti subito dopo ALLOCATE BY PRIORITY
    G.ALLOC_HOOK[] = inject === nothing ? nothing :
        (x, k) -> (for (s, v) in inject; x[s] = v[k]; end)
    G.init_rest!(x, t0, 1, st)
    out = record ? zeros(G.NX, length(times)) : zeros(0, 0)
    for k in eachindex(times)
        t = times[k]
        G.step_aux!(x, t, k)
        record && (out[:, k] = x)
        k == length(times) && break
        G.step_rates!(x, r, t, k, st)
        G.step_update!(x, r, dt, st)
    end
    return times, out, slots
end
