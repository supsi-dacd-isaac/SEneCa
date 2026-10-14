using JSON3
include(joinpath(@__DIR__, "allocation.jl"))
function main(directory)
rows = Dict{String,Any}[]
# Materialize the JSON once: lazy JSON3 indexing repeatedly scans large model
# samples, while this harness only needs ordinary vectors and dictionaries.
for item in JSON3.read(read(joinpath(directory, "oracles.json"), String), Vector{Dict{String,Any}})
    expected = Float64.(item["expected"])
    actual = [seneca_numpy_reduce(Float64.(values), Int(item["blocksize"])) for values in item["vectors"]]
    failures = findall(reinterpret(UInt64, expected) .!= reinterpret(UInt64, actual))
    row = Dict{String,Any}("shape" => Int.(item["shape"]), "reduced" => Int.(item["reduced"]),
        "transposed" => Bool(item["transposed"]), "blocksize" => Int(item["blocksize"]),
        "pass" => isempty(failures), "cells" => length(actual), "failures" => length(failures))
    for name in ("binding", "sample", "component")
        haskey(item, name) && (row[name] = item[name])
    end
    if !isempty(failures)
        index = first(failures)
        row["first_failure"] = Dict("index" => index, "python" => expected[index], "julia" => actual[index])
    end
    push!(rows, row)
end
write(joinpath(directory, "results.json"), JSON3.write(Dict(
    "pass" => all(row["pass"] for row in rows), "cases" => length(rows),
    "cells" => sum(row["cells"] for row in rows), "results" => rows)))
end

main(ARGS[1])
