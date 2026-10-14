# Exact coordinate dispatch and PySD input interpolation for any array rank.
struct SenecaExternalGrid{N}
    time::Vector{Float64}
    values::Array{Float64,N}
    interpolation::Symbol
end

function seneca_external_grid(spec)
    dimensions = String.(spec["dimensions"])
    sizes = Tuple(length(spec["coordinates"][dim]) for dim in dimensions)
    ts = Float64.(spec["time"])
    isempty(ts) && error("Empty external input grid")
    all(isfinite, ts) && all(diff(ts) .> 0) || error("Invalid external input grid")
    values = fill(NaN, length(ts), sizes...)
    assigned = Set{Tuple}()
    for series in spec["series"]
        cell = Tuple(Int.(series["indices"]))
        length(cell) == length(sizes) || error("External input rank mismatch")
        cell in assigned && error("Duplicate external input cell")
        push!(assigned, cell)
        ys = Float64.(series["values"])
        length(ys) == length(ts) || error("External input time length mismatch")
        values[:, cell...] = ys
    end
    all(isfinite, values) || error("Nonfinite or uncovered external input cell")
    mode = Symbol(spec["interpolation"])
    mode in (:interpolate, :hold_backward, :look_forward, :raw, :extrapolate) || error("Unsupported interpolation")
    return SenecaExternalGrid(ts, values, mode)
end

@inline function seneca_external_value(grid::SenecaExternalGrid, x::Real, indices::Tuple)
    ts, values, mode = grid.time, grid.values, grid.interpolation
    isfinite(x) || error("Nonfinite external input argument")
    length(indices) == ndims(values)-1 || error("External input index rank mismatch")
    j = searchsortedfirst(ts, x)
    if j <= length(ts) && ts[j] == x
        return values[j, indices...]
    elseif mode == :raw
        return NaN
    elseif j == 1
        mode == :extrapolate && length(ts) > 1 || return values[1, indices...]
        j = 2
    elseif j > length(ts)
        mode == :extrapolate && length(ts) > 1 || return values[end, indices...]
        j = length(ts)
    elseif mode == :hold_backward
        return values[j-1, indices...]
    elseif mode == :look_forward
        return values[j, indices...]
    end
    lo, hi = values[j-1, indices...], values[j, indices...]
    return (hi-lo)/(ts[j]-ts[j-1])*(x-ts[j-1])+lo
end
