using JSON3
include(joinpath(@__DIR__, "allocation.jl"))
rows = JSON3.read(read(ARGS[1], String), Vector{Dict{String,Any}})
failures = []
maximum_error = 0.0
positive_mask_failures = 0
for (index, row) in enumerate(rows)
    profiles = reduce(vcat, (permutedims(Float64.(r)) for r in row["pp"]))
    expected = Float64.(row["expected"])
    actual = seneca_allocate_vector(Float64.(row["request"]), profiles, Float64(row["available"]))
    errors = abs.(actual .- expected)
    mask_matches = (actual .> 0) == (expected .> 0)
    global positive_mask_failures += !mask_matches
    global maximum_error = max(maximum_error, maximum(errors))
    # Allocation gets subtracted from supply downstream. Check absolute errors
    # as well as the original per-cell tolerance to expose cancellation.
    if !mask_matches || any(errors .> 1e-12 .* max.(1., abs.(expected)) .+ 1e-9 .* abs.(expected))
        push!(failures, Dict("case"=>index, "max_abs"=>maximum(errors), "actual"=>actual,
                             "expected"=>expected, "positive_mask_matches"=>mask_matches))
    end
end
result = Dict("pass"=>isempty(failures), "cases"=>length(rows), "max_abs"=>maximum_error,
              "failures"=>failures, "positive_mask_failures"=>positive_mask_failures)
write(ARGS[2], JSON3.write(result))
println("Allocation: ",length(rows)," cases, ",length(failures)," failures, maxabs=",maximum_error)
