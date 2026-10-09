using JSON3
using LinearAlgebra
BLAS.set_num_threads(1)
VERSION == v"1.10.12" || error("Unexpected Julia version: $VERSION")
Threads.nthreads() == 1 || error("Single-threaded execution required")
Base.cumulative_compile_timing(true)

function execute(model_file, export_file, output_dir, iterations=1; cache=Dict{String,Module}())
    mkpath(output_dir)
    requested = JSON3.read(read(export_file, String))
    load_start = time_ns()
    load_compile_start = first(Base.cumulative_compile_time_ns())
    model = get!(cache, model_file) do
        m = Module(gensym(:Scenario))
        Base.include(m, model_file)
        m
    end
    for variable in requested, dimension in variable.dims
        model._dim_labels[String(dimension)] == String.(variable.coords[dimension]) || error("Coordinate mismatch: $dimension")
    end
    load_seconds = (time_ns() - load_start) / 1e9
    load_compile_seconds = (first(Base.cumulative_compile_time_ns()) - load_compile_start) / 1e9
    timings = []
    for iteration in 1:iterations
        target = iterations == 1 ? output_dir : joinpath(output_dir, string(iteration))
        mkpath(target)
        start = time_ns()
        initial = deepcopy(model.u0)
        initialize_seconds = (time_ns() - start) / 1e9
        start = time_ns()
        solve_compile_start = first(Base.cumulative_compile_time_ns())
        solution = Base.invokelatest(model.run_model; u0=initial)
        solve_seconds = (time_ns() - start) / 1e9
        solve_compile_seconds = (first(Base.cumulative_compile_time_ns()) - solve_compile_start) / 1e9
        all(isfinite, reduce(vcat, solution.u)) || error("Nonfinite state")
        start = time_ns()
        extraction_compile_start = first(Base.cumulative_compile_time_ns())
        streams = [open(joinpath(target, "v$(lpad(i-1, 4, '0')).bin"), "w") for i in eachindex(requested)]
        try
            for (time, state) in zip(solution.t, solution.u)
                observed = Base.invokelatest(model.observe, state, time)
                for (i, variable) in enumerate(requested)
                    value = observed[String(variable.julia_name)]
                    dims = [length(variable.coords[d]) for d in variable.dims]
                    if isempty(dims)
                        value isa Number || error("Expected scalar: $(variable.name)")
                        isfinite(value) || error("Nonfinite output: $(variable.name) at $time")
                        write(streams[i], Float64(value))
                    else
                        collect(size(value)) == dims || error("Shape mismatch: $(variable.name): $(size(value)) != $dims")
                        # Python product order: last coordinate varies fastest.
                        for reverse_index in Iterators.product((1:n for n in reverse(dims))...)
                            x = value[reverse(reverse_index)...]
                            isfinite(x) || error("Nonfinite output: $(variable.name) at $time")
                            write(streams[i], Float64(x))
                        end
                    end
                end
            end
        finally
            foreach(close, streams)
        end
        extraction_seconds = (time_ns() - start) / 1e9
        extraction_compile_seconds = (first(Base.cumulative_compile_time_ns()) - extraction_compile_start) / 1e9
        metadata = Dict("years" => solution.t, "byte_order" => "little", "float" => "Float64",
                        "load_seconds" => iteration == 1 ? load_seconds : 0.0,
                        "load_compilation_seconds" => iteration == 1 ? load_compile_seconds : 0.0,
                        "initialize_seconds" => initialize_seconds,
                        "solve_seconds" => solve_seconds, "extraction_seconds" => extraction_seconds,
                        "solve_compilation_seconds" => solve_compile_seconds,
                        "extraction_compilation_seconds" => extraction_compile_seconds,
                        "max_rss_bytes" => Sys.maxrss(), "iteration" => iteration)
        write(joinpath(target, "timing.json"), JSON3.write(metadata))
        push!(timings, metadata)
    end
    return timings
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    execute(abspath(ARGS[1]), abspath(ARGS[2]), abspath(ARGS[3]),
            length(ARGS) > 3 ? parse(Int, ARGS[4]) : 1)
end
