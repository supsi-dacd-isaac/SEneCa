# Run with the pinned Julia project and the generated model directory.
using Test, JSON3

directory = abspath(only(ARGS))
model = Module(:ParametricContract)
Base.include(model, joinpath(directory, "SURE_parametric.jl"))
values = Dict(String(k) => Float64(v) for (k, v) in JSON3.read(read(joinpath(directory, "model.json"), String)).defaults)

@testset "SURE parameter API" begin
    parameters = model.parameters_from_dict(values)
    @test length(fieldnames(typeof(parameters))) == 20
    @test all(==(Float64), fieldtypes(typeof(parameters)))
    @test parameters == model.DEFAULT_PARAMETERS
    @test model.parameters_from_dict(Dict(reverse(collect(values)))) == parameters
    for name in ("Provvedimento 1.2", "Provvedimento 1.3", "Provvedimento 1.4", "Provvedimento 1.7")
        changed = model.parameters_from_dict(merge(values, Dict(name => 1.)))
        @test typeof(changed) === typeof(parameters)
        @test changed != parameters
        @test_throws ErrorException model.parameters_from_dict(merge(values, Dict(name => .5)))
    end
    missing = copy(values)
    delete!(missing, first(keys(values)))
    @test_throws ErrorException model.parameters_from_dict(missing)
    @test_throws ErrorException model.parameters_from_dict(merge(values, Dict("Unknown" => 1.)))
    @test_throws ErrorException model.parameters_from_dict(merge(values, Dict("FiT" => NaN)))
    @test_throws ErrorException model.parameters_from_dict(merge(values, Dict("FiT" => Inf)))
end
