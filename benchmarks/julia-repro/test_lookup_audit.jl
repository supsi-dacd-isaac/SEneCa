using JSON3
include(joinpath(@__DIR__,"lookup.jl"))
function main(directory)
    inputs=collect(reinterpret(Float64,read(joinpath(directory,"input.bin"))))
    expected=collect(reinterpret(Float64,read(joinpath(directory,"expected.bin"))))
    rows=[]
    for record in JSON3.read(read(joinpath(directory,"records.json"),String),Vector{Dict{String,Any}})
        table=SenecaNumpyLookup(Float64.(record["xs"]),Float64.(record["ys"]))
        bounds=(Int(record["offset"])+1):(Int(record["offset"])+Int(record["count"]))
        actual=table.(view(inputs,bounds));truth=expected[bounds]
        failures=findall(reinterpret(UInt64,actual).!=reinterpret(UInt64,truth))
        push!(rows,merge(record,Dict("pass"=>isempty(failures),"failures"=>length(failures),
                                    "max_abs"=>maximum(abs.(actual-truth)))))
    end
    result=Dict("pass"=>all(row["pass"] for row in rows),"cases"=>length(rows),
                "elements"=>length(inputs),"results"=>rows)
    write(joinpath(directory,"results.json"),JSON3.write(result))
    result["pass"] || error("Actual lookup calls differ from NumPy")
end
main(ARGS[1])
