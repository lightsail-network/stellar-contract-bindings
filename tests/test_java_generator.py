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


def _struct(name: bytes, fields: list[tuple[bytes, xdr.SCSpecTypeDef]]) -> xdr.SCSpecEntry:
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


def _result(ok: xdr.SCSpecTypeDef, error: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
        result=xdr.SCSpecTypeResult(ok_type=ok, error_type=error),
    )


class TestResultValuesEncode:
    """A Result-typed value encodes as its Ok arm rather than emitting garbage.

    to_java_type() and from_scval() already reduce Result<T, E> to T, so the
    Java value in hand is a T. to_scval() used to `return` a NotImplementedError
    instead of raising it, which interpolated the exception's message into the
    generated source as a bare expression.
    """

    def setup_method(self):
        u32 = _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        error = _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        self.generated = generate_binding(
            [_struct(b"HasResult", [(b"r", _result(u32, error))])],
            package="org.example",
        )

    def test_encodes_the_ok_arm(self):
        assert 'fields.put("r", Scv.toUint32(this.r));' in self.generated

    def test_decodes_the_ok_arm(self):
        assert 'Scv.fromUint32(map.get(Scv.toSymbol("r")))' in self.generated

    def test_no_exception_text_leaks_into_the_source(self):
        assert "not supported" not in self.generated
        assert "NotImplementedError" not in self.generated


class TestVoidValuesDecode:
    """A void field decodes to null.

    `Scv.fromVoid` is declared `void fromVoid(SCVal)`: it takes an argument and
    returns nothing, so `Scv.fromVoid()` neither compiles nor can stand where a
    value is expected. to_java_type() maps void to Void, whose only value is
    null.
    """

    def setup_method(self):
        self.generated = generate_binding(
            [
                _struct(
                    b"HasVoid",
                    [
                        (b"v", _type(xdr.SCSpecType.SC_SPEC_TYPE_VOID)),
                        (b"n", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    ],
                )
            ],
            package="org.example",
        )

    def test_encoding_still_uses_to_void(self):
        assert 'fields.put("v", Scv.toVoid());' in self.generated

    def test_decoding_emits_null_not_a_bare_from_void_call(self):
        assert "Scv.fromVoid()" not in self.generated
        constructor = self.generated[self.generated.index("public static HasVoid fromSCVal") :]
        assert "null," in constructor
