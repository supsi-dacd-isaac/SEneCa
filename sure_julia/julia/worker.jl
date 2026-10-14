using JSON3
using LinearAlgebra
BLAS.set_num_threads(1)
VERSION == v"1.10.12" || error("Julia 1.10.12 required")
Threads.nthreads() == 1 || error("One Julia thread per worker required")
Base.cumulative_compile_timing(true)
seconds_since(start) = (time_ns() - start) / 1e9

function execute(model, catalog, job)
    started = time_ns()
    compile_before = first(Base.cumulative_compile_time_ns())
    parameters = Base.invokelatest(model.parameters_from_dict, job.parameters)
    wanted = String.(job.outputs)
    length(unique(wanted)) == length(wanted) || error("Duplicate outputs")
    requested = [only(filter(x -> x.name == name, catalog)) for name in wanted]
    names = String[String(x.julia_name) for x in requested]
    start = time_ns()
    initial = Base.invokelatest(model.initial_state, parameters)
    initialize_seconds = seconds_since(start)
    before = copy(initial)
    start = time_ns()
    solution = Base.invokelatest(model.run_model, parameters; u0=initial)
    solve_seconds = seconds_since(start)
    isequal(initial, before) || error("Initial conditions mutated")
    solution.t == collect(2011.0:2050.0) || error("Incomplete years")
    all(u -> all(isfinite, u), solution.u) || error("Nonfinite state")
    target = String(job.directory)
    isdir(target) || error("Missing private result directory")
    streams = [open(joinpath(target, "v$(lpad(i-1, 4, '0')).bin"), "w") for i in eachindex(requested)]
    start = time_ns()
    try
        for (t, state) in zip(solution.t, solution.u)
            observed = Base.invokelatest(model.observe, state, t, names; parameters=parameters)
            for (i, item) in enumerate(requested)
                value = observed[String(item.julia_name)]
                dims = [length(item.coords[d]) for d in item.dims]
                if isempty(dims)
                    value isa Number && isfinite(value) || error("Invalid scalar $(item.name)")
                    write(streams[i], Float64(value))
                else
                    collect(size(value)) == dims || error("Shape mismatch $(item.name)")
                    all(isfinite, value) || error("Nonfinite output $(item.name)")
                    # Explicit axis reversal writes last original index fastest,
                    # matching the declared coordinate product in the export.
                    buffer = vec(permutedims(Array{Float64}(value), reverse(1:ndims(value))))
                    write(streams[i], buffer)
                end
            end
        end
    finally
        foreach(close, streams)
    end
    extraction_seconds = seconds_since(start)
    Dict("ok" => true, "id" => job.id, "years" => solution.t,
         "initialize_seconds" => initialize_seconds, "solve_seconds" => solve_seconds,
         "extraction_seconds" => extraction_seconds, "seconds" => seconds_since(started),
         "compilation_seconds" => (first(Base.cumulative_compile_time_ns()) - compile_before) / 1e9,
         "max_rss_bytes" => Sys.maxrss(), "module_id" => string(objectid(model)))
end

function main(model_file, export_file)
    started = time_ns()
    model = Module(:SURESession)
    catalog = JSON3.read(read(export_file, String))
    redirect_stdout(stderr) do
        Base.include(model, abspath(model_file))
    end
    for item in catalog, dim in item.dims
        model._dim_labels[String(dim)] == String.(item.coords[dim]) || error("Coordinate mismatch")
    end
    println(JSON3.write(Dict("ready" => true, "load_seconds" => seconds_since(started),
                            "module_id" => string(objectid(model))))); flush(stdout)
    for line in eachline(stdin)
        job = JSON3.read(line)
        try
            result = redirect_stdout(stderr) do
                execute(model, catalog, job)
            end
            println(JSON3.write(result))
        catch error
            showerror(stderr, error, catch_backtrace()); println(stderr)
            println(JSON3.write(Dict("ok" => false, "id" => job.id, "error" => sprint(showerror, error))))
        end
        flush(stdout)
    end
end
main(ARGS...)
