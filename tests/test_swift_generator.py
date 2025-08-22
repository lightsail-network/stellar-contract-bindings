"""Tests for Swift binding generator."""

import pytest
from stellar_sdk import xdr

from stellar_contract_bindings.swift import (
    is_swift_keyword,
    is_tuple_struct,
    snake_to_pascal,
    snake_to_camel,
    camel_to_snake,
    escape_keyword,
    to_swift_type,
    to_scval,
    from_scval,
    render_enum,
    render_error_enum,
    render_struct,
    render_tuple_struct,
    render_union,
    render_client,
    generate_binding,
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
    
    def test_to_scval_bigint(self):
        # U128
        u128_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U128)
        assert to_scval(u128_type, "myBigInt") == "try SCValXDR.u128(stringValue: myBigInt)"
        
        # I256
        i256_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I256)
        assert to_scval(i256_type, "myBigInt") == "try SCValXDR.i256(stringValue: myBigInt)"
    
    def test_to_scval_string_bytes(self):
        # String
        string_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert to_scval(string_type, "myString") == "SCValXDR.string(myString)"
        
        # Symbol
        symbol_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        assert to_scval(symbol_type, "mySymbol") == "SCValXDR.symbol(mySymbol)"
        
        # Bytes
        bytes_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert to_scval(bytes_type, "myBytes") == "SCValXDR.bytes(myBytes)"
    
    def test_to_scval_address(self):
        # Address
        address_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        assert to_scval(address_type, "myAddress") == "SCValXDR.address(myAddress)"
    
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
    
    def test_from_scval_bigint(self):
        # U128
        u128_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_U128)
        assert from_scval(u128_type, "val") == 'val.u128String ?? "0"'
        
        # I256
        i256_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_I256)
        assert from_scval(i256_type, "val") == 'val.i256String ?? "0"'
    
    def test_from_scval_string_bytes(self):
        # String
        string_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert from_scval(string_type, "val") == 'val.string ?? ""'
        
        # Symbol
        symbol_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        assert from_scval(symbol_type, "val") == 'val.symbol ?? ""'
        
        # Bytes
        bytes_type = xdr.SCSpecTypeDef(type=xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert from_scval(bytes_type, "val") == "val.bytes ?? Data()"


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
        assert "public enum TestContractStatus: UInt32, CaseIterable" in result
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
        assert "public enum TestContractCommonError: UInt32, Error, CaseIterable" in result
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
        assert "public enum MyContractStatus: UInt32, CaseIterable" in result
        assert "public struct MyContractUser: Codable" in result
        assert "public class MyContract" in result
        assert "public func getUser(" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])