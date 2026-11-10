# Variabili che dipendono (anche attraverso stock e ritardi) dalle uscite di ALLOCATE BY PRIORITY.
# Uso: julia downstream.jl SURE.mdl out.txt
const SRC = joinpath(@__DIR__, "..", "src")
include(joinpath(SRC, "parser.jl")); include(joinpath(SRC, "model.jl"))
m = build_model(abspath(ARGS[1]))
users = Dict{String,Set{String}}()
for d in m.defs
    refs = Tuple{VRef,Vector{String}}[]
    for e in (d.expr, d.init, d.extra)
        e isa Node && collect_refs!(refs, e, String[])
    end
    for (r, _) in refs
        push!(get!(users, r.name, Set{String}()), d.var.name)
    end
end
seen = Set{String}(v.name for v in values(m.vars) if v.kind == :alloc)
queue = collect(seen)
while !isempty(queue)
    v = pop!(queue)
    for u in get(users, v, Set{String}())
        u in seen || (push!(seen, u); push!(queue, u))
    end
end
# le variabili nascoste prendono il nome del padre
names = sort([m.vars[v].display for v in seen if !m.vars[v].hidden])
write(abspath(ARGS[2]), join(names, "\n") * "\n")
println("variabili a valle dell'allocazione: $(length(names)) su $(count(v -> !v.hidden, values(m.vars)))")
