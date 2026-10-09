using JSON3, LinearAlgebra
BLAS.set_num_threads(1)
directory = ARGS[1]
oracles = JSON3.read(read(joinpath(directory, "oracle.json"), String))
results = []
for item in JSON3.read(read(joinpath(directory, "models.json"), String))
    model = Module(gensym(:Reduction))
    Base.include(model, String(item.path))
    rows = []
    observation = Base.invokelatest(model.observe, model.u0, model.initial_time)
    for record in oracles[String(item.name)].rows
        actual = observation[String(record.identifier)]
        values = actual isa Number ? [Float64(actual)] : vec([actual[reverse(index)...] for index in Iterators.product((1:n for n in reverse(size(actual)))...)])
        expected = Float64.(record.values)
        bad = findall(reinterpret(UInt64, values) .!= reinterpret(UInt64, expected))
        supported = startswith(String(item.name), "rank_1_") && String(item.mode) == "current"
        row = Dict{String,Any}("name" => String(record.name), "source" => String(record.source), "gated" => supported,
                               "reduced" => String.(record.reduced), "pass" => isempty(bad),
                               "cells" => length(values), "failures" => length(bad),
                               "max_abs" => maximum(abs.(values-expected)))
        if !isempty(bad)
            i = first(bad)
            row["first_cell"], row["python"], row["julia"] = i, expected[i], values[i]
        end
        push!(rows, row)
    end
    push!(results, Dict("fixture" => String(item.name), "mode" => String(item.mode),
                        "pass" => all(row["pass"] for row in rows), "rows" => rows))
end
helpers = Module(gensym(:VectorReductions))
Base.include(helpers, joinpath(@__DIR__, "allocation.jl"))
vectors = []
for item in JSON3.read(read(joinpath(directory, "vector-oracles.json"), String))
    value = 0.0 + Base.invokelatest(helpers.seneca_numpy_sum, Float64.(item.values))
    expected = Float64(item.sum)
    push!(vectors, Dict("name" => String(item.name), "pass" => reinterpret(UInt64, value) == reinterpret(UInt64, expected),
                        "python" => expected, "julia" => value))
end
gated_pass = all(row["pass"] for item in results for row in item["rows"] if row["gated"]) && all(item["pass"] for item in vectors)
write(joinpath(directory, "results.json"), JSON3.write(Dict("pass" => gated_pass,
    "scope" => "Only proven one-dimensional reductions are gated; multidimensional rows are layout diagnostics",
    "all_diagnostic_rows_bitwise" => all(item["pass"] for item in results), "vectors" => vectors, "results" => results)))
