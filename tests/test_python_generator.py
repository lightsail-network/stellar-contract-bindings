"""Tests for the Python binding generator (non-event specs)."""

import ast
import inspect

import black
import pytest
from stellar_sdk import scval, xdr

from stellar_contract_bindings.python import (
    _ADDRESS_TYPES,
    _PY_TYPES,
    _SCVAL_CODECS,
    from_scval,
    generate_binding,
    python_docstring,
    to_py_type,
    to_scval,
)


def _type(t: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(t)


def _void_case(name: bytes) -> xdr.SCSpecUDTUnionCaseV0:
    return xdr.SCSpecUDTUnionCaseV0(
        xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
        void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=name),
    )


def _tuple_case(name: bytes, *types: xdr.SCSpecTypeDef) -> xdr.SCSpecUDTUnionCaseV0:
    return xdr.SCSpecUDTUnionCaseV0(
        xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
        tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(doc=b"", name=name, type=list(types)),
    )


def _union(name: bytes, cases: list) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
        udt_union_v0=xdr.SCSpecUDTUnionV0(doc=b"", lib=b"", name=name, cases=cases),
    )


def _load_bindings(specs: list[xdr.SCSpecEntry], client_type: str = "none") -> dict:
    code = generate_binding(specs, client_type=client_type)
    code = black.format_str(code, mode=black.Mode())
    namespace: dict = {}
    exec(compile(code, "bindings.py", "exec"), namespace)
    return namespace


class TestUnionKeywordCaseNames:
    """A union case named after a Python keyword keeps its on-chain symbol.

    ``append_underscore`` renames such cases to ``<name>_`` so the generated
    module parses; the wire encoding must still use the original name.
    """

    def setup_method(self):
        self.specs = [
            _union(
                b"Kw",
                [
                    _void_case(b"import"),
                    _tuple_case(b"class", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _void_case(b"plain"),
                ],
            )
        ]
        self.ns = _load_bindings(self.specs)

    def test_kind_values_are_the_on_chain_names(self):
        kind = self.ns["KwKind"]
        assert [(member.name, member.value) for member in kind] == [
            ("import_", "import"),
            ("class_", "class"),
            ("plain", "plain"),
        ]

    def test_to_scval_emits_the_on_chain_name(self):
        kw, kind = self.ns["Kw"], self.ns["KwKind"]
        assert scval.from_enum(kw(kind.import_).to_scval())[0] == "import"
        assert scval.from_enum(kw(kind.class_, class_=7).to_scval())[0] == "class"
        assert scval.from_enum(kw(kind.plain).to_scval())[0] == "plain"

    def test_round_trip(self):
        kw, kind = self.ns["Kw"], self.ns["KwKind"]
        for value in (kw(kind.import_), kw(kind.class_, class_=7), kw(kind.plain)):
            assert kw.from_scval(value.to_scval()) == value

    def test_from_scval_accepts_the_on_chain_name(self):
        kw, kind = self.ns["Kw"], self.ns["KwKind"]
        encoded = scval.to_enum("class", scval.to_uint32(7))
        assert kw.from_scval(encoded) == kw(kind.class_, class_=7)


# Spec docs are attacker-controlled: they arrive in the contract's spec from
# the chain. Interpolating them into a docstring literal let a contract close
# the literal and have the rest of its "doc" run as code on import.
#
# Both payloads below are needed. The generator quotes with double quotes, so
# the single-quoted payload is inert as text and rides the readable path; only
# the double-quoted one forces the repr() fallback.
INJECTION_DOC = b"x'''\n    import os\n    PWNED = os.getcwd()\n    _ = '''"
DQUOTE_INJECTION_DOC = b'x"""\nimport os\nPWNED = os.getcwd()\n_ = """'
INJECTION_DOCS = [INJECTION_DOC, DQUOTE_INJECTION_DOC]

# Text a triple-quoted literal carries unchanged, so it stays readable.
QUOTABLE_DOCS = [
    b"plain",
    b"first line\n\nthird line",
    b"tab\there",
    b'apostrophes and "quotes" inside',
    "emoji \U0001f48e".encode(),
    INJECTION_DOC,
]

# Text that would mean something else inside a triple-quoted literal, or make
# the generated module warn on import, so it has to fall back to repr().
UNQUOTABLE_DOCS = [
    DQUOTE_INJECTION_DOC,
    b'ends with a quote "',
    b"trailing backslash \\",
    b"a\\nb",  # a literal backslash-n, which must not become a newline
    b"carriage\r\nreturn",
    b'implicit """ """ concatenation',
    b"\x00nul",
]


def _enum(name: bytes, doc: bytes) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0,
        udt_enum_v0=xdr.SCSpecUDTEnumV0(
            doc=doc,
            lib=b"",
            name=name,
            cases=[xdr.SCSpecUDTEnumCaseV0(doc=b"", name=b"A", value=xdr.Uint32(1))],
        ),
    )


def _error_enum(name: bytes, doc: bytes) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0,
        udt_error_enum_v0=xdr.SCSpecUDTErrorEnumV0(
            doc=doc,
            lib=b"",
            name=name,
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(doc=b"", name=b"A", value=xdr.Uint32(1))
            ],
        ),
    )


def _struct(name: bytes, doc: bytes, field_names: list[bytes]) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
        udt_struct_v0=xdr.SCSpecUDTStructV0(
            doc=doc,
            lib=b"",
            name=name,
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=n, type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                )
                for n in field_names
            ],
        ),
    )


def _function(name: bytes, doc: bytes) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
        function_v0=xdr.SCSpecFunctionV0(
            doc=doc, name=xdr.SCSymbol(name), inputs=[], outputs=[]
        ),
    )


class TestDocLiterals:
    """python_docstring() renders any doc text as exactly one string constant.

    That is the whole safety property: whatever the contract publishes ends up
    as a value, never as syntax. Readability is a second concern, handled by
    picking the triple-quoted form whenever it holds the text unchanged.
    """

    @pytest.mark.parametrize("doc", QUOTABLE_DOCS + UNQUOTABLE_DOCS + [b""])
    def test_renders_one_constant_holding_the_original_text(self, doc):
        node = ast.parse(python_docstring(doc), mode="eval").body
        assert isinstance(node, ast.Constant)
        assert node.value == doc.decode()

    @pytest.mark.parametrize("doc", QUOTABLE_DOCS)
    def test_quotable_docs_keep_their_line_breaks(self, doc):
        rendered = python_docstring(doc)
        assert rendered == '"""' + doc.decode() + '"""'

    @pytest.mark.parametrize("doc", UNQUOTABLE_DOCS)
    def test_unquotable_docs_fall_back_to_repr(self, doc):
        assert python_docstring(doc) == repr(doc.decode())

    def test_a_normal_doc_is_not_escaped_into_one_line(self):
        """Guards the readability the fallback costs, so it stays the exception."""
        assert python_docstring(b"first line\nsecond line") == (
            '"""first line\nsecond line"""'
        )


class TestHostileSpecDocs:
    """A contract's doc text cannot alter the generated program."""

    @staticmethod
    def _bindings(doc: bytes) -> tuple[list, dict]:
        specs = [
            _enum(b"HEnum", doc),
            _error_enum(b"HError", doc),
            _struct(b"HStruct", doc, [b"v"]),
            _struct(b"HTuple", doc, [b"0"]),
            _union(b"HUnion", [_void_case(b"a")]),
        ]
        specs[-1].udt_union_v0.doc = doc
        return specs, _load_bindings(specs)

    @pytest.mark.parametrize("doc", INJECTION_DOCS)
    def test_nothing_from_the_doc_executes(self, doc):
        _, ns = self._bindings(doc)
        assert "PWNED" not in ns
        assert "os" not in ns

    @pytest.mark.parametrize("doc", INJECTION_DOCS)
    def test_doc_is_preserved_verbatim_on_every_udt(self, doc):
        _, ns = self._bindings(doc)
        for name in ("HEnum", "HError", "HStruct", "HTuple", "HUnion"):
            assert ns[name].__doc__ == doc.decode()
            assert not hasattr(ns[name], "PWNED")

    @pytest.mark.parametrize("doc", INJECTION_DOCS)
    def test_the_payload_survives_only_inside_a_string(self, doc):
        """The text may appear in the source; it must never become syntax.

        Checked against the parsed module rather than the text, so it holds for
        both the triple-quoted and the repr() rendering: the doc has to show up
        as a constant, and nothing it names may exist as code.
        """
        tree = ast.parse(generate_binding([_function(b"hello", doc)], "both"))
        constants = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert doc.decode() in constants
        assert not [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "PWNED"
        ]
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "os" not in imported

    @pytest.mark.parametrize("doc", INJECTION_DOCS)
    def test_client_method_docs_are_inert(self, doc):
        """Method docs sit in docstring position, where black reindents them.

        So unlike the class ``__doc__`` assignments above, the stored text is
        the doc with its common indent stripped - which is what a reader gets
        back out of ``help()`` either way. None of it runs.
        """
        for client_type, classes in (
            ("sync", ["Client"]),
            ("async", ["ClientAsync"]),
            ("both", ["Client", "ClientAsync"]),
        ):
            ns = _load_bindings([_function(b"hello", doc)], client_type)
            assert "PWNED" not in ns
            for name in classes:
                assert not hasattr(ns[name], "PWNED")
                got = inspect.getdoc(ns[name].hello)
                assert got == inspect.cleandoc(doc.decode())


class TestTypeMappingTables:
    """Guards for the lookup tables the three type functions are built on."""

    def test_every_spec_type_is_handled(self):
        """No SCSpecType falls through to the trailing raise.

        A gap here would only surface as a generation failure against some
        contract in the wild, so check the whole enum up front.
        """
        unhandled = []
        for spec_type in xdr.SCSpecType:
            td = _type(spec_type)
            for fn, args in (
                (to_py_type, ()),
                (to_scval, ("v",)),
                (from_scval, ("v",)),
            ):
                try:
                    fn(td, *args)
                except (ValueError, NotImplementedError):
                    unhandled.append((spec_type.name, fn.__name__))
                except AttributeError:
                    pass  # composite type, needs a payload the bare def lacks
        assert unhandled == []

    def test_codec_names_exist_in_both_directions(self):
        """_SCVAL_CODECS assumes scval.to_<x> and scval.from_<x> both exist.

        That symmetry is what lets one table drive both directions; if the SDK
        ever renames one side, generated bindings would call a helper that is
        not there.
        """
        missing = [
            f"scval.{direction}{codec}"
            for codec in sorted(set(_SCVAL_CODECS.values()))
            for direction in ("to_", "from_")
            if not hasattr(scval, f"{direction}{codec}")
        ]
        assert missing == []

    def test_tables_do_not_overlap_the_special_cases(self):
        """Types handled explicitly must not also sit in a table.

        Both functions check their special cases before the table, so an
        overlap would be silently shadowed rather than reported.
        """
        special = {
            xdr.SCSpecType.SC_SPEC_TYPE_VAL,
            xdr.SCSpecType.SC_SPEC_TYPE_VOID,
            xdr.SCSpecType.SC_SPEC_TYPE_ERROR,
        }
        assert special & set(_SCVAL_CODECS) == set()
        assert set(_ADDRESS_TYPES) & set(_PY_TYPES) == set()
