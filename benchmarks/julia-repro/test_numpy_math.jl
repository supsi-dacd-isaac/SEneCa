using JSON3
include(joinpath(@__DIR__, "numpy_math.jl"))

function main(directory)
    platform = JSON3.read(read(joinpath(directory, "platform.json"), String))
    seneca_verify_numpy_math(String(platform.macos_version), Int(platform.libsystem_version), Int(platform.libsystem_m_version))
    values = collect(reinterpret(Float64, read(joinpath(directory, "input.bin"))))
    expected = collect(reinterpret(Float64, read(joinpath(directory, "expected.bin"))))
    right = isfile(joinpath(directory, "right.bin")) ? collect(reinterpret(Float64, read(joinpath(directory, "right.bin")))) : zeros(length(values))
    length(values) == length(expected) || error("Truncated NumPy math fixture")
    rows = Dict{String,Any}[]
    for record in JSON3.read(read(joinpath(directory, "records.json"), String), Vector{Dict{String,Any}})
        bounds = (Int(record["offset"])+1):(Int(record["offset"])+Int(record["count"]))
        name = record["name"]
        # LOG remains Julia's implementation: actual SURE inputs proved exact.
        actual = if name in ("numpy_power", "python_power")
            operation = name == "numpy_power" ? seneca_numpy_power : seneca_python_power
            operation.(view(values, bounds), view(right, bounds))
        else
            operation = name == "exp" ? seneca_numpy_exp : name == "log" ? log : name == "sqrt" ? sqrt : error("Unknown math fixture operation")
            operation.(view(values, bounds))
        end
        truth = expected[bounds]
        failures = findall(reinterpret(UInt64, actual) .!= reinterpret(UInt64, truth))
        row = merge(record, Dict("pass"=>isempty(failures), "failures"=>length(failures), "cells"=>length(actual)))
        if !isempty(failures)
            i = first(failures)
            row["first_failure"] = Dict("cell"=>i, "input"=>values[bounds[i]], "python"=>truth[i], "julia"=>actual[i])
        end
        push!(rows, row)
    end
    write(joinpath(directory, "results.json"), JSON3.write(Dict("pass"=>all(row["pass"] for row in rows),
        "cases"=>length(rows), "cells"=>sum(row["cells"] for row in rows), "platform"=>platform,
        "uint64_bitwise"=>all(row["pass"] for row in rows), "results"=>rows)))
end

main(ARGS[1])
