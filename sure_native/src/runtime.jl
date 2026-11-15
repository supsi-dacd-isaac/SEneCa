# Funzioni con la semantica di Vensim usate dal codice generato.
module SureRuntime

using SpecialFunctions: loggamma

export zidz, xidz, vln, vlog, vpow, lkp, b2f, alloc_priority, vgammaln, NA_VALUE,
       data_table

const NA_VALUE = -1.298074214633707e33   # :NA: di Vensim
const SMALL = 1e-6                        # soglia di ZIDZ / XIDZ

@inline zidz(a::Float64, b::Float64) = abs(b) <= SMALL ? 0.0 : a / b
@inline xidz(a::Float64, b::Float64, x::Float64) = abs(b) <= SMALL ? x : a / b
@inline vln(a::Float64) = a > 0 ? log(a) : (a == 0 ? -Inf : NaN)
@inline vlog(a::Float64, b::Float64) = vln(a) / vln(b)
@inline function vpow(a::Float64, b::Float64)
    (a < 0 && !isinteger(b)) && return NaN
    return a^b
end
@inline b2f(c::Bool) = c ? 1.0 : 0.0
@inline vgammaln(a::Float64) = a > 0 ? loggamma(a) : NaN

"""Lookup di Vensim: interpolazione lineare, valori costanti fuori dall'intervallo.

Formula verificata sul riferimento (52'680 valori su 52'680 identici):
y0 + (x - x0) / (x1 - x0) * (y1 - y0), in Float64.
"""
@inline function lkp(xs::NTuple{N,Float64}, ys::NTuple{N,Float64}, v::Float64) where {N}
    v <= xs[1] && return ys[1]
    v >= xs[N] && return ys[N]
    i = 1
    @inbounds while xs[i+1] < v
        i += 1
    end
    @inbounds return ys[i] + (v - xs[i]) / (xs[i+1] - xs[i]) * (ys[i+1] - ys[i])
end

"""Valori di una serie di dati sugli istanti del modello, secondo il modo Vensim."""
function data_table(st::Vector{Float64}, sv::Vector{Float64}, times::AbstractVector{Float64}, mode::Symbol)
    ok = findall(!isnan, sv)
    out = fill(NA_VALUE, length(times))
    isempty(ok) && return out
    xs, ys = st[ok], sv[ok]
    for (k, t) in enumerate(times)
        if mode == :raw
            j = findfirst(==(t), xs)
            out[k] = j === nothing ? NA_VALUE : ys[j]
        elseif t <= xs[1]
            out[k] = ys[1]
        elseif t >= xs[end]
            out[k] = ys[end]
        else
            j = searchsortedlast(xs, t)
            if xs[j] == t
                out[k] = ys[j]
            elseif mode == :interpolate
                out[k] = ys[j] + (t - xs[j]) * (ys[j+1] - ys[j]) / (xs[j+1] - xs[j])
            elseif mode == :look_forward
                out[k] = ys[j+1]
            else  # :hold
                out[k] = ys[j]
            end
        end
    end
    out
end

"""ALLOCATE BY PRIORITY con larghezza comune (profilo rettangolare di Vensim)."""
function alloc_priority(request::Vector{Float64}, priority::Vector{Float64}, width::Float64,
                        supply::Float64)
    width > 0 || error("ALLOCATE BY PRIORITY: larghezza non positiva")
    q = max.(request, 0.0)
    total = sum(q)
    supply >= total && return q
    supply <= 0 && return zeros(length(q))
    idx = findall(!iszero, q)
    idx = idx[sortperm(-priority[idx]; alg=Base.Sort.MergeSort)]
    r, p = q[idx], priority[idx]
    n = length(r)
    out, dist = zeros(n), fill(NaN, n)
    n > 1 && (dist[1:end-1] .= min.(-diff(p) ./ width, 1.0) .* r[1:end-1])
    active = falses(n); active[1] = true
    cur = 1
    it = 0
    while supply > 0
        it += 1
        it <= 4n + 4 || error("ALLOCATE BY PRIORITY non converge")
        slopes = r .* active
        slopes ./= sum(slopes)
        top = minimum((r .- out)[active] ./ slopes[active])
        start = (dist[cur] - out[cur]) / slopes[cur]
        dx = isnan(start) ? min(top, supply) : min(top, start, supply)
        out .+= slopes .* dx
        if abs(dx - start) <= 1e-16 + 1e-10abs(start)
            cur += 1
            active[cur] = true
        end
        dx == top && (active[out .== r] .= false)
        supply -= dx
    end
    res = zeros(length(q))
    res[idx] = out
    res
end

end
