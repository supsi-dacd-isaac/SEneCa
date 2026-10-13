using JSON3
function main(directory)
    metadata = JSON3.read(read(joinpath(directory, "model.json"), String))
    model = Module(gensym(:NumpyMath))
    Base.include(model, String(metadata.path))
    expected = collect(reinterpret(Float64, read(joinpath(directory, "expected.bin"))))
    records = JSON3.read(read(joinpath(directory, "records.json"), String), Vector{Dict{String,Any}})
    requested = unique(String(record["identifier"]) for record in records)
    observations = Dict(time => Base.invokelatest(model.observe, model.u0, Float64(time), requested) for time in (0, 1))
    results = Dict{String,Any}[]
    for record in records
        actual = observations[record["time"]][record["identifier"]]
        values = actual isa Number ? [Float64(actual)] : vec([actual[reverse(index)...] for index in Iterators.product((1:n for n in reverse(size(actual)))...)])
        bounds = (Int(record["offset"])+1):(Int(record["offset"])+Int(record["count"]))
        truth = expected[bounds]
        failures = findall(reinterpret(UInt64, values) .!= reinterpret(UInt64, truth))
        row = merge(record, Dict("pass"=>isempty(failures), "failures"=>length(failures)))
        if !isempty(failures)
            i = first(failures)
            row["first_failure"] = Dict("cell"=>i, "python"=>truth[i], "julia"=>values[i])
        end
        push!(results, row)
    end
    write(joinpath(directory, "results.json"), JSON3.write(Dict("pass"=>all(row["pass"] for row in results),
        "cases"=>length(results), "cells"=>sum(row["count"] for row in results), "uint64_bitwise"=>all(row["pass"] for row in results), "results"=>results)))
end
main(ARGS[1])
