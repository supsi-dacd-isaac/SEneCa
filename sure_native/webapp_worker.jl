# Worker persistente della webapp per la traduzione nativa di SURE.mdl.
#
# Stesso protocollo di sure_julia/julia/worker.jl (una riga JSON per richiesta e per
# risposta; uscite scritte come v0000.bin ... in Float64 little endian, anno per anno,
# celle nell'ordine del prodotto delle coordinate con l'ultimo indice più veloce),
# così sure_julia/runtime.py e sure_julia/batch.py restano invariati.
#
# Uso: julia --startup-file=no --project=sure_native webapp_worker.jl BUILD_DIR EXPORT.json
using JSON3
VERSION >= v"1.10" || error("Julia 1.10 o successivo richiesto")
Threads.nthreads() == 1 || error("Un solo thread Julia per worker")
Base.cumulative_compile_timing(true)
seconds_since(start) = (time_ns() - start) / 1e9

const SRC = joinpath(@__DIR__, "src")
include(joinpath(SRC, "parser.jl"))
include(joinpath(SRC, "runtime.jl")); using .SureRuntime

function progress(protocol, job, phase; completed=0, total=1, year=0)
    get(job, :progress, false) || return
    println(protocol, JSON3.write(Dict{String,Any}("event" => "progress", "id" => job.id,
        "phase" => phase, "completed" => completed, "total" => total, "year" => year)))
    flush(protocol)
end

"Posizioni nel vettore di stato delle celle di una uscita, nell'ordine dell'export."
function cell_slots(slots, item)
    dims = [String.(item.coords[d]) for d in item.dims]
    key = String(item.julia_name)
    isempty(dims) && return [slots[key]]
    out = Int[]
    # Iterators.product fa variare più in fretta il primo indice: si invertono gli
    # assi per avere l'ultimo indice più veloce, come frame_from_arrays in runtime.py
    for combo in Iterators.product(reverse(dims)...)
        push!(out, slots[normkey(key, collect(reverse(combo)))])
    end
    out
end

function execute(G, build, catalog, cells, job, protocol)
    started = time_ns()
    compile_before = first(Base.cumulative_compile_time_ns())
    wanted = String.(job.outputs)
    length(unique(wanted)) == length(wanted) || error("Uscite duplicate")
    requested = [catalog[n] for n in wanted]
    setvals = Pair{String,Float64}[]
    for (k, v) in pairs(job.parameters)
        key = parse_key(String(k))
        haskey(build.slots, key) || error("Parametro sconosciuto al modello: $k")
        push!(setvals, key => Float64(v))
    end
    rows = reduce(vcat, (cells[n] for n in wanted); init=Int[])
    progress(protocol, job, "initialize")
    progress(protocol, job, "integrate")
    start = time_ns()
    times, out, _ = simulate(G, build.inputs; changes=build.changes, setvals=setvals,
                             final_time=2050.0, record_slots=rows)
    solve_seconds = seconds_since(start)
    times == collect(2011.0:2050.0) || error("Anni incompleti")
    target = String(job.directory)
    isdir(target) || error("Cartella privata dei risultati mancante")
    progress(protocol, job, "extract"; total=length(times))
    start = time_ns()
    r0 = 0
    for (i, item) in enumerate(requested)
        n = length(cells[wanted[i]])
        block = out[r0+1:r0+n, :]            # celle × anni
        r0 += n
        all(isfinite, block) || error("Uscita non finita: $(item.name)")
        open(joinpath(target, "v$(lpad(i-1, 4, '0')).bin"), "w") do io
            write(io, vec(block))            # per colonna: anno per anno, celle in ordine
        end
    end
    for k in eachindex(times)
        progress(protocol, job, "extract"; completed=k, total=length(times), year=Int(times[k]))
    end
    Dict("ok" => true, "id" => job.id, "years" => times,
         "initialize_seconds" => 0.0, "solve_seconds" => solve_seconds,
         "extraction_seconds" => seconds_since(start), "seconds" => seconds_since(started),
         "compilation_seconds" => (first(Base.cumulative_compile_time_ns()) - compile_before) / 1e9,
         "max_rss_bytes" => Sys.maxrss(), "module_id" => string(objectid(G)))
end

# Il modulo generato e simulate.jl si caricano al livello superiore, prima di servire
# le richieste: le funzioni definite dopo l'avvio di main non sarebbero visibili.
const STARTED = time_ns()
const BUILD_DIR, EXPORT_FILE = ARGS
const META = JSON3.read(read(joinpath(BUILD_DIR, "build.json"), String))
redirect_stdout(stderr) do
    include(joinpath(BUILD_DIR, String(META.model)))
end
include(joinpath(SRC, "simulate.jl"))
const G = SUREGenerated
# simulate confronta G.DATA con le tabelle in cache solo dalla seconda simulazione:
# si compila subito, così nessuna richiesta dopo il riscaldamento compila codice
precompile(getindex, (Vector{Matrix{Float64}}, Int))

function main()
    protocol = stdout
    slots = slot_index(G)
    build = (slots=slots, inputs=joinpath(BUILD_DIR, String(META.inputs)),
             changes=read_changes(joinpath(BUILD_DIR, String(META.calibration))))
    export_ = JSON3.read(read(EXPORT_FILE, String))
    catalog = Dict(String(x.name) => x for x in export_)
    cells = Dict(String(x.name) => cell_slots(slots, x) for x in export_)
    println(JSON3.write(Dict("ready" => true, "load_seconds" => seconds_since(STARTED),
                            "module_id" => string(objectid(G))))); flush(stdout)
    for line in eachline(stdin)
        job = JSON3.read(line)
        try
            result = redirect_stdout(stderr) do
                execute(G, build, catalog, cells, job, protocol)
            end
            println(JSON3.write(result))
        catch error
            showerror(stderr, error, catch_backtrace()); println(stderr)
            println(JSON3.write(Dict("ok" => false, "id" => job.id, "error" => sprint(showerror, error))))
        end
        flush(stdout)
    end
end
main()
