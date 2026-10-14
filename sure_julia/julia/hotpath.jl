# Current Python SURE hotpath: C-contiguous (District, HS, Performance, Type,
# PVpanel), sum(axis=1). HS is not the contiguous axis, so NumPy accumulates
# it sequentially into +0.0. Do not replace this by sum-all minus exclusions.
function seneca_hotpath_ms_normalize(input::Array{Float64,5}, excluded::Vector{Int})
    shape = size(input)
    all(index -> 1 <= index <= shape[2], excluded) || error("Invalid HS exclusion index")
    length(unique(excluded)) == length(excluded) || error("Duplicate HS exclusion index")
    values = copy(input)
    for hs in excluded
        values[:, hs, :, :, :] .= 0.0
    end
    for pv in 1:shape[5], kind in 1:shape[4], performance in 1:shape[3], district in 1:shape[1]
        denominator = 0.0
        for hs in 1:shape[2]
            denominator += values[district, hs, performance, kind, pv]
        end
        for hs in 1:shape[2]
            values[district, hs, performance, kind, pv] /= denominator
        end
    end
    return values
end
