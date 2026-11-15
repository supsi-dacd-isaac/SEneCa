# Determinismo: le stesse simulazioni in serie (due volte) e in parallelo su thread
# devono dare risultati identici bit per bit.
# Uso: julia -t 4 --project=sure_native determinism.jl GENERATED.jl INPUTS SCENARIOS.json CALIBRATION.out OUT.json
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl")); include(joinpath(SRC, "runtime.jl")); using .SureRuntime
gen, inputs, scenfile, calib, outfile = abspath.(ARGS[1:5])
include(gen); const G = SUREGenerated
include(joinpath(SRC, "simulate.jl"))
using JSON3
spec = JSON3.read(read(scenfile, String))
ids = ["base", "all_min", "oat_04_max", "lhs_00", "lhs_07", "lhs_15", "lhs_29", "oat_10_min"]
scs = [only(s for s in spec.scenarios if s.id == id) for id in ids]
ch = read_changes(calib)
run(sc) = simulate(G, inputs; changes=ch, setvals=[parse_key(String(k)) => Float64(v) for (k, v) in pairs(sc.settings)],
                   final_time=Float64(sc.final_time))[2]
serial1 = [run(sc) for sc in scs]
serial2 = [run(sc) for sc in scs]
par = Vector{Matrix{Float64}}(undef, length(scs))
Threads.@threads for i in eachindex(scs)
    par[i] = run(scs[i])
end
same12 = [isequal(serial1[i], serial2[i]) for i in eachindex(scs)]
samepar = [isequal(serial1[i], par[i]) for i in eachindex(scs)]
res = Dict("threads" => Threads.nthreads(), "scenarios" => ids,
           "serial_repeat_identical" => same12, "parallel_identical" => samepar)
open(outfile, "w") do io; JSON3.pretty(io, res); end
println(res)
