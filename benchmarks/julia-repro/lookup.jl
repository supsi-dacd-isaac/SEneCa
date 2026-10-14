# np.interp in the frozen NumPy arm64 build fuses slope*(x-xlo)+ylo.
# DataInterpolations and ordinary Julia multiplication/addition do not preserve
# that last rounding. Named multidimensional inputs use their separate reader.
struct SenecaNumpyLookup
    xs::Vector{Float64}
    ys::Vector{Float64}
    mode::Symbol
    function SenecaNumpyLookup(xs, ys, mode=:interpolate)
        length(xs) == length(ys) > 0 || error("Invalid lookup lengths")
        all(isfinite, xs) && all(isfinite, ys) || error("Nonfinite lookup grid")
        all(diff(xs) .> 0) || error("Lookup coordinates must strictly increase")
        mode in (:interpolate, :extrapolate, :hold_backward) || error("Unsupported lookup mode")
        mode == :extrapolate && length(xs) < 2 && error("Extrapolation needs two knots")
        new(Float64.(xs), Float64.(ys), mode)
    end
end

@inline function (table::SenecaNumpyLookup)(query::Real)
    x = Float64(query)
    isfinite(x) || error("Nonfinite lookup query")
    xs, ys, mode = table.xs, table.ys, table.mode
    j = searchsortedfirst(xs, x)
    if j <= length(xs) && xs[j] == x
        return ys[j]
    elseif j == 1
        mode == :extrapolate || return first(ys)
        # PySD HardcodedLookups extrapolates through xarray operations, which
        # round multiplication separately from addition.
        slope = (ys[2]-ys[1])/(xs[2]-xs[1])
        return ys[1] + slope*(x-xs[1])
    elseif j > length(xs)
        mode == :extrapolate || return last(ys)
        slope = (ys[end]-ys[end-1])/(xs[end]-xs[end-1])
        return ys[end] + slope*(x-xs[end])
    elseif mode == :hold_backward
        return ys[j-1]
    end
    slope = (ys[j]-ys[j-1])/(xs[j]-xs[j-1])
    return fma(slope, x-xs[j-1], ys[j-1])
end
