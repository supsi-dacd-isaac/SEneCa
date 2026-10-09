# Exact inverse of rectangular priority curves (profile 1, as used by SURE v3).
# Other profiles fail explicitly; this is not a proportional-allocation fallback.
function seneca_allocate_vector(request, pp, available)
    all(isfinite, request) && all(isfinite, pp) && isfinite(available) || error("Nonfinite allocation input")
    available >= 0 || error("Negative availability")
    size(pp) == (length(request), 4) || error("Invalid priority profile shape")
    all(pp[:, 1] .== 1) || error("Only SURE rectangular priority profiles are supported")
    all(pp[:, 3] .> 0) || error("Nonpositive priority width")
    q = max.(Float64.(request), 0.0)  # existing SURE Python correction
    available >= sum(q) && return q
    available == 0 && return zeros(length(q))
    lower = pp[:, 2] .- pp[:, 3] ./ 2
    upper = pp[:, 2] .+ pp[:, 3] ./ 2
    curve(x) = q .* clamp.(1 .- (x .- lower) ./ pp[:, 3], 0., 1.)
    knots = sort!(unique(vcat(lower, upper)))
    for k in 1:length(knots)-1
        lo, hi = knots[k], knots[k+1]
        left, right = sum(curve(lo)), sum(curve(hi))
        if right <= available <= left
            left == right && return curve(lo)
            priority = lo + (hi-lo) * ((left-available)/(left-right))
            return curve(priority)
        end
    end
    error("No allocation interval contains the available supply")
end

function seneca_allocate_available(request, pp, available)
    ndims(request) == 1 && return seneca_allocate_vector(request, pp, available)
    size(available) == size(request)[1:end-1] || error("Availability shape mismatch")
    result = similar(request, Float64)
    for idx in CartesianIndices(available)
        prefix = Tuple(idx)
        result[prefix..., :] = seneca_allocate_vector(request[prefix..., :], pp, available[idx])
    end
    return result
end
