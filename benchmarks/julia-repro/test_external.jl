using JSON3, OrdinaryDiffEqLowOrderRK, LinearAlgebra
LinearAlgebra.BLAS.set_num_threads(1)
directory = ARGS[1]
models = JSON3.read(read(joinpath(directory, "models.json"), String))
oracle = JSON3.read(read(joinpath(directory, "oracle.json"), String))
results = Any[]
for item in models
    name = String(item["name"])
    try
        m = Module(Symbol("external_", name))
        Base.include(m, String(item["path"]))
        labels = getfield(m, :_dim_labels)
        dims = String.(item["dims"])
        ranges = [1:length(labels[d]) for d in dims]
        cells = [Tuple(reverse(c)) for c in Iterators.product(reverse(ranges)...)]
        expected = oracle[name]
        comparisons = 0
        for (row, t) in enumerate(expected["queries"])
            for (column, cell) in enumerate(vec(cells))
                value = Base.invokelatest(m.x, cell..., Float64(t))
                wanted = expected["values"][row][column]
                if wanted === nothing
                    isnan(value) || error("RAW interpolation changed missing value")
                else
                    abs(value-Float64(wanted)) <= 1e-12 + 1e-12*abs(wanted) || error("Cell mismatch t=$t cell=$cell: $value != $wanted")
                end
                comparisons += 1
            end
        end
        if expected["stocks"] !== nothing
            solution = Base.invokelatest(m.run_model)
            for (i, t) in enumerate(solution.t)
                observation = Base.invokelatest(m.observe, solution.u[i], t)
                value = observation["stock"]
                wanted = Float64(expected["stocks"][i])
                abs(value-wanted) <= 1e-12 + 1e-12*abs(wanted) || error("Integrated stock mismatch t=$t: $value != $wanted")
            end
        end
        push!(results, Dict("fixture"=>name, "pass"=>true, "comparisons"=>comparisons))
    catch exception
        push!(results, Dict("fixture"=>name, "pass"=>false, "error"=>sprint(showerror, exception, catch_backtrace())))
    end
end
write(joinpath(directory, "results.json"), JSON3.write(Dict("pass"=>all(r["pass"] for r in results), "results"=>results)))
all(r["pass"] for r in results) || error("External input fixture failed")
