"""Compile the generated Java, rather than only asserting on its text.

Two of the three Java codegen bugs found so far (PR #27, and the nested-lambda
name collision fixed alongside this file) produced source that read correctly
and did not compile. Text assertions cannot catch that class of defect; only a
compiler can.

The toolchain is resolved lazily and the module skips when it is unavailable,
so contributors without a JDK still get a green suite. CI sets
``STELLAR_BINDINGS_REQUIRE_JAVAC=1`` to turn every skip into a failure.
"""

import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from stellar_sdk import xdr

from stellar_contract_bindings.java import generate_binding
from stellar_contract_bindings.metadata import get_token_sc_spec_entry

# The generated code compiles against these three. stellar-sdk publishes JDK 8
# bytecode, which is what pins --release 8 below.
_JARS = {
    "lombok.jar": "https://repo1.maven.org/maven2/org/projectlombok/lombok/1.18.34/lombok-1.18.34.jar",
    "javatuples.jar": "https://repo1.maven.org/maven2/org/javatuples/javatuples/1.2/javatuples-1.2.jar",
    "stellar-sdk.jar": "https://repo1.maven.org/maven2/network/lightsail/stellar-sdk/4.0.1/stellar-sdk-4.0.1.jar",
}

_REQUIRED = os.environ.get("STELLAR_BINDINGS_REQUIRE_JAVAC") == "1"


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
    if shutil.which("javac") is None:
        _unavailable("javac not on PATH")
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


def _compile(source: str, classpath: str, tmp_path: Path) -> None:
    src = tmp_path / "com" / "example" / "Client.java"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(source)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    result = subprocess.run(
        # -proc:full runs lombok; --release 8 is what the SDK jar targets, and
        # is the constraint that rules out records, sealed types and var.
        [
            "javac",
            "--release",
            "8",
            "-proc:full",
            "-cp",
            classpath,
            "-d",
            str(out),
            str(src),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            f"generated Java did not compile:\n{result.stdout}\n{result.stderr}"
        )


def _type(t: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(t)


def _u32() -> xdr.SCSpecTypeDef:
    return _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)


def _udt(name: bytes) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_UDT, udt=xdr.SCSpecTypeUDT(name=name)
    )


def _vec(inner: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_VEC, vec=xdr.SCSpecTypeVec(inner)
    )


def _map(key: xdr.SCSpecTypeDef, value: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_MAP, map=xdr.SCSpecTypeMap(key, value)
    )


def _option(inner: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_OPTION, option=xdr.SCSpecTypeOption(inner)
    )


def _struct(name: bytes, fields: list) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
        udt_struct_v0=xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=name,
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=b"", name=n, type=t) for n, t in fields
            ],
        ),
    )


def _function(name: bytes, inputs: list, outputs: list) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
        function_v0=xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(name),
            inputs=[
                xdr.SCSpecFunctionInputV0(doc=b"", name=n, type=t) for n, t in inputs
            ],
            outputs=outputs,
        ),
    )


class TestGeneratedJavaCompiles:
    def test_stellar_asset_contract(self, classpath, tmp_path):
        """The SAC spec: every scalar type, plus 13 event declarations."""
        source = generate_binding(get_token_sc_spec_entry(), package="com.example")
        _compile(source, classpath, tmp_path)

    def test_nested_collections(self, classpath, tmp_path):
        """A collection inside a collection puts one lambda inside another.

        Java forbids shadowing a lambda parameter, so each nesting level needs
        its own name; every level using ``e`` was a real bug this catches.
        """
        specs = [
            _struct(b"Thing", [(b"value", _u32())]),
            _function(
                b"nested",
                [
                    (b"a", _vec(_vec(_u32()))),
                    (b"b", _map(_u32(), _vec(_udt(b"Thing")))),
                    (b"c", _vec(_map(_u32(), _vec(_option(_u32()))))),
                    (b"d", _map(_vec(_u32()), _map(_u32(), _vec(_u32())))),
                ],
                [],
            ),
        ]
        _compile(generate_binding(specs, package="com.example"), classpath, tmp_path)

    def test_java_keyword_names(self, classpath, tmp_path):
        """Spec names that are Java keywords must be renamed, not emitted raw."""
        specs = [
            _struct(b"Keywords", [(b"new", _u32()), (b"class", _u32())]),
            _function(b"switch", [(b"final", _u32()), (b"void", _u32())], []),
        ]
        _compile(generate_binding(specs, package="com.example"), classpath, tmp_path)


# Text a contract could publish as a name. Each one either ends a Java string
# literal, assembles an escape out of the characters that follow, or depends on
# the encoding javac reads the file with.
HOSTILE_NAMES = [
    "plain",
    'a", Scv.toSymbol("x',  # closes the literal and injects a call
    'ends with a quote "',
    "trailing backslash \\",
    "a\\nb",  # a literal backslash-n, which must not become a newline
    "\\u0022",  # a unicode escape for the quote: processed before lexing
    "\\\\u0022",
    "newline\nhere",
    "carriage\r\nreturn",
    "tab\there",
    "bell\x07and\x00nul",
    "delete\x7f",
    "中文名字",
    "emoji \U0001f48e",
    "combining é",
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
        from stellar_contract_bindings.java import java_string_literal

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
        src.write_text(source)
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        compiled = subprocess.run(
            ["javac", "--release", "8", "-d", str(out), str(src)],
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

    def test_the_generated_source_is_pure_ascii(self, classpath, tmp_path):
        """Non-ASCII escaped means javac's default encoding cannot change meaning."""
        from stellar_contract_bindings.java import java_string_literal

        for name in HOSTILE_NAMES:
            literal = java_string_literal(name)
            assert literal.isascii(), name
