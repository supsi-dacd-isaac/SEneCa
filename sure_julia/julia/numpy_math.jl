# Explicit array power special cases follow NumPy; general math is portable.
@inline seneca_numpy_exp(x::Real) = exp(Float64(x))
function seneca_python_power(x::Real, y::Real)
    x < 0 && !isinteger(y) && return NaN
    Float64(x)^Float64(y)
end
function seneca_numpy_power(x::Real, y::Real)
    x, y = Float64(x), Float64(y)
    y == -1.0 && return 1.0 / x
    y == 0.0 && return 1.0
    y == 0.5 && return x < 0 ? NaN : sqrt(x)
    y == 1.0 && return x
    y == 2.0 && return x * x
    seneca_python_power(x, y)
end
