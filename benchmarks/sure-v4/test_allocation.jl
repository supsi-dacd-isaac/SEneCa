using JSON3, Test
include("../julia-repro/allocation.jl")
# The inherited helper defines the original wrapper. Rename it while loading
# in the standalone test to match the translated v4 model.
old = read(joinpath(@__DIR__, "../julia-repro/allocation.jl"), String)
module Fallback end
Base.include_string(Fallback, replace(old, "function seneca_allocate_available(" => "function sure_v3_allocate_available("))
sure_v3_allocate_available(args...) = Fallback.sure_v3_allocate_available(args...)
include("allocation.jl")
cases = JSON3.read(read(ARGS[1], String))
@testset "v4 allocation: common-width priority and rectangular fallback" begin
    for c in cases
        q = Float64.(c.request)
        pp = reduce(vcat, [permutedims(Float64.(row)) for row in c.pp])
        expected = Float64.(c.expected)
        result = seneca_allocate_available(q, pp, Float64(c.supply))
        @test all(abs.(result-expected) .<= 1e-12 .* max.(1., abs.(expected)))
        # Also exercise month/hour broadcasting with exactly the same profile.
        batch = repeat(reshape(q, 1, 1, :), 2, 3, 1)
        allocated = seneca_allocate_available(batch, pp, fill(Float64(c.supply), 2, 3))
        @test all(allocated[2, 3, :] .== result)
        @test all(isfinite, result)
    end
    @test_throws ErrorException sure_v4_priority([1.], [1.], 0., 1.)
    @test_throws ErrorException sure_v4_priority([1.], [1.], 1., -1.)
end
write(replace(ARGS[1], "allocation-fixtures.json" => "allocation-result.json"),
      JSON3.write(Dict("pass" => true, "cases" => length(cases), "checks" => 3length(cases)+2)))
