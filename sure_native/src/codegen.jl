# Generatore del modulo Julia a partire dalla rappresentazione intermedia.

mutable struct Gen
    m::Model
    io::IOBuffer
    nx::Int                      # celle nel vettore di stato
    nr::Int                      # celle nel vettore dei tassi
    roff::Dict{Int,Int}          # def.id => offset nei tassi
    ndelay::Int
    delayid::Dict{Int,Int}
    ndata::Int
    dataid::Dict{Int,Int}
    datadefs::Vector{Any}
    tmp::Int
end

# Vensim memorizza gli ingressi numerici (costanti, numeri nelle equazioni, lookup,
# dati e modifiche da file) in Float32 e calcola in Float64.
input_value(v::Float64) = isfinite(v) ? Float64(Float32(v)) : v

function fmtnum(v::Float64)
    isnan(v) && return "NaN"
    isinf(v) && return v > 0 ? "Inf" : "-Inf"
    return repr(v)
end
litnum(v::Float64) = fmtnum(input_value(v))

tuplestr(v) = "(" * join(string.(v), ",") * (length(v) == 1 ? ",)" : ")")
ftuplestr(v) = "(" * join(litnum.(Float64.(v)), ",") * (length(v) == 1 ? ",)" : ")")

struct Ctx
    d::Def
    bangs::Vector{Pair{String,String}}   # range => variabile di ciclo
end

newtmp!(g::Gen, base="v") = (g.tmp += 1; "$(base)$(g.tmp)")

function index_expr(g::Gen, ctx::Ctx, w::Var, binds::Vector{Bind})
    isempty(binds) && return string(w.offset)
    terms = String[]
    stride = 1
    for (j, b) in enumerate(binds)
        if b.kind == :const
            idx = "$(b.k)"
        elseif b.kind == :lhs
            V = ctx.d.var.dims[b.p]
            ident = all(k -> b.map[k] == k || b.map[k] == 0, eachindex(b.map)) &&
                    length(b.map) <= w.shape[j]
            idx = ident ? "i$(b.p)" : "$(tuplestr(b.map))[i$(b.p)]"
        else
            lv = ""
            for (r, v) in ctx.bangs
                r == b.range && (lv = v)
            end
            lv == "" && merr(ctx.d, "indice di riduzione $(b.range) senza SUM")
            ident = b.map == collect(1:length(b.map))
            idx = ident ? lv : "$(tuplestr(b.map))[$lv]"
        end
        stride == 1 ? push!(terms, "($idx - 1)") : push!(terms, "$stride*($idx - 1)")
        stride *= w.shape[j]
    end
    return "$(w.offset) + " * join(terms, " + ")
end

function gen(g::Gen, n::Num, ctx::Ctx)
    litnum(n.v)
end

function gen(g::Gen, n::VRef, ctx::Ctx)
    n.name == "time" && return "t"
    haskey(g.m.vars, n.name) || merr(ctx.d, "variabile non definita: $(n.name)")
    w = g.m.vars[n.name]
    w.kind == :lookup && merr(ctx.d, "lookup $(w.display) usato senza argomento")
    bangs = [r for (r, _) in ctx.bangs]
    _, binds = bind_ref(g.m, ctx.d, n, bangs)
    return "x[" * index_expr(g, ctx, w, binds) * "]"
end

const ARITH = Dict(:+ => "+", :- => "-", :* => "*", :/ => "/")
const CMPS = Dict(:eq => "==", :ne => "!=", :lt => "<", :gt => ">", :le => "<=", :ge => ">=")

function gen(g::Gen, n::Op, ctx::Ctx)
    a = [gen(g, x, ctx) for x in n.args]
    if haskey(ARITH, n.op)
        return "($(a[1]) $(ARITH[n.op]) $(a[2]))"
    elseif n.op == :^
        return "vpow($(a[1]), $(a[2]))"
    elseif n.op == :neg
        return "(-$(a[1]))"
    elseif haskey(CMPS, n.op)
        return "b2f($(a[1]) $(CMPS[n.op]) $(a[2]))"
    elseif n.op == :and
        return "b2f(($(a[1]) != 0.0) & ($(a[2]) != 0.0))"
    elseif n.op == :or
        return "b2f(($(a[1]) != 0.0) | ($(a[2]) != 0.0))"
    elseif n.op == :not
        return "b2f($(a[1]) == 0.0)"
    end
    merr(ctx.d, "operatore $(n.op) non supportato")
end

function gen(g::Gen, n::Call, ctx::Ctx)
    f = n.f
    A() = [gen(g, x, ctx) for x in n.args]
    nargs(k) = length(n.args) == k || merr(ctx.d, "$f con $(length(n.args)) argomenti")
    if f == "if then else"
        nargs(3); a = A()
        return "(($(a[1])) != 0.0 ? ($(a[2])) : ($(a[3])))"
    elseif f in ("max", "min")
        nargs(2); a = A()
        return "$f($(a[1]), $(a[2]))"
    elseif f == "exp"
        nargs(1); return "exp($(A()[1]))"
    elseif f == "abs"
        nargs(1); return "abs($(A()[1]))"
    elseif f == "ln"
        nargs(1); return "vln($(A()[1]))"
    elseif f == "log"
        nargs(2); a = A(); return "vlog($(a[1]), $(a[2]))"
    elseif f == "zidz"
        nargs(2); a = A(); return "zidz($(a[1]), $(a[2]))"
    elseif f == "xidz"
        nargs(3); a = A(); return "xidz($(a[1]), $(a[2]), $(a[3]))"
    elseif f == "gamma ln"
        nargs(1); return "vgammaln($(A()[1]))"
    elseif f == "elmcount"
        nargs(1)
        r = n.args[1]
        (r isa VRef && haskey(g.m.dims, r.name)) || merr(ctx.d, "ELMCOUNT senza range")
        return fmtnum(Float64(length(g.m.dims[r.name].elements)))
    elseif f in ("sum", "vmin", "vmax")
        nargs(1)
        nb = String[]
        find_bangs!(nb, n.args[1])
        isempty(nb) && merr(ctx.d, "$f senza indice di riduzione")
        bangs = copy(ctx.bangs)
        loops = String[]
        for r in nb
            lv = newtmp!(g, "b")
            push!(bangs, r => lv)
            push!(loops, "$lv in 1:$(length(g.m.dims[r].elements))")
        end
        body = gen(g, n.args[1], Ctx(ctx.d, bangs))
        acc = newtmp!(g, "acc")
        init, upd = f == "sum" ? ("0.0", "$acc += $body") :
                    f == "vmin" ? ("Inf", "$acc = min($acc, $body)") : ("-Inf", "$acc = max($acc, $body)")
        return "(let $acc = $init; for $(join(loops, ", ")); $upd; end; $acc end)"
    elseif f == "with lookup"
        tab = n.args[2]::LookupTable
        return "lkp($(ftuplestr(tab.xs)), $(ftuplestr(tab.ys)), $(gen(g, n.args[1], ctx)))"
    elseif haskey(g.m.vars, f) && g.m.vars[f].kind == :lookup
        nargs(1)
        tab = g.m.vars[f].defs[1].expr::LookupTable
        return "lkp($(ftuplestr(tab.xs)), $(ftuplestr(tab.ys)), $(gen(g, n.args[1], ctx)))"
    end
    merr(ctx.d, "funzione non supportata: $f")
end

gen(g::Gen, n::Node, ctx::Ctx) = merr(ctx.d, "nodo non supportato: $(typeof(n))")

# ------------------------------------------------------------------ definizioni

function lhs_index(d::Def)
    v = d.var
    isempty(v.shape) && return string(v.offset)
    terms = String[]
    stride = 1
    for p in eachindex(v.shape)
        push!(terms, stride == 1 ? "(i$p - 1)" : "$stride*(i$p - 1)")
        stride *= v.shape[p]
    end
    "$(v.offset) + " * join(terms, " + ")
end

function loop_head(io, d::Def)
    nd = size(d.cells, 1)
    println(io, "    @inbounds for c in 1:$(size(d.cells, 2))")
    for p in 1:nd
        println(io, "        i$p = C$(d.id)[$p, c]")
    end
end

function emit_cells(g::Gen, d::Def)
    C = d.cells
    if size(C, 1) > 0
        println(g.io, "const C$(d.id) = reshape(Int32[", join(vec(C), ","), "], $(size(C,1)), $(size(C,2)))")
    end
end

header(d::Def) = "# $(d.var.display) — riga $(d.eq.line) ($(d.kind))"

function numarray_values(g::Gen, d::Def)
    vals = (d.expr::NumArray).vals
    isempty(d.eq.except) || merr(d, "lista di costanti con :EXCEPT:")
    sets = [[d.var.dims[k].index[x] for x in element_set(g.m.dims, d.lhs[k])] for k in eachindex(d.lhs)]
    n = isempty(sets) ? 1 : prod(length.(sets))
    length(vals) == n || merr(d, "$(length(vals)) valori per $n celle")
    out = Float64[]
    for c in eachcol(d.cells)
        # ordine riga per riga: l'ultimo subscript varia più velocemente
        pos = 0
        for k in eachindex(sets)
            pos = pos * length(sets[k]) + (findfirst(==(c[k]), sets[k]) - 1)
        end
        push!(out, vals[pos+1])
    end
    out
end

function emit_value_def(g::Gen, d::Def, fname::String, expr::Node)
    io = g.io
    println(io, header(d))
    println(io, "function $fname(x::Vector{Float64}, t::Float64, k::Int)")
    if expr isa NumArray
        vals = numarray_values(g, d)
        println(io, "    vals = $(ftuplestr(vals))")
        loop_head(io, d)
        println(io, "        x[$(lhs_index(d))] = vals[c]")
    else
        rhs = gen(g, expr, Ctx(d, Pair{String,String}[]))
        loop_head(io, d)
        println(io, "        x[$(lhs_index(d))] = $rhs")
    end
    println(io, "    end\n    nothing\nend\n")
end

function emit_data_def(g::Gen, d::Def)
    io = g.io
    call = d.expr::Call
    file = (call.args[1]::Str).s
    src = (call.args[2]::Str).s
    m = match(r"^([^\[]+)(\[(.*)\])?$", strip(src))
    sname = normname(m[1])
    ssubs = m[3] === nothing ? String[] : [normname(s) for s in split(m[3], ',')]
    # nome della serie sorgente per ogni cella del membro sinistro
    names = String[]
    for c in eachcol(d.cells)
        els = String[]
        for s in ssubs
            if haskey(g.m.dims, s)
                R = g.m.dims[s]
                p = lhs_position(g.m, d, R)
                p == 0 && merr(d, "subscript $s della sorgente non legato")
                e = d.var.dims[p].elements[c[p]]
                haskey(R.index, e) || merr(d, "elemento $e fuori da $s")
                push!(els, e)
            else
                push!(els, s)
            end
        end
        push!(names, isempty(els) ? sname : "$sname[$(join(els, ","))]")
    end
    g.ndata += 1
    j = g.ndata
    g.dataid[d.id] = j
    lhskeys = [isempty(d.var.dims) ? d.var.name :
               d.var.name * "[" * join([d.var.dims[p].elements[c[p]] for p in eachindex(c)], ",") * "]"
               for c in eachcol(d.cells)]
    push!(g.datadefs, (j, file, names, d.eq.datamode, lhskeys))
    println(io, header(d))
    println(io, "function data$(d.id)!(x::Vector{Float64}, t::Float64, k::Int)")
    println(io, "    tab = DATA[$j]")
    loop_head(io, d)
    println(io, "        x[$(lhs_index(d))] = tab[c, k]")
    println(io, "    end\n    nothing\nend\n")
end

function emit_alloc_def(g::Gen, d::Def)
    io = g.io
    call = d.expr::Call
    length(call.args) == 5 || merr(d, "ALLOCATE BY PRIORITY con $(length(call.args)) argomenti")
    nd = size(d.cells, 1)
    # gruppi: celle con lo stesso prefisso, ordinate sull'ultimo subscript
    groups = Dict{Vector{Int},Vector{Int}}()
    for (ci, c) in enumerate(eachcol(d.cells))
        push!(get!(groups, c[1:end-1], Int[]), ci)
    end
    keys_ = sort(collect(keys(groups)))
    G = reduce(hcat, [sort(groups[k]; by = ci -> d.cells[end, ci]) for k in keys_])
    S = size(G, 1)
    ctx = Ctx(d, Pair{String,String}[])
    req = gen(g, call.args[1], ctx)
    pri = gen(g, call.args[2], ctx)
    cnt = gen(g, call.args[3], ctx)
    wid = gen(g, call.args[4], ctx)
    sup = gen(g, call.args[5], ctx)
    println(io, header(d))
    println(io, "const G$(d.id) = reshape(Int32[", join(vec(G), ","), "], $S, $(size(G,2)))")
    println(io, "function alloc$(d.id)!(x::Vector{Float64}, t::Float64, k::Int)")
    println(io, "    req = zeros($S); pri = zeros($S)")
    println(io, "    @inbounds for g in 1:$(size(G,2))")
    println(io, "        for j in 1:$S")
    println(io, "            c = G$(d.id)[j, g]")
    for p in 1:nd
        println(io, "            i$p = C$(d.id)[$p, c]")
    end
    println(io, "            req[j] = $req; pri[j] = $pri")
    println(io, "        end")
    println(io, "        c = G$(d.id)[1, g]")
    for p in 1:nd
        println(io, "        i$p = C$(d.id)[$p, c]")
    end
    println(io, "        $cnt == $S || error(\"ALLOCATE BY PRIORITY: numero di fornitori\")")
    println(io, "        out = alloc_priority(req, pri, $wid, $sup)")
    println(io, "        for j in 1:$S")
    println(io, "            c = G$(d.id)[j, g]")
    for p in 1:nd
        println(io, "            i$p = C$(d.id)[$p, c]")
    end
    println(io, "            x[$(lhs_index(d))] = out[j]")
    println(io, "        end")
    println(io, "    end\n    nothing\nend\n")
end

function emit_state_def(g::Gen, d::Def)
    io = g.io
    ctx = Ctx(d, Pair{String,String}[])
    nc = size(d.cells, 2)
    println(io, header(d))
    if d.kind == :stock
        g.roff[d.id] = g.nr; g.nr += nc
        println(io, "function init$(d.id)!(x::Vector{Float64}, t::Float64, k::Int, st)")
        loop_head(io, d)
        println(io, "        x[$(lhs_index(d))] = $(gen(g, d.init, ctx))")
        println(io, "    end\n    nothing\nend")
        println(io, "function rate$(d.id)!(x::Vector{Float64}, r::Vector{Float64}, t::Float64, k::Int, st)")
        loop_head(io, d)
        println(io, "        r[$(g.roff[d.id]) + c] = $(gen(g, d.expr, ctx))")
        println(io, "    end\n    nothing\nend")
        println(io, "function update$(d.id)!(x::Vector{Float64}, r::Vector{Float64}, dt::Float64, st)")
        loop_head(io, d)
        println(io, "        x[$(lhs_index(d))] += dt * r[$(g.roff[d.id]) + c]")
        println(io, "    end\n    nothing\nend\n")
    elseif d.kind == :smooth
        g.roff[d.id] = g.nr; g.nr += nc
        println(io, "function init$(d.id)!(x::Vector{Float64}, t::Float64, k::Int, st)")
        loop_head(io, d)
        println(io, "        x[$(lhs_index(d))] = $(gen(g, d.expr, ctx))")
        println(io, "    end\n    nothing\nend")
        println(io, "function rate$(d.id)!(x::Vector{Float64}, r::Vector{Float64}, t::Float64, k::Int, st)")
        loop_head(io, d)
        println(io, "        r[$(g.roff[d.id]) + c] = ($(gen(g, d.expr, ctx)) - x[$(lhs_index(d))]) / ($(gen(g, d.extra, ctx)))")
        println(io, "    end\n    nothing\nend")
        println(io, "function update$(d.id)!(x::Vector{Float64}, r::Vector{Float64}, dt::Float64, st)")
        loop_head(io, d)
        println(io, "        x[$(lhs_index(d))] += dt * r[$(g.roff[d.id]) + c]")
        println(io, "    end\n    nothing\nend\n")
    elseif d.kind == :delay
        g.ndelay += 1
        j = g.ndelay
        g.delayid[d.id] = j
        g.roff[d.id] = g.nr; g.nr += nc
        # st.delay[j] = (buf::Matrix, n::Vector{Int}, head::Vector{Int})
        println(io, "function init$(d.id)!(x::Vector{Float64}, t::Float64, k::Int, st)")
        println(io, "    ns = zeros(Int, $nc); vals = zeros($nc)")
        loop_head(io, d)
        println(io, "        ns[c] = max(1, round(Int, ($(gen(g, d.extra, ctx))) / st.dt))")
        println(io, "        vals[c] = $(gen(g, d.init, ctx))")
        println(io, "        x[$(lhs_index(d))] = vals[c]")
        println(io, "    end")
        println(io, "    buf = zeros(maximum(ns), $nc)")
        println(io, "    for c in 1:$nc; buf[1:ns[c], c] .= vals[c]; end")
        println(io, "    st.delay[$j] = (buf, ns, ones(Int, $nc))")
        println(io, "    nothing\nend")
        println(io, "function rate$(d.id)!(x::Vector{Float64}, r::Vector{Float64}, t::Float64, k::Int, st)")
        loop_head(io, d)
        println(io, "        r[$(g.roff[d.id]) + c] = $(gen(g, d.expr, ctx))")
        println(io, "    end\n    nothing\nend")
        println(io, "function update$(d.id)!(x::Vector{Float64}, r::Vector{Float64}, dt::Float64, st)")
        println(io, "    buf, ns, head = st.delay[$j]")
        loop_head(io, d)
        println(io, "        h = head[c]")
        println(io, "        buf[h, c] = r[$(g.roff[d.id]) + c]")
        println(io, "        h = h == ns[c] ? 1 : h + 1")
        println(io, "        head[c] = h")
        println(io, "        x[$(lhs_index(d))] = buf[h, c]")
        println(io, "    end\n    nothing\nend\n")
    end
end

function assign_offsets!(m::Model)
    off = 1
    for name in m.order
        v = m.vars[name]
        v.kind in (:lookup, :time) && continue
        v.offset = off
        off += ncells(v)
    end
    return off - 1
end

function generate(m::Model; modname="SUREGenerated")
    nx = assign_offsets!(m)
    g = Gen(m, IOBuffer(), nx, 0, Dict{Int,Int}(), 0, Dict{Int,Int}(), 0, Dict{Int,Int}(), Any[], 0)
    io = g.io
    init_order, c1 = order_defs(m, :init)
    step_order, c2 = order_defs(m, :step)
    isempty(c1) || throw(ModelError("cicli nell'inizializzazione"))
    isempty(c2) || throw(ModelError("cicli nel passo"))
    println(io, "# Codice generato da sure_native: non modificare a mano.")
    println(io, "module $modname\nusing ..SureRuntime\n")
    println(io, "const NX = $nx")
    for d in m.defs
        d.kind == :lookup && continue
        emit_cells(g, d)
    end
    println(io, "const DATA = Matrix{Float64}[]\n")
    # aggancio per i test: sostituisce l'uscita di ALLOCATE BY PRIORITY (es. con i valori di Vensim)
    println(io, "const ALLOC_HOOK = Ref{Any}(nothing)")
    for d in m.defs
        k = d.kind
        if k == :lookup
            continue
        elseif k == :data
            emit_data_def(g, d)
        elseif k in (:aux, :const)
            emit_value_def(g, d, "def$(d.id)!", d.expr)
        elseif k == :alloc
            emit_alloc_def(g, d)
        else
            emit_state_def(g, d)
        end
    end
    println(io, "const NR = $(g.nr)")
    println(io, "const NDELAY = $(g.ndelay)")
    # dati
    println(io, "const DATA_SPECS = [")
    for (j, file, names, mode, lhskeys) in g.datadefs
        println(io, "    ($j, $(repr(file)), $(repr(names)), :$mode, $(repr(lhskeys))),")
    end
    println(io, "]")
    # fasi
    call(d, phase) = d.kind == :data ? "data$(d.id)!(x, t, k)" :
                     d.kind == :alloc ? "(alloc$(d.id)!(x, t, k); ALLOC_HOOK[] === nothing || ALLOC_HOOK[](x, k))" :
                     d.kind in (:aux, :const) ? "def$(d.id)!(x, t, k)" :
                     "init$(d.id)!(x, t, k, st)"
    consts = [d for d in init_order if d.kind == :const]
    others = [d for d in init_order if d.kind != :const]
    println(io, "\nfunction init_constants!(x::Vector{Float64}, t::Float64, k::Int)")
    for d in consts
        println(io, "    ", call(d, :init))
    end
    println(io, "    nothing\nend")
    println(io, "\nfunction init_rest!(x::Vector{Float64}, t::Float64, k::Int, st)")
    for d in m.defs
        d.kind == :data && println(io, "    ", call(d, :init))
    end
    for d in others
        println(io, "    ", call(d, :init))
    end
    println(io, "    nothing\nend")
    println(io, "\nfunction step_aux!(x::Vector{Float64}, t::Float64, k::Int)")
    for d in m.defs
        d.kind == :data && println(io, "    ", call(d, :step))
    end
    for d in step_order
        println(io, "    ", call(d, :step))
    end
    println(io, "    nothing\nend")
    states = [d for d in m.defs if d.kind in (:stock, :smooth, :delay)]
    println(io, "\nfunction step_rates!(x::Vector{Float64}, r::Vector{Float64}, t::Float64, k::Int, st)")
    for d in states
        println(io, "    rate$(d.id)!(x, r, t, k, st)")
    end
    println(io, "    nothing\nend")
    println(io, "\nfunction step_update!(x::Vector{Float64}, r::Vector{Float64}, dt::Float64, st)")
    for d in states
        println(io, "    update$(d.id)!(x, r, dt, st)")
    end
    println(io, "    nothing\nend")
    # indice dei nomi: variabile normalizzata, nome visibile, offset, elementi per dimensione
    println(io, "\nconst VARS = [")
    for name in m.order
        v = m.vars[name]
        (v.kind in (:lookup, :time) || v.hidden) && continue
        els = [d.elements for d in v.dims]
        println(io, "    ($(repr(v.name)), $(repr(v.display)), $(v.offset), $(repr(els)), :$(v.kind)),")
    end
    println(io, "]\n\nend # module")
    return String(take!(io))
end
