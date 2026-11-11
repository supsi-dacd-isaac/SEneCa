# Catalogo delle uscite per la webapp (export.json), nel formato di sure_julia/build.py:
# nome, chiave nativa, dimensioni e coordinate con le maiuscole originali di SURE.mdl.
# Uso: julia --project=sure_native webapp_export.jl SURE.mdl NAMES.txt EXPORT.json
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl"))
include(joinpath(SRC, "model.jl"))
using JSON3
mdl, namesfile, outfile = ARGS
m = build_model(mdl)
disp = display_names(mdl)
# maiuscole originali degli elementi, dalle definizioni dei range
elcase = Dict{String,String}()
for b in read_blocks(mdl)
    mm = match(r"^\s*([^:~=\(\[]+):(?!=)([^~]*)"s, b.eq)
    mm === nothing && continue
    body = split(mm[2], "->")[1]
    for raw in split(body, ',')
        r = join(split(strip(raw, [' ', '\t', '\r', '\n', '\\', '(', ')'])), ' ')
        isempty(r) || get!(elcase, normname(r), r)
    end
end
label(e) = get(elcase, e, e)
missing_case = Set{String}()
export_ = Any[]
for raw in filter(!isempty, strip.(readlines(namesfile)))
    key = normname(replace(raw, "\"" => ""))
    haskey(m.vars, key) || error("uscita non presente nel modello: $raw")
    v = m.vars[key]
    v.hidden && error("uscita nascosta: $raw")
    dims = String[]; coords = Dict{String,Vector{String}}()
    for d in v.dims
        dn = get(disp, d.name, d.name)
        push!(dims, dn)
        coords[dn] = [label(e) for e in d.elements]
        foreach(e -> haskey(elcase, e) || push!(missing_case, e), d.elements)
    end
    push!(export_, Dict("name" => raw, "julia_name" => key, "dims" => dims, "coords" => coords,
                        "kind" => String(v.kind)))
end
isempty(missing_case) || @warn "elementi senza maiuscole originali" collect(missing_case)
open(outfile, "w") do io; JSON3.pretty(io, export_); end
println("export: $(length(export_)) uscite")
