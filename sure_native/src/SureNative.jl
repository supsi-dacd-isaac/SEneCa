"""Traduttore diretto Vensim .mdl -> Julia per SURE, senza PySD."""
module SureNative
include("parser.jl")
include("model.jl")
include("codegen.jl")
export build_model, generate, parse_model
end
