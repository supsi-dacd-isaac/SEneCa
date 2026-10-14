using JSON3, Test, LinearAlgebra
BLAS.set_num_threads(1)
results = []
VERSION == v"1.10.12" || error("Unexpected Julia version")
Threads.nthreads() == 1 || error("Single-threaded fixtures required")
oracles = JSON3.read(read(joinpath(dirname(ARGS[1]), "python-oracles.json"), String))
include(joinpath(@__DIR__, "allocation.jl"))
try
    for item in JSON3.read(read(joinpath(dirname(ARGS[1]), "allocation.json"), String))
        pp = reduce(vcat, (permutedims(Float64.(row)) for row in item.pp))
        actual = seneca_allocate_vector(Float64.(item.request), pp, Float64(item.available))
        expected = Float64.(item.expected)
        @test all(abs.(actual-expected) .<= 1e-12 .* max.(1., abs.(expected)) .+ 1e-9 .* abs.(expected))
        @test isapprox(sum(actual), min(sum(max.(Float64.(item.request), 0.)), item.available); atol=1e-12, rtol=1e-9)
    end
    @test_throws ErrorException seneca_allocate_vector([1.], [1. 0. .1 0.], -1.)
    @test_throws ErrorException seneca_allocate_vector([1.], [3. 0. .1 0.], 0.5)
    push!(results, Dict("fixture" => "allocation_vs_python", "pass" => true))
catch error
    push!(results, Dict("fixture" => "allocation_vs_python", "pass" => false, "error" => sprint(showerror, error)))
end
for item in JSON3.read(read(ARGS[1], String))
    name = String(item.name)
    try
        m = Module(gensym(:Fixture))
        Base.include(m, String(item.path))
        sol = Base.invokelatest(m.run_model)
        @test sol.t == collect(0.0:6.0)
        for (t, u) in zip(sol.t, sol.u)
            obs = Base.invokelatest(m.observe, u, t)
            if startswith(name, "rank_")
                rank = parse(Int, split(name, "_")[end])
                @test size(obs["x"]) == Tuple(fill(2, rank))
                for index in CartesianIndices(obs["x"])
                    expected = index[rank] == 1 ? 7.0 : 11.0
                    @test obs["x"][index] == expected
                    initial = sum(index[axis]*10.0^(axis-1) for axis in 1:rank)
                    @test obs["stock"][index] == initial + expected*t
                end
            elseif startswith(name, "delay_")
                delay = parse(Float64, replace(name[7:end], "_" => "."))
                steps = max(1, round(Int, delay))
                @test obs["d"] ≈ (t < steps ? -1.0 : t-steps) atol=1e-12 rtol=1e-9
            elseif name == "selfref"
                @test collect(obs["x"]) == [3.0, 6.0]
                @test obs["stock"] == 9*t
            elseif name == "subgroup"
                @test collect(obs["x"]) == [2., 3., 3.]
                @test collect(obs["stock"]) == [2., 3., 3.] .* (t+1)
            elseif name == "external"
                @test Base.invokelatest(m.x, t) == (t <= 2 ? 10+5*t : 20+10*(t-2))
                @test obs["stock"] == sum(s <= 2 ? 10+5*s : 20+10*(s-2) for s in 0:t-1; init=0.)
            end
            for (variable, expected_rows) in pairs(oracles[name].variables)
                actual = name == "external" && variable == :x ? Base.invokelatest(m.x, t) : obs[String(variable)]
                values = actual isa Number ? [actual] : [actual[reverse(index)...] for index in Iterators.product((1:n for n in reverse(size(actual)))...)]
                expected = Float64.(expected_rows[Int(t)+1])
                scale = [max(1., maximum(abs(row[j]) for row in expected_rows)) for j in eachindex(expected)]
                @test length(values) == length(expected)
                @test all(abs.(vec(values)-expected) .<= 1e-12 .* scale .+ 1e-9 .* abs.(expected))
            end
        end
        if name == "external"
            @test Base.invokelatest(m.x, -1.) == 10.
            @test Base.invokelatest(m.x, 7.) == 60.
        end
        push!(results, Dict("fixture" => name, "pass" => true))
    catch error
        push!(results, Dict("fixture" => name, "pass" => false, "error" => sprint(showerror, error, catch_backtrace())))
    end
end
write(ARGS[2], JSON3.write(Dict("pass" => !isempty(results) && all(x["pass"] for x in results), "results" => results)))
