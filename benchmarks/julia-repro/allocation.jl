# Profile 1 as used by SURE. Preserve PySD 3.14.3's scalar dogbox stopping
# criteria, including its finite-difference Jacobian: an exact analytic inverse
# can differ from the current Python outputs after subtracting allocations.
function seneca_numpy_sum(a)
    n = length(a)
    n < 8 && return foldl(+, a; init=-0.0)
    if n <= 128
        r = collect(a[1:8])
        i = 9
        while i + 7 <= n
            for j in 1:8
                r[j] += a[i+j-1]
            end
            i += 8
        end
        value = ((r[1]+r[2])+(r[3]+r[4]))+((r[5]+r[6])+(r[7]+r[8]))
        while i <= n
            value += a[i]
            i += 1
        end
        return value
    end
    midpoint = (n ÷ 2) ÷ 8 * 8
    return seneca_numpy_sum(@view(a[1:midpoint])) + seneca_numpy_sum(@view(a[midpoint+1:n]))
end

# NumPy reduces the contiguous inner block pairwise, then adds the remaining
# strided blocks sequentially. The translator supplies the audited physical
# iteration order and block size; neither is inferred from Julia's storage.
function seneca_numpy_reduce(values, blocksize::Int)
    blocksize >= 1 || error("Nonpositive NumPy reduction block")
    length(values) % blocksize == 0 || error("Incomplete NumPy reduction block")
    result = 0.0
    for first_index in 1:blocksize:length(values)
        result += seneca_numpy_sum(@view(values[first_index:first_index+blocksize-1]))
    end
    return result
end

function seneca_scalar_dogbox(f, x, lower, upper)
    function jacobian(x, fx)
        h = sqrt(eps(Float64)) * (x >= 0 ? 1.0 : -1.0) * max(1.0, abs(x))
        left, right = x-lower, upper-x
        if abs(h) > max(left, right)
            h = right >= left ? right : -left
        elseif !(lower <= x+h <= upper)
            h = -h
        end
        dx = (x+h)-x
        return (f(x+h)-fx)/dx
    end
    fx = f(x)
    cost = 0.5 * fx * fx
    J = jacobian(x, fx)
    radius = abs(x) == 0 ? 1.0 : abs(x)
    evaluations = 1
    terminated = false
    while !terminated && evaluations < 100
        gradient = J*fx
        active = (x == lower && gradient > 0) || (x == upper && gradient < 0)
        (active || abs(gradient) < 1e-8) && return x
        newton = -fx/J
        reduction = -1.0
        while reduction <= 0 && evaluations < 100
            lo, hi = max(lower-x, -radius), min(upper-x, radius)
            step = clamp(newton, lo, hi)
            trust_hit = (step == -radius || step == radius) && !(lo <= newton <= hi)
            predicted = -(0.5 * (J*step)^2 + gradient*step)
            next_x = clamp(x+step, lower, upper)
            next_fx = f(next_x)
            evaluations += 1
            next_cost = 0.5 * next_fx * next_fx
            reduction = cost-next_cost
            ratio = predicted > 0 ? reduction/predicted : predicted == reduction == 0 ? 1.0 : 0.0
            if ratio < 0.25
                radius = 0.25*abs(step)
            elseif ratio > 0.75 && trust_hit
                radius *= 2.0
            end
            terminated = (reduction < 1e-8*cost && ratio > 0.25) || abs(step) < 1e-8*(1e-8+abs(x))
            if reduction > 0
                x, fx, cost = next_x, next_fx, next_cost
                J = jacobian(x, fx)
            end
            terminated && break
        end
    end
    return x
end

function seneca_allocate_vector(request, pp, available)
    all(isfinite, request) && all(isfinite, pp) && isfinite(available) || error("Nonfinite allocation input")
    available >= 0 || error("Negative availability")
    size(pp) == (length(request), 4) || error("Invalid priority profile shape")
    all(pp[:, 1] .== 1) || error("Only SURE rectangular priority profiles are supported")
    all(pp[:, 3] .> 0) || error("Nonpositive priority width")
    q = max.(Float64.(request), 0.0)
    available >= seneca_numpy_sum(q) && return q
    available == 0 && return zeros(length(q))
    lower = pp[:, 2] .- pp[:, 3] .* 0.5
    upper = pp[:, 2] .+ pp[:, 3] .* 0.5
    curve(x) = [q[i] == 0 ? 0.0 : x <= lower[i] ? q[i] : x < upper[i] ?
                q[i]*(1-(x-pp[i,2]+pp[i,3]*0.5)/pp[i,3]) : 0.0 for i in eachindex(q)]
    total(x) = seneca_numpy_sum(curve(x))
    # PySD unions OPEN profile intervals; touching intervals remain distinct.
    ranges = sort!([(lower[i], upper[i]) for i in eachindex(q) if q[i] != 0])
    intervals = Tuple{Float64,Float64}[]
    for (lo, hi) in ranges
        if !isempty(intervals) && lo < last(intervals)[2]
            intervals[end] = (last(intervals)[1], max(last(intervals)[2], hi))
        else
            push!(intervals, (lo, hi))
        end
    end
    for (lo, hi) in intervals
        if total(hi) <= available <= total(lo)
            priority = seneca_scalar_dogbox(x -> total(x)-available, 0.5*(hi+lo), lo, hi)
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
