import os
import tempfile

import pytest
from click.testing import CliRunner
from stellar_sdk import StrKey, xdr

from stellar_contract_bindings.flutter import (
    generate_binding,
    render_client,
    render_info,
    to_dart_type,
    to_scval,
    from_scval,
    snake_to_camel,
    camel_to_snake,
    is_keywords,
    prefixed_type_name,
    render_enum,
    render_struct,
    render_tuple_struct,
    render_union,
    command,
)


def _type(t: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(t)


def _map_type(key: xdr.SCSpecTypeDef, value: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MAP)
    td.map = xdr.SCSpecTypeMap(key_type=key, value_type=value)
    return td


def _function(name: bytes, inputs=None, outputs=None) -> xdr.SCSpecEntry:
    entry = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
    entry.function_v0 = xdr.SCSpecFunctionV0(
        doc=b"",
        name=xdr.SCSymbol(sc_symbol=name),
        inputs=inputs or [],
        outputs=outputs or [],
    )
    return entry


def _input(name: bytes, td: xdr.SCSpecTypeDef) -> xdr.SCSpecFunctionInputV0:
    return xdr.SCSpecFunctionInputV0(doc=b"", name=name, type=td)


def _option(value_type: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_OPTION)
    td.option = xdr.SCSpecTypeOption(value_type=value_type)
    return td


def _vec(element_type: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VEC)
    td.vec = xdr.SCSpecTypeVec(element_type)
    return td


def _tuple(*value_types: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_TUPLE)
    td.tuple = xdr.SCSpecTypeTuple(value_types=list(value_types))
    return td


def _udt(name: bytes) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
    td.udt = xdr.SCSpecTypeUDT(name=name)
    return td


def _result(ok_type: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_RESULT)
    td.result = xdr.SCSpecTypeResult(
        ok_type=ok_type, error_type=_type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
    )
    return td


def _bytes_n(n: int) -> xdr.SCSpecTypeDef:
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
    td.bytes_n = xdr.SCSpecTypeBytesN(n=xdr.Uint32(n))
    return td


def _unknown_type() -> xdr.SCSpecTypeDef:
    # A spec type value outside the generator's known set, as a future protocol
    # revision could introduce; every conversion must fail loudly for it.
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
    td.type = object()
    return td


_VALID_CONTRACT_ID = StrKey.encode_contract(b"\x00" * 32)


class TestFlutterHelpers:
    def test_snake_to_camel(self):
        assert snake_to_camel("hello_world") == "helloWorld"
        assert snake_to_camel("test_case", first_letter_lower=False) == "TestCase"
        assert snake_to_camel("simple") == "simple"
        assert snake_to_camel("a_b_c_d") == "aBCD"

    def test_camel_to_snake(self):
        assert camel_to_snake("HelloWorld") == "hello_world"
        assert camel_to_snake("MyContract") == "my_contract"
        assert camel_to_snake("Single") == "single"

    def test_is_keywords(self):
        assert is_keywords("class") is True
        assert is_keywords("if") is True
        assert is_keywords("async") is True
        assert is_keywords("hello") is False
        assert is_keywords("world") is False

    def test_prefixed_type_name(self):
        assert prefixed_type_name("MyStruct", "TestContract") == "TestContractMyStruct"
        # Dart built-in and SDK type names pass through unprefixed.
        assert prefixed_type_name("bool", "TestContract") == "bool"
        assert prefixed_type_name("Address", "TestContract") == "Address"


class TestToDartType:
    def test_basic_types(self):
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)) == "bool"
        assert (
            to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL), nullable=True)
            == "bool?"
        )
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)) == "int"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_I32)) == "int"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_STRING)) == "String"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)) == "String"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)) == "Uint8List"

    def test_64_bit_types_are_bigint(self):
        # u64/i64/timepoint/duration map to Dart BigInt, matching the SDK factories.
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U64)) == "BigInt"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_I64)) == "BigInt"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT)) == "BigInt"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_DURATION)) == "BigInt"
        assert (
            to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U64), nullable=True)
            == "BigInt?"
        )

    def test_128_and_256_bit_types_are_bigint(self):
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U128)) == "BigInt"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_I128)) == "BigInt"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_U256)) == "BigInt"
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_I256)) == "BigInt"

    def test_option_and_collection_types(self):
        assert to_dart_type(_option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U64))) == "BigInt?"

        assert to_dart_type(_vec(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))) == "List<int>"

        map_type = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U64),
        )
        assert to_dart_type(map_type) == "Map<String, BigInt>"

    def test_val_is_raw_xdr_scval(self):
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_VAL)) == "XdrSCVal"
        assert (
            to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_VAL), nullable=True)
            == "XdrSCVal?"
        )

    def test_void_type(self):
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_VOID)) == "void"

    def test_muxed_address_is_address(self):
        # Muxed addresses map to the same SDK Address class as plain addresses.
        assert to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)) == "Address"
        assert (
            to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS), nullable=True)
            == "Address?"
        )

    def test_bytes_n_is_uint8list(self):
        assert to_dart_type(_bytes_n(32)) == "Uint8List"
        assert to_dart_type(_bytes_n(32), nullable=True) == "Uint8List?"

    def test_result_type_uses_ok_type(self):
        assert to_dart_type(_result(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))) == "int"
        assert (
            to_dart_type(_result(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)), nullable=True)
            == "int?"
        )

    def test_empty_tuple_is_void(self):
        assert to_dart_type(_tuple()) == "void"

    def test_udt_prefixed_with_class_name(self):
        assert to_dart_type(_udt(b"Point"), class_name="TestContract") == "TestContractPoint"
        assert (
            to_dart_type(_udt(b"Point"), nullable=True, class_name="TestContract")
            == "TestContractPoint?"
        )

    def test_error_type_raises(self):
        with pytest.raises(NotImplementedError):
            to_dart_type(_type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR))

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            to_dart_type(_unknown_type())


class TestToScVal:
    def test_option_local_subject_relies_on_promotion(self):
        # A local variable or parameter is type-promoted by Dart after the null
        # check, so no non-null assertion is emitted.
        option_type = _option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        assert (
            to_scval(option_type, "value")
            == "value == null ? XdrSCVal.forVoid() : XdrSCVal.forU32(value)"
        )

    def test_option_in_tuple_asserts_non_null(self):
        # Dart does not promote record accessors, so the non-null branch must
        # assert explicitly.
        tuple_type = _tuple(
            _option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
        )
        assert to_scval(tuple_type, "x") == (
            "XdrSCVal.forVec([x.$1 == null ? XdrSCVal.forVoid() : "
            "XdrSCVal.forU32(x.$1!), XdrSCVal.forU32(x.$2)])"
        )

    def test_option_map_value_asserts_non_null(self):
        # Dart does not promote map-entry getters, so the non-null branch must
        # assert explicitly.
        map_type = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
        )
        assert (
            "e.value == null ? XdrSCVal.forVoid() : XdrSCVal.forU32(e.value!)"
            in to_scval(map_type, "x")
        )

    def test_option_field_subject_asserts_non_null(self):
        # Dart never promotes public class fields; struct renderers encode fields
        # with subject_promotable=False.
        option_type = _option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        assert (
            to_scval(option_type, "a", subject_promotable=False)
            == "a == null ? XdrSCVal.forVoid() : XdrSCVal.forU32(a!)"
        )

    def test_option_in_vec_relies_on_closure_promotion(self):
        # The vec element is a closure parameter, which Dart promotes after the
        # null check regardless of the surrounding subject.
        vec_type = _vec(_option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)))
        assert to_scval(vec_type, "x") == (
            "XdrSCVal.forVec(x.map((e) => e == null ? XdrSCVal.forVoid() : "
            "XdrSCVal.forU32(e)).toList())"
        )

    def test_val_passes_through_unconverted(self):
        assert to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_VAL), "value") == "value"

    def test_void_encoder(self):
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_VOID), "value")
            == "XdrSCVal.forVoid()"
        )

    def test_scalar_encoders(self):
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL), "value")
            == "XdrSCVal.forBool(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32), "value")
            == "XdrSCVal.forU32(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_I32), "value")
            == "XdrSCVal.forI32(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_STRING), "value")
            == "XdrSCVal.forString(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_BYTES), "value")
            == "XdrSCVal.forBytes(value)"
        )
        assert (
            to_scval(_bytes_n(32), "value")
            == "XdrSCVal.forBytes(value)"
        )

    def test_128_and_256_bit_encoders(self):
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_U128), "value")
            == "XdrSCVal.forU128BigInt(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_I128), "value")
            == "XdrSCVal.forI128BigInt(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_U256), "value")
            == "XdrSCVal.forU256BigInt(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_I256), "value")
            == "XdrSCVal.forI256BigInt(value)"
        )

    def test_address_and_muxed_address_encoders(self):
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), "value")
            == "value.toXdrSCVal()"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS), "value")
            == "value.toXdrSCVal()"
        )

    def test_udt_encoder(self):
        assert (
            to_scval(_udt(b"Point"), "value", "TestContract") == "value.toScVal()"
        )

    def test_vec_encoder(self):
        assert to_scval(_vec(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)), "x") == (
            "XdrSCVal.forVec(x.map((e) => XdrSCVal.forU32(e)).toList())"
        )

    def test_vec_of_128_bit_and_udt_elements(self):
        assert to_scval(_vec(_type(xdr.SCSpecType.SC_SPEC_TYPE_U128)), "x") == (
            "XdrSCVal.forVec(x.map((e) => XdrSCVal.forU128BigInt(e)).toList())"
        )
        assert to_scval(_vec(_udt(b"Color")), "x", "TestContract") == (
            "XdrSCVal.forVec(x.map((e) => e.toScVal()).toList())"
        )

    def test_vec_of_map_encoder(self):
        # The inner map subject is the vec closure parameter `e`.
        vec_type = _vec(
            _map_type(
                _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            )
        )
        assert to_scval(vec_type, "x") == (
            "XdrSCVal.forVec(x.map((e) => XdrSCVal.forMap((e.entries.toList()"
            "..sort((a, b) => a.key.compareTo(b.key))).map((e) => "
            "XdrSCMapEntry(XdrSCVal.forU32(e.key), XdrSCVal.forString(e.value)))"
            ".toList())).toList())"
        )

    def test_map_of_vec_encoder(self):
        # The inner vec lambda parameter shadows the outer map-entry `e`,
        # which is valid Dart.
        map_type = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _vec(_type(xdr.SCSpecType.SC_SPEC_TYPE_STRING)),
        )
        assert to_scval(map_type, "x") == (
            "XdrSCVal.forMap((x.entries.toList()..sort((a, b) => "
            "a.key.compareTo(b.key))).map((e) => XdrSCMapEntry("
            "XdrSCVal.forU32(e.key), XdrSCVal.forVec(e.value.map((e) => "
            "XdrSCVal.forString(e)).toList()))).toList())"
        )

    def test_tuple_in_tuple_encoder(self):
        # Nested tuples encode via chained record accessors.
        tuple_type = _tuple(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _tuple(
                _type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL),
                _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            ),
        )
        assert to_scval(tuple_type, "x") == (
            "XdrSCVal.forVec([XdrSCVal.forU32(x.$1), XdrSCVal.forVec(["
            "XdrSCVal.forBool(x.$2.$1), XdrSCVal.forString(x.$2.$2)])])"
        )

    def test_error_type_raises(self):
        with pytest.raises(NotImplementedError):
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR), "value")

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            to_scval(_unknown_type(), "value")

    def test_64_bit_encoders(self):
        # The BigInt value is passed straight to the SDK factories,
        # and timepoint uses the lowercase-p factory name.
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_U64), "value")
            == "XdrSCVal.forU64(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_I64), "value")
            == "XdrSCVal.forI64(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT), "value")
            == "XdrSCVal.forTimepoint(value)"
        )
        assert (
            to_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_DURATION), "value")
            == "XdrSCVal.forDuration(value)"
        )

    def test_map_encode_builds_xdr_map_entry_list(self):
        # Encode a Dart Map into a List<XdrSCMapEntry> for XdrSCVal.forMap.
        # Entries are sorted ascending by key first (host rejects unsorted ScMap);
        # a string key sorts by UTF-8 byte order.
        map_type = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
        )
        assert to_scval(map_type, "myMap") == (
            "XdrSCVal.forMap((myMap.entries.toList()..sort((a, b) => "
            "_compareBytesLex(utf8.encode(a.key), utf8.encode(b.key)))).map((e) => "
            "XdrSCMapEntry(XdrSCVal.forString(e.key), XdrSCVal.forU32(e.value)))"
            ".toList())"
        )

    def test_tuple_encode_uses_record_accessors(self):
        # Tuple-typed arguments encode via Dart record positional accessors.
        tuple_type = _tuple(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U64),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL),
        )
        assert to_scval(tuple_type, "v") == (
            "XdrSCVal.forVec([XdrSCVal.forU64(v.$1), XdrSCVal.forBool(v.$2)])"
        )

    def test_result_type_raises(self):
        # Result-typed inputs must fail loudly rather than emit an error instance.
        with pytest.raises(NotImplementedError):
            to_scval(_result(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)), "value")


class TestFromScVal:
    def test_scalar_decoders(self):
        assert from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL), "val") == "val.b!"
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32), "val")
            == "val.u32!.uint32"
        )
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_I32), "val")
            == "val.i32!.int32"
        )
        assert from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_STRING), "val") == "val.str!"

    def test_64_bit_decoders_return_bigint_getters(self):
        # The BigInt getters are returned directly; timepoint/duration read
        # their own populated fields, not .u64.
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_U64), "val")
            == "val.u64!.uint64"
        )
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_I64), "val")
            == "val.i64!.int64"
        )
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT), "val")
            == "val.timepoint!.uint64"
        )
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_DURATION), "val")
            == "val.duration!.uint64"
        )

    def test_bytes_decoders_use_scbytes(self):
        # bytes and bytesN read the XdrSCBytes accessor.
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_BYTES), "val")
            == "val.bytes!.sCBytes"
        )
        assert from_scval(_bytes_n(32), "val") == "val.bytes!.sCBytes"

    def test_map_decode_iterates_entry_list(self):
        # Decode iterates the List<XdrSCMapEntry> via .key / .val.
        map_type = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
        )
        assert from_scval(map_type, "val") == (
            "Map.fromEntries(val.map!.map((e) => "
            "MapEntry(e.key.str!, e.val.u32!.uint32)))"
        )

    def test_val_passes_through_unconverted(self):
        assert from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_VAL), "val") == "val"

    def test_void_decodes_to_null(self):
        assert from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_VOID), "val") == "null"

    def test_128_and_256_bit_decoders_use_to_bigint(self):
        for t in (
            xdr.SCSpecType.SC_SPEC_TYPE_U128,
            xdr.SCSpecType.SC_SPEC_TYPE_I128,
            xdr.SCSpecType.SC_SPEC_TYPE_U256,
            xdr.SCSpecType.SC_SPEC_TYPE_I256,
        ):
            assert from_scval(_type(t), "val") == "val.toBigInt()!"

    def test_address_and_muxed_address_decoders(self):
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), "val")
            == "Address.fromXdrSCVal(val)"
        )
        assert (
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS), "val")
            == "Address.fromXdrSCVal(val)"
        )

    def test_option_decoder_checks_void_discriminant(self):
        option_type = _option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        assert from_scval(option_type, "val") == (
            "val.discriminant == XdrSCValType.SCV_VOID ? null : val.u32!.uint32"
        )

    def test_result_decoder_uses_ok_type(self):
        assert (
            from_scval(_result(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)), "val")
            == "val.u32!.uint32"
        )

    def test_vec_decoder(self):
        assert from_scval(_vec(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)), "val") == (
            "val.vec!.map((e) => e.u32!.uint32).toList()"
        )

    def test_udt_decoder(self):
        assert (
            from_scval(_udt(b"Point"), "val", "TestContract")
            == "TestContractPoint.fromScVal(val)"
        )

    def test_empty_tuple_decodes_to_null(self):
        assert from_scval(_tuple(), "val") == "null"

    def test_option_in_vec_decoder(self):
        vec_type = _vec(_option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)))
        assert from_scval(vec_type, "val") == (
            "val.vec!.map((e) => e.discriminant == XdrSCValType.SCV_VOID ? "
            "null : e.u32!.uint32).toList()"
        )

    def test_map_of_vec_decoder(self):
        # The inner vec lambda parameter shadows the outer map-entry `e`,
        # which is valid Dart.
        map_type = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _vec(_type(xdr.SCSpecType.SC_SPEC_TYPE_STRING)),
        )
        assert from_scval(map_type, "val") == (
            "Map.fromEntries(val.map!.map((e) => MapEntry(e.key.u32!.uint32, "
            "e.val.vec!.map((e) => e.str!).toList())))"
        )

    def test_tuple_in_tuple_decoder(self):
        # Nested tuples decode by indexing into the inner vec.
        tuple_type = _tuple(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _tuple(
                _type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL),
                _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            ),
        )
        assert from_scval(tuple_type, "val") == (
            "(val.vec![0].u32!.uint32, (val.vec![1].vec![0].b!, "
            "val.vec![1].vec![1].str!))"
        )

    def test_error_type_raises(self):
        with pytest.raises(NotImplementedError):
            from_scval(_type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR), "val")

    def test_unknown_type_raises(self):
        with pytest.raises(NotImplementedError):
            from_scval(_unknown_type(), "val")


class TestRenderInfo:
    def test_header_states_minimum_sdk_version(self):
        # Header advertises the minimum compatible Flutter SDK version.
        header = render_info()
        assert "stellar_contract_bindings" in header
        assert "This code requires stellar_flutter_sdk (Soneso) v3.3.0 or later." in header


class TestRenderUDTs:
    def test_render_enum(self):
        enum_entry = xdr.SCSpecUDTEnumV0(
            doc=b"Test enum",
            lib=b"",
            name=b"TestEnum",
            cases=[
                xdr.SCSpecUDTEnumCaseV0(doc=b"", name=b"First", value=xdr.Uint32(0)),
                xdr.SCSpecUDTEnumCaseV0(doc=b"", name=b"Second", value=xdr.Uint32(1)),
            ],
        )
        result = render_enum(enum_entry, "TestContract")
        assert "enum TestContractTestEnum {" in result
        assert "First(0)," in result
        assert "Second(1);" in result
        assert "factory TestContractTestEnum.fromValue(int value)" in result
        assert "static TestContractTestEnum fromScVal(XdrSCVal val)" in result

    def test_render_struct(self):
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"Test struct",
            lib=b"",
            name=b"TestStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"field_one",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"field_two",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL),
                ),
            ],
        )
        result = render_struct(struct_entry, "TestContract")
        assert "class TestContractTestStruct {" in result
        assert "final int fieldOne;" in result
        assert "final bool fieldTwo;" in result
        assert "factory TestContractTestStruct.fromScVal(XdrSCVal val)" in result

    def test_render_struct_option_field_asserts_non_null(self):
        # Struct fields are public class members: the encode must null-check the
        # raw field and assert non-null in the conversion.
        struct = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        struct.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Config",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"memo",
                    type=_option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                )
            ],
        )
        result = render_struct(struct.udt_struct_v0, "TestContract")
        assert "final int? memo;" in result
        assert "memo == null ? XdrSCVal.forVoid() : XdrSCVal.forU32(memo!)" in result

    def test_render_union_option_payload_encodes_void_for_null(self):
        # A union's nullable payload holder must be null-checked raw: an absent
        # option encodes as void instead of throwing on the assertion.
        tuple_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
        )
        tuple_case.tuple_case = xdr.SCSpecUDTUnionCaseTupleV0(
            doc=b"",
            name=b"maybe",
            type=[_option(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
        )
        union = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0)
        union.udt_union_v0 = xdr.SCSpecUDTUnionV0(
            doc=b"", lib=b"", name=b"Choice", cases=[tuple_case]
        )
        result = render_union(union.udt_union_v0, "TestContract")
        assert (
            "maybe == null ? XdrSCVal.forVoid() : XdrSCVal.forU32(maybe!)" in result
        )
        assert "maybe! == null" not in result

    def test_render_struct_with_64_bit_field(self):
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Ledger",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"created_at",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT),
                ),
            ],
        )
        result = render_struct(struct_entry, "TestContract")
        assert "final BigInt createdAt;" in result
        assert "XdrSCVal.forTimepoint(createdAt)" in result
        assert "createdAt: fieldsMap[\"created_at\"]!.timepoint!.uint64" in result

    def test_render_tuple_struct(self):
        tuple_struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"TupleStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=b"0", type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=b"1", type=_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
                ),
            ],
        )
        result = render_tuple_struct(tuple_struct_entry, "TestContract")
        assert "class TestContractTupleStruct {" in result
        assert "final (int, bool) value;" in result
        assert "factory TestContractTupleStruct.fromScVal(XdrSCVal val)" in result

    def test_render_union(self):
        void_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
        )
        void_case.void_case = xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=b"None")
        tuple_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
        )
        tuple_case.tuple_case = xdr.SCSpecUDTUnionCaseTupleV0(
            doc=b"", name=b"Some", type=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)]
        )
        union_entry = xdr.SCSpecUDTUnionV0(
            doc=b"", lib=b"", name=b"Option", cases=[void_case, tuple_case]
        )
        result = render_union(union_entry, "TestContract")
        assert "enum TestContractOptionKind {" in result
        assert "class TestContractOption {" in result
        assert "factory TestContractOption.none()" in result
        assert "factory TestContractOption.some(int value)" in result

    def test_render_struct_single_field_hash_code(self):
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Single",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"def",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
            ],
        )
        result = render_struct(struct_entry, "TestContract")
        assert "int get hashCode => Object.hashAll([" in result

    def test_typed_data_import_only_when_bytes_used(self):
        no_bytes = _function(
            b"hello",
            inputs=[_input(b"to", _type(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL))],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)],
        )
        generated = generate_binding([no_bytes], "TestContract")
        assert "import 'dart:typed_data';" not in generated

        with_bytes = _function(
            b"digest",
            inputs=[_input(b"data", _type(xdr.SCSpecType.SC_SPEC_TYPE_BYTES))],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)],
        )
        generated = generate_binding([with_bytes], "TestContract")
        assert "import 'dart:typed_data';" in generated

    def test_render_struct_escapes_keyword_field_names(self):
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Escaped",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"class",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"other",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL),
                ),
            ],
        )
        result = render_struct(struct_entry, "TestContract")
        assert "final int class_;" in result
        assert "required this.class_," in result
        assert "class_ == other.class_" in result
        assert "XdrSCVal.forSymbol('class')" in result

    def test_render_client_escapes_keyword_method_and_param_names(self):
        function = _function(
            b"void",
            inputs=[
                xdr.SCSpecFunctionInputV0(
                    doc=b"",
                    name=b"finally",
                    type=_type(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL),
                ),
            ],
            outputs=[],
        )
        result = render_client([function.function_v0], "TestContract")
        assert "Future<void> void_({" in result
        assert "required String finally_," in result
        assert "XdrSCVal.forSymbol(finally_)" in result
        assert "name: 'void'," in result

    def test_render_union_case_name_escapes_dart_keyword(self):
        void_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
        )
        void_case.void_case = xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=b"Void")
        tuple_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
        )
        tuple_case.tuple_case = xdr.SCSpecUDTUnionCaseTupleV0(
            doc=b"", name=b"As", type=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)]
        )
        union_entry = xdr.SCSpecUDTUnionV0(
            doc=b"", lib=b"", name=b"ComplexEnum", cases=[void_case, tuple_case]
        )
        result = render_union(union_entry, "TestContract")
        assert "factory TestContractComplexEnum.void_()" in result
        assert "return TestContractComplexEnum.void_();" in result
        assert "factory TestContractComplexEnum.as_(int value)" in result
        assert "final int? as_;" in result
        assert "as_ == other.as_" in result
        assert "TestContractComplexEnum.void()" not in result


class TestRenderClient:
    def _client_with_transfer(self) -> str:
        function = _function(
            b"transfer",
            inputs=[
                _input(b"to", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)),
                _input(b"amount", _type(xdr.SCSpecType.SC_SPEC_TYPE_I128)),
            ],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)],
        )
        return render_client([function.function_v0], "TestContract")

    def test_convenience_method_forwards_method_options(self):
        # The convenience method builds MethodOptions from its parameters.
        result = self._client_with_transfer()
        assert "final methodOptions = MethodOptions(" in result
        assert "fee: baseFee," in result
        assert "timeoutInSeconds: transactionTimeout," in result
        assert "simulate: simulate," in result
        assert "restore: restore," in result

    def test_convenience_method_parameter_defaults(self):
        result = self._client_with_transfer()
        assert "int baseFee = 100," in result
        assert "int transactionTimeout = 300," in result
        assert "bool simulate = true," in result
        assert "bool restore = false," in result
        assert "bool force = false," in result

    def test_convenience_method_drops_removed_parameters(self):
        # The client method declares no signer or submitTimeout parameter -
        # SorobanClient has no counterpart for either.
        result = self._client_with_transfer()
        assert "signer" not in result
        assert "submitTimeout" not in result
        assert "You can customize method options" not in result

    def test_build_tx_variant_keeps_method_options_parameter(self):
        result = self._client_with_transfer()
        assert "Future<AssembledTransaction> buildTransferTx({" in result
        assert "MethodOptions? methodOptions," in result

    def test_void_method_does_not_bind_unused_result(self):
        # A void-returning method awaits the call without binding an unused variable.
        function = _function(
            b"do_nothing",
            inputs=[_input(b"note", _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING))],
            outputs=[],
        )
        result = render_client([function.function_v0], "TestContract")
        assert "Future<void> doNothing({" in result
        assert "await _client.invokeMethod(" in result
        assert "final result = await _client.invokeMethod(" not in result

    def test_multi_output_raises(self):
        # Functions with more than one output are unsupported and must fail loudly.
        # The XDR type caps outputs at one, so the multi-output list is assembled
        # directly to exercise the generator guard.
        function = _function(
            b"pair",
            inputs=[],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
        )
        function.function_v0.outputs.append(_type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        with pytest.raises(NotImplementedError):
            render_client([function.function_v0], "TestContract")

    def test_single_tuple_output_still_works(self):
        # A single tuple-typed output is handled by the normal single-output path.
        tuple_type = _tuple(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL),
        )
        function = _function(b"get_pair", inputs=[], outputs=[tuple_type])
        result = render_client([function.function_v0], "TestContract")
        assert "Future<(int, bool)> getPair({" in result


class TestGenerateBinding:
    def test_generate_binding_basic(self):
        function = _function(
            b"test_function",
            inputs=[_input(b"input", _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING))],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
        )
        generated = generate_binding([function], "TestContract")
        assert "// This file was generated by stellar_contract_bindings" in generated
        assert "// This code requires stellar_flutter_sdk (Soneso) v3.3.0 or later." in generated
        assert "import 'dart:typed_data';" not in generated
        assert (
            "import 'package:stellar_flutter_sdk/stellar_flutter_sdk.dart';"
            in generated
        )
        assert "class TestContract {" in generated
        assert "static Future<TestContract> forContractId(" in generated
        assert "Future<int> testFunction({" in generated
        assert "required String input," in generated

    def test_generate_binding_ends_with_single_newline(self):
        function = _function(
            b"noop",
            inputs=[],
            outputs=[],
        )
        generated = generate_binding([function], "TestContract")
        assert generated.endswith("\n")
        assert not generated.endswith("\n\n")
        assert not any(line != line.rstrip() for line in generated.splitlines())

    def test_generate_binding_with_complex_types(self):
        enum_spec = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0
        )
        enum_spec.udt_enum_v0 = xdr.SCSpecUDTEnumV0(
            doc=b"",
            lib=b"",
            name=b"Status",
            cases=[
                xdr.SCSpecUDTEnumCaseV0(doc=b"", name=b"Option1", value=xdr.Uint32(0)),
                xdr.SCSpecUDTEnumCaseV0(doc=b"", name=b"Option2", value=xdr.Uint32(1)),
            ],
        )

        struct_spec = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0
        )
        struct_spec.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Person",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=b"name", type=_type(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
                )
            ],
        )

        func_spec = _function(
            b"test_function",
            inputs=[_input(b"input", _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING))],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
        )

        generated = generate_binding([enum_spec, struct_spec, func_spec], "TestContract")
        assert "enum TestContractStatus {" in generated
        assert "class TestContractPerson {" in generated
        assert "final String name;" in generated
        assert "class TestContract {" in generated
        assert "Future<int> testFunction({" in generated

    def test_generate_binding_dispatches_error_enum_tuple_struct_and_union(self):
        error_enum_spec = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0
        )
        error_enum_spec.udt_error_enum_v0 = xdr.SCSpecUDTErrorEnumV0(
            doc=b"",
            lib=b"",
            name=b"MyError",
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(
                    doc=b"", name=b"Overflow", value=xdr.Uint32(1)
                ),
            ],
        )

        tuple_struct_spec = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0
        )
        tuple_struct_spec.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Pair",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=b"0", type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=b"1", type=_type(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
                ),
            ],
        )

        void_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
        )
        void_case.void_case = xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=b"None")
        tuple_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
        )
        tuple_case.tuple_case = xdr.SCSpecUDTUnionCaseTupleV0(
            doc=b"", name=b"Some", type=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)]
        )
        union_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0)
        union_spec.udt_union_v0 = xdr.SCSpecUDTUnionV0(
            doc=b"", lib=b"", name=b"Choice", cases=[void_case, tuple_case]
        )

        func_spec = _function(
            b"test_function",
            inputs=[_input(b"input", _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING))],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
        )

        generated = generate_binding(
            [error_enum_spec, tuple_struct_spec, union_spec, func_spec],
            "TestContract",
        )
        assert "enum TestContractMyError {" in generated
        assert "Overflow(1);" in generated
        assert "factory TestContractMyError.fromValue(int value)" in generated
        assert "class TestContractPair {" in generated
        assert "final (int, bool) value;" in generated
        assert "enum TestContractChoiceKind {" in generated
        assert "class TestContractChoice {" in generated
        assert "factory TestContractChoice.none()" in generated
        assert "factory TestContractChoice.some(int value)" in generated
        assert "class TestContract {" in generated
        assert "Future<int> testFunction({" in generated

    def test_generate_binding_map_and_64_bit_roundtrip(self):
        # End-to-end emission of a function that takes a Map<String, u64> and
        # returns a timepoint through the full pipeline.
        map_in = _map_type(
            _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
            _type(xdr.SCSpecType.SC_SPEC_TYPE_U64),
        )
        function = _function(
            b"record",
            inputs=[_input(b"entries", map_in)],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT)],
        )
        generated = generate_binding([function], "TestContract")
        assert "required Map<String, BigInt> entries," in generated
        assert "Future<BigInt> record({" in generated
        assert (
            "XdrSCVal.forMap((entries.entries.toList()..sort((a, b) => "
            "_compareBytesLex(utf8.encode(a.key), utf8.encode(b.key)))).map((e) => "
            "XdrSCMapEntry(XdrSCVal.forString(e.key), XdrSCVal.forU64(e.value)))"
            ".toList())" in generated
        )
        assert "return result.timepoint!.uint64;" in generated

    def test_generate_binding_muxed_address_param_and_return(self):
        function = _function(
            b"transfer_muxed",
            inputs=[_input(b"to", _type(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS))],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)],
        )
        generated = generate_binding([function], "TestContract")
        assert "Future<Address> transferMuxed({" in generated
        assert "required Address to," in generated
        assert "to.toXdrSCVal()," in generated
        assert "return Address.fromXdrSCVal(result);" in generated

    def test_generate_binding_escapes_keyword_struct_and_field_names(self):
        struct_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        struct_spec.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"class",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"", name=b"for", type=_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
            ],
        )
        generated = generate_binding([struct_spec], "TestContract")
        assert "class TestContractclass_ {" in generated
        assert "final int for_;" in generated
        # The encoded symbol and decode lookup keep the original spec field name.
        assert "XdrSCVal.forSymbol('for')" in generated
        assert 'for_: fieldsMap["for"]!.u32!.uint32,' in generated

    def test_generate_binding_escapes_keyword_enum_and_error_enum_names(self):
        enum_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0)
        enum_spec.udt_enum_v0 = xdr.SCSpecUDTEnumV0(
            doc=b"",
            lib=b"",
            name=b"enum",
            cases=[xdr.SCSpecUDTEnumCaseV0(doc=b"", name=b"if", value=xdr.Uint32(0))],
        )
        error_enum_spec = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0
        )
        error_enum_spec.udt_error_enum_v0 = xdr.SCSpecUDTErrorEnumV0(
            doc=b"",
            lib=b"",
            name=b"switch",
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(doc=b"", name=b"catch", value=xdr.Uint32(1))
            ],
        )
        generated = generate_binding([enum_spec, error_enum_spec], "TestContract")
        assert "enum TestContractenum_ {" in generated
        assert "If(0);" in generated
        assert "enum TestContractswitch_ {" in generated
        assert "Catch(1);" in generated

    def test_generate_binding_escapes_keyword_union_and_case_names(self):
        void_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
        )
        void_case.void_case = xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=b"break")
        tuple_case = xdr.SCSpecUDTUnionCaseV0(
            xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
        )
        tuple_case.tuple_case = xdr.SCSpecUDTUnionCaseTupleV0(
            doc=b"", name=b"new", type=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)]
        )
        union_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0)
        union_spec.udt_union_v0 = xdr.SCSpecUDTUnionV0(
            doc=b"", lib=b"", name=b"extends", cases=[void_case, tuple_case]
        )
        generated = generate_binding([union_spec], "TestContract")
        assert "class TestContractextends_ {" in generated
        assert "enum TestContractextends_Kind {" in generated
        # Kind values keep the original spec symbol for BOTH case kinds - they are
        # what goes on the wire, while the Dart identifiers are escaped.
        assert "Break('break')" in generated
        assert "New('new')" in generated
        assert "New('new_')" not in generated
        assert "factory TestContractextends_.break_()" in generated
        assert "factory TestContractextends_.new_(int value)" in generated
        assert "final int? new_;" in generated

    def test_generate_binding_escapes_keyword_function_and_param_names(self):
        function = _function(
            b"for",
            inputs=[_input(b"is", _type(xdr.SCSpecType.SC_SPEC_TYPE_STRING))],
            outputs=[],
        )
        generated = generate_binding([function], "TestContract")
        assert "Future<void> for_({" in generated
        assert "required String is_," in generated
        assert "XdrSCVal.forString(is_)," in generated
        # The invoked method name keeps the original spec symbol.
        assert "name: 'for'," in generated
        assert "Future<AssembledTransaction> buildForTx({" in generated

    def test_file_output(self):
        function = _function(
            b"test_function",
            inputs=[],
            outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = generate_binding([function], "TestContract")
            output_path = os.path.join(tmpdir, "test_contract_client.dart")
            with open(output_path, "w") as f:
                f.write(generated)
            assert os.path.exists(output_path)
            with open(output_path, "r") as f:
                content = f.read()
            assert "class TestContract {" in content
            assert (
                "import 'package:stellar_flutter_sdk/stellar_flutter_sdk.dart';"
                in content
            )


class TestCommand:
    def test_invalid_contract_id(self):
        runner = CliRunner()
        result = runner.invoke(command, ["--contract-id", "invalid"])
        assert result.exit_code != 0
        assert "Invalid contract ID" in result.output

    def test_get_specs_failure_aborts(self, monkeypatch):
        def fail(contract_id, rpc_url):
            raise RuntimeError("rpc unreachable")

        monkeypatch.setattr(
            "stellar_contract_bindings.flutter.get_specs_by_contract_id", fail
        )
        runner = CliRunner()
        result = runner.invoke(command, ["--contract-id", _VALID_CONTRACT_ID])
        assert result.exit_code != 0
        assert "Get contract specs failed: rpc unreachable" in result.output

    def test_writes_bindings_to_output_directory(self, monkeypatch):
        specs = [
            _function(
                b"hello",
                inputs=[_input(b"to", _type(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL))],
                outputs=[_type(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)],
            )
        ]
        monkeypatch.setattr(
            "stellar_contract_bindings.flutter.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            # The command creates a missing output directory itself.
            output_dir = os.path.join(tmpdir, "generated")
            result = runner.invoke(
                command,
                [
                    "--contract-id",
                    _VALID_CONTRACT_ID,
                    "--output",
                    output_dir,
                    "--class-name",
                    "MyToken",
                ],
            )
            assert result.exit_code == 0
            output_path = os.path.join(output_dir, "my_token_client.dart")
            assert f"Generated Flutter bindings to {output_path}" in result.output
            with open(output_path) as f:
                content = f.read()
            assert "class MyToken {" in content
            assert "Future<String> hello({" in content

    def test_default_output_is_current_directory(self, monkeypatch):
        specs = [_function(b"noop", inputs=[], outputs=[])]
        monkeypatch.setattr(
            "stellar_contract_bindings.flutter.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(command, ["--contract-id", _VALID_CONTRACT_ID])
            assert result.exit_code == 0
            # Default class name is Contract, written to the working directory.
            with open("contract_client.dart") as f:
                content = f.read()
            assert "class Contract {" in content
            assert "Future<void> noop({" in content


class TestFlutterMapKeySort:
    """Map arguments are sorted ascending by key (host rejects unsorted ScMap)."""

    def _map(self, key_type):
        return to_scval(
            _map_type(_type(key_type), _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            "m",
        )

    def test_int_keys_compareto_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert "m.entries.toList()..sort((a, b) => a.key.compareTo(b.key))" in result

    def test_bigint_keys_compareto_sort(self):
        # BigInt keys compare numerically (signed) via compareTo, same as int.
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_I128)
        assert "..sort((a, b) => a.key.compareTo(b.key))" in result

    def test_string_keys_utf8_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert "..sort((a, b) => _compareBytesLex(utf8.encode(a.key), utf8.encode(b.key)))" in result

    def test_bytes_keys_lexicographic_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert "..sort((a, b) => _compareBytesLex(a.key, b.key))" in result

    def test_bool_keys_false_before_true(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert "..sort((a, b) => (a.key ? 1 : 0).compareTo(b.key ? 1 : 0))" in result

    def test_address_keys_xdr_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        assert "..sort((a, b) => _compareBytesLex(_addressSortBytes(a.key), _addressSortBytes(b.key)))" in result

    def test_muxed_address_keys_xdr_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        assert "..sort((a, b) => _compareBytesLex(_addressSortBytes(a.key), _addressSortBytes(b.key)))" in result

    def test_struct_keyed_map_raises_at_generation(self):
        map_type = _map_type(_udt(b"Point"), _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        with pytest.raises(NotImplementedError):
            to_scval(map_type, "m")

    def _binding_with_map(self, key_type):
        map_in = _map_type(_type(key_type), _type(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        fn = _function(b"put", inputs=[_input(b"m", map_in)], outputs=[])
        return generate_binding([fn], "TestContract")

    def test_byte_helper_and_convert_import_emitted_for_string_keys(self):
        generated = self._binding_with_map(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert "int _compareBytesLex(List<int> a, List<int> b)" in generated
        assert "import 'dart:convert';" in generated

    def test_address_helper_emitted_for_address_keys(self):
        generated = self._binding_with_map(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        assert "Uint8List _addressSortBytes(Address address)" in generated
        assert "int _compareBytesLex(List<int> a, List<int> b)" in generated
        assert "import 'dart:typed_data';" in generated

    def test_helpers_and_convert_absent_for_int_keys(self):
        generated = self._binding_with_map(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert "_compareBytesLex" not in generated
        assert "_addressSortBytes" not in generated
        assert "import 'dart:convert';" not in generated
