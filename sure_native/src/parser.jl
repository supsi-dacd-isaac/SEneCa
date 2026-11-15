# Parser del formato testuale .mdl di Vensim (sezione equazioni).
#
# Produce una lista di blocchi grezzi con l'espressione già analizzata.
# Il parser riconosce solo i costrutti usati da SURE: qualunque altro costrutto
# ferma la traduzione con il nome della variabile e la riga del .mdl.

# ------------------------------------------------------------------ AST

abstract type Node end

struct Num <: Node
    v::Float64
end

struct Sub
    name::String   # nome normalizzato (elemento o range)
    bang::Bool     # Range! (riduzione)
end

struct VRef <: Node
    name::String   # nome normalizzato della variabile
    subs::Vector{Sub}
end

struct Call <: Node
    f::String             # nome normalizzato della funzione o del lookup
    args::Vector{Node}
end

struct Op <: Node
    op::Symbol
    args::Vector{Node}
end

struct Str <: Node
    s::String
end

struct LookupTable <: Node
    xs::Vector{Float64}
    ys::Vector{Float64}
end

struct NumArray <: Node     # TABBED ARRAY o liste di costanti
    vals::Vector{Float64}
end

struct ParseError_ <: Exception
    msg::String
end
Base.showerror(io::IO, e::ParseError_) = print(io, e.msg)

normname(s::AbstractString) = lowercase(join(split(replace(strip(s), '_' => ' ')), ' '))

# ------------------------------------------------------------------ blocchi

struct RawBlock
    line::Int          # riga del .mdl dove inizia il blocco
    eq::String         # testo dell'equazione con le continuazioni unite
    units::String
    comment::String
end

"""Divide il file .mdl in blocchi `equazione ~ unità ~ commento |`."""
function read_blocks(path::AbstractString)
    text = read(path, String)
    text = replace(text, "\r\n" => "\n")
    startswith(text, "{UTF-8}") && (text = text[8:end])
    cut = findfirst("\\\\\\---///", text)
    cut === nothing || (text = text[1:prevind(text, first(cut))])
    blocks = RawBlock[]
    line = startswith(read(path, String), "{UTF-8}") ? 1 : 1
    i = firstindex(text)
    cur_line = 1
    buf = IOBuffer()
    start_line = 1
    started = false
    # Il separatore | chiude il blocco; dentro equazioni e unità non compare.
    for c in text
        if c == '|'
            push!(blocks, make_block(String(take!(buf)), start_line))
            started = false
        else
            if !started && !isspace(c)
                started = true
                start_line = cur_line
            end
            write(buf, c)
        end
        c == '\n' && (cur_line += 1)
    end
    rest = strip(String(take!(buf)))
    isempty(rest) || error("Testo dopo l'ultimo blocco alla riga $start_line")
    return filter(b -> !isempty(strip(b.eq)) || false, blocks)
end

function make_block(s::String, line::Int)
    # continuazioni: backslash + a capo + tab iniziali
    s = replace(s, r"\\\n[\t]*" => "")
    parts = split(s, '~'; limit=3)
    eq = strip(parts[1])
    units = length(parts) >= 2 ? strip(parts[2]) : ""
    comment = length(parts) >= 3 ? strip(parts[3]) : ""
    # Le intestazioni di gruppo (*****) precedono un'equazione nello stesso blocco
    eq = replace(eq, r"^\*{5,}.*?\*{5,}\s*"s => "")
    eq = replace(eq, r"^\*+\n.*?\n\*+\s*"s => "")
    return RawBlock(line, String(eq), String(units), String(comment))
end

# ------------------------------------------------------------------ tokenizer

struct Tok
    kind::Symbol   # :num :name :str :op :kw :eof
    s::String
    v::Float64
end

isnamechar(c::Char) = isletter(c) || isdigit(c) || c in (' ', '_', '$', '\'', '.', '&', '\t', '\n')

function tokenize(s::AbstractString)
    toks = Tok[]
    cs = collect(s)
    n = length(cs)
    i = 1
    while i <= n
        c = cs[i]
        if isspace(c)
            i += 1
        elseif c == '"'
            j = findnext(==('"'), cs, i + 1)
            j === nothing && throw(ParseError_("virgolette non chiuse"))
            push!(toks, Tok(:name, normname(String(cs[i+1:j-1])), 0.0))
            i = j + 1
        elseif c == '\''
            j = findnext(==('\''), cs, i + 1)
            j === nothing && throw(ParseError_("apice non chiuso"))
            push!(toks, Tok(:str, String(cs[i+1:j-1]), 0.0))
            i = j + 1
        elseif isdigit(c) || (c == '.' && i < n && isdigit(cs[i+1]))
            j = i
            while j <= n && (isdigit(cs[j]) || cs[j] == '.')
                j += 1
            end
            if j <= n && cs[j] in ('e', 'E') && j < n &&
               (isdigit(cs[j+1]) || (cs[j+1] in ('+', '-') && j + 1 < n && isdigit(cs[j+2])))
                j += 2
                while j <= n && isdigit(cs[j])
                    j += 1
                end
            end
            txt = String(cs[i:j-1])
            push!(toks, Tok(:num, txt, parse(Float64, txt)))
            i = j
        elseif isletter(c) || c == '_'
            j = i
            while j <= n && isnamechar(cs[j])
                j += 1
            end
            push!(toks, Tok(:name, normname(String(cs[i:j-1])), 0.0))
            i = j
        elseif c == ':' && i < n && cs[i+1] == '='
            push!(toks, Tok(:op, ":=", 0.0)); i += 2
        elseif c == ':'
            j = findnext(==(':'), cs, i + 1)
            j === nothing && throw(ParseError_("':' isolato"))
            kw = uppercase(strip(String(cs[i+1:j-1])))
            push!(toks, Tok(:kw, kw, 0.0))
            i = j + 1
        else
            two = i < n ? String(cs[i:i+1]) : ""
            if two in ("<=", ">=", "<>", ":=", "==")
                push!(toks, Tok(:op, two, 0.0)); i += 2
            elseif c in ('+', '-', '*', '/', '^', '(', ')', '[', ']', ',', '!', '=', '<', '>', ';')
                push!(toks, Tok(:op, string(c), 0.0)); i += 1
            else
                throw(ParseError_("carattere inatteso '$c'"))
            end
        end
    end
    push!(toks, Tok(:eof, "", 0.0))
    return toks
end

# ------------------------------------------------------------------ parser espressioni

mutable struct P
    t::Vector{Tok}
    i::Int
end
peek(p::P) = p.t[p.i]
next!(p::P) = (p.i += 1; p.t[p.i-1])
isop(p::P, s) = (t = peek(p); t.kind == :op && t.s == s)
iskw(p::P, s) = (t = peek(p); t.kind == :kw && t.s == s)
function expect!(p::P, s)
    t = next!(p)
    (t.kind == :op && t.s == s) || throw(ParseError_("atteso '$s', trovato '$(t.s)'"))
    t
end

const BUILTINS = Set(["if then else", "sum", "max", "min", "vmax", "vmin", "exp", "ln", "log",
    "abs", "zidz", "xidz", "integ", "smooth", "delay fixed", "elmcount", "gamma ln",
    "allocate by priority", "with lookup", "get vdf data", "tabbed array"])

function parse_expr(p::P)
    return parse_or(p)
end

function parse_or(p)
    a = parse_and(p)
    while iskw(p, "OR")
        next!(p); a = Op(:or, [a, parse_and(p)])
    end
    a
end

function parse_and(p)
    a = parse_not(p)
    while iskw(p, "AND")
        next!(p); a = Op(:and, [a, parse_not(p)])
    end
    a
end

function parse_not(p)
    if iskw(p, "NOT")
        next!(p); return Op(:not, [parse_not(p)])
    end
    parse_cmp(p)
end

const CMP = Dict("=" => :eq, "<>" => :ne, "<" => :lt, ">" => :gt, "<=" => :le, ">=" => :ge)

function parse_cmp(p)
    a = parse_add(p)
    t = peek(p)
    if t.kind == :op && haskey(CMP, t.s)
        next!(p)
        a = Op(CMP[t.s], [a, parse_add(p)])
    end
    a
end

function parse_add(p)
    a = parse_mul(p)
    while isop(p, "+") || isop(p, "-")
        o = next!(p).s
        a = Op(o == "+" ? :+ : :-, [a, parse_mul(p)])
    end
    a
end

function parse_mul(p)
    a = parse_unary(p)
    while isop(p, "*") || isop(p, "/")
        o = next!(p).s
        a = Op(o == "*" ? :* : :/, [a, parse_unary(p)])
    end
    a
end

function parse_unary(p)
    if isop(p, "-")
        next!(p); return Op(:neg, [parse_unary(p)])
    elseif isop(p, "+")
        next!(p); return parse_unary(p)
    end
    parse_pow(p)
end

function parse_pow(p)
    a = parse_primary(p)
    if isop(p, "^")
        next!(p)
        a = Op(:^, [a, parse_unary(p)])
    end
    a
end

function parse_subs(p)
    subs = Sub[]
    expect!(p, "[")
    while true
        t = next!(p)
        t.kind == :name || throw(ParseError_("subscript atteso, trovato '$(t.s)'"))
        bang = false
        if isop(p, "!")
            next!(p); bang = true
        end
        push!(subs, Sub(t.s, bang))
        isop(p, ",") ? next!(p) : break
    end
    expect!(p, "]")
    subs
end

function parse_number(p)
    neg = false
    if isop(p, "-")
        next!(p); neg = true
    elseif isop(p, "+")
        next!(p)
    end
    t = next!(p)
    t.kind == :num || throw(ParseError_("numero atteso, trovato '$(t.s)'"))
    neg ? -t.v : t.v
end

"""Tabella lookup: ( [(x0,y0)-(x1,y1)...], (x,y), ... ) — la parentesi aperta è già consumata."""
function parse_lookup_body(p)
    if isop(p, "[")
        depth = 0
        while true
            t = next!(p)
            t.kind == :eof && throw(ParseError_("riquadro lookup non chiuso"))
            t.kind == :op && t.s == "[" && (depth += 1)
            if t.kind == :op && t.s == "]"
                depth -= 1
                depth == 0 && break
            end
        end
        isop(p, ",") && next!(p)
    end
    xs, ys = Float64[], Float64[]
    while isop(p, "(")
        next!(p)
        push!(xs, parse_number(p)); expect!(p, ",")
        push!(ys, parse_number(p)); expect!(p, ")")
        isop(p, ",") ? next!(p) : break
    end
    expect!(p, ")")
    isempty(xs) && throw(ParseError_("lookup senza punti"))
    LookupTable(xs, ys)
end

function parse_primary(p)
    t = peek(p)
    if t.kind == :num
        next!(p); return Num(t.v)
    elseif t.kind == :str
        next!(p); return Str(t.s)
    elseif t.kind == :op && t.s == "("
        next!(p)
        e = parse_expr(p)
        expect!(p, ")")
        return e
    elseif t.kind == :name
        next!(p)
        name = t.s
        if isop(p, "(")
            next!(p)
            if name == "with lookup"
                x = parse_expr(p)
                expect!(p, ",")
                expect!(p, "(")
                tab = parse_lookup_body(p)
                expect!(p, ")")
                return Call(name, Node[x, tab])
            end
            args = Node[]
            if !isop(p, ")")
                while true
                    push!(args, parse_expr(p))
                    isop(p, ",") ? next!(p) : break
                end
            end
            expect!(p, ")")
            return Call(name, args)
        elseif isop(p, "[")
            return VRef(name, parse_subs(p))
        end
        return VRef(name, Sub[])
    elseif t.kind == :kw && t.s == "NA"
        next!(p); return Num(-1.298074214633707e33)
    end
    throw(ParseError_("espressione inattesa a '$(t.s)'"))
end

# ------------------------------------------------------------------ equazioni

struct Equation
    line::Int
    name::String
    subs::Vector{Sub}                  # subscript del membro sinistro
    except::Vector{Vector{Sub}}        # liste :EXCEPT:
    kind::Symbol                       # :eq :data :lookup :range
    datamode::Symbol                   # :interpolate :raw :look_forward :none
    rhs::Node
    elements::Vector{String}           # solo per :range
    units::String
end

function parse_numarray(s::AbstractString)
    vals = Float64[]
    for m in eachmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", s)
        push!(vals, parse(Float64, m.match))
    end
    vals
end

function parse_range_elements(s::AbstractString)
    els = String[]
    for part in split(s, ',')
        part = strip(part)
        isempty(part) && continue
        m = match(r"^\(\s*([A-Za-z_]*)(\d+)\s*-\s*([A-Za-z_]*)(\d+)\s*\)$", part)
        if m !== nothing
            for k in parse(Int, m[2]):parse(Int, m[4])
                push!(els, normname(m[1] * string(k)))
            end
        else
            occursin("->", part) && throw(ParseError_("mapping di subscript non supportato"))
            push!(els, normname(part))
        end
    end
    els
end

function parse_equation(b::RawBlock)
    s = b.eq
    try
        # definizione di subscript range: Nome: a, b, c
        m = match(r"^([^=:\[\(]+?)\s*:\s*(?!(EXCEPT|INTERPOLATE|RAW|LOOK FORWARD|HOLD BACKWARD|SUPPLEMENTARY)\s*:)(?!=)(.*)$"s, s)
        if m !== nothing && !occursin('=', s)
            return Equation(b.line, normname(m[1]), Sub[], Vector{Sub}[], :range, :none,
                            Num(0), parse_range_elements(m[3]), b.units)
        end
        # TABBED ARRAY e liste numeriche si riconoscono sul testo
        eqpos = findfirst('=', s)
        if eqpos !== nothing
            rhs_text = strip(s[nextind(s, eqpos):end])
            if startswith(uppercase(rhs_text), "TABBED ARRAY")
                lhs_toks = tokenize(s[1:prevind(s, eqpos)])
                name, subs, exc, mode = parse_lhs(P(lhs_toks, 1))
                inner = rhs_text[findfirst('(', rhs_text)+1:findlast(')', rhs_text)-1]
                return Equation(b.line, name, subs, exc, :eq, :none,
                                NumArray(parse_numarray(inner)), String[], b.units)
            end
        end
        toks = tokenize(s)
        p = P(toks, 1)
        name, subs, exc, mode = parse_lhs(p)
        t = next!(p)
        if t.kind == :op && t.s == "("
            tab = parse_lookup_body(p)
            peek(p).kind == :eof || throw(ParseError_("testo dopo la tabella lookup"))
            return Equation(b.line, name, subs, exc, :lookup, :none, tab, String[], b.units)
        end
        isdata = t.kind == :op && t.s == ":="
        isdata || (t.kind == :op && t.s == "=") || throw(ParseError_("'=' atteso dopo il nome"))
        if peek(p).kind == :eof
            rhs = Num(NaN)  # equazione vuota (es. SAVEPER = ): risolta dopo
        else
            # lista di costanti: 1, 2, 3; 4, 5, 6;
            save = p.i
            vals = Float64[]
            islist = false
            try
                while true
                    push!(vals, parse_number(p))
                    if isop(p, ",") || isop(p, ";")
                        islist = true
                        next!(p)
                        peek(p).kind == :eof && break
                    else
                        break
                    end
                end
                peek(p).kind == :eof || (islist = false)
            catch
                islist = false
            end
            if islist
                rhs = NumArray(vals)
            else
                p.i = save
                rhs = parse_expr(p)
                peek(p).kind == :eof || throw(ParseError_("testo inatteso '$(peek(p).s)'"))
            end
        end
        return Equation(b.line, name, subs, exc, isdata ? :data : :eq,
                        isdata ? (mode == :none ? :interpolate : mode) : :none, rhs, String[], b.units)
    catch e
        e isa ParseError_ || rethrow()
        snippet = first(s, 120)
        throw(ParseError_("riga $(b.line): $(e.msg)\n  in: $snippet"))
    end
end

function parse_lhs(p::P)
    t = next!(p)
    t.kind == :name || throw(ParseError_("nome di variabile atteso"))
    name = t.s
    subs = isop(p, "[") ? parse_subs(p) : Sub[]
    exc = Vector{Sub}[]
    mode = :none
    while peek(p).kind == :kw
        kw = next!(p).s
        if kw == "EXCEPT"
            push!(exc, parse_subs(p))
            while isop(p, ",")
                next!(p); push!(exc, parse_subs(p))
            end
        elseif kw == "INTERPOLATE"
            mode = :interpolate
        elseif kw == "RAW"
            mode = :raw
        elseif kw == "LOOK FORWARD"
            mode = :look_forward
        elseif kw == "HOLD BACKWARD"
            mode = :hold
        else
            throw(ParseError_("parola chiave :$kw: non supportata"))
        end
    end
    return name, subs, exc, mode
end

parse_model(path) = [parse_equation(b) for b in read_blocks(path) if !isempty(strip(b.eq))]
