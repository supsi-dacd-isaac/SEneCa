using JSON3
directory = ARGS[1]
oracles = JSON3.read(read(joinpath(directory, "oracle.json"), String))
results = []
for item in JSON3.read(read(joinpath(directory, "models.json"), String))
    name = String(item["name"])
    try
        m = Module(gensym(:Indexing))
        Base.include(m, String(item["path"]))
        solution = Base.invokelatest(m.run_model)
        solution.t == [0., 1., 2.] || error("Truncated fixture")
        count = 0
        for (i, t) in enumerate(solution.t)
            observation = Base.invokelatest(m.observe, solution.u[i], t)
            for record in oracles[name]
                actual = observation[String(record["identifier"])]
                dims = String.(record["dimensions"])
                for dim in dims
                    String.(record["coordinates"][dim]) == m._dim_labels[dim] || error("Coordinate order changed")
                end
                values = actual isa Real ? [actual] : vec([actual[reverse(cell)...] for cell in Iterators.product((1:n for n in reverse(size(actual)))...)])
                expected = Float64.(record["values"][i])
                length(values) == length(expected) || error("Shape mismatch")
                all(abs.(values .- expected) .<= 1e-12 .+ 1e-12 .* abs.(expected)) || error("$(record["name"]) differs at t=$t; first=$(findfirst(abs.(values .- expected) .> 1e-12 .+ 1e-12 .* abs.(expected)))")
                count += length(expected)
            end
        end
        push!(results, Dict("fixture"=>name, "pass"=>true, "comparisons"=>count))
    catch exception
        push!(results, Dict("fixture"=>name, "pass"=>false, "error"=>sprint(showerror, exception, catch_backtrace())))
    end
end
write(joinpath(directory, "results.json"), JSON3.write(Dict("pass"=>all(r["pass"] for r in results), "results"=>results)))
all(r["pass"] for r in results) || error("Indexing fixtures failed")
