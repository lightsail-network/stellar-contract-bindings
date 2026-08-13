"""Tests for the Python binding generator (non-event specs)."""

import black
from stellar_sdk import scval, xdr

from stellar_contract_bindings.python import generate_binding


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
INJECTION_DOC = b"x'''\n    import os\n    PWNED = os.getcwd()\n    _ = '''"


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


class TestHostileSpecDocs:
    """A contract's doc text cannot alter the generated program."""

    def setup_method(self):
        self.specs = [
            _enum(b"HEnum", INJECTION_DOC),
            _error_enum(b"HError", INJECTION_DOC),
            _struct(b"HStruct", INJECTION_DOC, [b"v"]),
            _struct(b"HTuple", INJECTION_DOC, [b"0"]),
            _union(b"HUnion", [_void_case(b"a")]),
        ]
        self.specs[-1].udt_union_v0.doc = INJECTION_DOC
        self.ns = _load_bindings(self.specs)

    def test_nothing_from_the_doc_executes(self):
        assert "PWNED" not in self.ns
        assert "os" not in self.ns

    def test_doc_is_preserved_verbatim_on_every_udt(self):
        for name in ("HEnum", "HError", "HStruct", "HTuple", "HUnion"):
            assert self.ns[name].__doc__ == INJECTION_DOC.decode()
            assert not hasattr(self.ns[name], "PWNED")

    def test_generated_source_never_opens_a_docstring_literal(self):
        source = generate_binding(self.specs, client_type="none")
        assert "'''x'''" not in source
        assert "PWNED = os.getcwd()\n" not in source

    def test_client_method_docs_are_inert(self):
        """Method docs stay docstrings, so the payload survives only as text.

        black re-indents docstrings, so the text is compared loosely here;
        what matters is that none of it ran.
        """
        for client_type, classes in (
            ("sync", ["Client"]),
            ("async", ["ClientAsync"]),
            ("both", ["Client", "ClientAsync"]),
        ):
            ns = _load_bindings([_function(b"hello", INJECTION_DOC)], client_type)
            assert "PWNED" not in ns
            for name in classes:
                assert not hasattr(ns[name], "PWNED")
                assert "PWNED = os.getcwd()" in ns[name].hello.__doc__
