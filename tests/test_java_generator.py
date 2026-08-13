"""Tests for the Java binding generator."""

from stellar_sdk import xdr

from stellar_contract_bindings.java import generate_binding


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


class TestUnionKindWireNames:
    """``Kind`` carries the on-chain case name, not the Java identifier.

    ``append_underscore`` camelCases every case name so the generated Java
    compiles; ``toSCVal`` writes ``kind.value`` and ``fromSCVal`` looks the
    symbol back up with ``Kind.fromValue``, so that value has to stay the
    name the contract actually uses.
    """

    def setup_method(self):
        union = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
            udt_union_v0=xdr.SCSpecUDTUnionV0(
                doc=b"",
                lib=b"",
                name=b"Choice",
                cases=[
                    _void_case(b"no_data"),
                    _tuple_case(b"set_admin", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _tuple_case(b"plain", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ],
            ),
        )
        self.generated = generate_binding([union], package="org.example")

    def test_tuple_case_keeps_the_on_chain_name(self):
        assert 'setAdmin("set_admin")' in self.generated
        assert 'setAdmin("setAdmin")' not in self.generated

    def test_void_case_keeps_the_on_chain_name(self):
        assert 'noData("no_data")' in self.generated

    def test_unrenamed_case_is_unaffected(self):
        assert 'plain("plain")' in self.generated
