# Rappresentazione intermedia: dimensioni, variabili, domini delle definizioni,
# legami dei subscript e grafo delle dipendenze.

struct Dim
    name::String
    elements::Vector{String}
    index::Dict{String,Int}
end
Dim(name, els) = Dim(name, els, Dict(e => i for (i, e) in enumerate(els)))

mutable struct Var
    name::String
    display::String
    kind::Symbol                 # :aux :const :stock :data :lookup :smooth :delay :alloc
    dims::Vector{Dim}
    shape::Vector{Int}
    defs::Vector{Any}
    offset::Int                  # posizione nel vettore di stato (1-based, prima cella)
    hidden::Bool
end
ncells(v::Var) = isempty(v.shape) ? 1 : prod(v.shape)

mutable struct Def
    var::Var
    eq::Equation
    lhs::Vector{Sub}             # subscript del membro sinistro (nascosti: quelli del padre)
    cells::Matrix{Int}           # ndims × ncelle, indici nelle dimensioni della variabile
    kind::Symbol                 # come Var.kind
    expr::Node                   # :aux/:const espressione; :stock tasso; :smooth ingresso
    init::Node                   # :stock / :delay valore iniziale
    extra::Node                  # :smooth tempo; :delay ritardo
    id::Int
end

struct Model
    dims::Dict{String,Dim}
    vars::Dict{String,Var}
    defs::Vector{Def}
    order::Vector{String}        # ordine di dichiarazione delle variabili
    control::Dict{String,Float64}
end

struct ModelError <: Exception
    msg::String
end
Base.showerror(io::IO, e::ModelError) = print(io, e.msg)
merr(d, msg) = throw(ModelError("riga $(d isa Def ? d.eq.line : d.line) ($(d isa Def ? d.var.display : d.name)): $msg"))

# ------------------------------------------------------------------ costruzione

function element_set(dims::Dict{String,Dim}, s::Sub)
    haskey(dims, s.name) && return dims[s.name].elements
    return [s.name]
end

"""Dimensione di una posizione: il range dichiarato più piccolo che contiene tutti gli elementi usati."""
function parent_dim(dims::Dict{String,Dim}, used::Vector{String}, declared::Vector{String}, ctx)
    best = nothing
    # preferenza ai range scritti nelle definizioni, poi a tutti i range
    for pool in (declared, collect(keys(dims)))
        for r in pool
            haskey(dims, r) || continue
            d = dims[r]
            all(e -> haskey(d.index, e), used) || continue
            if best === nothing || length(d.elements) < length(best.elements) ||
               (length(d.elements) == length(best.elements) && d.name < best.name)
                best = d
            end
        end
        best === nothing || break
    end
    best === nothing && throw(ModelError("$ctx: nessun range contiene gli elementi $(used)"))
    # se un range più grande contiene il migliore e compare tra i dichiarati, usa il più grande
    for r in declared
        haskey(dims, r) || continue
        d = dims[r]
        if length(d.elements) > length(best.elements) && all(e -> haskey(d.index, e), best.elements)
            best = d
        end
    end
    return best
end

function display_names(path)
    # nome con le maiuscole originali, dalla prima occorrenza nel membro sinistro
    names = Dict{String,String}()
    for b in read_blocks(path)
        m = match(r"^\s*\"?([^\[\(=:~\"]+)"s, b.eq)
        m === nothing && continue
        raw = join(split(m[1]), ' ')
        get!(names, normname(raw), raw)
    end
    names
end

function build_model(path::AbstractString)
    eqs = parse_model(path)
    disp = display_names(path)
    dims = Dict{String,Dim}()
    for e in eqs
        e.kind == :range || continue
        dims[e.name] = Dim(e.name, e.elements)
    end
    for (r, d) in dims
        haskey(dims, r) && any(el -> haskey(dims, el), d.elements) &&
            throw(ModelError("il range $r ha elementi che sono anche nomi di range"))
    end
    bynames = Dict{String,Vector{Equation}}()
    order = String[]
    for e in eqs
        e.kind == :range && continue
        haskey(bynames, e.name) || push!(order, e.name)
        push!(get!(bynames, e.name, Equation[]), e)
    end
    vars = Dict{String,Var}()
    defs = Def[]
    control = Dict{String,Float64}()
    for name in order
        list = bynames[name]
        nd = length(list[1].subs)
        all(e -> length(e.subs) == nd, list) || merr(list[1], "definizioni con numero di subscript diverso")
        kinds = unique(e.kind for e in list)
        length(kinds) == 1 || merr(list[1], "definizioni di tipo diverso")
        vdims = Dim[]
        for k in 1:nd
            used = unique(vcat([element_set(dims, e.subs[k]) for e in list]...))
            declared = unique([e.subs[k].name for e in list if haskey(dims, e.subs[k].name)])
            push!(vdims, parent_dim(dims, used, declared, "$(disp[name]) posizione $k"))
        end
        shape = [length(d.elements) for d in vdims]
        v = Var(name, get(disp, name, name), :aux, vdims, shape, Def[], 0, false)
        vars[name] = v
        covered = zeros(Int, isempty(shape) ? 1 : prod(shape))
        for e in list
            sets = [[vdims[k].index[x] for x in element_set(dims, e.subs[k])] for k in 1:nd]
            excl = Set{Vector{Int}}()
            for ex in e.except
                length(ex) == nd || merr(e, ":EXCEPT: con numero di subscript diverso")
                esets = [[vdims[k].index[x] for x in element_set(dims, ex[k])] for k in 1:nd]
                for c in Iterators.product(esets...)
                    push!(excl, collect(c))
                end
            end
            cells = Vector{Int}[]
            if nd == 0
                push!(cells, Int[])
            else
                # ordine column-major come Julia
                for c in Iterators.product(sets...)
                    cv = collect(c)
                    cv in excl || push!(cells, cv)
                end
            end
            C = nd == 0 ? zeros(Int, 0, 1) : reduce(hcat, cells)
            d = Def(v, e, e.subs, C, :aux, e.rhs, Num(NaN), Num(NaN), 0)
            classify!(d, dims)
            push!(v.defs, d)
            for c in eachcol(C)
                covered[linear(v, c)] += 1
            end
        end
        if any(>(1), covered)
            merr(list[1], "celle definite più volte")
        end
        if any(==(0), covered)
            merr(list[1], "$(count(==(0), covered)) celle senza definizione")
        end
        kinds_def = unique(d.kind for d in v.defs)
        if length(kinds_def) > 1
            # costanti e ausiliarie insieme: la variabile resta ausiliaria
            if Set(kinds_def) ⊆ Set([:aux, :const])
                for d in v.defs
                    d.kind = d.kind == :const ? :const : :aux
                end
                v.kind = :aux
            else
                merr(list[1], "definizioni di natura diversa: $(kinds_def)")
            end
        else
            v.kind = kinds_def[1]
        end
        append!(defs, v.defs)
    end
    for (k, d) in enumerate(defs)
        d.id = k
    end
    haskey(vars, "time") && throw(ModelError("Time ridefinita nel modello"))
    vars["time"] = Var("time", "Time", :time, Dim[], Int[], Def[], 0, true)
    m = Model(dims, vars, defs, order, control)
    lift_stateful!(m)
    return m
end

function linear(v::Var, c::AbstractVector{<:Integer})
    isempty(c) && return 1
    l, s = 1, 1
    for k in eachindex(c)
        l += (c[k] - 1) * s
        s *= v.shape[k]
    end
    l
end

function classify!(d::Def, dims)
    e = d.eq
    r = e.rhs
    if e.kind == :lookup
        d.kind = :lookup
    elseif e.kind == :data
        d.kind = :data
        (r isa Call && r.f == "get vdf data") || merr(d, "dato senza GET VDF DATA")
    elseif r isa NumArray || r isa Num
        d.kind = :const
    elseif r isa Call && r.f == "integ"
        length(r.args) == 2 || merr(d, "INTEG con $(length(r.args)) argomenti")
        d.kind = :stock; d.expr = r.args[1]; d.init = r.args[2]
    elseif r isa Call && r.f == "smooth"
        length(r.args) == 2 || merr(d, "SMOOTH con $(length(r.args)) argomenti")
        d.kind = :smooth; d.expr = r.args[1]; d.extra = r.args[2]
    elseif r isa Call && r.f == "delay fixed"
        length(r.args) == 3 || merr(d, "DELAY FIXED con $(length(r.args)) argomenti")
        d.kind = :delay; d.expr = r.args[1]; d.extra = r.args[2]; d.init = r.args[3]
    elseif r isa Call && r.f == "allocate by priority"
        d.kind = :alloc
    elseif is_constant_expr(r)
        d.kind = :const
    else
        d.kind = :aux
    end
    if d.kind == :const && r isa Op
        # espressione numerica pura (es. -0.5): resta costante
    end
end

is_constant_expr(n::Num) = true
is_constant_expr(n::Op) = all(is_constant_expr, n.args)
is_constant_expr(n::Node) = false

"""Sposta SMOOTH e DELAY FIXED annidati in variabili nascoste."""
function lift_stateful!(m::Model)
    counter = Ref(0)
    newdefs = Def[]
    function lift(n::Node, d::Def)
        if n isa Call
            args = Node[lift(a, d) for a in n.args]
            if n.f in ("smooth", "delay fixed", "integ")
                n.f == "integ" && merr(d, "INTEG annidata")
                counter[] += 1
                hname = "__$(replace(n.f, ' ' => '_'))_$(counter[])"
                hv = Var(hname, hname, n.f == "smooth" ? :smooth : :delay, d.var.dims, d.var.shape,
                         Def[], 0, true)
                he = Equation(d.eq.line, hname, d.eq.subs, d.eq.except, :eq, :none,
                              Call(n.f, args), String[], "")
                hd = Def(hv, he, d.lhs, d.cells, :aux, Call(n.f, args), Num(NaN), Num(NaN), 0)
                classify!(hd, m.dims)
                push!(hv.defs, hd)
                m.vars[hname] = hv
                push!(m.order, hname)
                push!(newdefs, hd)
                return VRef(hname, d.lhs)
            end
            return Call(n.f, args)
        elseif n isa Op
            return Op(n.op, Node[lift(a, d) for a in n.args])
        end
        return n
    end
    for d in m.defs
        if d.kind in (:smooth, :delay, :stock)
            d.expr = lift(d.expr, d)
            d.init isa Num || (d.init = lift(d.init, d))
        elseif d.kind in (:aux, :alloc)
            d.expr = lift(d.expr, d)
        end
    end
    for hd in newdefs
        push!(m.defs, hd)
        hd.id = length(m.defs)
    end
end

# ------------------------------------------------------------------ legami dei subscript

# Un indice in una posizione della variabile riferita:
#   (:const, k)            elemento fisso
#   (:lhs, p, map)         indice della posizione p del membro sinistro, tradotto con map
#   (:bang, r, map)        indice di riduzione sul range r
struct Bind
    kind::Symbol
    k::Int
    p::Int
    range::String
    map::Vector{Int}
end

"""Legame dei subscript di un riferimento `ref` dentro la definizione `d`."""
function bind_ref(m::Model, d::Def, ref::VRef, bangs::Vector{String})
    haskey(m.vars, ref.name) || merr(d, "variabile non definita: $(ref.name)")
    w = m.vars[ref.name]
    length(ref.subs) == length(w.dims) ||
        merr(d, "$(w.display) ha $(length(w.dims)) subscript, riferita con $(length(ref.subs))")
    binds = Bind[]
    for (j, s) in enumerate(ref.subs)
        D = w.dims[j]
        if s.bang || s.name in bangs
            haskey(m.dims, s.name) || merr(d, "$(s.name)! non è un range")
            R = m.dims[s.name]
            mp = [get(D.index, e, 0) for e in R.elements]
            any(==(0), mp) && merr(d, "$(s.name) non è contenuto in $(D.name) di $(w.display)")
            push!(binds, Bind(:bang, 0, 0, s.name, mp))
        elseif !haskey(m.dims, s.name)
            haskey(D.index, s.name) || merr(d, "elemento $(s.name) non in $(D.name) di $(w.display)")
            push!(binds, Bind(:const, D.index[s.name], 0, "", Int[]))
        else
            R = m.dims[s.name]
            p = lhs_position(m, d, R)
            p == 0 && merr(d, "subscript $(s.name) di $(w.display) non legato al membro sinistro")
            V = d.var.dims[p]
            mp = Int[]
            for e in V.elements
                push!(mp, haskey(R.index, e) ? get(D.index, e, 0) : 0)
            end
            # le celle effettivamente percorse devono avere un indice valido
            for c in eachcol(d.cells)
                mp[c[p]] == 0 && merr(d, "elemento $(V.elements[c[p]]) non disponibile in $(s.name) per $(w.display)")
            end
            push!(binds, Bind(:lhs, 0, p, s.name, mp))
        end
    end
    return w, binds
end

function lhs_position(m::Model, d::Def, R::Dim)
    # 1) stesso nome nel membro sinistro
    for (p, s) in enumerate(d.lhs)
        s.name == R.name && return p
    end
    # 2) range del membro sinistro della stessa famiglia (elementi in comune)
    cands = Int[]
    for (p, s) in enumerate(d.lhs)
        if haskey(m.dims, s.name)
            L = m.dims[s.name]
            any(e -> haskey(R.index, e), L.elements) && push!(cands, p)
        end
    end
    length(cands) == 1 && return cands[1]
    length(cands) > 1 && merr(d, "subscript $(R.name) ambiguo")
    # 3) elemento fisso del membro sinistro contenuto nel range
    for (p, s) in enumerate(d.lhs)
        !haskey(m.dims, s.name) && haskey(R.index, s.name) && return p
    end
    return 0
end

# ------------------------------------------------------------------ dipendenze

"""Riferimenti istantanei di un'espressione (ignora gli argomenti delle funzioni con stato)."""
function collect_refs!(out::Vector{Tuple{VRef,Vector{String}}}, n::Node, bangs::Vector{String})
    if n isa VRef
        push!(out, (n, bangs))
    elseif n isa Call
        if n.f in ("sum", "vmin", "vmax")
            nb = copy(bangs)
            find_bangs!(nb, n.args[1])
            for a in n.args
                collect_refs!(out, a, nb)
            end
        elseif n.f == "elmcount"
            # costante
        else
            for a in n.args
                collect_refs!(out, a, bangs)
            end
        end
    elseif n isa Op
        for a in n.args
            collect_refs!(out, a, bangs)
        end
    end
    out
end

function find_bangs!(nb::Vector{String}, n::Node)
    if n isa VRef
        for s in n.subs
            s.bang && !(s.name in nb) && push!(nb, s.name)
        end
    elseif n isa Call
        n.f in ("sum", "vmin", "vmax") && return  # riduzioni annidate hanno i propri indici
        foreach(a -> find_bangs!(nb, a), n.args)
    elseif n isa Op
        foreach(a -> find_bangs!(nb, a), n.args)
    end
end

"""Celle lineari di `w` lette dalla definizione `d` attraverso i legami `binds`."""
function referenced_cells(m::Model, d::Def, w::Var, binds::Vector{Bind})
    out = Set{Int}()
    nd = length(binds)
    if nd == 0
        push!(out, 1)
        return out
    end
    for c in eachcol(d.cells)
        choices = Vector{Vector{Int}}(undef, nd)
        for (j, b) in enumerate(binds)
            choices[j] = b.kind == :const ? [b.k] : b.kind == :lhs ? [b.map[c[b.p]]] : b.map
        end
        for t in Iterators.product(choices...)
            push!(out, linear(w, collect(t)))
        end
    end
    out
end

def_cells(d::Def) = Set(linear(d.var, c) for c in eachcol(d.cells))

"""Espressioni valutate da una definizione in una fase (:init o :step)."""
function phase_exprs(d::Def, phase::Symbol)
    k = d.kind
    if phase == :init
        k == :stock && return Node[d.init]
        k == :smooth && return Node[d.expr]
        k == :delay && return Node[d.init, d.extra]
        k in (:aux, :const, :alloc) && return Node[d.expr]
        return Node[]
    else
        k in (:aux, :alloc) && return Node[d.expr]
        return Node[]   # stati e costanti non hanno dipendenze nel passo
    end
end

"""Ordina le definizioni di una fase; le variabili con stato sono sorgenti nel passo."""
function order_defs(m::Model, phase::Symbol)
    nodes = phase == :init ? [d for d in m.defs if d.kind != :lookup && d.kind != :data] :
                             [d for d in m.defs if d.kind in (:aux, :alloc)]
    pos = Dict(d.id => i for (i, d) in enumerate(nodes))
    # definizioni di ogni variabile con le loro celle
    cellsets = Dict(d.id => def_cells(d) for d in m.defs)
    deps = [Int[] for _ in nodes]
    for (i, d) in enumerate(nodes)
        refs = Tuple{VRef,Vector{String}}[]
        for e in phase_exprs(d, phase)
            collect_refs!(refs, e, String[])
        end
        for (r, bangs) in refs
            haskey(m.vars, r.name) || merr(d, "variabile non definita: $(r.name)")
            w = m.vars[r.name]
            w.kind in (:lookup, :data, :time) && continue
            phase == :step && !(w.kind in (:aux, :alloc)) && continue
            _, binds = bind_ref(m, d, r, bangs)
            cells = referenced_cells(m, d, w, binds)
            for wd in w.defs
                haskey(pos, wd.id) || continue
                isempty(intersect(cells, cellsets[wd.id])) && continue
                push!(deps[i], pos[wd.id])
            end
        end
    end
    return toposort(nodes, deps, m)
end

function toposort(nodes, deps, m)
    n = length(nodes)
    state = zeros(Int8, n)
    out = eltype(nodes)[]
    cyc = Vector{Int}[]
    # DFS iterativa con rilevazione dei cicli
    for s in 1:n
        state[s] == 0 || continue
        stack = [(s, 1)]
        path = [s]
        state[s] = 1
        while !isempty(stack)
            v, k = stack[end]
            if k <= length(deps[v])
                stack[end] = (v, k + 1)
                u = deps[v][k]
                if state[u] == 0
                    state[u] = 1
                    push!(stack, (u, 1)); push!(path, u)
                elseif state[u] == 1
                    if u == v
                        push!(cyc, [v])
                    else
                        i = findlast(==(u), path)
                        push!(cyc, path[i:end])
                    end
                end
            else
                pop!(stack); pop!(path)
                state[v] = 2
                push!(out, nodes[v])
            end
        end
    end
    return out, [[nodes[i] for i in c] for c in cyc]
end
