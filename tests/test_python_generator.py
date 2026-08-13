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


def _load_bindings(specs: list[xdr.SCSpecEntry]) -> dict:
    code = generate_binding(specs, client_type="none")
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
