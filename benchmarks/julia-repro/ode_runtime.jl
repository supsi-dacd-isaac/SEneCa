mutable struct SenecaContext
    state::Vector{Float64}
    time::Float64
    initializing::Bool
    values::Vector{Any}
    status::Vector{UInt8}
end
SenecaContext(state, time, initializing, n) = SenecaContext(state, Float64(time), initializing, Vector{Any}(undef, n), zeros(UInt8, n))

# Match PySD 3.14.3 numerical helpers, including SMALL_VENSIM=1e-6.
seneca_xidz(x, y, z) = abs(y) < 1e-6 ? z : x / y
seneca_zidz(x, y) = abs(y) < 1e-6 ? 0.0 : x / y
seneca_step(t, height, start) = height * (t + time_step/2 > start)
seneca_ramp(t, slope, start, finish=Inf) = (t + 1e-6 > start) * slope * (min(t, finish)-start)
seneca_power(x, y) = x < 0 && !isinteger(y) ? NaN : x ^ y
seneca_logical_and(a, b) = (a != 0) & (b != 0)
seneca_logical_or(a, b) = (a != 0) | (b != 0)
seneca_logical_not(a) = !(a != 0)
seneca_pulse(t, start, width) = start - 1e-6 <= t < start + width ? 1.0 : 0.0
seneca_pulse_train(t, start, interval, width, finish) =
    interval == 0 ? seneca_pulse(t, start, width) :
    start <= t < finish && mod(t - start + 1e-6, interval) < width ? 1.0 : 0.0
seneca_modulo(x, m) = x - (m < 1e-6 ? x : m * trunc(x / m))
