using JSON3, Test, LinearAlgebra
BLAS.set_num_threads(1)
VERSION == v"1.10.12" || error("Unexpected Julia version")
Threads.nthreads() == 1 || error("Single-threaded fixtures required")
oracles = JSON3.read(read(joinpath(dirname(ARGS[1]), "python-oracles.json"), String))
results = []
for item in JSON3.read(read(ARGS[1], String))
    name = String(item.name)
    try
        model = Module(gensym(:StatefulFixture))
        Base.include(model, String(item.path))
        first_run = nothing
        for repetition in 1:2
            # Every integration starts from an independent state vector.
            solution = Base.invokelatest(model.run_model; u0=deepcopy(model.u0))
            @test solution.t == Float64.(oracles[name].years)
            if first_run === nothing
                first_run = deepcopy(solution.u)
            else
                @test solution.u == first_run
            end
            for (row, (t, state)) in enumerate(zip(solution.t, solution.u))
                obs = Base.invokelatest(model.observe, state, t)
                for (variable, expected_rows) in pairs(oracles[name].variables)
                    actual = obs[String(variable)]
                    values = actual isa Number ? [actual] : vec([actual[reverse(index)...] for index in Iterators.product((1:n for n in reverse(size(actual)))...)])
                    expected = Float64.(expected_rows[row])
                    scale = [max(1., maximum(abs(expected_row[j]) for expected_row in expected_rows)) for j in eachindex(expected)]
                    @test length(values) == length(expected)
                    @test all(isfinite, values)
                    if haskey(oracles[name], :exact) && oracles[name].exact
                        @test reinterpret(UInt64, Float64.(values)) == reinterpret(UInt64, expected)
                    end
                    errors = abs.(values - expected)
                    limits = 1e-12 .* scale .+ 1e-9 .* abs.(expected)
                    first_bad = findfirst(errors .> limits)
                    first_bad === nothing || error("$(name), $(variable), time=$(t), cell=$(first_bad): Julia=$(values[first_bad]), Python=$(expected[first_bad]), tolerance=$(limits[first_bad])")
                end
            end
        end
        push!(results, Dict("fixture" => name, "pass" => true))
    catch error
        push!(results, Dict("fixture" => name, "pass" => false,
                           "error" => sprint(showerror, error, catch_backtrace())))
    end
end
write(ARGS[2], JSON3.write(Dict("pass" => !isempty(results) && all(item["pass"] for item in results), "results" => results)))
