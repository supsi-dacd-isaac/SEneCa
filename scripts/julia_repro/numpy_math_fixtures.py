"""Bitwise EXP checks with difficult synthetic values and native platform pins."""
from pathlib import Path
import warnings

from .common import CONFIG, RUNTIME, dump, read, run_logged
from .numpy_math_patch import platform_contract


def oracle(target):
    import numpy as np
    import pysd
    if pysd.__version__ != "3.14.3" or np.__version__ != "2.4.6":
        raise RuntimeError("NumPy math fixtures require the frozen Python environment")
    rng = np.random.default_rng(20261009)
    points = np.concatenate((np.array([-745., -744., -710., -709., -1., -0., 0., 1., 709.,
                                      -5.553533227325897]), rng.uniform(-740., 709., 4096),
                             np.nextafter(np.linspace(-10, 10, 401), np.inf)))
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    left, right, expected = [points], [np.zeros_like(points)], [np.exp(points)]
    records = [{"name": "exp", "component": "synthetic", "offset": 0,
                "count": len(points), "time": 0, "phase": "fixture"}]
    offset = len(points)
    exponents = np.concatenate(([-50., -30., -20., -3., -2., -1., -.5, 0., .5, 1., 2., 3.,
                                15., 20., 30., 1/30], rng.uniform(-8, 8, 40)))
    for exponent in exponents:
        bases = np.exp(rng.uniform(-10, 10, 64))
        for name in ("numpy_power", "python_power"):
            result = (np.power(bases, exponent) if name == "numpy_power" else
                      np.asarray([float(base) ** float(exponent) for base in bases]))
            left.append(bases); right.append(np.full_like(bases, exponent)); expected.append(result)
            records.append({"name": name, "component": "synthetic", "offset": offset,
                            "count": len(bases), "time": 0, "phase": "fixture"})
            offset += len(bases)
    for name in ("numpy_power", "python_power"):
        bases = np.array([-2., -1., -0., 0., 1., 2.])
        for exponent in (0., 1., 2., 3., .5):
            selected = bases[bases >= 0] if exponent == .5 else bases
            result = (np.power(selected, exponent) if name == "numpy_power" else
                      np.asarray([float(base) ** exponent for base in selected]))
            left.append(selected); right.append(np.full_like(selected, exponent)); expected.append(result)
            records.append({"name": name, "component": "signed_zero_negative_integer", "offset": offset,
                            "count": len(selected), "time": 0, "phase": "fixture"})
            offset += len(selected)
    np.concatenate(left).astype("<f8").tofile(target / "input.bin")
    np.concatenate(right).astype("<f8").tofile(target / "right.bin")
    np.concatenate(expected).astype("<f8").tofile(target / "expected.bin")
    dump(target / "records.json", records)
    dump(target / "platform.json", platform_contract())


def run(directory):
    from .execution import julia_command
    target = Path(directory).resolve() / "numpy-math-fixtures"
    command = f"from scripts.julia_repro.numpy_math_fixtures import oracle; oracle({str(target)!r})"
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command], target / "oracle.log")
    run_logged([*julia_command(), CONFIG / "test_numpy_math.jl", target], target / "julia.log")
    result = read(target / "results.json")
    translated = target / "translated"
    for reference, runtime in ((True, "python-reference"), (False, "python-julia")):
        command = ("from scripts.julia_repro.numpy_math_fixtures import prepare_models; "
                   f"prepare_models({str(translated)!r}, reference={reference!r})")
        run_logged([RUNTIME / runtime / "bin/python", "-B", "-c", command],
                   translated / ("oracle.log" if reference else "translation.log"))
    run_logged([*julia_command(), CONFIG / "test_numpy_math_models.jl", translated], translated / "julia.log")
    result["translated"] = read(translated / "results.json")
    result["pass"] = result["pass"] and result["translated"]["pass"]
    dump(target / "results.json", result)
    return result


def model_case():
    values = [4.2295703667071044e-05, 60044137.971663624, 1.9932962504268722e-14,
              4.6569883610240055, 1.25, 3.5]
    body = "D: a,b,c,d,e,f ~~|\nScalar base=4.2295703667071044e-05 ~~|\n"
    body += "Scalar exp input=-5.553533227325897 ~~|\n"
    for label, value in zip("abcdef", values):
        body += f"Array base[{label}]={value!r} ~~|\n"
    body += "Array exp input[D]=-5.553533227325897+Array base[D]/1e8 ~~|\n"
    expressions = {"Scalar exp": "EXP(Scalar exp input)", "Array exp[D]": "EXP(Array exp input[D])"}
    for label, exponent in (("reciprocal", "-1"), ("root", "0.5"), ("square", "2"), ("fraction", "1/30")):
        expressions[f"Scalar {label}"] = f"Scalar base^({exponent})"
        expressions[f"Array {label}[D]"] = f"Array base[D]^({exponent})"
        expressions[f"Selected {label}"] = f"Array base[a]^({exponent})"
    expressions["Scalar composed"] = "(Scalar base+Time/10+0.125)^(1/30)+Scalar base^2"
    expressions["Array composed[D]"] = "(Array base[D]+Time/10+0.125)^(1/30)+Array base[D]^2"
    expressions["Power call scalar"] = "POWER(Scalar base,2)"
    expressions["Power call array[D]"] = "POWER(Array base[D],2)"
    body += "Z: negative,negzero,zero,positive ~~|\nSigned base[negative]=-2 ~~|\nSigned base[negzero]=-0.0 ~~|\nSigned base[zero]=0 ~~|\nSigned base[positive]=2 ~~|\n"
    expressions["Signed square[Z]"] = "Signed base[Z]^2"
    expressions["Signed odd[Z]"] = "Signed base[Z]^3"
    expressions["Negative fraction[Z]"] = "Signed base[Z]^0.5"
    body += "\n".join(f"{name}={expression} ~~|" for name, expression in expressions.items())
    body += "\nStock=INTEG(1,0) ~~|\nINITIAL TIME=0 ~~|\nFINAL TIME=1 ~~|\nTIME STEP=1 ~~|\nSAVEPER=1 ~~|\n"
    return "{UTF-8}\n" + body, [name.split("[")[0] for name in expressions]


def prepare_models(target, reference=False):
    import numpy as np
    import pysd
    target = Path(target)
    folder = target / ("python" if reference else "julia")
    folder.mkdir(parents=True, exist_ok=True)
    body, outputs = model_case()
    source = folder / "math.mdl"
    source.write_text(body)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        if reference:
            model = pysd.read_vensim(source)
            frame = model.run(return_columns=outputs, return_timestamps=[0, 1], flatten_output=False)
            records, values, offset = [], [], 0
            for name in outputs:
                for time in (0, 1):
                    value = np.asarray(frame.loc[time, name], dtype=np.float64).ravel(order="C")
                    if name != "Negative fraction" and not np.isfinite(value).all():
                        raise ValueError("Unexpected nonfinite translated math oracle")
                    records.append({"name": name, "identifier": model._namespace[name], "time": time,
                                    "offset": offset, "count": len(value), "expected_nan": name == "Negative fraction"})
                    values.append(value)
                    offset += len(value)
            np.concatenate(values).astype("<f8").tofile(target / "expected.bin")
            dump(target / "records.json", records)
        else:
            from .builder_patch import apply
            apply()
            # Deliberate repeated apply verifies that fixture setup cannot undo
            # the later NumPy arithmetic patch.
            from .ode_patch import apply as apply_ode
            apply_ode()
            path = pysd.translate_to_julia(source, backend="ode", data_format="json")
            dump(target / "model.json", {"path": str(path.resolve())})
    messages = [str(item.message) for item in captured]
    if any(not reference or "invalid value encountered in power" not in message for message in messages):
        raise ValueError(f"Unexpected translated math warning: {messages}")
    dump(folder / "warnings.json", messages)
