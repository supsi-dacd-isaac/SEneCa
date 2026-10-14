using JSON3
VERSION == v"1.10.12" || error("Pinned Julia required")
Threads.nthreads() == 1 || error("Single thread required")
include("../julia-repro/allocation.jl")
old = read(joinpath(@__DIR__, "../julia-repro/allocation.jl"), String)
module Fallback end
Base.include_string(Fallback, replace(old, "function seneca_allocate_available(" => "function sure_v3_allocate_available("))
sure_v3_allocate_available(args...) = Fallback.sure_v3_allocate_available(args...)
include("../sure-v4/allocation.jl")

function replay(path)
    # Materialize JSON instead of carrying a view of the whole archive through
    # interpreted top-level iteration. The allocator is the existing v4 helper.
    cases = JSON3.read(read(path, String), Vector{Dict{String,Any}})
    worst = 0.0
    cells = 0
    for (index, c) in enumerate(cases)
        q = Float64.(c["request"])
        pp = reduce(vcat, [permutedims(Float64.(row)) for row in c["pp"]])
        expected = Float64.(c["expected"])
        actual = seneca_allocate_available(q, pp, Float64(c["supply"]))
        all(isfinite, actual) || error("Nonfinite result at case $index")
        delta = abs.(actual - expected)
        all(delta .<= 1e-12 .* max.(1., abs.(expected))) || error("Mismatch at case $index")
        worst = max(worst, maximum(delta))
        cells += length(actual)
    end
    result = Dict("pass" => true, "cases" => length(cases), "cells" => cells, "max_abs" => worst)
    write(replace(path, "allocation-fixtures.json" => "allocation-result.json"), JSON3.write(result))
    println(JSON3.write(result))
end

replay(only(ARGS))
