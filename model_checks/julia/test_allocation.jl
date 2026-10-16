using JSON3, Test
include(joinpath(@__DIR__, "../../sure_julia/julia/allocation.jl"))
# The inherited helper defines the original wrapper. Rename it while loading
# in the standalone test to match the current translated model.
old = read(joinpath(@__DIR__, "../../sure_julia/julia/allocation.jl"), String)
module Fallback end
Base.include_string(Fallback, replace(old, "function seneca_allocate_available(" => "function sure_v3_allocate_available("))
sure_v3_allocate_available(args...) = Fallback.sure_v3_allocate_available(args...)
include(joinpath(@__DIR__, "../../sure_julia/julia/priority_allocation.jl"))
cases = JSON3.read(read(ARGS[1], String))
@testset "Production allocation: direct common-width priority" begin
    for c in cases
        q = Float64.(c.request)
        pp = reduce(vcat, [permutedims(Float64.(row)) for row in c.pp])
        expected = Float64.(c.expected)
        result = seneca_allocate_by_priority(q, pp[:, 2], length(q), pp[1, 3], Float64(c.supply))
        @test all(abs.(result-expected) .<= 1e-12 .* max.(1., abs.(expected)))
        # Also exercise month/hour broadcasting with exactly the same profile.
        batch = repeat(reshape(q, 1, 1, :), 2, 3, 1)
        allocated = seneca_allocate_by_priority(batch, pp[:, 2], length(q), pp[1, 3], fill(Float64(c.supply), 2, 3))
        @test all(allocated[2, 3, :] .== result)
        @test all(isfinite, result)
    end
    @test_throws ErrorException seneca_priority([1.], [1.], 0., 1.)
    @test_throws ErrorException seneca_priority([1.], [1.], 1., -1.)
end
write(replace(ARGS[1], "allocation-fixtures.json" => "allocation-result.json"),
      JSON3.write(Dict("pass" => true, "cases" => length(cases), "checks" => 3length(cases)+2)))
