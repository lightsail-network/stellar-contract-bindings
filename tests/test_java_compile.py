"""Compile and run the generated Java, rather than only asserting on its text.

Text assertions cannot tell whether generated source compiles, whether Java 8
type inference accepts the codec lambdas, or whether Lombok produces what the
code expects; only a compiler can. The harnesses in tests/java go one step
further and run the decoders against real SCVals.

The toolchain is resolved lazily and the module skips when it is unavailable,
so contributors without a JDK still get a green suite. CI sets
``STELLAR_BINDINGS_REQUIRE_JAVAC=1`` to turn every skip into a failure. The
harness that calls the reference contract on testnet deploys it through the
fixture in conftest.py, and skips when ``STELLAR_BINDINGS_OFFLINE=1``.
"""

import os
import pathlib
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from stellar_sdk import xdr

from stellar_contract_bindings.java import (
    generate_binding,
    generate_binding_with_diagnostics,
    java_string_literal,
)
from stellar_contract_bindings.metadata import get_token_sc_spec_entry

from .reference_contract import specs as python_contract_specs
from .java_spec_helpers import (
    DATA,
    MAP_FORMAT,
    SINGLE,
    TOPIC,
    VEC_FORMAT,
    address,
    bytes_n,
    enum,
    error,
    error_enum,
    event,
    function,
    map_of,
    option,
    result,
    scalar,
    struct,
    tuple_case,
    tuple_of,
    u32,
    udt,
    union,
    vec,
    void,
    void_case,
)

# The generated code compiles against the first two. stellar-sdk publishes JDK
# 8 bytecode, which is what pins --release 8 below; running the harnesses
# reaches the SDK's own dependencies.
_JARS = {
    "lombok.jar": "https://repo1.maven.org/maven2/org/projectlombok/lombok/1.18.34/lombok-1.18.34.jar",
    "stellar-sdk.jar": "https://repo1.maven.org/maven2/network/lightsail/stellar-sdk/4.0.1/stellar-sdk-4.0.1.jar",
    "gson.jar": "https://repo1.maven.org/maven2/com/google/code/gson/gson/2.14.0/gson-2.14.0.jar",
    "bcprov.jar": "https://repo1.maven.org/maven2/org/bouncycastle/bcprov-jdk18on/1.84/bcprov-jdk18on-1.84.jar",
    "commons-codec.jar": "https://repo1.maven.org/maven2/commons-codec/commons-codec/1.22.0/commons-codec-1.22.0.jar",
    # Only the live harness reaches the network, through OkHttp.
    "okhttp.jar": "https://repo1.maven.org/maven2/com/squareup/okhttp3/okhttp/4.12.0/okhttp-4.12.0.jar",
    "okio.jar": "https://repo1.maven.org/maven2/com/squareup/okio/okio-jvm/3.6.0/okio-jvm-3.6.0.jar",
    "kotlin-stdlib.jar": "https://repo1.maven.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/1.9.10/kotlin-stdlib-1.9.10.jar",
}

_REQUIRED = os.environ.get("STELLAR_BINDINGS_REQUIRE_JAVAC") == "1"

_JAVA_SOURCES = pathlib.Path(__file__).parent / "java"


def _unavailable(reason: str):
    """Skip locally, fail in CI."""
    if _REQUIRED:
        pytest.fail(f"{reason} (STELLAR_BINDINGS_REQUIRE_JAVAC=1)")
    pytest.skip(reason)


def _cache_dir() -> Path:
    override = os.environ.get("STELLAR_BINDINGS_JAR_CACHE")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "stellar-contract-bindings" / "jars"


@pytest.fixture(scope="module")
def classpath() -> str:
    if shutil.which("javac") is None or shutil.which("java") is None:
        _unavailable("javac and java are not both on PATH")
    cache = _cache_dir()
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _unavailable(f"jar cache {cache} is not usable: {exc}")
    for name, url in _JARS.items():
        target = cache / name
        if target.exists() and target.stat().st_size > 0:
            continue
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                target.write_bytes(response.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            target.unlink(missing_ok=True)
            _unavailable(f"could not fetch {name}: {exc}")
    return os.pathsep.join(str(cache / name) for name in _JARS)


def _javac(sources, classpath: str, out: Path) -> None:
    # -proc:full runs Lombok; --release 8 is what the SDK jar targets, and is
    # the constraint that rules out records, sealed types and var. Every lint
    # is an error, so a warning in the generated code fails the build here
    # before it shows up in a user's.
    result = subprocess.run(
        [
            "javac",
            "--release",
            "8",
            "-Xlint:all,-options",
            "-Werror",
            "-encoding",
            "US-ASCII",
            "-proc:full",
            "-cp",
            os.pathsep.join([classpath, str(out)]),
            "-processorpath",
            classpath,
            "-d",
            str(out),
            *[str(source) for source in sources],
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"generated Java did not compile:\n{result.stdout}\n{result.stderr}"
        )


def _write_client(source: str, tmp_path: Path, class_name: str = "Client") -> Path:
    client = tmp_path / "com" / "example" / f"{class_name}.java"
    client.parent.mkdir(parents=True, exist_ok=True)
    # US-ASCII on purpose: the generator promises pure ASCII output.
    client.write_text(source, encoding="ascii")
    return client


def _compile(
    source: str, classpath: str, tmp_path: Path, class_name: str = "Client"
) -> None:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    _javac([_write_client(source, tmp_path, class_name)], classpath, out)


def _run_harness(
    source: str, harness: str, classpath: str, tmp_path: Path, *args: str
) -> None:
    """Compile generated bindings with a harness beside them, and run it.

    Each harness prints one line per check and ends with a summary line;
    ``args`` are passed to its main method.
    """
    client = _write_client(source, tmp_path)
    harness_path = tmp_path / f"{harness}.java"
    shutil.copyfile(_JAVA_SOURCES / f"{harness}.java", harness_path)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    _javac([client, harness_path], classpath, out)

    run = subprocess.run(
        ["java", "-cp", os.pathsep.join([classpath, str(out)]), harness, *args],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, f"{run.stdout}\n{run.stderr}"
    assert "all checks passed" in run.stdout
    assert "FAIL" not in run.stdout


def _generate(specs, **kwargs) -> str:
    return generate_binding(specs, package="com.example", **kwargs)


class TestGeneratedJavaCompiles:
    def test_stellar_asset_contract(self, classpath, tmp_path):
        """The SAC spec: every common scalar type, plus 13 event declarations."""
        _compile(_generate(get_token_sc_spec_entry()), classpath, tmp_path)

    def test_the_test_contract(self, classpath, tmp_path):
        """Structs, tuple structs, enums, error enums, a union, keywords, docs."""
        _compile(_generate(python_contract_specs()), classpath, tmp_path)

    def test_a_custom_class_name(self, classpath, tmp_path):
        _compile(
            _generate(python_contract_specs(), class_name="Token"),
            classpath,
            tmp_path,
            "Token",
        )

    def test_a_class_named_after_the_sdk_base_class(self, classpath, tmp_path):
        _compile(
            _generate(python_contract_specs(), class_name="ContractClient"),
            classpath,
            tmp_path,
            "ContractClient",
        )

    def test_a_class_named_after_a_builder(self, classpath, tmp_path):
        _compile(
            _generate(python_contract_specs(), class_name="Builder"),
            classpath,
            tmp_path,
            "Builder",
        )

    def test_every_scalar_in_every_position(self, classpath, tmp_path):
        """Each scalar as a field, a parameter, an output and an event topic."""
        scalars = [
            t
            for t in xdr.SCSpecType
            if t.name.startswith("SC_SPEC_TYPE_")
            and t
            not in (
                xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
                xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
                xdr.SCSpecType.SC_SPEC_TYPE_VEC,
                xdr.SCSpecType.SC_SPEC_TYPE_MAP,
                xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
                xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N,
                xdr.SCSpecType.SC_SPEC_TYPE_UDT,
            )
        ]
        fields = [(f"f{i}".encode(), scalar(t)) for i, t in enumerate(scalars)]
        fields.append((b"fixed", bytes_n(32)))
        specs = [struct(b"Every", fields)]
        for i, (name, td) in enumerate(fields):
            specs.append(
                function(f"fn{i}".encode(), [(b"a", td), (b"o", option(td))], [td])
            )
            specs.append(
                event(f"ev{i}".encode(), [b"ev"], [(b"t", td, TOPIC), (b"d", td, DATA)])
            )
        _compile(_generate(specs), classpath, tmp_path)

    def test_nested_collections(self, classpath, tmp_path):
        """A collection inside a collection puts one lambda inside another.

        Java forbids shadowing a lambda parameter, so each nesting level needs
        its own name, and Java 8 has to infer every level's type.
        """
        specs = [
            struct(b"Thing", [(b"value", u32())]),
            function(
                b"nested",
                [
                    (b"a", vec(vec(u32()))),
                    (b"b", map_of(u32(), vec(udt(b"Thing")))),
                    (b"c", vec(map_of(u32(), vec(option(u32()))))),
                    (b"d", map_of(vec(u32()), map_of(u32(), vec(u32())))),
                    (b"e", option(vec(option(map_of(u32(), option(u32())))))),
                    (
                        b"f",
                        vec(
                            tuple_of(
                                vec(u32()),
                                map_of(u32(), tuple_of(u32(), option(u32()))),
                            )
                        ),
                    ),
                ],
                [map_of(vec(u32()), option(vec(tuple_of(u32(), udt(b"Thing")))))],
            ),
            struct(
                b"Holder",
                [
                    (b"a", vec(vec(option(udt(b"Thing"))))),
                    (b"b", map_of(option(u32()), tuple_of(vec(u32()), void()))),
                ],
            ),
        ]
        _compile(_generate(specs), classpath, tmp_path)

    def test_tuples_at_every_arity(self, classpath, tmp_path):
        """Twelve is the most SCSpecTypeTuple can hold."""
        specs = [
            struct(b"Thing", [(b"value", u32())]),
            union(b"Choice", [tuple_case(b"pair", u32(), udt(b"Thing"))]),
            function(
                b"tuples",
                [(f"a{n}".encode(), tuple_of(*[u32()] * n)) for n in range(1, 13)],
                [tuple_of(u32(), udt(b"Thing"), tuple_of(u32()))],
            ),
            function(
                b"nested",
                [
                    (b"a", vec(tuple_of(u32(), u32()))),
                    (b"b", map_of(u32(), tuple_of(u32(), u32(), u32()))),
                    (b"c", option(tuple_of(u32(), u32()))),
                    (b"d", tuple_of()),
                ],
                [tuple_of()],
            ),
        ]
        source = _generate(specs)
        for n in range(1, 13):
            assert f"public static class Tuple{n}<" in source
        _compile(source, classpath, tmp_path)

    def test_every_event_data_format(self, classpath, tmp_path):
        """SINGLE_VALUE, VEC and MAP take different decoding paths."""
        specs = [
            struct(b"Thing", [(b"value", u32())]),
            event(b"single", [b"single"], [(b"amount", u32(), DATA)], SINGLE),
            event(b"empty", [b"empty"], [], SINGLE),
            event(b"no_prefix", [], [(b"who", u32(), TOPIC)], SINGLE),
            event(
                b"vec",
                [b"vec"],
                [
                    (b"who", u32(), TOPIC),
                    (b"a", u32(), DATA),
                    (b"b", udt(b"Thing"), DATA),
                ],
                VEC_FORMAT,
            ),
            event(
                b"mapped",
                [b"mapped"],
                [
                    (b"who", u32(), TOPIC),
                    (b"required", vec(u32()), DATA),
                    (b"optional", option(udt(b"Thing")), DATA),
                    (b"nested", option(vec(option(u32()))), DATA),
                ],
                MAP_FORMAT,
            ),
            event(
                b"kw",
                [b"kw"],
                [(b"class", u32(), TOPIC), (b"new", u32(), DATA)],
                SINGLE,
            ),
            event(
                b"composite",
                [b"a", b"b"],
                [
                    (b"t", tuple_of(u32(), option(u32())), TOPIC),
                    (b"r", result(u32(), error()), DATA),
                ],
                SINGLE,
            ),
        ]
        _compile(_generate(specs), classpath, tmp_path)

    def test_names_that_collide_with_generated_ones(self, classpath, tmp_path):
        """Everything the generator emits shares one nested-class namespace."""
        specs = [
            struct(b"Client", [(b"v", u32())]),
            struct(b"MethodOptions", [(b"v", u32())]),
            struct(b"Result", [(b"r", result(u32(), error()))]),
            struct(b"Tuple2", [(b"t", tuple_of(u32(), u32()))]),
            struct(b"Event", [(b"v", u32())]),
            struct(b"DecodedEvent", [(b"v", u32())]),
            struct(b"UnparsedEventException", [(b"v", u32())]),
            struct(b"TopicFilterBuilder", [(b"v", u32())]),
            struct(b"Kind", [(b"v", u32())]),
            struct(b"Codec", [(b"v", u32())]),
            # Fields named after the locals and lambda parameters their own
            # methods use.
            struct(
                b"Locals",
                [
                    (b"fields", u32()),
                    (b"elements", vec(u32())),
                    (b"element", vec(vec(u32()))),
                    (b"scVal", u32()),
                    (b"some", option(u32())),
                    (b"map_key", map_of(u32(), u32())),
                    (b"tuple_values", tuple_of(u32(), u32())),
                    (b"topics", u32()),
                    (b"data", u32()),
                    (b"row", u32()),
                    (b"ok", result(u32(), error())),
                ],
            ),
            struct(
                b"0", [(b"0", vec(u32())), (b"1", tuple_of(u32(), tuple_of(u32())))]
            ),
            struct(b"snake_type", [(b"v", u32())]),
            struct(
                b"Holder", [(b"thing", udt(b"snake_type")), (b"self", udt(b"Holder"))]
            ),
            struct(
                b"Getters",
                [(b"foo", u32()), (b"Foo", u32()), (b"foo_", u32()), (b"class", u32())],
            ),
            # Lombok warns, and -Werror fails, when two fields derive one getter.
            struct(
                b"Booleans",
                [
                    (b"is_ready", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)),
                    (b"ready", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)),
                    (b"is_done", option(scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL))),
                    (b"done", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)),
                    (b"is", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)),
                ],
            ),
            # A case named after match's type parameter, and one holding a
            # tuple whose element lambdas sit one level down.
            union(
                b"Generic", [void_case(b"R"), tuple_case(b"T", tuple_of(vec(u32())))]
            ),
            # Fields whose builder setters would override Object's methods.
            struct(
                b"Waits", [(b"wait", u32()), (b"notify", u32()), (b"finalize", u32())]
            ),
            # Enum constants named after what the enum body qualifies with.
            error_enum(
                b"Shadows", [(b"Codec", 1), (b"Optional", 2), (b"Scv", 3), (b"org", 4)]
            ),
            enum(b"Shadows2", [(b"Scv", 1), (b"Codec", 2)]),
            # Types named like the variables the generated code declares.
            struct(b"scVal", [(b"v", u32())]),
            struct(b"data", [(b"v", u32())]),
            struct(b"element", [(b"v", u32())]),
            struct(
                b"Lowercase",
                [
                    (b"data", udt(b"data")),
                    (b"element", vec(udt(b"element"))),
                    (b"scVal", udt(b"scVal")),
                ],
            ),
            function(b"lowercase", [(b"data", udt(b"data"))], [udt(b"scVal")]),
            event(
                b"lowercase",
                [b"lowercase"],
                [
                    (b"data", udt(b"data"), DATA),
                    (b"element", vec(udt(b"element")), TOPIC),
                ],
            ),
            event(
                b"waits",
                [b"waits"],
                [(b"wait", u32(), TOPIC), (b"notify", u32(), TOPIC)],
            ),
            struct(b"Empty", []),
            enum(b"Nothing", []),
            union(b"Nowhere", []),
            union(
                b"Members",
                [
                    void_case(b"symbol"),
                    tuple_case(b"value", u32()),
                    tuple_case(b"elements", vec(u32())),
                ],
            ),
            enum(b"Values", [(b"value", 0), (b"values", 1)]),
            error_enum(b"Codes", [(b"value", 0)]),
            union(
                b"Cases",
                [
                    void_case(b"Cases"),
                    void_case(b"Kind"),
                    void_case(b"Holder"),
                    tuple_case(b"Client", udt(b"Client")),
                    tuple_case(b"String", scalar(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)),
                    void_case(b"Void"),
                    tuple_case(b"pair", udt(b"Holder"), udt(b"Kind")),
                ],
            ),
            function(b"close", [], []),
            function(b"invoke", [(b"function_name", u32())], []),
            # Parameters named after the lambda parameters of their own codec.
            function(
                b"lambdas",
                [
                    (b"element", vec(vec(u32()))),
                    (b"element1", u32()),
                    (b"some", option(u32())),
                    (b"sc_val", u32()),
                    (b"map_key", map_of(u32(), option(u32()))),
                    (b"ok", result(u32(), error())),
                    (b"tuple_values", u32()),
                    (b"pair", tuple_of(vec(u32()), option(u32()))),
                ],
                [tuple_of(vec(u32()), option(u32()))],
            ),
            function(b"tupled", [(b"element", tuple_of(vec(u32())))], []),
            # Functions named after the generated helpers, with the parameter
            # types those helpers take.
            function(
                b"decode_void", [(b"v", scalar(xdr.SCSpecType.SC_SPEC_TYPE_VAL))], []
            ),
            function(
                b"encode_topic", [(b"v", scalar(xdr.SCSpecType.SC_SPEC_TYPE_VAL))], []
            ),
            function(b"bytes_n", [(b"v", bytes_n(9))], [bytes_n(9)]),
            function(
                b"struct_field",
                [
                    (b"v", map_of(u32(), u32())),
                    (b"n", scalar(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)),
                ],
                [],
            ),
            function(b"to_string", [], [scalar(xdr.SCSpecType.SC_SPEC_TYPE_STRING)]),
            function(b"parse_event", [(b"options", u32()), (b"v", u32())], [void()]),
            function(b"same", [(b"a", u32())], []),
            function(b"same", [(b"a", u32()), (b"b", u32())], []),
            event(
                b"clash",
                [b"clash"],
                [
                    (b"foo", u32(), TOPIC),
                    (b"foo_set", u32(), TOPIC),
                    (b"row", u32(), TOPIC),
                    (b"build", u32(), TOPIC),
                    (b"topic_values", u32(), TOPIC),
                ],
            ),
            event(
                b"lambdas",
                [b"lambdas"],
                [
                    (b"element", vec(u32()), TOPIC),
                    (b"some", option(u32()), TOPIC),
                    (b"topics", u32(), TOPIC),
                    (b"data", vec(u32()), DATA),
                    (b"map_key", map_of(u32(), u32()), DATA),
                ],
                VEC_FORMAT,
            ),
            event(
                b"lambdas_map",
                [b"lambdas_map"],
                [(b"data", u32(), DATA), (b"element", vec(u32()), DATA)],
                MAP_FORMAT,
            ),
            event(
                b"hostile_map",
                [b"hostile_map"],
                [
                    (b'k", "v', u32(), DATA),
                    (b"is_done", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL), TOPIC),
                    (b"done", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL), DATA),
                ],
                MAP_FORMAT,
            ),
            union(
                b"Hostile",
                [
                    tuple_case(b'a", "b', u32()),
                    tuple_case(b"element", tuple_of(vec(u32()))),
                ],
            ),
            event(b"unnamed", [b"unnamed"], [(b"", u32(), TOPIC), (b"_", u32(), DATA)]),
            event(
                b"udt_param",
                [b"udt_param"],
                [(b"thing", udt(b"snake_type"), TOPIC), (b"kind", udt(b"Kind"), DATA)],
            ),
            event(b"Event", [b"event"], []),
            event(b"transfer", [b"a"], []),
            event(b"transfer", [b"b"], []),
        ]
        _compile(_generate(specs), classpath, tmp_path)

    def test_union_cases_named_after_helpers_and_members(self, classpath, tmp_path):
        """A case is a class nested in its union, so it can hide a helper from
        a sibling case that holds one; the helpers move aside instead."""
        specs = [
            union(
                b"U",
                [
                    tuple_case(b"Result", u32()),
                    tuple_case(b"Other", result(u32(), error())),
                    tuple_case(b"Tuple2", u32()),
                    tuple_case(b"Pair", tuple_of(u32(), u32())),
                    void_case(b"MethodOptions"),
                    void_case(b"Event"),
                    void_case(b"DecodedEvent"),
                    void_case(b"UnparsedEventException"),
                ],
            ),
            event(b"e", [b"e"], [(b"u", udt(b"U"), DATA)]),
            function(b"f", [(b"u", udt(b"U"))], [udt(b"U")]),
            # The members every enum and union already has.
            enum(
                b"E",
                [
                    (n, i)
                    for i, n in enumerate(
                        [
                            b"values",
                            b"valueOf",
                            b"name",
                            b"ordinal",
                            b"hashCode",
                            b"toString",
                            b"getValue",
                            b"fromValue",
                            b"toSCVal",
                            b"fromSCVal",
                        ]
                    )
                ],
            ),
            union(
                b"V",
                [
                    void_case(n)
                    for n in (
                        b"getKind",
                        b"toSCVal",
                        b"fromSCVal",
                        b"values",
                        b"getSymbol",
                        b"symbol",
                    )
                ],
            ),
            struct(
                b"S",
                [
                    (b"get_a", u32()),
                    (b"a", u32()),
                    (b"hash_code", u32()),
                    (b"equals", u32()),
                ],
            ),
        ]
        source, diagnostics = generate_binding_with_diagnostics(
            specs, package="com.example"
        )
        assert diagnostics == []
        for helper in (
            "Result2",
            "Tuple22",
            "MethodOptions2",
            "Event2",
            "DecodedEvent2",
            "UnparsedEventException2",
        ):
            assert helper in source
        _compile(source, classpath, tmp_path)

    def test_types_named_after_the_sdk_and_jdk_types_the_generator_uses(
        self, classpath, tmp_path
    ):
        """A nested type shadows a same-named import, so those are spelled in full."""
        from stellar_contract_bindings.java import _EXTERNAL_TYPES

        specs = [
            struct(name.encode(), [(b"v", u32())]) for name in sorted(_EXTERNAL_TYPES)
        ]
        specs += [
            error_enum(b"Code", [(b"Bad", 7)]),
            struct(
                b"Uses",
                [
                    (b"a", address()),
                    (b"b", scalar(xdr.SCSpecType.SC_SPEC_TYPE_STRING)),
                    (b"c", scalar(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)),
                    (
                        b"d",
                        vec(
                            map_of(
                                u32(), option(scalar(xdr.SCSpecType.SC_SPEC_TYPE_I128))
                            )
                        ),
                    ),
                    (b"e", result(void(), error())),
                    (b"f", tuple_of(u32(), scalar(xdr.SCSpecType.SC_SPEC_TYPE_VAL))),
                    (b"g", result(u32(), udt(b"Code"))),
                    (b"h", scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)),
                ],
            ),
            union(
                b"Choice",
                [void_case(b"a"), tuple_case(b"b", udt(b"Address"), udt(b"Uses"))],
            ),
            function(
                b"f", [(b"x", udt(b"Address")), (b"y", udt(b"Uses"))], [udt(b"Choice")]
            ),
            event(
                b"boom",
                [b"boom"],
                [(b"why", error(), DATA), (b"who", address(), TOPIC)],
                SINGLE,
            ),
            event(b"mapped", [b"mapped"], [(b"a", option(u32()), DATA)], MAP_FORMAT),
            # With every external spelled in full, a name hiding a package
            # root would break each of those references.
            struct(b"java", [(b"org", u32()), (b"lombok", vec(u32()))]),
            union(b"Roots", [void_case(b"java"), tuple_case(b"org", u32())]),
            enum(b"Root", [(b"java", 1), (b"org", 2)]),
            function(b"roots", [(b"org", u32()), (b"java", vec(u32()))], [u32()]),
            event(
                b"roots",
                [b"roots"],
                [(b"java", u32(), TOPIC), (b"org", u32(), DATA)],
                MAP_FORMAT,
            ),
        ]
        source = _generate(specs)
        # Not a single import is left: every one would be shadowed.
        assert "\nimport " not in source
        _compile(source, classpath, tmp_path)

    def test_results_in_every_awkward_position(self, classpath, tmp_path):
        code = udt(b"Code")
        specs = [
            error_enum(b"Code", [(b"Bad", 7)]),
            struct(b"Thing", [(b"v", u32())]),
            struct(
                b"A",
                [(b"r", result(scalar(xdr.SCSpecType.SC_SPEC_TYPE_BYTES), error()))],
            ),
            struct(b"B", [(b"r", result(void(), code))]),
            struct(b"C", [(b"r", result(udt(b"Thing"), code))]),
            struct(b"D", [(b"r", vec(result(u32(), code)))]),
            struct(b"E", [(b"r", map_of(u32(), result(u32(), code)))]),
            struct(b"F", [(b"r", tuple_of(result(u32(), code), u32()))]),
            struct(b"G", [(b"r", option(result(u32(), code)))]),
            struct(b"H", [(b"r", result(option(u32()), code))]),
            struct(b"I", [(b"r", result(result(u32(), code), error()))]),
            struct(b"J", [(b"r", result(vec(tuple_of(u32(), option(code))), code))]),
            function(b"take", [(b"r", result(u32(), code))], []),
            function(b"give", [], [result(u32(), code)]),
            function(b"give_nested", [], [result(vec(result(u32(), code)), code)]),
        ]
        source = _generate(specs)
        assert "AssembledTransaction<Long> give(" in source
        assert "take(Result<Long, Code> r)" in source
        _compile(source, classpath, tmp_path)

    def test_java_keywords_and_hostile_names(self, classpath, tmp_path):
        specs = [
            struct(
                b"Keywords",
                [
                    (b"new", u32()),
                    (b"class", u32()),
                    (b"var", u32()),
                    (b"_", u32()),
                    (b"", u32()),
                ],
            ),
            struct(b"import", [(b"package", u32())]),
            enum(b"enum", [(b"true", 0), (b"null", 1), (b"9", 2), (b"", 3)]),
            union(
                b"switch",
                [
                    void_case(b"case"),
                    tuple_case(b"default", udt(b"import")),
                    void_case(b""),
                ],
            ),
            function(
                b"switch",
                [(b"final", u32()), (b"void", u32()), (b"", u32())],
                [udt(b"switch")],
            ),
            function(b"", [], []),
            function('go", null); //'.encode(), [], []),
            struct(
                "中文".encode(),
                [
                    (
                        "字段 */".encode(),
                        u32(),
                        "文档 */ @param x \\u002a\\u002f".encode(),
                    )
                ],
                doc="结构 <b>".encode(),
            ),
            function(
                "方法".encode(),
                [("参数".encode(), udt("中文".encode()), "说明".encode())],
                [],
                doc="doc \x07 \x00 tab\there".encode(),
            ),
            event(
                'ev"ent'.encode(),
                ['pre"fix'.encode(), "中".encode()],
                [("参".encode(), u32(), TOPIC)],
                doc="event doc".encode(),
            ),
            struct(b"a::b::Thing", [(b"v", u32())]),
            struct(b"c::Thing", [(b"v", u32())]),
            struct(b"Other", [(b"x", udt(b"a::b::Thing")), (b"y", udt(b"c::Thing"))]),
        ]
        source = _generate(specs)
        assert source.isascii()
        _compile(source, classpath, tmp_path)


# Text a contract could publish as a name. Each one either ends a Java string
# literal, assembles an escape out of the characters that follow, or depends on
# the encoding javac reads the file with.
HOSTILE_NAMES = [
    "plain",
    'a", Scv.toSymbol("x',
    'ends with a quote "',
    "trailing backslash \\",
    "a\\nb",
    "\\u0022",
    "\\\\u0022",
    "newline\nhere",
    "carriage\r\nreturn",
    "tab\there",
    "bell\x07and\x00nul",
    "delete\x7f",
    "octal\x07" + "1",
    "中文名字",
    "emoji \U0001f48e",
    "combining é",
    "*/ still a comment breaker",
    "'single' quotes",
]


class TestJavaStringLiteralRoundTrips:
    """Whatever a contract publishes, the literal must evaluate back to it.

    Python can check this with ast.literal_eval; Java has no such function, so
    the check is the real thing: compile the literals and run the class, then
    compare the bytes the JVM actually produced.
    """

    def test_every_hostile_name_survives_compilation(self, classpath, tmp_path):
        literals = ",\n            ".join(java_string_literal(n) for n in HOSTILE_NAMES)
        source = f"""
import java.nio.charset.StandardCharsets;

public class LiteralRoundTrip {{
    public static void main(String[] args) {{
        String[] values = {{
            {literals}
        }};
        StringBuilder out = new StringBuilder();
        for (String value : values) {{
            for (byte b : value.getBytes(StandardCharsets.UTF_8)) {{
                out.append(String.format("%02x", b));
            }}
            out.append('\\n');
        }}
        System.out.print(out);
    }}
}}
"""
        src = tmp_path / "LiteralRoundTrip.java"
        src.write_text(source, encoding="ascii")
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        compiled = subprocess.run(
            [
                "javac",
                "--release",
                "8",
                "-encoding",
                "US-ASCII",
                "-d",
                str(out),
                str(src),
            ],
            capture_output=True,
            text=True,
        )
        assert compiled.returncode == 0, f"did not compile:\n{compiled.stderr}"

        run = subprocess.run(
            ["java", "-cp", str(out), "LiteralRoundTrip"],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr
        produced = run.stdout.strip().split("\n")
        expected = [name.encode("utf-8").hex() for name in HOSTILE_NAMES]
        assert produced == expected


class TestGeneratedCodeBehaves:
    """Compile the bindings with a harness beside them, and run it."""

    def test_round_trip_harness(self, classpath, tmp_path):
        """Every type the test contract declares, encoded and decoded."""
        _run_harness(
            _generate(python_contract_specs()), "RoundTripSmoke", classpath, tmp_path
        )

    def test_tuple_harness(self, classpath, tmp_path):
        specs = [
            struct(b"Holder", [(b"pair", tuple_of(u32(), u32()))]),
            struct(b"Wide", [(b"wide", tuple_of(*[u32()] * 12))]),
        ]
        _run_harness(_generate(specs), "TupleSmoke", classpath, tmp_path)

    def test_event_harness(self, classpath, tmp_path):
        """The four SAC transfer declarations share a topic shape and are
        separated only by the type of their data."""
        _run_harness(
            _generate(get_token_sc_spec_entry()), "EventSmoke", classpath, tmp_path
        )

    def test_result_harness(self, classpath, tmp_path):
        """Result, SCError and error enums, which the SAC spec does not use."""
        code = udt(b"Code")
        specs = [
            error_enum(b"Code", [(b"Bad", 7)]),
            struct(b"Wrapper", [(b"r", result(u32(), code))]),
            event(
                b"outcome", [b"outcome"], [(b"r", result(u32(), code), DATA)], SINGLE
            ),
            event(b"raw", [b"raw"], [(b"why", error(), DATA)], SINGLE),
            function(b"get", [], [result(u32(), code)]),
        ]
        _run_harness(_generate(specs), "ResultSmoke", classpath, tmp_path)

    def test_live_harness(self, classpath, request, tmp_path):
        """Simulates calls to the reference contract on testnet.

        The contract is asked for after the toolchain, so that a machine
        without a JDK skips without deploying anything.
        """
        contract_id = request.getfixturevalue("reference_contract_id")
        _run_harness(
            _generate(python_contract_specs()),
            "LiveSmoke",
            classpath,
            tmp_path,
            contract_id,
        )
