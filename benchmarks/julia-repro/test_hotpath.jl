using JSON3
Base.include(@__MODULE__, joinpath(@__DIR__, "hotpath.jl"))
target = abspath(ARGS[1])
rows = JSON3.read(read(joinpath(target,"cases.json"),String))
metadata = JSON3.read(read(joinpath(target,"metadata.json"),String))
expected = Vector{Array{Float64,5}}()
inputs = Vector{Array{Float64,5}}()
function canonical_array(io, row)
    seek(io,8*Int(row.offset))
    raw = Vector{Float64}(undef,Int(row.elements)); read!(io,raw)
    shape = Int.(row.shape)
    return permutedims(reshape(raw,reverse(shape)...),reverse(1:length(shape)))
end
open(joinpath(target,"inputs.bin")) do input
    open(joinpath(target,"expected.bin")) do oracle
        for row in rows
            push!(inputs,canonical_array(input,row))
            push!(expected,canonical_array(oracle,row))
        end
    end
end
failures = []
maximum_error = 0.0
for (i,row) in enumerate(rows)
    original = copy(inputs[i])
    actual = seneca_hotpath_ms_normalize(inputs[i],Int[Int(index) for index in row.excluded_indices])
    unchanged = isequal(original,inputs[i])
    error = maximum(abs.(actual.-expected[i]))
    global maximum_error = max(maximum_error,error)
    (!isequal(actual,expected[i]) || !unchanged) && push!(failures,Dict("case"=>i,"stage"=>"helper","max_abs"=>error,"unchanged_input"=>unchanged))
end
model_cases = 0
model_file = joinpath(target,"models.json")
if isfile(model_file)
    for item in JSON3.read(read(model_file,String))
        model = Module(gensym(:HotpathFixture))
        Base.include(model,String(item.path))
        requested = String.(item.outputs)
        observed = Base.invokelatest(model.observe,Base.invokelatest(model.initial_state),0.0,requested)
        for (case,name) in zip(Int.(item.cases),requested)
            actual = observed[name]
            error = maximum(abs.(actual.-expected[case]))
            global maximum_error = max(maximum_error,error)
            !isequal(actual,expected[case]) && push!(failures,Dict("case"=>case,"stage"=>"translated_model","max_abs"=>error))
            global model_cases += 1
        end
    end
end
result = Dict("pass"=>isempty(failures),"helper_cases"=>length(rows),"translated_cases"=>model_cases,
              "elements"=>sum(Int(row.elements) for row in rows),"all_bitwise"=>isempty(failures),
              "max_abs"=>maximum_error,"failures"=>failures)
write(joinpath(target,"results.json"),JSON3.write(result))
println(result)
isempty(failures) || error("Python HS hotpath parity failed")
