using JSON3
using LinearAlgebra
BLAS.set_num_threads(1)
VERSION == v"1.10.12" || error("Pinned Julia required")
Threads.nthreads() == 1 || error("Single thread required")
Base.cumulative_compile_timing(true)

# Awake time, the same clock as pinned Python. The caller additionally guards
# against suspend because Julia's internal JIT counter includes suspension.
const timebase = Ref{Tuple{UInt32,UInt32}}((0, 0))
ccall(:mach_timebase_info, Cint, (Ref{Tuple{UInt32,UInt32}},), timebase) == 0 || error("Clock unavailable")
awake_ns() = UInt64(UInt128(ccall(:mach_absolute_time, UInt64, ())) * timebase[][1] ÷ timebase[][2])
seconds_since(start) = (awake_ns() - start) / 1e9

function main(model_file, export_file, jobs_file, output_dir)
    mkpath(output_dir)
    requested = JSON3.read(read(export_file, String))
    names = String[String(item.julia_name) for item in requested]
    load_start = awake_ns()
    compile_start = first(Base.cumulative_compile_time_ns())
    model = Module(:SURESession)
    Base.include(model, abspath(model_file))
    load = Dict("seconds" => seconds_since(load_start),
                "compilation_seconds" => (first(Base.cumulative_compile_time_ns()) - compile_start) / 1e9,
                "module" => string(model), "module_id" => string(objectid(model)), "loads" => 1)
    write(joinpath(output_dir, "load.json"), JSON3.write(load))
    for item in requested, dim in item.dims
        model._dim_labels[String(dim)] == String.(item.coords[dim]) || error("Coordinate mismatch")
    end
    jobs = JSON3.read(read(jobs_file, String))
    for job in jobs
        target = joinpath(output_dir, String(job.id))
        ispath(target) && error("Existing request result: $target")
        mkpath(target)
        println("Starting ", job.id); flush(stdout)
        compiled_before = first(Base.cumulative_compile_time_ns())
        request_start = awake_ns()
        parameters = Base.invokelatest(model.parameters_from_dict, job.parameters)
        configuration_seconds = seconds_since(request_start)
        start = awake_ns()
        initial = Base.invokelatest(model.initial_state, parameters)
        initialization_seconds = seconds_since(start)
        initial_before = copy(initial)
        start = awake_ns()
        solution = Base.invokelatest(model.run_model, parameters; u0=initial)
        solve_seconds = seconds_since(start)
        isequal(initial_before, initial) || error("Simulation mutated caller's initial state")
        solution.t == collect(2011.0:2050.0) || error("Incomplete years")
        all(isfinite, reduce(vcat, solution.u)) || error("Nonfinite state")
        start = awake_ns()
        streams = [open(joinpath(target, "v$(lpad(i-1, 4, '0')).bin"), "w") for i in eachindex(requested)]
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
                        collect(size(value)) == dims || error("Invalid shape $(item.name)")
                        for index in Iterators.product((1:n for n in reverse(dims))...)
                            v = value[reverse(index)...]
                            isfinite(v) || error("Nonfinite $(item.name)")
                            write(streams[i], Float64(v))
                        end
                    end
                end
            end
        finally
            foreach(close, streams)
        end
        extraction_seconds = seconds_since(start)
        timing = Dict("years" => solution.t, "byte_order" => "little", "float" => "Float64",
                      "configuration_seconds" => configuration_seconds,
                      "initialize_seconds" => initialization_seconds, "solve_seconds" => solve_seconds,
                      "extraction_seconds" => extraction_seconds,
                      "simulation_and_capture_seconds" => configuration_seconds + initialization_seconds + solve_seconds + extraction_seconds,
                      "request_wall_seconds" => seconds_since(request_start),
                      "compilation_seconds" => (first(Base.cumulative_compile_time_ns()) - compiled_before) / 1e9,
                      "max_rss_bytes" => Sys.maxrss(), "module_id" => string(objectid(model)),
                      "parameter_type" => string(typeof(parameters)), "parameters" => job.parameters,
                      "initial_state_preserved" => true)
        write(joinpath(target, "timing.json"), JSON3.write(timing))
        println("Completed ", job.id, ": ", timing["simulation_and_capture_seconds"], "s, JIT ", timing["compilation_seconds"], "s"); flush(stdout)
    end
end

main(ARGS...)
