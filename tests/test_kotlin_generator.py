"""Tests for the Kotlin Multiplatform binding generator."""

import os

import pytest
from stellar_sdk import xdr

from stellar_contract_bindings.kmp import (
    MINIMUM_SDK_VERSION,
    is_kotlin_keyword,
    is_tuple_struct,
    snake_to_pascal,
    snake_to_camel,
    escape_keyword,
    prefixed_type_name,
    to_kotlin_type,
    to_scval,
    from_scval,
    map_key_sort_comparator,
    collect_import_flags,
    render_info,
    render_imports,
    render_helpers,
    render_enum,
    render_error_enum,
    render_struct,
    render_tuple_struct,
    render_union,
    render_client,
    generate_binding,
    command,
)


# ---------------------------------------------------------------------------
# Helpers for building inline SCSpec mocks
# ---------------------------------------------------------------------------


def _t(spec_type: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(type=spec_type)


def _udt(name: bytes) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_UDT,
        udt=xdr.SCSpecTypeUDT(name=name),
    )


def _option(inner: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
        option=xdr.SCSpecTypeOption(value_type=inner),
    )


def _vec(inner: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
        vec=xdr.SCSpecTypeVec(element_type=inner),
    )


def _map(key: xdr.SCSpecTypeDef, val: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
        map=xdr.SCSpecTypeMap(key_type=key, value_type=val),
    )


def _tuple(*value_types: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
        tuple=xdr.SCSpecTypeTuple(value_types=list(value_types)),
    )


def _result(ok: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    error = _t(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
        result=xdr.SCSpecTypeResult(ok_type=ok, error_type=error),
    )


def _function(
    name: bytes,
    inputs=None,
    outputs=None,
    doc: bytes = None,
) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
        function_v0=xdr.SCSpecFunctionV0(
            doc=doc,
            name=xdr.SCSymbol(sc_symbol=name),
            inputs=inputs or [],
            outputs=outputs or [],
        ),
    )


def _input(name: bytes, td: xdr.SCSpecTypeDef, doc: bytes = None):
    return xdr.SCSpecFunctionInputV0(doc=doc, name=name, type=td)


U32 = _t(xdr.SCSpecType.SC_SPEC_TYPE_U32)
BOOL = _t(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
SYMBOL = _t(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestKotlinUtilities:
    def test_is_kotlin_keyword(self):
        assert is_kotlin_keyword("val") is True
        assert is_kotlin_keyword("class") is True
        assert is_kotlin_keyword("import") is True
        assert is_kotlin_keyword("finally") is True
        assert is_kotlin_keyword("is") is True
        assert is_kotlin_keyword("hello") is False
        assert is_kotlin_keyword("transfer") is False

    def test_snake_to_pascal(self):
        assert snake_to_pascal("hello_world") == "HelloWorld"
        assert snake_to_pascal("u32_fail_on_even") == "U32FailOnEven"
        assert snake_to_pascal("simple") == "Simple"
        assert snake_to_pascal("") == ""

    def test_snake_to_camel(self):
        assert snake_to_camel("hello_world") == "helloWorld"
        assert snake_to_camel("multi_args") == "multiArgs"
        assert snake_to_camel("muxed_address") == "muxedAddress"
        assert snake_to_camel("simple") == "simple"

    def test_escape_keyword(self):
        assert escape_keyword("val") == "`val`"
        assert escape_keyword("finally") == "`finally`"
        assert escape_keyword("import") == "`import`"
        assert escape_keyword("hello") == "hello"

    def test_prefixed_type_name(self):
        assert prefixed_type_name("SimpleStruct", "Contract") == "ContractSimpleStruct"
        # An error enum reference uses the same plain prefixed name (no Error suffix).
        assert prefixed_type_name("Error", "Contract") == "ContractError"

    def test_is_tuple_struct(self):
        tuple_fields = [
            xdr.SCSpecUDTStructFieldV0(doc=None, name=b"0", type=U32),
            xdr.SCSpecUDTStructFieldV0(doc=None, name=b"1", type=SYMBOL),
        ]
        assert is_tuple_struct(
            xdr.SCSpecUDTStructV0(doc=None, lib=None, name=b"T", fields=tuple_fields)
        )
        named_fields = [xdr.SCSpecUDTStructFieldV0(doc=None, name=b"a", type=U32)]
        assert not is_tuple_struct(
            xdr.SCSpecUDTStructV0(doc=None, lib=None, name=b"S", fields=named_fields)
        )


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------


class TestKotlinTypeMapping:
    def test_integer_types(self):
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_U32)) == "UInt"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_I32)) == "Int"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_U64)) == "ULong"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_I64)) == "Long"

    def test_timepoint_duration_are_ulong(self):
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT)) == "ULong"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_DURATION)) == "ULong"

    def test_bigint_types(self):
        for st in (
            xdr.SCSpecType.SC_SPEC_TYPE_U128,
            xdr.SCSpecType.SC_SPEC_TYPE_I128,
            xdr.SCSpecType.SC_SPEC_TYPE_U256,
            xdr.SCSpecType.SC_SPEC_TYPE_I256,
        ):
            assert to_kotlin_type(_t(st)) == "BigInteger"

    def test_bool_bytes_string(self):
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)) == "Boolean"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)) == "ByteArray"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)) == "ByteArray"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_STRING)) == "String"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)) == "String"

    def test_address_and_muxed_map_to_address(self):
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)) == "Address"
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)) == "Address"

    def test_val_maps_to_scvalxdr(self):
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_VAL)) == "SCValXdr"

    def test_void_and_empty_tuple_are_unit(self):
        assert to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_VOID)) == "Unit"
        assert to_kotlin_type(_tuple()) == "Unit"

    def test_option(self):
        assert to_kotlin_type(_option(U32)) == "UInt?"

    def test_vec_and_map(self):
        assert to_kotlin_type(_vec(U32)) == "List<UInt>"
        assert to_kotlin_type(_map(U32, BOOL)) == "Map<UInt, Boolean>"

    def test_tuple_pair_and_triple(self):
        assert to_kotlin_type(_tuple(SYMBOL, U32)) == "Pair<String, UInt>"
        assert to_kotlin_type(_tuple(SYMBOL, U32, BOOL)) == "Triple<String, UInt, Boolean>"

    def test_tuple_one_element_raises(self):
        with pytest.raises(NotImplementedError):
            to_kotlin_type(_tuple(U32))

    def test_tuple_over_three_raises(self):
        with pytest.raises(NotImplementedError):
            to_kotlin_type(_tuple(U32, U32, U32, U32))

    def test_error_type_raises(self):
        with pytest.raises(NotImplementedError):
            to_kotlin_type(_t(xdr.SCSpecType.SC_SPEC_TYPE_ERROR))

    def test_result_unwraps_ok_type(self):
        assert to_kotlin_type(_result(U32)) == "UInt"

    def test_udt(self):
        assert to_kotlin_type(_udt(b"SimpleStruct"), "Contract") == "ContractSimpleStruct"


# ---------------------------------------------------------------------------
# to_scval / from_scval
# ---------------------------------------------------------------------------


class TestKotlinToScval:
    def test_integers(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U32), "x") == "Scv.toUint32(x)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I32), "x") == "Scv.toInt32(x)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U64), "x") == "Scv.toUint64(x)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I64), "x") == "Scv.toInt64(x)"

    def test_timepoint_capital_p(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT), "x") == "Scv.toTimePoint(x)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_DURATION), "x") == "Scv.toDuration(x)"

    def test_bigint(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U128), "x") == "Scv.toUint128(x)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I256), "x") == "Scv.toInt256(x)"

    def test_string_uses_explicit_receiver(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_STRING), "x") == "Scv.toString(x)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL), "x") == "Scv.toSymbol(x)"

    def test_val_passthrough(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_VAL), "x") == "x"

    def test_address_uses_to_scval(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), "addr") == "addr.toSCVal()"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS), "addr") == "addr.toSCVal()"

    def test_option_encode(self):
        result = to_scval(_option(U32), "x")
        assert result == "if (x == null) Scv.toVoid() else Scv.toUint32(x)"

    def test_vec_encode(self):
        result = to_scval(_vec(U32), "items")
        assert result == "Scv.toVec(items.map { v0 -> Scv.toUint32(v0) })"

    def test_map_encode_builds_linked_hash_map_and_sorts_by_key(self):
        result = to_scval(_map(U32, BOOL), "m")
        assert "LinkedHashMap<SCValXdr, SCValXdr>()" in result
        assert ".apply {" in result
        # Entries must be sorted ascending by key before insertion (host rejects unsorted).
        assert "m.entries.sortedWith(compareBy { it.key }).forEach { (k0, v0) -> " in result
        assert "put(Scv.toUint32(k0), Scv.toBoolean(v0))" in result

    def test_map_encode_string_key_sorts_by_utf8_bytes(self):
        result = to_scval(_map(SYMBOL, U32), "m")
        assert (
            "m.entries.sortedWith(Comparator { a, b -> "
            "compareUnsignedByteArrays(a.key.encodeToByteArray(), b.key.encodeToByteArray()) })"
        ) in result

    def test_map_encode_bytes_key_sorts_by_unsigned_bytes(self):
        result = to_scval(_map(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES), U32), "m")
        assert (
            "m.entries.sortedWith(Comparator { a, b -> "
            "compareUnsignedByteArrays(a.key, b.key) })"
        ) in result

    def test_map_encode_address_key_sorts_by_scaddress_bytes(self):
        result = to_scval(_map(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), U32), "m")
        assert (
            "m.entries.sortedWith(Comparator { a, b -> "
            "compareUnsignedByteArrays(scAddressXdrBytes(a.key), scAddressXdrBytes(b.key)) })"
        ) in result

    def test_map_encode_unsupported_key_raises(self):
        # A struct (UDT) key has no defined host key ordering here: fail loudly.
        struct_key = _udt(b"SimpleStruct")
        with pytest.raises(NotImplementedError):
            to_scval(_map(struct_key, U32), "m")

    def test_tuple_encode(self):
        result = to_scval(_tuple(SYMBOL, U32), "t")
        assert result == "Scv.toVec(listOf(Scv.toSymbol(t.first), Scv.toUint32(t.second)))"

    def test_option_in_tuple_binds_accessor_to_local(self):
        # Pair/Triple accessors are cross-module properties, which Kotlin cannot
        # smart-cast to non-null; the option conversion binds them to a local first.
        result = to_scval(_tuple(_option(U32), U32), "x")
        assert (
            "x.first.let { o0 -> if (o0 == null) Scv.toVoid() else Scv.toUint32(o0) }"
            in result
        )
        assert "Scv.toUint32(x.second)" in result

    def test_void_and_empty_tuple_encode_to_void(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_VOID), "v") == "Scv.toVoid()"
        assert to_scval(_tuple(), "v") == "Scv.toVoid()"

    def test_u256_and_fixed_bytes_encode(self):
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U256), "v") == "Scv.toUint256(v)"
        assert to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N), "v") == "Scv.toBytes(v)"

    def test_error_type_encode_raises(self):
        with pytest.raises(NotImplementedError):
            to_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_ERROR), "v")

    def test_one_element_tuple_encode_raises(self):
        with pytest.raises(NotImplementedError):
            to_scval(_tuple(U32), "v")

    def test_udt_encode(self):
        assert to_scval(_udt(b"SimpleStruct"), "s", "Contract") == "s.toSCVal()"

    def test_result_encode_raises(self):
        with pytest.raises(NotImplementedError):
            to_scval(_result(U32), "x")


class TestKotlinFromScval:
    def test_integers(self):
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U32), "v") == "Scv.fromUint32(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I64), "v") == "Scv.fromInt64(v)"

    def test_timepoint_duration(self):
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT), "v") == "Scv.fromTimePoint(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_DURATION), "v") == "Scv.fromDuration(v)"

    def test_address_decode(self):
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), "v") == "Address.fromSCVal(v)"
        assert (
            from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS), "v")
            == "Address.fromSCVal(v)"
        )

    def test_option_decode_uses_void_discriminant(self):
        result = from_scval(_option(U32), "v")
        assert result == "if (v.discriminant == SCValTypeXdr.SCV_VOID) null else Scv.fromUint32(v)"

    def test_vec_decode(self):
        assert from_scval(_vec(U32), "v") == "Scv.fromVec(v).map { e0 -> Scv.fromUint32(e0) }"

    def test_map_decode(self):
        result = from_scval(_map(U32, BOOL), "v")
        assert result == (
            "Scv.fromMap(v).entries.associate { (k0, v0) -> "
            "Scv.fromUint32(k0) to Scv.fromBoolean(v0) }"
        )

    def test_tuple_decode(self):
        result = from_scval(_tuple(SYMBOL, U32), "v")
        assert result == (
            "Scv.fromVec(v).let { t0 -> Pair(Scv.fromSymbol(t0[0]), Scv.fromUint32(t0[1])) }"
        )

    def test_result_decode_unwraps(self):
        assert from_scval(_result(U32), "v") == "Scv.fromUint32(v)"

    def test_scalar_decodes(self):
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I32), "v") == "Scv.fromInt32(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U64), "v") == "Scv.fromUint64(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U128), "v") == "Scv.fromUint128(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I128), "v") == "Scv.fromInt128(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_U256), "v") == "Scv.fromUint256(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_I256), "v") == "Scv.fromInt256(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES), "v") == "Scv.fromBytes(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N), "v") == "Scv.fromBytes(v)"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_STRING), "v") == "Scv.fromString(v)"

    def test_val_passthrough_void_and_empty_tuple(self):
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_VAL), "v") == "v"
        assert from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_VOID), "v") == "Unit"
        assert from_scval(_tuple(), "v") == "Unit"

    def test_error_type_decode_raises(self):
        with pytest.raises(NotImplementedError):
            from_scval(_t(xdr.SCSpecType.SC_SPEC_TYPE_ERROR), "v")

    def test_one_element_tuple_decode_raises(self):
        with pytest.raises(NotImplementedError):
            from_scval(_tuple(U32), "v")

    def test_option_keyed_map_decode_parenthesizes_key(self):
        # Without parentheses the if-else key expression would swallow the infix `to`.
        result = from_scval(_map(_option(U32), U32), "x")
        assert (
            "(if (k0.discriminant == SCValTypeXdr.SCV_VOID) null else Scv.fromUint32(k0))"
            " to Scv.fromUint32(v0)"
        ) in result

    def test_udt_decode(self):
        assert (
            from_scval(_udt(b"SimpleStruct"), "v", "Contract")
            == "ContractSimpleStruct.fromSCVal(v)"
        )


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


class TestKotlinUnknownSpecType:
    def test_unknown_spec_type_raises_in_all_converters(self):
        # A spec type without a mapping must fail loudly in every converter.
        class UnknownTypeDef:
            type = object()

        td = UnknownTypeDef()
        with pytest.raises(ValueError):
            to_kotlin_type(td)
        with pytest.raises(ValueError):
            to_scval(td, "x")
        with pytest.raises(NotImplementedError):
            from_scval(td, "x")


class TestKotlinCodeGeneration:
    def test_render_enum(self):
        entry = xdr.SCSpecUDTEnumV0(
            doc=None,
            lib=None,
            name=b"RoyalCard",
            cases=[
                xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"Jack", value=xdr.Uint32(11)),
                xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"Queen", value=xdr.Uint32(12)),
            ],
        )
        result = render_enum(entry, "Contract")
        assert "enum class ContractRoyalCard(val value: UInt)" in result
        assert "Jack(11u)" in result
        assert "Queen(12u)" in result
        assert "fun toSCVal(): SCValXdr = Scv.toUint32(value)" in result
        assert "fun fromSCVal(scVal: SCValXdr): ContractRoyalCard" in result

    def test_render_error_enum_uses_plain_prefixed_name(self):
        entry = xdr.SCSpecUDTErrorEnumV0(
            doc=None,
            lib=None,
            name=b"Error",
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(
                    doc=None, name=b"NumberMustBeOdd", value=xdr.Uint32(1)
                )
            ],
        )
        result = render_error_enum(entry, "Contract")
        # No "Error" suffix beyond the type's own name; declaration name is the plain prefix.
        assert "enum class ContractError(val value: UInt)" in result
        assert "ContractErrorError" not in result
        assert "NumberMustBeOdd(1u)" in result

    def test_error_enum_reference_resolves_to_declaration_name(self):
        # A struct field that references the error enum by UDT name must resolve to the same
        # plain prefixed name the error enum is declared with.
        struct = xdr.SCSpecUDTStructV0(
            doc=None,
            lib=None,
            name=b"Holder",
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"err", type=_udt(b"Error"))
            ],
        )
        result = render_struct(struct, "Contract")
        assert "val err: ContractError" in result
        assert "ContractError.fromSCVal(" in result

    def test_render_struct_keyword_field_escapes_identifier_not_symbol_key(self):
        # A keyword-named field escapes with backticks at the declaration, the encode
        # reference, and the decode assignment, while the SCV_MAP symbol key keeps the
        # raw contract-spec name.
        struct = xdr.SCSpecUDTStructV0(
            doc=None,
            lib=None,
            name=b"Config",
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"val", type=U32),
            ],
        )
        result = render_struct(struct, "Contract")
        assert "val `val`: UInt" in result
        assert 'map[Scv.toSymbol("val")] = Scv.toUint32(`val`)' in result
        assert '`val` = Scv.fromUint32(map[Scv.toSymbol("val")]!!)' in result

    def test_render_struct_field_order_and_symbol_keys(self):
        struct = xdr.SCSpecUDTStructV0(
            doc=None,
            lib=None,
            name=b"SimpleStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"a", type=U32),
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"b", type=BOOL),
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"c", type=SYMBOL),
            ],
        )
        result = render_struct(struct, "Contract")
        assert "data class ContractSimpleStruct(" in result
        assert "LinkedHashMap<SCValXdr, SCValXdr>()" in result
        # Symbol keys are emitted in declaration order.
        idx_a = result.index('Scv.toSymbol("a")')
        idx_b = result.index('Scv.toSymbol("b")')
        idx_c = result.index('Scv.toSymbol("c")')
        assert idx_a < idx_b < idx_c

    def test_render_tuple_struct_sorts_fields_numerically(self):
        # Fields declared out of numeric order must be sorted for the vec encoding.
        struct = xdr.SCSpecUDTStructV0(
            doc=None,
            lib=None,
            name=b"TupleStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"1", type=SYMBOL),
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"0", type=U32),
            ],
        )
        result = render_tuple_struct(struct, "Contract")
        assert "data class ContractTupleStruct(" in result
        # value0 (u32) is declared before value1 (symbol) despite the reversed input order.
        assert result.index("value0: UInt") < result.index("value1: String")
        assert result.index("Scv.toUint32(value0)") < result.index("Scv.toSymbol(value1)")

    def test_render_union_tag_first(self):
        union = xdr.SCSpecUDTUnionV0(
            doc=None,
            lib=None,
            name=b"ComplexEnum",
            cases=[
                xdr.SCSpecUDTUnionCaseV0(
                    kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                    void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=None, name=b"Void"),
                ),
                xdr.SCSpecUDTUnionCaseV0(
                    kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                    tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                        doc=None,
                        name=b"Asset",
                        type=[_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), U32],
                    ),
                ),
            ],
        )
        result = render_union(union, "Contract")
        assert "sealed class ContractComplexEnum" in result
        assert "object Void : ContractComplexEnum()" in result
        assert "data class Asset(" in result
        # The case-tag symbol is the first vec element.
        assert 'Scv.toVec(listOf(Scv.toSymbol("Void")))' in result
        asset_encode = result[result.index("data class Asset(") :]
        tag_idx = asset_encode.index('Scv.toSymbol("Asset")')
        val_idx = asset_encode.index("value0.toSCVal()")
        assert tag_idx < val_idx
        # Decode dispatches on the tag symbol.
        assert 'Scv.fromSymbol(elements[0])' in result
        assert '"Asset" -> Asset(' in result

    def test_render_client_invoke_and_build_shapes(self):
        fn = _function(
            b"transfer",
            inputs=[
                _input(b"to", _t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                _input(b"amount", _t(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
            ],
            outputs=[BOOL],
            doc=b"Transfer tokens",
        )
        result = render_client([fn.function_v0], "Token")
        # The primary constructor is internal (module-visible) so the public path stays the
        # forContract factory while callers in the same module can wrap a custom-configured
        # client.
        assert "class Token internal constructor(val client: ContractClient)" in result
        assert (
            "fun forContract(contractId: String, rpcUrl: String, network: Network): Token"
            in result
        )
        assert "ContractClient.forContractWithoutSpec(contractId, rpcUrl, network)" in result
        # invoke method
        assert "suspend fun transfer(" in result
        assert "to: Address," in result
        assert "amount: BigInteger," in result
        assert "source: String," in result
        assert "signer: KeyPair?" in result
        assert "): Boolean =" in result
        assert 'functionName = "transfer"' in result
        assert "parameters = listOf(to.toSCVal(), Scv.toInt128(amount))" in result
        assert "parseResultXdrFn = { result -> Scv.fromBoolean(result) }" in result
        # build method
        assert "suspend fun buildTransferTx(" in result
        assert "): AssembledTransaction<Boolean> =" in result
        assert "client.buildInvoke(" in result

    def test_render_client_void_function(self):
        fn = _function(b"void", inputs=[], outputs=[])
        result = render_client([fn.function_v0], "Contract")
        # Void function: no return type, empty parse function, returns Unit cleanly.
        assert "suspend fun void(" in result
        assert "parseResultXdrFn = { }" in result
        assert "): AssembledTransaction<Unit> =" in result

    def test_render_client_empty_tuple_output_is_void(self):
        fn = _function(b"empty_tuple", inputs=[], outputs=[_tuple()])
        result = render_client([fn.function_v0], "Contract")
        assert "suspend fun emptyTuple(" in result
        # No non-Unit return annotation on the invoke method; the parse function is empty.
        assert "parseResultXdrFn = { }" in result
        assert "): AssembledTransaction<Unit> =" in result

    def test_render_client_multi_output_raises(self):
        # The XDR type enforces at most one output at construction time, so assign the
        # multi-output list afterwards to exercise the generator's own guard.
        fn = _function(b"pair_out", inputs=[], outputs=[U32])
        fn.function_v0.outputs = [U32, BOOL]
        with pytest.raises(NotImplementedError):
            render_client([fn.function_v0], "Contract")

    def test_render_client_escapes_keyword_names(self):
        # Function named `val`, param named `finally`.
        fn = _function(
            b"val",
            inputs=[_input(b"finally", SYMBOL)],
            outputs=[SYMBOL],
        )
        result = render_client([fn.function_v0], "Contract")
        assert "suspend fun `val`(" in result
        assert "`finally`: String," in result
        assert "buildValTx(" in result
        # The wire function name keeps the original contract symbol.
        assert 'functionName = "val"' in result
        assert "Scv.toSymbol(`finally`)" in result


# ---------------------------------------------------------------------------
# Import detection and header
# ---------------------------------------------------------------------------


class TestKotlinImports:
    def test_render_info_contains_versions_and_sdk_requirement(self):
        info = render_info({"address": False, "bigint": False, "option": False})
        assert "stellar_contract_bindings" in info
        assert f"kmp-stellar-sdk (Soneso) v{MINIMUM_SDK_VERSION}" in info
        assert "@generated" in info

    def test_render_info_notes_bignum_when_used(self):
        info = render_info({"address": False, "bigint": True, "option": False})
        assert "com.ionspin.kotlin:bignum" in info

    def test_collect_import_flags(self):
        # The option is a function output (a decode-reachable position), so it sets
        # the option flag; address and bigint are set from the inputs.
        specs = [
            _function(
                b"f",
                inputs=[
                    _input(b"a", _t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                    _input(b"b", _t(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                ],
                outputs=[_option(U32)],
            )
        ]
        flags = collect_import_flags(specs)
        assert flags == {
            "address": True,
            "bigint": True,
            "option": True,
            "map_byte_cmp": False,
            "map_address_cmp": False,
        }

    def test_option_import_flag_only_for_decode_positions(self):
        # An Option only in encode positions (function inputs) does not require the
        # SCValTypeXdr import; only decode-reachable Options (function outputs, struct
        # fields, union case types) do.
        input_only = [
            _function(b"f", inputs=[_input(b"o", _option(U32))], outputs=[BOOL])
        ]
        assert collect_import_flags(input_only)["option"] is False
        code_in = generate_binding(
            input_only, package="com.example.bindings", class_name="Demo"
        )
        assert "import com.soneso.stellar.sdk.xdr.SCValTypeXdr" not in code_in

        output_option = [_function(b"g", inputs=[], outputs=[_option(U32)])]
        assert collect_import_flags(output_option)["option"] is True
        code_out = generate_binding(
            output_option, package="com.example.bindings", class_name="Demo"
        )
        assert "import com.soneso.stellar.sdk.xdr.SCValTypeXdr" in code_out

    def test_scan_type_recurses_nested_containers(self):
        # The import flags must be found through every container: a result's ok type,
        # vec elements, tuple values, and union tuple-case types.
        via_result = [_function(b"f", inputs=[], outputs=[_result(_t(xdr.SCSpecType.SC_SPEC_TYPE_I128))])]
        assert collect_import_flags(via_result)["bigint"] is True

        via_vec = [_function(b"f", inputs=[_input(b"a", _vec(_t(xdr.SCSpecType.SC_SPEC_TYPE_U256)))], outputs=[])]
        assert collect_import_flags(via_vec)["bigint"] is True

        via_tuple = [_function(b"f", inputs=[_input(b"a", _tuple(_t(xdr.SCSpecType.SC_SPEC_TYPE_I256), U32))], outputs=[])]
        assert collect_import_flags(via_tuple)["bigint"] is True

        via_union_case = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
                udt_union_v0=xdr.SCSpecUDTUnionV0(
                    doc=None,
                    lib=None,
                    name=b"Choice",
                    cases=[
                        xdr.SCSpecUDTUnionCaseV0(
                            kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                            tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                                doc=None,
                                name=b"Some",
                                type=[_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)],
                            ),
                        )
                    ],
                ),
            )
        ]
        assert collect_import_flags(via_union_case)["address"] is True

    def test_map_helper_flags_only_for_encode_positions(self):
        # Only encoding sorts map entries, so a map that appears solely in a decode
        # position (a function output) needs neither the comparator helpers nor the
        # XdrWriter import.
        output_only = [
            _function(
                b"f",
                inputs=[],
                outputs=[_map(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), U32)],
            )
        ]
        flags = collect_import_flags(output_only)
        assert flags["map_byte_cmp"] is False
        assert flags["map_address_cmp"] is False
        code = generate_binding(
            output_only, package="com.example.bindings", class_name="Demo"
        )
        assert "XdrWriter" not in code
        assert "compareUnsignedByteArrays" not in code
        assert "scAddressXdrBytes" not in code

        # Struct fields encode in toSCVal, so a struct-field map still pulls them in.
        struct_field_map = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
                udt_struct_v0=xdr.SCSpecUDTStructV0(
                    doc=None,
                    lib=None,
                    name=b"Holder",
                    fields=[
                        xdr.SCSpecUDTStructFieldV0(
                            doc=None,
                            name=b"m",
                            type=_map(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), U32),
                        )
                    ],
                ),
            )
        ]
        flags = collect_import_flags(struct_field_map)
        assert flags["map_byte_cmp"] is True
        assert flags["map_address_cmp"] is True

    def test_render_imports_conditionals(self):
        imports = render_imports({"address": True, "bigint": True, "option": True})
        assert "import com.soneso.stellar.sdk.Address" in imports
        assert "import com.ionspin.kotlin.bignum.integer.BigInteger" in imports
        assert "import com.soneso.stellar.sdk.xdr.SCValTypeXdr" in imports
        # Always present
        assert "import com.soneso.stellar.sdk.contract.ContractClient" in imports
        assert "import com.soneso.stellar.sdk.contract.AssembledTransaction" in imports
        assert "import com.soneso.stellar.sdk.scval.Scv" in imports

    def test_render_imports_omits_unused(self):
        imports = render_imports({"address": False, "bigint": False, "option": False})
        assert "Address" not in imports
        assert "BigInteger" not in imports
        assert "SCValTypeXdr" not in imports
        assert "XdrWriter" not in imports

    def test_address_key_map_pulls_xdrwriter_import_and_helpers(self):
        specs = [
            _function(
                b"f",
                inputs=[
                    _input(
                        b"m",
                        _map(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), U32),
                    )
                ],
                outputs=[BOOL],
            )
        ]
        flags = collect_import_flags(specs)
        assert flags["map_byte_cmp"] is True
        assert flags["map_address_cmp"] is True
        assert flags["address"] is True
        imports = render_imports(flags)
        assert "import com.soneso.stellar.sdk.xdr.XdrWriter" in imports
        helpers = render_helpers(flags)
        assert "private fun compareUnsignedByteArrays(a: ByteArray, b: ByteArray): Int" in helpers
        assert "private fun scAddressXdrBytes(address: Address): ByteArray" in helpers
        assert "address.toSCAddress().encode(writer)" in helpers

    def test_string_key_map_pulls_byte_helper_only(self):
        specs = [
            _function(b"f", inputs=[_input(b"m", _map(SYMBOL, U32))], outputs=[BOOL])
        ]
        flags = collect_import_flags(specs)
        assert flags["map_byte_cmp"] is True
        assert flags["map_address_cmp"] is False
        helpers = render_helpers(flags)
        assert "compareUnsignedByteArrays" in helpers
        assert "scAddressXdrBytes" not in helpers

    def test_numeric_key_map_needs_no_helpers(self):
        specs = [
            _function(b"f", inputs=[_input(b"m", _map(U32, BOOL))], outputs=[BOOL])
        ]
        flags = collect_import_flags(specs)
        assert flags["map_byte_cmp"] is False
        assert flags["map_address_cmp"] is False
        assert render_helpers(flags) == ""


class TestKotlinMapKeyComparator:
    def test_numeric_and_bool_keys_use_natural_order(self):
        for st in (
            xdr.SCSpecType.SC_SPEC_TYPE_U32,
            xdr.SCSpecType.SC_SPEC_TYPE_I32,
            xdr.SCSpecType.SC_SPEC_TYPE_U64,
            xdr.SCSpecType.SC_SPEC_TYPE_I64,
            xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT,
            xdr.SCSpecType.SC_SPEC_TYPE_DURATION,
            xdr.SCSpecType.SC_SPEC_TYPE_U128,
            xdr.SCSpecType.SC_SPEC_TYPE_I128,
            xdr.SCSpecType.SC_SPEC_TYPE_BOOL,
        ):
            assert map_key_sort_comparator(_t(st)) == "compareBy { it.key }"

    def test_string_symbol_keys_use_utf8_bytes(self):
        expected = (
            "Comparator { a, b -> "
            "compareUnsignedByteArrays(a.key.encodeToByteArray(), b.key.encodeToByteArray()) }"
        )
        assert map_key_sort_comparator(_t(xdr.SCSpecType.SC_SPEC_TYPE_STRING)) == expected
        assert map_key_sort_comparator(_t(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)) == expected

    def test_bytes_keys_use_unsigned_bytes(self):
        expected = "Comparator { a, b -> compareUnsignedByteArrays(a.key, b.key) }"
        assert map_key_sort_comparator(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)) == expected
        assert map_key_sort_comparator(_t(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)) == expected

    def test_address_keys_use_scaddress_bytes(self):
        expected = (
            "Comparator { a, b -> "
            "compareUnsignedByteArrays(scAddressXdrBytes(a.key), scAddressXdrBytes(b.key)) }"
        )
        assert map_key_sort_comparator(_t(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)) == expected
        assert map_key_sort_comparator(_t(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)) == expected

    def test_unsupported_key_raises(self):
        with pytest.raises(NotImplementedError):
            map_key_sort_comparator(_udt(b"SimpleStruct"))


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestKotlinGenerateBinding:
    def test_generate_binding_full_surface(self):
        specs = [
            # enum named `import` (Kotlin hard keyword defused by prefixing)
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0,
                udt_enum_v0=xdr.SCSpecUDTEnumV0(
                    doc=None,
                    lib=None,
                    name=b"import",
                    cases=[
                        xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"not", value=xdr.Uint32(11)),
                    ],
                ),
            ),
            # error enum
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0,
                udt_error_enum_v0=xdr.SCSpecUDTErrorEnumV0(
                    doc=None,
                    lib=None,
                    name=b"Error",
                    cases=[
                        xdr.SCSpecUDTErrorEnumCaseV0(
                            doc=None, name=b"NumberMustBeOdd", value=xdr.Uint32(1)
                        )
                    ],
                ),
            ),
            # struct
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
                udt_struct_v0=xdr.SCSpecUDTStructV0(
                    doc=None,
                    lib=None,
                    name=b"SimpleStruct",
                    fields=[
                        xdr.SCSpecUDTStructFieldV0(doc=None, name=b"a", type=U32),
                        xdr.SCSpecUDTStructFieldV0(doc=None, name=b"c", type=SYMBOL),
                    ],
                ),
            ),
            # tuple struct
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
                udt_struct_v0=xdr.SCSpecUDTStructV0(
                    doc=None,
                    lib=None,
                    name=b"TupleStruct",
                    fields=[
                        xdr.SCSpecUDTStructFieldV0(doc=None, name=b"0", type=U32),
                        xdr.SCSpecUDTStructFieldV0(
                            doc=None, name=b"1", type=_udt(b"SimpleStruct")
                        ),
                    ],
                ),
            ),
            # function using several mapped types + the `option`, `map`, `address`, bigint.
            # The option return value is decode-reachable, so it pulls the SCValTypeXdr import.
            _function(
                b"transfer",
                inputs=[
                    _input(b"to", _t(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)),
                    _input(b"amount", _t(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
                    _input(b"cfg", _map(U32, BOOL)),
                ],
                outputs=[_option(SYMBOL)],
            ),
            _function(b"void", inputs=[], outputs=[]),
        ]

        code = generate_binding(specs, package="com.example.bindings", class_name="Demo")

        assert "package com.example.bindings" in code
        assert "import com.soneso.stellar.sdk.contract.ContractClient" in code
        assert "import com.soneso.stellar.sdk.Address" in code
        assert "import com.ionspin.kotlin.bignum.integer.BigInteger" in code
        assert "import com.soneso.stellar.sdk.xdr.SCValTypeXdr" in code
        assert "enum class Demoimport(val value: UInt)" in code
        assert "enum class DemoError(val value: UInt)" in code
        assert "data class DemoSimpleStruct(" in code
        assert "data class DemoTupleStruct(" in code
        assert "class Demo internal constructor(val client: ContractClient)" in code
        assert "suspend fun transfer(" in code
        assert "suspend fun buildTransferTx(" in code
        assert "suspend fun void(" in code

    def test_generate_binding_default_class_name(self):
        code = generate_binding(
            [_function(b"hello", inputs=[_input(b"who", SYMBOL)], outputs=[SYMBOL])],
            package="com.example",
        )
        assert "class Contract internal constructor(val client: ContractClient)" in code
        assert "suspend fun hello(" in code

    def test_generate_binding_includes_union_and_map_helpers(self):
        # A union entry dispatches through generate_binding, and a byte-comparable map
        # argument pulls the private sort helpers into the output.
        specs = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
                udt_union_v0=xdr.SCSpecUDTUnionV0(
                    doc=None,
                    lib=None,
                    name=b"Choice",
                    cases=[
                        xdr.SCSpecUDTUnionCaseV0(
                            kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                            void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=None, name=b"Idle"),
                        )
                    ],
                ),
            ),
            _function(b"f", inputs=[_input(b"m", _map(SYMBOL, U32))], outputs=[]),
        ]
        code = generate_binding(specs, package="com.example", class_name="Demo")
        assert "sealed class DemoChoice" in code
        assert "private fun compareUnsignedByteArrays(a: ByteArray, b: ByteArray): Int" in code

    def test_generate_binding_rejects_reserved_class_names(self):
        # A client class named after a type the generated file imports or references
        # would shadow that type inside its own file and the output would not compile.
        specs = [_function(b"hello", inputs=[], outputs=[SYMBOL])]
        for reserved in ("ContractClient", "Address", "Scv", "Pair", "String"):
            with pytest.raises(ValueError, match="collides"):
                generate_binding(specs, package="com.example", class_name=reserved)

    def test_generate_binding_rejects_zero_field_struct(self):
        # A fieldless struct would render as `data class X()`, which is invalid Kotlin.
        struct = xdr.SCSpecEntry(
            kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
            udt_struct_v0=xdr.SCSpecUDTStructV0(
                doc=None, lib=None, name=b"Empty", fields=[]
            ),
        )
        with pytest.raises(NotImplementedError, match="no fields"):
            generate_binding([struct], package="com.example")

    def test_generate_binding_ends_with_single_newline(self):
        code = generate_binding(
            [_function(b"noop", inputs=[], outputs=[])],
            package="com.example",
        )
        assert code.endswith("\n")
        assert not code.endswith("\n\n")
        assert not any(line != line.rstrip() for line in code.splitlines())


class TestCommand:
    def test_invalid_contract_id(self):
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            command,
            ["--contract-id", "invalid", "--package", "com.example.bindings"],
        )
        assert result.exit_code != 0
        assert "Invalid contract ID" in result.output

    def test_spec_fetch_failure_aborts(self, monkeypatch):
        from click.testing import CliRunner

        def raise_fetch(contract_id, rpc_url):
            raise RuntimeError("rpc unavailable")

        monkeypatch.setattr(
            "stellar_contract_bindings.kmp.get_specs_by_contract_id", raise_fetch
        )
        runner = CliRunner()
        result = runner.invoke(
            command,
            [
                "--contract-id",
                "CDX62OSVWH2M6RECZXUCLG2YF4YMX3HIYSXMDEYUDAQPUQCMONYV46RX",
                "--package",
                "com.example.bindings",
            ],
        )
        assert result.exit_code != 0
        assert "Get contract specs failed" in result.output

    def test_default_output_is_current_directory(self, monkeypatch):
        from click.testing import CliRunner

        specs = [_function(b"hello", inputs=[], outputs=[SYMBOL])]
        monkeypatch.setattr(
            "stellar_contract_bindings.kmp.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                command,
                [
                    "--contract-id",
                    "CDX62OSVWH2M6RECZXUCLG2YF4YMX3HIYSXMDEYUDAQPUQCMONYV46RX",
                    "--package",
                    "com.example.bindings",
                ],
            )
            assert result.exit_code == 0
            assert os.path.exists(
                os.path.join("com", "example", "bindings", "Contract.kt")
            )

    def test_cli_group_registers_kmp(self):
        from click.testing import CliRunner

        from stellar_contract_bindings.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["kmp", "--help"])
        assert result.exit_code == 0
        assert "--package" in result.output
        assert "--class-name" in result.output

    def test_output_lands_in_package_directory(self, monkeypatch):
        from click.testing import CliRunner

        specs = [_function(b"hello", inputs=[_input(b"who", SYMBOL)], outputs=[SYMBOL])]
        monkeypatch.setattr(
            "stellar_contract_bindings.kmp.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                command,
                [
                    "--contract-id",
                    "CDX62OSVWH2M6RECZXUCLG2YF4YMX3HIYSXMDEYUDAQPUQCMONYV46RX",
                    "--package",
                    "com.example.bindings",
                    "--output",
                    "out",
                ],
            )
            assert result.exit_code == 0
            path = os.path.join("out", "com", "example", "bindings", "Contract.kt")
            assert os.path.exists(path)
            with open(path) as f:
                content = f.read()
            assert "package com.example.bindings" in content
            assert (
                "class Contract internal constructor(val client: ContractClient)"
                in content
            )
