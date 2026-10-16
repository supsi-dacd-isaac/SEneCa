# Common-width priority allocation matching PySD 3.14.3 in Float64.
# The endpoint guard is shared with the canonical Python reference.
function seneca_priority(request, priority, width, supply)
    width > 0 || error("Allocation width must be positive")
    supply >= 0 || error("Allocation supply must be nonnegative")
    q = max.(Float64.(request), 0.0)
    total = seneca_numpy_sum(q)
    if supply < total && total - supply <= 4eps(total)
        supply = total
    end
    supply >= total && return q
    supply == 0 && return zeros(length(q))
    indices = findall(!iszero, q)
    # SURE has fewer than sixteen suppliers. NumPy's indirect quicksort uses
    # stable insertion sort at this size; explicitly restrict the contract.
    length(indices) <= 15 || error("Priority tie ordering unverified above 15 suppliers")
    indices = indices[sortperm(-priority[indices]; alg=Base.Sort.MergeSort)]
    r, p = q[indices], priority[indices]
    out, distances = zeros(length(r)), fill(NaN, length(r))
    distances[1:end-1] .= min.(-diff(p) ./ width, 1.0) .* r[1:end-1]
    active = falses(length(r)); active[1] = true
    current = 1
    iterations = 0
    while supply > 0
        iterations += 1
        iterations <= 4length(r) + 4 || error("Allocation did not converge")
        slopes = r .* active
        slopes ./= seneca_numpy_sum(slopes)
        top = minimum((r .- out)[active] ./ slopes[active])
        start = (distances[current] - out[current]) / slopes[current]
        dx = isnan(start) ? min(top, supply) : min(top, start, supply)
        out .+= slopes .* dx
        if abs(dx-start) <= 1e-16 + 1e-10abs(start)
            current += 1
            active[current] = true
        end
        if dx == top
            active[out .== r] .= false
        end
        supply -= dx
    end
    result = zeros(length(q))
    result[indices] = out
    return result
end

function seneca_allocate_available(request, pp, available)
    ndims(pp) == 2 || error("Only the shared Supplier × PProfile SURE profile is validated")
    widths = unique(round.(filter(isfinite, pp[:, 3]); digits=6))
    if !(all(pp[:, 1] .== 1) && length(widths) == 1)
        return sure_v3_allocate_available(request, pp, available)
    end
    width = only(widths)
    if ndims(request) == 1
        return seneca_priority(request, pp[:, 2], width, available)
    end
    size(available) == size(request)[1:end-1] || error("Availability shape mismatch")
    result = similar(request, Float64)
    for idx in CartesianIndices(available)
        prefix = Tuple(idx)
        result[prefix..., :] = seneca_priority(request[prefix..., :], pp[:, 2], width, available[idx])
    end
    return result
end


function seneca_allocate_by_priority(request, priority, count, width, available)
    ndims(priority) == 1 || error("Expected one shared Supplier priority vector")
    length(priority) == size(request, ndims(request)) == count || error("Supplier count mismatch")
    width isa Real || error("Expected the scalar common priority width")
    all(request .>= 0) || error("Negative dispatchable capacity")
    if ndims(request) == 1
        return seneca_priority(request, priority, width, available)
    end
    size(available) == size(request)[1:end-1] || error("Availability shape mismatch")
    result = similar(request, Float64)
    for idx in CartesianIndices(available)
        prefix = Tuple(idx)
        result[prefix..., :] = seneca_priority(request[prefix..., :], priority, width, available[idx])
    end
    return result
end
