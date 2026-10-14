# NumPy 2.4.6 on the pinned macOS arm64 reference uses Apple's scalar EXP.
# The exact OS and native library versions are checked by generated models.
if !Sys.isapple() || Sys.ARCH != :aarch64
    error("NumPy EXP compatibility requires the audited macOS arm64 platform")
end

@inline seneca_numpy_exp(x::Float64) =
    ccall((:exp, "/usr/lib/libSystem.B.dylib"), Float64, (Float64,), x)
seneca_numpy_exp(x::Real) = seneca_numpy_exp(Float64(x))

@inline seneca_system_power(x::Float64, y::Float64) =
    ccall((:pow, "/usr/lib/libSystem.B.dylib"), Float64, (Float64, Float64), x, y)

function seneca_python_power(x::Real, y::Real)
    x < 0 && !isinteger(y) && return NaN
    seneca_system_power(Float64(x), Float64(y))
end

function seneca_numpy_power(x::Real, y::Real)
    x, y = Float64(x), Float64(y)
    y == -1.0 && return 1.0 / x
    y == 0.0 && return 1.0
    y == 0.5 && return x < 0 ? NaN : sqrt(x)
    y == 1.0 && return x
    y == 2.0 && return x * x
    x < 0 && !isinteger(y) && return NaN
    seneca_system_power(x, y)
end

function seneca_numpy_math_platform()
    (macos_version = readchomp(`/usr/bin/sw_vers -productVersion`),
     libsystem_version = Int(ccall(:NSVersionOfRunTimeLibrary, Cint, (Cstring,), "System")),
     libsystem_m_version = Int(ccall(:NSVersionOfRunTimeLibrary, Cint, (Cstring,), "system_m")))
end

function seneca_verify_numpy_math(macos_version, libsystem_version, libsystem_m_version)
    actual = seneca_numpy_math_platform()
    expected = (; macos_version, libsystem_version, libsystem_m_version)
    actual == expected || error("Native math library/platform changed since translation: $actual != $expected")
    nothing
end
