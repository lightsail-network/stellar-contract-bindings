"""Tests for Swift binding generator."""

import os
import re

import pytest
from click.testing import CliRunner
from stellar_sdk import xdr

from stellar_contract_bindings.swift import (
    MINIMUM_SDK_VERSION,
    is_swift_keyword,
    is_tuple_struct,
    snake_to_pascal,
    snake_to_camel,
    camel_to_snake,
    escape_keyword,
    prefixed_type_name,
    to_swift_type,
    to_scval,
    from_scval,
    render_info,
    render_enum,
    render_error_enum,
    render_struct,
    render_tuple_struct,
    render_union,
    render_client,
    generate_binding,
    compute_codable_capability,
    command,
)


def _udt(name: bytes) -> xdr.SCSpecTypeDef:
    """Helper: build a UDT type reference by spec name."""
    return xdr.SCSpecTypeDef(
        type=xdr.SCSpecType.SC_SPEC_TYPE_UDT,
        udt=xdr.SCSpecTypeUDT(name=name),
    )


class TestSwiftUtilities:
    """Test Swift utility functions."""
    
    def test_is_swift_keyword(self):
        assert is_swift_keyword("class") is True
        assert is_swift_keyword("func") is True
        assert is_swift_keyword("var") is True
        assert is_swift_keyword("myVariable") is False
        assert is_swift_keyword("hello") is False
    
    def test_snake_to_pascal(self):
        assert snake_to_pascal("hello_world") == "HelloWorld"
        assert snake_to_pascal("my_test_function") == "MyTestFunction"
        assert snake_to_pascal("simple") == "Simple"
        assert snake_to_pascal("") == ""
    
    def test_snake_to_camel(self):
        assert snake_to_camel("hello_world") == "helloWorld"
        assert snake_to_camel("my_test_function") == "myTestFunction"
        assert snake_to_camel("simple") == "simple"
        assert snake_to_camel("") == ""
    
    def test_camel_to_snake(self):
        assert camel_to_snake("HelloWorld") == "hello_world"
        assert camel_to_snake("MyTestFunction") == "my_test_function"
        assert camel_to_snake("simple") == "simple"
        assert camel_to_snake("S") == "s"
    
    def test_escape_keyword(self):
        assert escape_keyword("class") == "`class`"
        assert escape_keyword("func") == "`func`"
        assert escape_keyword("myVariable") == "myVariable"
        assert escape_keyword("hello") == "hello"

    def test_prefixed_type_name(self):
        # Contract UDT names are prefixed with the class name.
        assert prefixed_type_name("DataKey", "Hello") == "HelloDataKey"
        # Primitive and SDK type names pass through unprefixed.
        for name in ("String", "Bool", "Data", "SCAddressXDR", "SCValXDR", "UInt64", "Int128"):
            assert prefixed_type_name(name, "Hello") == name
        # A reference to an error enum resolves to its Error-suffixed declaration.
        assert prefixed_type_name("Common", "Hello", frozenset({"Common"})) == "HelloCommonError"


class TestSwiftTypeConversion:
    """Test Swift type conversion functions."""
    
    def test_to_swift_type_primitives(self):
        # Boolean
        bool_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert to_swift_type(bool_type) == "Bool"
        assert to_swift_type(bool_type, nullable=True) == "Bool?"
        
        # Void
        void_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VOID)
        assert to_swift_type(void_type) == "Void"
        
        # Integers
        u32_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert to_swift_type(u32_type) == "UInt32"
        
        i32_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I32)
        assert to_swift_type(i32_type) == "Int32"
        
        u64_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U64)
        assert to_swift_type(u64_type) == "UInt64"
        
        i64_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I64)
        assert to_swift_type(i64_type) == "Int64"

    def test_to_swift_type_val(self):
        # Val is the raw SCVal passthrough type.
        val_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VAL)
        assert to_swift_type(val_type) == "SCValXDR"
        assert to_swift_type(val_type, nullable=True) == "SCValXDR?"

    def test_to_swift_type_timepoint_duration(self):
        # Timepoint and Duration surface as their underlying u64 representation.
        for kind in (xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT, xdr.SCSpecType.SC_SPEC_TYPE_DURATION):
            assert to_swift_type(xdr.SCSpecTypeDef(type=kind)) == "UInt64"

    def test_to_swift_type_error_raises(self):
        with pytest.raises(NotImplementedError):
            to_swift_type(xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR))

    def test_to_swift_type_bigint(self):
        # BigInt types (represented as String)
        u128_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U128)
        assert to_swift_type(u128_type) == "String"
        
        i128_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I128)
        assert to_swift_type(i128_type) == "String"
        
        u256_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U256)
        assert to_swift_type(u256_type) == "String"
        
        i256_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I256)
        assert to_swift_type(i256_type) == "String"
    
    def test_to_swift_type_string_bytes(self):
        # String
        string_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert to_swift_type(string_type) == "String"
        
        # Symbol
        symbol_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        assert to_swift_type(symbol_type) == "String"
        
        # Bytes
        bytes_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert to_swift_type(bytes_type) == "Data"
        
        # Fixed-length bytes
        bytes_n_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
        assert to_swift_type(bytes_n_type) == "Data"
    
    def test_to_swift_type_address(self):
        # Address
        address_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        assert to_swift_type(address_type) == "SCAddressXDR"
        
        # Muxed Address
        muxed_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        assert to_swift_type(muxed_type) == "SCAddressXDR"
    
    def test_to_swift_type_collections(self):
        # Vector
        element_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        vec_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(element_type=element_type)
        )
        assert to_swift_type(vec_type) == "[UInt32]"
        assert to_swift_type(vec_type, nullable=True) == "[UInt32]?"
        
        # Map
        key_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        val_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U64)
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(key_type=key_type, value_type=val_type)
        )
        assert to_swift_type(map_type) == "[String: UInt64]"
    
    def test_to_swift_type_option(self):
        # Option
        inner_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        option_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
            option=xdr.SCSpecTypeOption(value_type=inner_type)
        )
        assert to_swift_type(option_type) == "UInt32?"
    
    def test_to_swift_type_tuple(self):
        # Empty tuple
        empty_tuple = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
            tuple=xdr.SCSpecTypeTuple(value_types=[])
        )
        assert to_swift_type(empty_tuple) == "Void"
        
        # Multi-element tuple
        type1 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        type2 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        multi_tuple = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
            tuple=xdr.SCSpecTypeTuple(value_types=[type1, type2])
        )
        assert to_swift_type(multi_tuple) == "(UInt32, String)"

    def test_to_swift_type_result(self):
        # A Result maps to its ok type; the error side surfaces as a thrown error.
        result_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
            result=xdr.SCSpecTypeResult(
                ok_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
                error_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
            ),
        )
        assert to_swift_type(result_type) == "UInt32"
        assert to_swift_type(result_type, nullable=True) == "UInt32?"

    def test_to_swift_type_address_keyed_map_raises(self):
        # SCAddressXDR is not Hashable, so an address-keyed Swift Dictionary
        # cannot be represented; the type mapping must fail loudly.
        for key_kind in (
            xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS,
            xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS,
        ):
            map_type = xdr.SCSpecTypeDef(
                type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
                map=xdr.SCSpecTypeMap(
                    key_type=xdr.SCSpecTypeDef(type=key_kind),
                    value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
            )
            with pytest.raises(NotImplementedError):
                to_swift_type(map_type)


class TestSwiftSCValConversion:
    """Test SCVal conversion functions."""
    
    def test_to_scval_primitives(self):
        # Boolean
        bool_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert to_scval(bool_type, "myBool") == "SCValXDR.bool(myBool)"
        
        # Void
        void_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VOID)
        assert to_scval(void_type, "ignored") == "SCValXDR.void"
        
        # U32
        u32_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert to_scval(u32_type, "myU32") == "SCValXDR.u32(myU32)"
        
        # I32
        i32_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I32)
        assert to_scval(i32_type, "myI32") == "SCValXDR.i32(myI32)"

        # I64
        i64_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I64)
        assert to_scval(i64_type, "myI64") == "SCValXDR.i64(myI64)"

        # Timepoint and Duration use their dedicated SCVal constructors, not u64.
        timepoint_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT)
        assert to_scval(timepoint_type, "myTime") == "SCValXDR.timepoint(myTime)"
        duration_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_DURATION)
        assert to_scval(duration_type, "myDur") == "SCValXDR.duration(myDur)"

    def test_to_scval_val_passthrough(self):
        # A raw SCVal argument is passed through unchanged.
        val_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VAL)
        assert to_scval(val_type, "raw") == "raw"

    def test_to_scval_error_raises(self):
        with pytest.raises(NotImplementedError):
            to_scval(xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR), "value")

    def test_to_scval_bigint(self):
        # All four big-integer types encode via the SDK's throwing string initializers.
        for acc in ("u128", "i128", "u256", "i256"):
            td = xdr.SCSpecTypeDef(type=getattr(xdr.SCSpecType, f"SC_SPEC_TYPE_{acc.upper()}"))
            assert to_scval(td, "myBigInt") == f"try SCValXDR.{acc}(stringValue: myBigInt)"

    def test_to_scval_string_bytes(self):
        # String
        string_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert to_scval(string_type, "myString") == "SCValXDR.string(myString)"

        # Symbol
        symbol_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        assert to_scval(symbol_type, "mySymbol") == "SCValXDR.symbol(mySymbol)"

        # Bytes and BytesN share the bytes constructor.
        bytes_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert to_scval(bytes_type, "myBytes") == "SCValXDR.bytes(myBytes)"
        bytes_n_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
        assert to_scval(bytes_n_type, "myBytes") == "SCValXDR.bytes(myBytes)"

    def test_to_scval_address(self):
        # Address and MuxedAddress share the address constructor.
        address_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        assert to_scval(address_type, "myAddress") == "SCValXDR.address(myAddress)"
        muxed_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        assert to_scval(muxed_type, "myAddress") == "SCValXDR.address(myAddress)"

    def test_empty_tuple_encodes_void_decodes_unit(self):
        td = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
            tuple=xdr.SCSpecTypeTuple(value_types=[]),
        )
        assert to_scval(td, "v") == "SCValXDR.void"
        assert from_scval(td, "val") == "()"

    def test_to_scval_option(self):
        # nil encodes as void; a present value is force-unwrapped for the
        # inner conversion.
        inner_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        option_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
            option=xdr.SCSpecTypeOption(value_type=inner_type),
        )
        assert to_scval(option_type, "myOpt") == "(myOpt != nil ? SCValXDR.u32(myOpt!) : SCValXDR.void)"

    def test_from_scval_primitives(self):
        # Boolean
        bool_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert from_scval(bool_type, "val") == "val.bool ?? false"
        
        # Void
        void_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VOID)
        assert from_scval(void_type, "val") == "()"
        
        # U32
        u32_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert from_scval(u32_type, "val") == "val.u32 ?? 0"

    def test_from_scval_val_passthrough(self):
        # A raw SCVal result is passed through unchanged in both modes.
        val_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VAL)
        assert from_scval(val_type, "val") == "val"
        assert from_scval(val_type, "val", "T", throw_on_missing=True) == "val"

    def test_from_scval_error_raises(self):
        with pytest.raises(NotImplementedError):
            from_scval(xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR), "val")

    def test_from_scval_integer_scalars_both_modes(self):
        # Each integer scalar decodes via its own SDK accessor: default 0 in
        # lenient mode, a thrown conversionFailed naming the accessor otherwise.
        for kind, acc in [
            (xdr.SCSpecType.SC_SPEC_TYPE_I32, "i32"),
            (xdr.SCSpecType.SC_SPEC_TYPE_U64, "u64"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I64, "i64"),
            (xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT, "timepoint"),
            (xdr.SCSpecType.SC_SPEC_TYPE_DURATION, "duration"),
        ]:
            td = xdr.SCSpecTypeDef(type=kind)
            assert from_scval(td, "val") == f"val.{acc} ?? 0"
            assert from_scval(td, "val", "T", throw_on_missing=True) == (
                f'try val.{acc} ?? {{ throw TError.conversionFailed(message: "Missing or invalid {acc} value") }}()'
            )

    def test_from_scval_bigint(self):
        # All four big-integer types decode via the SDK's decimal-string accessors.
        for acc in ("u128", "i128", "u256", "i256"):
            td = xdr.SCSpecTypeDef(type=getattr(xdr.SCSpecType, f"SC_SPEC_TYPE_{acc.upper()}"))
            assert from_scval(td, "val") == f'val.{acc}String ?? "0"'
            assert from_scval(td, "val", "T", throw_on_missing=True) == (
                f'try val.{acc}String ?? {{ throw TError.conversionFailed(message: "Missing or invalid {acc} value") }}()'
            )

    def test_from_scval_string_bytes(self):
        # String
        string_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert from_scval(string_type, "val") == 'val.string ?? ""'

        # Symbol
        symbol_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        assert from_scval(symbol_type, "val") == 'val.symbol ?? ""'

        # Bytes and BytesN share the bytes accessor and error message.
        throwing = 'try val.bytes ?? { throw TError.conversionFailed(message: "Missing or invalid bytes value") }()'
        for kind in (xdr.SCSpecType.SC_SPEC_TYPE_BYTES, xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N):
            td = xdr.SCSpecTypeDef(type=kind)
            assert from_scval(td, "val") == "val.bytes ?? Data()"
            assert from_scval(td, "val", "T", throw_on_missing=True) == throwing

    def test_from_scval_address_and_muxed(self):
        # Lenient mode force-unwraps: there is no sensible default address.
        address = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        muxed = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        assert from_scval(address, "val") == "val.address!"
        assert from_scval(muxed, "val") == "val.address!"
        assert from_scval(address, "val", "T", throw_on_missing=True) == (
            'try val.address ?? { throw TError.conversionFailed(message: "Missing or invalid address value") }()'
        )
        assert from_scval(muxed, "val", "T", throw_on_missing=True) == (
            'try val.address ?? { throw TError.conversionFailed(message: "Missing or invalid muxed address value") }()'
        )

    def test_from_scval_result(self):
        # A Result decodes as its ok type.
        result_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
            result=xdr.SCSpecTypeResult(
                ok_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
                error_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
            ),
        )
        assert from_scval(result_type, "val") == "val.u32 ?? 0"

    def test_from_scval_vec(self):
        # A non-throwing element conversion keeps the plain map call.
        vec_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(
                element_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
            ),
        )
        assert from_scval(vec_type, "val") == "val.vec?.map { $0.u32 ?? 0 } ?? []"

    def test_from_scval_nested_vec(self):
        # The inner closure's $0 shadows the outer one, which is valid Swift.
        inner_vec = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(
                element_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
            ),
        )
        vec_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(element_type=inner_vec),
        )
        assert (
            from_scval(vec_type, "val")
            == "val.vec?.map { $0.vec?.map { $0.u32 ?? 0 } ?? [] } ?? []"
        )

    def test_from_scval_map(self):
        # Non-throwing key/value conversions build the dictionary with map.
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
            ),
        )
        assert (
            from_scval(map_type, "val")
            == 'Dictionary(uniqueKeysWithValues: val.map?.map { ($0.key.string ?? "", $0.val.u32 ?? 0) } ?? [])'
        )

    def test_from_scval_map_throwing_value(self):
        # A throwing value conversion (UDT decode) switches to try + compactMap.
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                value_type=_udt(b"Point"),
            ),
        )
        assert (
            from_scval(map_type, "val", "T")
            == 'try Dictionary(uniqueKeysWithValues: val.map?.compactMap { ($0.key.string ?? "", try TPoint.fromSCVal($0.val)) } ?? [])'
        )

    def test_from_scval_map_throwing_key(self):
        # An enum-keyed map decodes fine (raw-value enums are Hashable); the
        # throwing key conversion alone switches the build to try + compactMap.
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=_udt(b"Color"),
                value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
            ),
        )
        assert (
            from_scval(map_type, "val", "T")
            == "try Dictionary(uniqueKeysWithValues: val.map?.compactMap { (try TColor.fromSCVal($0.key), $0.val.u32 ?? 0) } ?? [])"
        )


class TestSwiftUnknownSpecType:
    def test_unknown_spec_type_raises_in_all_converters(self):
        # A spec type without a mapping must fail loudly in every converter.
        class UnknownTypeDef:
            type = object()

        td = UnknownTypeDef()
        with pytest.raises(ValueError):
            to_swift_type(td)
        with pytest.raises(ValueError):
            to_scval(td, "x")
        with pytest.raises(NotImplementedError):
            from_scval(td, "x")


class TestSwiftCodeGeneration:
    """Test Swift code generation functions."""
    
    def test_render_enum(self):
        # Create a test enum
        cases = [
            xdr.SCSpecUDTEnumCaseV0(
                doc=None,
                name=b"pending",
                value=xdr.Uint32(0)
            ),
            xdr.SCSpecUDTEnumCaseV0(
                doc=None,
                name=b"completed",
                value=xdr.Uint32(1)
            ),
            xdr.SCSpecUDTEnumCaseV0(
                doc=None,
                name=b"failed",
                value=xdr.Uint32(2)
            )
        ]
        enum_entry = xdr.SCSpecUDTEnumV0(
            doc=b"Status of a transaction",
            lib=None,
            name=b"Status",
            cases=cases
        )
        
        result = render_enum(enum_entry, "TestContract")
        assert "public enum TestContractStatus: UInt32, Codable, CaseIterable" in result
        assert "case pending = 0" in result
        assert "case completed = 1" in result
        assert "case failed = 2" in result
        assert "public func toSCVal() throws -> SCValXDR" in result
        assert "public static func fromSCVal(_ val: SCValXDR) throws -> TestContractStatus" in result
    
    def test_render_error_enum(self):
        # Create a test error enum
        cases = [
            xdr.SCSpecUDTErrorEnumCaseV0(
                doc=None,
                name=b"not_found",
                value=xdr.Uint32(0)
            ),
            xdr.SCSpecUDTErrorEnumCaseV0(
                doc=None,
                name=b"unauthorized",
                value=xdr.Uint32(1)
            )
        ]
        error_enum = xdr.SCSpecUDTErrorEnumV0(
            doc=b"Common errors",
            lib=None,
            name=b"Common",
            cases=cases
        )
        
        result = render_error_enum(error_enum, "TestContract")
        assert "public enum TestContractCommonError: UInt32, Error, Codable, CaseIterable" in result
        assert "case not_found = 0" in result
        assert "case unauthorized = 1" in result
    
    def test_render_struct(self):
        # Create a test struct
        fields = [
            xdr.SCSpecUDTStructFieldV0(
                doc=None,
                name=b"name",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
            ),
            xdr.SCSpecUDTStructFieldV0(
                doc=None,
                name=b"age",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
            ),
            xdr.SCSpecUDTStructFieldV0(
                doc=None,
                name=b"active",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
            )
        ]
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"User information",
            lib=None,
            name=b"User",
            fields=fields
        )
        
        result = render_struct(struct_entry, "TestContract")
        assert "public struct TestContractUser: Codable" in result
        assert "public let name: String" in result
        assert "public let age: UInt32" in result
        assert "public let active: Bool" in result
        assert "public init(" in result
        assert "public func toSCVal() throws -> SCValXDR" in result
        assert "public static func fromSCVal(_ val: SCValXDR) throws -> TestContractUser" in result
    
    def test_render_tuple_struct(self):
        # Create a test tuple struct
        fields = [
            xdr.SCSpecUDTStructFieldV0(
                doc=None,
                name=b"0",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
            ),
            xdr.SCSpecUDTStructFieldV0(
                doc=None,
                name=b"1",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
            )
        ]
        tuple_struct = xdr.SCSpecUDTStructV0(
            doc=b"A tuple struct",
            lib=None,
            name=b"MyTuple",
            fields=fields
        )
        
        result = render_tuple_struct(tuple_struct, "TestContract")
        assert "public struct TestContractMyTuple: Codable" in result
        assert "public let value: (UInt32, String)" in result
        assert "public init(value: (UInt32, String))" in result
    
    def test_is_tuple_struct(self):
        # Test tuple struct (numeric field names)
        tuple_fields = [
            xdr.SCSpecUDTStructFieldV0(doc=None, name=b"0", type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)),
            xdr.SCSpecUDTStructFieldV0(doc=None, name=b"1", type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING))
        ]
        tuple_struct = xdr.SCSpecUDTStructV0(doc=None, lib=None, name=b"MyTuple", fields=tuple_fields)
        assert is_tuple_struct(tuple_struct) is True
        
        # Test normal struct (non-numeric field names)
        normal_fields = [
            xdr.SCSpecUDTStructFieldV0(doc=None, name=b"name", type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)),
            xdr.SCSpecUDTStructFieldV0(doc=None, name=b"age", type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32))
        ]
        normal_struct = xdr.SCSpecUDTStructV0(doc=None, lib=None, name=b"User", fields=normal_fields)
        assert is_tuple_struct(normal_struct) is False
    
    def test_render_union(self):
        # Create a test union with both void and tuple cases
        cases = [
            xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                void_case=xdr.SCSpecUDTUnionCaseVoidV0(
                    doc=None,
                    name=b"none"
                )
            ),
            xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                    doc=None,
                    name=b"some",
                    type=[xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)]
                )
            ),
            xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                    doc=None,
                    name=b"pair",
                    type=[
                        xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                        xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
                    ]
                )
            )
        ]
        union_entry = xdr.SCSpecUDTUnionV0(
            doc=b"Optional value",
            name=b"OptionalValue",
            lib=None,
            cases=cases
        )
        
        result = render_union(union_entry, "TestContract")
        assert "public enum TestContractOptionalValue" in result
        assert "case `none`" in result  # 'none' is a Swift keyword, so it's escaped
        assert "case `some`(UInt32)" in result  # 'some' is also a Swift keyword
        assert "case pair(String, Bool)" in result
        assert "public func toSCVal() throws -> SCValXDR" in result
        assert "public static func fromSCVal(_ val: SCValXDR) throws -> TestContractOptionalValue" in result
        assert "TestContractError.conversionFailed" in result  # Check for contract-specific error
    
    def test_render_client(self):
        # Create test function specs
        input1 = xdr.SCSpecFunctionInputV0(
            doc=None,
            name=b"amount",
            type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U64)
        )
        input2 = xdr.SCSpecFunctionInputV0(
            doc=None,
            name=b"recipient",
            type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        )
        
        function1 = xdr.SCSpecFunctionV0(
            doc=b"Transfer tokens",
            name=xdr.SCSymbol(sc_symbol=b"transfer"),
            inputs=[input1, input2],
            outputs=[xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BOOL)]
        )
        
        function2 = xdr.SCSpecFunctionV0(
            doc=b"Get balance",
            name=xdr.SCSymbol(sc_symbol=b"balance_of"),
            inputs=[xdr.SCSpecFunctionInputV0(
                doc=None,
                name=b"owner",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
            )],
            outputs=[xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U64)]
        )
        
        result = render_client([function1, function2], "TokenContract")
        
        # Check class definition
        assert "public class TokenContract" in result
        assert "private let client: SorobanClient" in result
        
        # Check transfer method
        assert "public func transfer(" in result
        assert "amount: UInt64" in result
        assert "recipient: SCAddressXDR" in result
        assert "-> Bool" in result
        
        # Check balanceOf method (snake_case to camelCase conversion)
        assert "public func balanceOf(" in result
        assert "owner: SCAddressXDR" in result
        assert "-> UInt64" in result
        
        # Check build methods
        assert "public func buildTransferTx(" in result
        assert "public func buildBalanceOfTx(" in result
        assert "-> AssembledTransaction" in result
    
    def test_generate_binding(self):
        # Create a complete set of specs
        specs = [
            # Enum
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0,
                udt_enum_v0=xdr.SCSpecUDTEnumV0(
                    doc=None,
                    lib=None,
                    name=b"Status",
                    cases=[
                        xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"active", value=xdr.Uint32(0)),
                        xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"inactive", value=xdr.Uint32(1))
                    ]
                )
            ),
            # Struct
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
                udt_struct_v0=xdr.SCSpecUDTStructV0(
                    doc=None,
                    lib=None,
                    name=b"User",
                    fields=[
                        xdr.SCSpecUDTStructFieldV0(
                            doc=None,
                            name=b"id",
                            type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U64)
                        ),
                        xdr.SCSpecUDTStructFieldV0(
                            doc=None,
                            name=b"status",
                            type=xdr.SCSpecTypeDef(
                                type=xdr.SCSpecType.SC_SPEC_TYPE_UDT,
                                udt=xdr.SCSpecTypeUDT(name=b"Status")
                            )
                        )
                    ]
                )
            ),
            # Function
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                function_v0=xdr.SCSpecFunctionV0(
                    doc=None,
                    name=xdr.SCSymbol(sc_symbol=b"get_user"),
                    inputs=[
                        xdr.SCSpecFunctionInputV0(
                            doc=None,
                            name=b"id",
                            type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U64)
                        )
                    ],
                    outputs=[
                        xdr.SCSpecTypeDef(
                            type=xdr.SCSpecType.SC_SPEC_TYPE_UDT,
                            udt=xdr.SCSpecTypeUDT(name=b"User")
                        )
                    ]
                )
            )
        ]
        
        result = generate_binding(specs, "MyContract")
        
        # Check that all parts are generated
        assert "import Foundation" in result
        assert "import stellarsdk" in result
        assert "public enum MyContractStatus: UInt32, Codable, CaseIterable" in result
        assert "public struct MyContractUser: Codable" in result
        assert "public class MyContract" in result
        assert "public func getUser(" in result

    def test_generate_binding_tuple_struct_and_union(self):
        # Tuple-struct (numeric field names) and union entries dispatch to
        # their dedicated renderers with the computed Codable capability.
        specs = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
                udt_struct_v0=xdr.SCSpecUDTStructV0(
                    doc=None,
                    lib=None,
                    name=b"Pair",
                    fields=[
                        xdr.SCSpecUDTStructFieldV0(
                            doc=None,
                            name=b"0",
                            type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
                        ),
                        xdr.SCSpecUDTStructFieldV0(
                            doc=None,
                            name=b"1",
                            type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                        ),
                    ],
                ),
            ),
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
                udt_union_v0=xdr.SCSpecUDTUnionV0(
                    doc=None,
                    lib=None,
                    name=b"Choice",
                    cases=[
                        xdr.SCSpecUDTUnionCaseV0(
                            kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                            void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=None, name=b"idle"),
                        ),
                        xdr.SCSpecUDTUnionCaseV0(
                            kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                            tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                                doc=None,
                                name=b"busy",
                                type=[xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)],
                            ),
                        ),
                    ],
                ),
            ),
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                function_v0=xdr.SCSpecFunctionV0(
                    doc=None,
                    name=xdr.SCSymbol(sc_symbol=b"pick"),
                    inputs=[],
                    outputs=[
                        xdr.SCSpecTypeDef(
                            type=xdr.SCSpecType.SC_SPEC_TYPE_UDT,
                            udt=xdr.SCSpecTypeUDT(name=b"Choice"),
                        )
                    ],
                ),
            ),
        ]
        result = generate_binding(specs, "T")
        # Tuple struct: rendered as a custom-Codable wrapper around a Swift tuple.
        assert "public struct TPair: Codable" in result
        assert "public let value: (UInt32, String)" in result
        assert "public init(from decoder: Decoder) throws" in result
        # Union: rendered as a Codable enum with void and payload cases.
        assert "public enum TChoice: Codable" in result
        assert "case idle" in result
        assert "case busy(UInt32)" in result
        # Client method referencing the union type.
        assert "public func pick(" in result
        assert ") async throws -> TChoice {" in result

    def test_generate_binding_ends_with_single_newline(self):
        specs = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                function_v0=xdr.SCSpecFunctionV0(
                    doc=None,
                    name=xdr.SCSymbol(sc_symbol=b"noop"),
                    inputs=[],
                    outputs=[],
                ),
            )
        ]
        result = generate_binding(specs, "MyContract")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")
        assert not any(line != line.rstrip() for line in result.splitlines())


class TestSwiftResultAndTupleReturns:
    """RESULT-typed inputs and multi-output functions must fail loudly."""

    def test_result_to_scval_raises(self):
        # A Result-typed input has no meaningful SCVal encoding; the generator
        # must raise rather than emit a NotImplementedError instance as text.
        result_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
            result=xdr.SCSpecTypeResult(
                ok_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
                error_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
            ),
        )
        with pytest.raises(NotImplementedError):
            to_scval(result_type, "value")

    def test_empty_tuple_output_is_void_without_return(self):
        # An empty-tuple output resolves to Void: no return type hint, no
        # unused result binding, no return statement.
        empty_tuple = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE)
        empty_tuple.tuple = xdr.SCSpecTypeTuple(value_types=[])
        function = xdr.SCSpecFunctionV0(
            doc=None,
            name=xdr.SCSymbol(sc_symbol=b"empty_tuple"),
            inputs=[],
            outputs=[empty_tuple],
        )
        result = render_client([function], "TestContract")
        assert "public func emptyTuple(" in result
        assert "async throws {" in result
        assert "-> Void" not in result
        assert "_ = try await client.invokeMethod(" in result
        assert "return ()" not in result

    def test_multi_output_raises(self):
        # Soroban functions have at most one output; the multi-output path is
        # dead and must raise. The XDR constructor caps outputs at 1, so the
        # list is populated after construction to reach the dead branch.
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        string = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        function = xdr.SCSpecFunctionV0(
            doc=None,
            name=xdr.SCSymbol(sc_symbol=b"f"),
            inputs=[],
            outputs=[u32],
        )
        function.outputs = [u32, string]
        with pytest.raises(NotImplementedError):
            render_client([function], "TestContract")

    def test_single_tuple_output_supported(self):
        # A single tuple-typed output is a normal single output and keeps working.
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        string = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        tuple_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
            tuple=xdr.SCSpecTypeTuple(value_types=[u32, string]),
        )
        function = xdr.SCSpecFunctionV0(
            doc=None,
            name=xdr.SCSymbol(sc_symbol=b"g"),
            inputs=[],
            outputs=[tuple_type],
        )
        result = render_client([function], "TestContract")
        assert "-> (UInt32, String)" in result
        assert "result.vec![0]" in result
        assert "result.vec![1]" in result
        # Template placeholders and doubled braces must never leak into rendered output.
        assert "{{ class_name }}" not in result
        assert "{{{{" not in result


class TestSwiftErrorEnumReferences:
    """Error enums are declared with an Error suffix; references must match."""

    def _specs(self):
        error_enum = xdr.SCSpecEntry(
            kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0,
            udt_error_enum_v0=xdr.SCSpecUDTErrorEnumV0(
                doc=None,
                lib=None,
                name=b"Common",
                cases=[
                    xdr.SCSpecUDTErrorEnumCaseV0(doc=None, name=b"not_found", value=xdr.Uint32(1)),
                ],
            ),
        )
        # Struct with a field typed as the error enum.
        holder = xdr.SCSpecEntry(
            kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
            udt_struct_v0=xdr.SCSpecUDTStructV0(
                doc=None,
                lib=None,
                name=b"Holder",
                fields=[xdr.SCSpecUDTStructFieldV0(doc=None, name=b"err", type=_udt(b"Common"))],
            ),
        )
        # Function taking the error enum as an argument and returning it.
        function = xdr.SCSpecEntry(
            kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
            function_v0=xdr.SCSpecFunctionV0(
                doc=None,
                name=xdr.SCSymbol(sc_symbol=b"check"),
                inputs=[xdr.SCSpecFunctionInputV0(doc=None, name=b"e", type=_udt(b"Common"))],
                outputs=[_udt(b"Common")],
            ),
        )
        return [error_enum, holder, function]

    def test_error_enum_declaration_is_suffixed(self):
        result = generate_binding(self._specs(), "T")
        assert "public enum TCommonError: UInt32, Error, Codable, CaseIterable" in result

    def test_error_enum_reference_as_argument_and_return(self):
        result = generate_binding(self._specs(), "T")
        # Argument and return references resolve to the suffixed declaration name.
        assert "e: TCommonError," in result
        assert ") async throws -> TCommonError {" in result
        # Encode/decode call sites use the suffixed name.
        assert "return try TCommonError.fromSCVal(result)" in result

    def test_error_enum_reference_as_struct_field(self):
        result = generate_binding(self._specs(), "T")
        assert "public let err: TCommonError" in result
        assert "try TCommonError.fromSCVal(field_0_val)" in result

    def test_error_enum_reference_inside_containers(self):
        # Container-nested references resolve to the suffixed name too.
        names = frozenset({"Common"})
        vec_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(element_type=_udt(b"Common")),
        )
        assert to_swift_type(vec_type, class_name="T", error_enum_names=names) == "[TCommonError]"
        assert from_scval(vec_type, "val", "T", error_enum_names=names) == (
            "try val.vec?.compactMap { try TCommonError.fromSCVal($0) } ?? []"
        )

    def test_no_unsuffixed_error_enum_reference_in_code(self):
        result = generate_binding(self._specs(), "T")
        # In code (non-comment) lines, no bare TCommon reference may appear -
        # it would not resolve to any declaration. Doc comments may still spell
        # the base type name and are excluded.
        for line in result.splitlines():
            if line.strip().startswith("//"):
                continue
            assert re.search(r"\bTCommon\b(?!Error)", line) is None, line


class TestSwiftKeywordCaseNames:
    """Keyword-named identifiers are escaped at declaration and reference; wire names stay raw."""

    def _union(self):
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        cases = [
            # Void case named after a Swift keyword.
            xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=None, name=b"as"),
            ),
            # Tuple case named after a Swift keyword.
            xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(doc=None, name=b"import", type=[u32]),
            ),
            # Case named "Void": not a reserved keyword, must stay unescaped.
            xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=None, name=b"Void"),
            ),
        ]
        return xdr.SCSpecUDTUnionV0(doc=None, lib=None, name=b"K", cases=cases)

    def test_keyword_void_case_escaped_everywhere(self):
        result = render_union(self._union(), "T")
        # Declaration and switch reference use backticks.
        assert "case `as`" in result
        assert "case .`as`:" in result
        assert "return .`as`" in result
        # The wire symbol keeps the raw, unescaped name.
        assert '.symbol("as")' in result
        assert 'case "as":' in result

    def test_keyword_tuple_case_escaped_everywhere(self):
        result = render_union(self._union(), "T")
        assert "case `import`(UInt32)" in result
        assert "case .`import`(let value):" in result
        assert '.symbol("import")' in result
        assert 'case "import":' in result
        assert "return .`import`(" in result

    def test_void_named_case_not_escaped(self):
        # "Void" is a typealias, not a reserved keyword: valid unescaped.
        result = render_union(self._union(), "T")
        assert "case Void" in result
        assert "case .Void:" in result
        assert "return .Void" in result
        assert '.symbol("Void")' in result
        # Never wrapped in backticks.
        assert "`Void`" not in result

    def test_keyword_struct_field_escaped_with_raw_wire_key(self):
        entry = xdr.SCSpecUDTStructV0(
            doc=None, lib=None, name=b"Cfg",
            fields=[xdr.SCSpecUDTStructFieldV0(
                doc=None, name=b"default",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
            )],
        )
        result = render_struct(entry, "T")
        # Property, initializer, and assignment all use the backticked name.
        assert "public let `default`: UInt32" in result
        assert "`default`: UInt32" in result
        assert "self.`default` = `default`" in result
        # The wire map key keeps the raw field name.
        assert 'key: .symbol("default")' in result
        assert 'map["default"]' in result

    def test_keyword_function_param_escaped(self):
        fn = xdr.SCSpecFunctionV0(
            doc=None,
            name=xdr.SCSymbol(sc_symbol=b"check"),
            inputs=[xdr.SCSpecFunctionInputV0(
                doc=None, name=b"in",
                type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
            )],
            outputs=[],
        )
        result = render_client([fn], "T")
        # Parameter declaration and the args-array reference are backticked.
        assert "`in`: UInt32," in result
        assert "SCValXDR.u32(`in`)" in result

    def test_keyword_function_name_escaped(self):
        # A contract function named after a Swift keyword declares a backticked
        # method; the invoked wire name stays raw, and the buildXxxTx variant
        # needs no escape (its name never collides).
        fn = xdr.SCSpecFunctionV0(
            doc=None,
            name=xdr.SCSymbol(sc_symbol=b"default"),
            inputs=[],
            outputs=[],
        )
        result = render_client([fn], "T")
        assert "public func `default`(" in result
        assert "public func buildDefaultTx(" in result
        assert 'name: "default"' in result


class TestSwiftOptionDecode:
    """Option decode must be a plain expression valid in any position."""

    def _option(self, inner_type, throw_on_missing):
        option_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
            option=xdr.SCSpecTypeOption(value_type=inner_type),
        )
        return from_scval(option_type, "val", "T", throw_on_missing=throw_on_missing)

    def test_option_decode_uses_isvoid_ternary(self):
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        result = self._option(u32, throw_on_missing=False)
        assert result == "(val.isVoid ? nil : val.u32 ?? 0)"

    def test_option_decode_not_if_expression(self):
        # An `if case .void` expression only compiles as a direct return or
        # assignment; it fails when nested (struct field, closure, tuple element).
        for throw in (True, False):
            u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
            string = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
            for inner in (u32, string):
                result = self._option(inner, throw_on_missing=throw)
                assert "if case" not in result
                assert result.startswith("(") and ".isVoid ? nil :" in result

    def test_option_decode_nested_in_vec_is_valid_expression(self):
        # Option inside a vec element must remain a nestable expression.
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        option_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
            option=xdr.SCSpecTypeOption(value_type=u32),
        )
        vec_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(element_type=option_type),
        )
        result = from_scval(vec_type, "val", "T", throw_on_missing=True)
        assert "$0.isVoid ? nil :" in result
        assert "if case" not in result


class TestSwiftCodableConsistency:
    """Every generated UDT is Codable so it can be a field of a Codable struct."""

    def test_enum_is_codable(self):
        entry = xdr.SCSpecUDTEnumV0(
            doc=None, lib=None, name=b"Color",
            cases=[xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"red", value=xdr.Uint32(0))],
        )
        result = render_enum(entry, "T")
        assert "public enum TColor: UInt32, Codable, CaseIterable" in result

    def test_error_enum_is_codable(self):
        entry = xdr.SCSpecUDTErrorEnumV0(
            doc=None, lib=None, name=b"Err",
            cases=[xdr.SCSpecUDTErrorEnumCaseV0(doc=None, name=b"bad", value=xdr.Uint32(1))],
        )
        result = render_error_enum(entry, "T")
        assert "public enum TErrError: UInt32, Error, Codable, CaseIterable" in result

    def test_union_is_codable(self):
        entry = xdr.SCSpecUDTUnionV0(
            doc=None, lib=None, name=b"Shape",
            cases=[xdr.SCSpecUDTUnionCaseV0(
                kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=None, name=b"none"),
            )],
        )
        result = render_union(entry, "T")
        assert "public enum TShape: Codable" in result

    def test_tuple_struct_has_custom_codable(self):
        entry = xdr.SCSpecUDTStructV0(
            doc=None, lib=None, name=b"Pair",
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"0", type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                xdr.SCSpecUDTStructFieldV0(doc=None, name=b"1", type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)),
            ],
        )
        result = render_tuple_struct(entry, "T")
        # Conformance is kept, implemented explicitly since Swift tuples are not Codable.
        assert "public struct TPair: Codable" in result
        assert "public init(from decoder: Decoder) throws" in result
        assert "public func encode(to encoder: Encoder) throws" in result
        assert "var container = try decoder.unkeyedContainer()" in result
        assert "try container.decode(UInt32.self)" in result
        assert "try container.decode(String.self)" in result
        assert "try container.encode(value.0)" in result
        assert "try container.encode(value.1)" in result


class TestSwiftConditionalCodable:
    """Codable is emitted only where the type graph supports it (no Swift tuple)."""

    @staticmethod
    def _tuple(*value_types):
        td = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_TUPLE)
        td.tuple = xdr.SCSpecTypeTuple(value_types=list(value_types))
        return td

    @staticmethod
    def _vec(inner):
        td = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_VEC)
        td.vec = xdr.SCSpecTypeVec(element_type=inner)
        return td

    @staticmethod
    def _field(name, td):
        return xdr.SCSpecUDTStructFieldV0(doc=None, name=name, type=td)

    @staticmethod
    def _struct_entry(name, fields):
        return xdr.SCSpecEntry(
            kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
            udt_struct_v0=xdr.SCSpecUDTStructV0(doc=None, lib=None, name=name, fields=fields),
        )

    @staticmethod
    def _tuple_case(name, *types):
        return xdr.SCSpecUDTUnionCaseV0(
            kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
            tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(doc=None, name=name, type=list(types)),
        )

    @staticmethod
    def _union_entry(name, cases):
        return xdr.SCSpecEntry(
            kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
            udt_union_v0=xdr.SCSpecUDTUnionV0(doc=None, lib=None, name=name, cases=cases),
        )

    def _u32(self):
        return xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)

    def test_struct_with_tuple_field_omits_codable(self):
        entry = xdr.SCSpecUDTStructV0(
            doc=None, lib=None, name=b"HasTuple",
            fields=[self._field(b"t", self._tuple(self._u32(), xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)))],
        )
        result = render_struct(entry, "T", frozenset(), codable=False)
        assert "public struct THasTuple {" in result
        assert ": Codable" not in result
        # Wire conversion methods remain.
        assert "public func toSCVal() throws -> SCValXDR" in result
        assert "public static func fromSCVal(_ val: SCValXDR) throws -> THasTuple" in result

    def test_union_with_vec_tuple_payload_omits_codable(self):
        entry = xdr.SCSpecUDTUnionV0(
            doc=None, lib=None, name=b"Rows",
            cases=[self._tuple_case(b"rows", self._vec(self._tuple(self._u32())))],
        )
        result = render_union(entry, "T", frozenset(), codable=False)
        assert "public enum TRows {" in result
        assert ": Codable" not in result
        assert "public func toSCVal() throws -> SCValXDR" in result

    def test_tuple_struct_incapable_omits_conformance_and_custom_coding(self):
        entry = xdr.SCSpecUDTStructV0(
            doc=None, lib=None, name=b"Pair",
            fields=[
                self._field(b"0", self._tuple(self._u32(), self._u32())),
                self._field(b"1", xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)),
            ],
        )
        result = render_tuple_struct(entry, "T", frozenset(), codable=False)
        assert "public struct TPair {" in result
        assert ": Codable" not in result
        assert "init(from decoder: Decoder)" not in result
        assert "func encode(to encoder: Encoder)" not in result
        # Wire conversion and the value initializer remain.
        assert "public init(value: " in result
        assert "public func toSCVal() throws -> SCValXDR" in result

    def test_capability_direct_tuple_field(self):
        specs = [self._struct_entry(b"HasTuple", [self._field(b"t", self._tuple(self._u32()))])]
        assert compute_codable_capability(specs) == {"HasTuple": False}

    def test_capability_vec_tuple_union(self):
        specs = [self._union_entry(b"Data", [self._tuple_case(b"rows", self._vec(self._tuple(self._u32())))])]
        assert compute_codable_capability(specs)["Data"] is False

    def test_capability_option_wrapped_tuple(self):
        option_td = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
            option=xdr.SCSpecTypeOption(value_type=self._tuple(self._u32())),
        )
        specs = [self._struct_entry(b"Opt", [self._field(b"maybe", option_td)])]
        assert compute_codable_capability(specs)["Opt"] is False

    def test_capability_map_value_wrapped_tuple(self):
        map_td = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=self._u32(),
                value_type=self._tuple(self._u32()),
            ),
        )
        specs = [self._struct_entry(b"MapV", [self._field(b"m", map_td)])]
        assert compute_codable_capability(specs)["MapV"] is False

    def test_capability_result_wrapped_tuple(self):
        result_td = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
            result=xdr.SCSpecTypeResult(
                ok_type=self._tuple(self._u32()),
                error_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
            ),
        )
        specs = [self._struct_entry(b"Res", [self._field(b"r", result_td)])]
        assert compute_codable_capability(specs)["Res"] is False

    def test_capability_result_wrapped_scalar_is_capable(self):
        result_td = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
            result=xdr.SCSpecTypeResult(
                ok_type=self._u32(),
                error_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
            ),
        )
        specs = [self._struct_entry(b"Res", [self._field(b"r", result_td)])]
        assert compute_codable_capability(specs)["Res"] is True

    def test_capability_unknown_udt_reference_is_capable(self):
        # A reference to a UDT not declared in the spec contributes no tuple.
        specs = [self._struct_entry(b"Ref", [self._field(b"x", _udt(b"External"))])]
        assert compute_codable_capability(specs)["Ref"] is True

    def test_capability_transitive_poisoning(self):
        specs = [
            self._struct_entry(b"A", [self._field(b"b", _udt(b"B"))]),
            self._struct_entry(b"B", [self._field(b"t", self._tuple(self._u32()))]),
        ]
        cap = compute_codable_capability(specs)
        assert cap["A"] is False and cap["B"] is False

    def test_capability_fully_capable_graph(self):
        specs = [
            self._struct_entry(b"A", [self._field(b"b", _udt(b"B")), self._field(b"n", self._u32())]),
            self._struct_entry(b"B", [self._field(b"s", xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING))]),
        ]
        cap = compute_codable_capability(specs)
        assert cap["A"] is True and cap["B"] is True

    def test_capability_cycle_without_tuple_is_capable(self):
        specs = [
            self._struct_entry(b"A", [self._field(b"b", _udt(b"B"))]),
            self._struct_entry(b"B", [self._field(b"a", _udt(b"A"))]),
        ]
        cap = compute_codable_capability(specs)
        assert cap["A"] is True and cap["B"] is True

    def test_capability_cycle_with_tuple_is_incapable(self):
        # C <-> D cycle where C also holds a tuple: both must be incapable.
        specs = [
            self._struct_entry(b"C", [self._field(b"d", _udt(b"D")), self._field(b"t", self._tuple(self._u32()))]),
            self._struct_entry(b"D", [self._field(b"c", _udt(b"C"))]),
        ]
        cap = compute_codable_capability(specs)
        assert cap["C"] is False and cap["D"] is False

    def test_capability_enum_always_capable(self):
        specs = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0,
                udt_enum_v0=xdr.SCSpecUDTEnumV0(
                    doc=None, lib=None, name=b"Color",
                    cases=[xdr.SCSpecUDTEnumCaseV0(doc=None, name=b"red", value=xdr.Uint32(0))],
                ),
            )
        ]
        assert compute_codable_capability(specs)["Color"] is True

    def test_generate_binding_selective_codable(self):
        specs = [
            self._struct_entry(b"Capable", [self._field(b"n", self._u32())]),
            self._struct_entry(b"Poisoned", [self._field(b"t", self._tuple(self._u32(), self._u32()))]),
        ]
        result = generate_binding(specs, "T")
        assert "public struct TCapable: Codable {" in result
        assert "public struct TPoisoned {" in result


class TestSwiftEncodeTryHygiene:
    """vec/map encode marks the map call throwing only when the element does."""

    def _vec(self, element_type):
        vec_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(element_type=element_type),
        )
        return to_scval(vec_type, "v")

    def _map(self, val_type):
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                value_type=val_type,
            ),
        )
        return to_scval(map_type, "v")

    def test_vec_non_throwing_element_omits_try(self):
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        result = self._vec(u32)
        assert result == "SCValXDR.vec(v.map { SCValXDR.u32($0) })"
        assert "vec(try" not in result

    def test_vec_throwing_element_keeps_try(self):
        u128 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U128)
        result = self._vec(u128)
        assert result == "SCValXDR.vec(try v.map { try SCValXDR.u128(stringValue: $0) })"

    def test_map_non_throwing_value_omits_try(self):
        # String key comparator does not throw, so a non-throwing value omits try.
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        result = self._map(u32)
        assert result.startswith("SCValXDR.map(v.sorted(by: {")
        assert "map(try" not in result

    def test_map_throwing_value_keeps_try(self):
        u128 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U128)
        result = self._map(u128)
        assert result.startswith("SCValXDR.map(try v.sorted(by: {")

    def test_vec_of_option_with_throwing_inner_keeps_try(self):
        # Option encode places try inside a ternary branch (valid Swift; the
        # emitted shape is swiftc-verified) and the containing vec map call
        # picks it up and becomes throwing.
        option_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
            option=xdr.SCSpecTypeOption(
                value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U128)
            ),
        )
        result = self._vec(option_type)
        assert result == (
            "SCValXDR.vec(try v.map { ($0 != nil ? try SCValXDR.u128(stringValue: $0!) : SCValXDR.void) })"
        )


class TestSwiftMapKeySort:
    """Map arguments are sorted ascending by key (host rejects unsorted ScMap)."""

    def _map(self, key_type):
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=xdr.SCSpecTypeDef(type=key_type),
                value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
            ),
        )
        return to_scval(map_type, "m")

    def test_u32_keys_numeric_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert "m.sorted(by: { $0.key < $1.key })" in result

    def test_string_keys_utf8_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert "m.sorted(by: { $0.key.utf8.lexicographicallyPrecedes($1.key.utf8) })" in result

    def test_symbol_keys_utf8_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        assert "$0.key.utf8.lexicographicallyPrecedes($1.key.utf8)" in result

    def test_bytes_keys_lexicographic_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert "m.sorted(by: { $0.key.lexicographicallyPrecedes($1.key) })" in result

    def test_bool_keys_false_before_true(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert "m.sorted(by: { !$0.key && $1.key })" in result

    def test_bigint_keys_decimal_numeric_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_I128)
        assert "m.sorted(by: { scMapKeyDecimalAscending($0.key, $1.key) })" in result

    def test_address_keyed_map_raises_not_hashable(self):
        # SCAddressXDR is not Hashable, so an address-keyed Swift Dictionary
        # cannot be represented; generation must fail loudly.
        with pytest.raises(NotImplementedError):
            self._map(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)

    def test_struct_keyed_map_raises_at_generation(self):
        map_type = xdr.SCSpecTypeDef(
            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
            map=xdr.SCSpecTypeMap(
                key_type=xdr.SCSpecTypeDef(
                    type=xdr.SCSpecType.SC_SPEC_TYPE_UDT,
                    udt=xdr.SCSpecTypeUDT(name=b"Point"),
                ),
                value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
            ),
        )
        with pytest.raises(NotImplementedError):
            to_scval(map_type, "m")

    def test_decimal_helper_emitted_only_when_needed(self):
        # Helper appears only when a big-integer-keyed map is generated.
        def fn_with_map(key_type):
            return xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                function_v0=xdr.SCSpecFunctionV0(
                    doc=None,
                    name=xdr.SCSymbol(sc_symbol=b"f"),
                    inputs=[xdr.SCSpecFunctionInputV0(
                        doc=None, name=b"m",
                        type=xdr.SCSpecTypeDef(
                            type=xdr.SCSpecType.SC_SPEC_TYPE_MAP,
                            map=xdr.SCSpecTypeMap(
                                key_type=xdr.SCSpecTypeDef(type=key_type),
                                value_type=xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32),
                            ),
                        ),
                    )],
                    outputs=[],
                ),
            )
        with_bigint = generate_binding([fn_with_map(xdr.SCSpecType.SC_SPEC_TYPE_U128)], "T")
        without_bigint = generate_binding([fn_with_map(xdr.SCSpecType.SC_SPEC_TYPE_U32)], "T")
        assert "fileprivate func scMapKeyDecimalAscending" in with_bigint
        assert "fileprivate func scMapKeyDecimalAscending" not in without_bigint


class TestSwiftVoidInvokeAssignment:
    """Void methods discard the invoke result to avoid an unused-value warning."""

    def _client(self, outputs):
        fn = xdr.SCSpecFunctionV0(
            doc=None, name=xdr.SCSymbol(sc_symbol=b"act"), inputs=[], outputs=outputs
        )
        return render_client([fn], "T")

    def test_void_method_discards_result(self):
        result = self._client([])
        assert "_ = try await client.invokeMethod(" in result
        assert "let result = try await client.invokeMethod(" not in result

    def test_value_method_binds_result(self):
        u32 = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U32)
        result = self._client([u32])
        assert "let result = try await client.invokeMethod(" in result
        assert "_ = try await client.invokeMethod(" not in result


class TestSwiftHeader:
    """Header advertises the minimum required target SDK version."""

    def test_render_info_contains_minimum_sdk_version(self):
        header = render_info()
        assert MINIMUM_SDK_VERSION in header
        assert "stellar-ios-mac-sdk" in header

    def test_generated_binding_header_contains_minimum_sdk_version(self):
        specs = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                function_v0=xdr.SCSpecFunctionV0(
                    doc=None,
                    name=xdr.SCSymbol(sc_symbol=b"noop"),
                    inputs=[],
                    outputs=[],
                ),
            )
        ]
        result = generate_binding(specs, "T")
        assert f"v{MINIMUM_SDK_VERSION} or later" in result


class TestSwiftCommand:
    """CLI command behavior with the RPC spec fetch stubbed out."""

    CONTRACT_ID = "CDX62OSVWH2M6RECZXUCLG2YF4YMX3HIYSXMDEYUDAQPUQCMONYV46RX"

    @pytest.fixture
    def stubbed_specs(self, monkeypatch):
        specs = [
            xdr.SCSpecEntry(
                kind=xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
                function_v0=xdr.SCSpecFunctionV0(
                    doc=None,
                    name=xdr.SCSymbol(sc_symbol=b"noop"),
                    inputs=[],
                    outputs=[],
                ),
            )
        ]
        monkeypatch.setattr(
            "stellar_contract_bindings.swift.get_specs_by_contract_id",
            lambda contract_id, rpc_url: specs,
        )

    def test_invalid_contract_id_aborts(self):
        runner = CliRunner()
        result = runner.invoke(command, ["--contract-id", "invalid"])
        assert result.exit_code != 0
        assert "Invalid contract ID" in result.output

    def test_spec_fetch_failure_aborts(self, monkeypatch):
        def raise_fetch(contract_id, rpc_url):
            raise RuntimeError("rpc unavailable")

        monkeypatch.setattr(
            "stellar_contract_bindings.swift.get_specs_by_contract_id", raise_fetch
        )
        runner = CliRunner()
        result = runner.invoke(command, ["--contract-id", self.CONTRACT_ID])
        assert result.exit_code != 0
        assert "Get contract specs failed" in result.output

    def test_default_output_writes_class_named_file_in_cwd(self, stubbed_specs):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(command, ["--contract-id", self.CONTRACT_ID])
            assert result.exit_code == 0
            assert os.path.exists("ContractClient.swift")
            with open("ContractClient.swift") as f:
                content = f.read()
            assert "public class ContractClient {" in content
            assert "Generated Swift bindings to" in result.output

    def test_missing_output_directory_is_created(self, stubbed_specs):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                command,
                ["--contract-id", self.CONTRACT_ID, "--output", "out", "--class-name", "MyClient"],
            )
            assert result.exit_code == 0
            path = os.path.join("out", "MyClient.swift")
            assert os.path.exists(path)
            with open(path) as f:
                assert "public class MyClient {" in f.read()

    def test_swift_file_output_path_creates_parent_directory(self, stubbed_specs):
        runner = CliRunner()
        with runner.isolated_filesystem():
            path = os.path.join("nested", "dir", "Bindings.swift")
            result = runner.invoke(
                command, ["--contract-id", self.CONTRACT_ID, "--output", path]
            )
            assert result.exit_code == 0
            assert os.path.exists(path)
            with open(path) as f:
                assert "public class ContractClient {" in f.read()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
