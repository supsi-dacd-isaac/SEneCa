# Uso: julia --project=sure_native sure_native/scripts/translate.jl SURE.mdl out.jl
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl"))
include(joinpath(SRC, "model.jl"))
include(joinpath(SRC, "codegen.jl"))

mdl, out = ARGS[1], ARGS[2]
m = build_model(mdl)
code = generate(m)
write(out, code)
println("scritto $out: $(count(==('\n'), code)) righe, $(m.defs |> length) definizioni")
