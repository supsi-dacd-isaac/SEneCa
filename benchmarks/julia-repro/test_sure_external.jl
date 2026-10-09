# Every external SURE input, every labelled cell, all annual timestamps.
using JSON3
VERSION == v"1.10.12" || error("Wrong Julia runtime")
Threads.nthreads() == 1 || error("External input comparison must use one thread")
directory = ARGS[1]
input_module = Module(:SUREExternal)
Base.include(input_module, joinpath(directory, "inputs.jl"))
records = JSON3.read(read(joinpath(directory, "oracle.json"), String))
mkpath(joinpath(directory, "julia"))
verified = []
for item in records
    identifier = String(item["identifier"])
    # Compare generated Julia input metadata with the independently loaded Python
    # oracle before evaluating anything; never infer axes from memory layout.
    spec = input_module._model_data["external"][identifier]
    collect(String.(spec["dimensions"])) == collect(String.(item["dimensions"])) || error("Dimension mismatch")
    for dim in String.(item["dimensions"])
        collect(String.(spec["coordinates"][dim])) == collect(String.(item["coordinates"][dim])) || error("Coordinate mismatch: $identifier/$dim")
    end
    dimensions = String.(item["dimensions"])
    ranges = [1:length(spec["coordinates"][dim]) for dim in dimensions]
    cells = [Tuple(reverse(c)) for c in Iterators.product(reverse(ranges)...)]
    func = getfield(input_module, Symbol(identifier))
    open(joinpath(directory, "julia", identifier * ".bin"), "w") do io
        for year in item["years"]
            for cell in vec(cells)
                value = Float64(Base.invokelatest(func, cell..., Float64(year)))
                (isfinite(value) || (isnan(value) && spec["interpolation"] == "raw")) || error("Unexpected nonfinite SURE input: $identifier")
                write(io, htol(reinterpret(UInt64, value)))
            end
        end
    end
    push!(verified, item)
end
write(joinpath(directory, "julia-metadata.json"), JSON3.write(verified))
