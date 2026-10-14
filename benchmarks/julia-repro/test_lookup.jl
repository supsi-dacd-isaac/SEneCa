using JSON3
include(joinpath(@__DIR__, "lookup.jl"))
directory = ARGS[1]
results = []
for row in JSON3.read(read(joinpath(directory,"cases.json"),String))
    table = SenecaNumpyLookup(Float64.(row.xs),Float64.(row.ys),Symbol(row.mode))
    actual = table.(Float64.(row.queries))
    expected = Float64.(row.expected)
    failures = findall(reinterpret(UInt64,actual) .!= reinterpret(UInt64,expected))
    push!(results, Dict("fixture"=>String(row.name),"pass"=>isempty(failures),
        "comparisons"=>length(actual), "failures"=>length(failures),
        "max_abs"=>maximum(abs.(actual-expected))))
end
spec=JSON3.read(read(joinpath(directory,"model.json"),String))
m=Module(gensym(:Lookup))
Base.include(m,String(spec.path))
solution=Base.invokelatest(m.run_model)
solution.t==[0.,1.,2.] || error("Truncated lookup model fixture")
expected=JSON3.read(read(joinpath(directory,"model-oracle.json"),String))
count=0
for (i,t) in enumerate(solution.t)
    observed=Base.invokelatest(m.observe,solution.u[i],t)
    for row in expected
        actual=vec(observed[String(row.identifier)])
        truth=Float64.(row.values[i])
        reinterpret(UInt64,actual)==reinterpret(UInt64,truth) || error("Translated lookup differs: $(row.name)/$t")
        global count+=length(actual)
    end
end
push!(results,Dict("fixture"=>"translated_inline_and_named","pass"=>true,"comparisons"=>count))
result=Dict("pass"=>all(row["pass"] for row in results),"results"=>results)
write(joinpath(directory,"results.json"),JSON3.write(result))
result["pass"] || error("Lookup fixtures failed")
