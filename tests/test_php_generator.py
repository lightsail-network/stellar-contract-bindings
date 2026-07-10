import os
import unittest
from unittest import mock

from click.testing import CliRunner
from stellar_sdk import StrKey, xdr
from stellar_contract_bindings.php import (
    MINIMUM_SDK_VERSION,
    command,
    is_php_keyword,
    is_tuple_struct,
    snake_to_pascal,
    snake_to_camel,
    camel_to_snake,
    escape_keyword,
    prefixed_type_name,
    to_php_type,
    to_scval,
    from_scval,
    render_info,
    render_enum,
    render_error_enum,
    render_struct,
    render_tuple_struct,
    render_union,
    generate_binding,
)


def _tuple_type(*value_types):
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_TUPLE)
    td.tuple = xdr.SCSpecTypeTuple(value_types=list(value_types))
    return td


def _map_type(key_type, value_type):
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MAP)
    td.map = xdr.SCSpecTypeMap(key_type=key_type, value_type=value_type)
    return td


def _option_type(value_type):
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_OPTION)
    td.option = xdr.SCSpecTypeOption(value_type=value_type)
    return td


def _vec_type(element_type):
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VEC)
    td.vec = xdr.SCSpecTypeVec(element_type=element_type)
    return td


def _result_type(ok_type):
    td = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_RESULT)
    td.result = xdr.SCSpecTypeResult(
        ok_type=ok_type,
        error_type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ERROR),
    )
    return td


class TestPHPGenerator(unittest.TestCase):
    
    def test_is_php_keyword(self):
        """Test PHP keyword detection."""
        self.assertTrue(is_php_keyword("class"))
        self.assertTrue(is_php_keyword("function"))
        self.assertTrue(is_php_keyword("return"))
        self.assertTrue(is_php_keyword("if"))
        self.assertFalse(is_php_keyword("myVariable"))
        self.assertFalse(is_php_keyword("someMethod"))
    
    def test_snake_to_pascal(self):
        """Test snake_case to PascalCase conversion."""
        self.assertEqual(snake_to_pascal("hello_world"), "HelloWorld")
        self.assertEqual(snake_to_pascal("my_contract_method"), "MyContractMethod")
        self.assertEqual(snake_to_pascal("single"), "Single")
        self.assertEqual(snake_to_pascal("a_b_c_d"), "ABCD")
    
    def test_snake_to_camel(self):
        """Test snake_case to camelCase conversion."""
        self.assertEqual(snake_to_camel("hello_world"), "helloWorld")
        self.assertEqual(snake_to_camel("my_contract_method"), "myContractMethod")
        self.assertEqual(snake_to_camel("single"), "single")
        self.assertEqual(snake_to_camel("a_b_c_d"), "aBCD")
    
    def test_camel_to_snake(self):
        """Test CamelCase to snake_case conversion."""
        self.assertEqual(camel_to_snake("HelloWorld"), "hello_world")
        self.assertEqual(camel_to_snake("MyContractMethod"), "my_contract_method")
        self.assertEqual(camel_to_snake("Single"), "single")
        self.assertEqual(camel_to_snake("XMLHttpRequest"), "x_m_l_http_request")
    
    def test_escape_keyword(self):
        """Test PHP keyword escaping."""
        self.assertEqual(escape_keyword("class"), "class_")
        self.assertEqual(escape_keyword("function"), "function_")
        self.assertEqual(escape_keyword("myVariable"), "myVariable")
        self.assertEqual(escape_keyword("return"), "return_")
    
    def test_to_php_type_primitives(self):
        """Test conversion of primitive Soroban types to PHP types."""
        # Boolean
        td_bool = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        self.assertEqual(to_php_type(td_bool), "bool")
        self.assertEqual(to_php_type(td_bool, nullable=True), "?bool")
        
        # Integers
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        self.assertEqual(to_php_type(td_u32), "int")
        
        td_i64 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I64)
        self.assertEqual(to_php_type(td_i64), "int")
        
        # Big integers (use string in PHP)
        td_u128 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U128)
        self.assertEqual(to_php_type(td_u128), "string")
        
        # String types
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        self.assertEqual(to_php_type(td_string), "string")
        
        td_symbol = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        self.assertEqual(to_php_type(td_symbol), "string")
        
        # Bytes
        td_bytes = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        self.assertEqual(to_php_type(td_bytes), "string")
        
        # Address
        td_address = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        self.assertEqual(to_php_type(td_address), "Address")
        
        # Muxed Address (same as Address in PHP)
        td_muxed_address = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        self.assertEqual(to_php_type(td_muxed_address), "Address")
        
        # Void
        td_void = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VOID)
        self.assertEqual(to_php_type(td_void), "void")
    
    def test_to_php_type_complex(self):
        """Test conversion of complex Soroban types to PHP types."""
        # Vector
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        td_vec = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VEC)
        td_vec.vec = xdr.SCSpecTypeVec(element_type=td_u32)
        self.assertEqual(to_php_type(td_vec), "array")
        
        # Map
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        td_map = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MAP)
        td_map.map = xdr.SCSpecTypeMap(key_type=td_string, value_type=td_u32)
        self.assertEqual(to_php_type(td_map), "array")
        
        # Option
        td_option = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_OPTION)
        td_option.option = xdr.SCSpecTypeOption(value_type=td_u32)
        self.assertEqual(to_php_type(td_option), "?int")
        
        # UDT
        td_udt = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
        td_udt.udt = xdr.SCSpecTypeUDT(name=b"MyContract")
        self.assertEqual(to_php_type(td_udt), "MyContract")
    
    def test_to_scval_primitives(self):
        """Test conversion to XdrSCVal for primitive types."""
        # Boolean
        td_bool = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        self.assertEqual(to_scval(td_bool, "myBool"), "XdrSCVal::forBool($myBool)")
        
        # Integer types
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        self.assertEqual(to_scval(td_u32, "myInt"), "XdrSCVal::forU32($myInt)")
        
        td_i64 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I64)
        self.assertEqual(to_scval(td_i64, "myLong"), "XdrSCVal::forI64($myLong)")
        
        # String
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        self.assertEqual(to_scval(td_string, "myString"), "XdrSCVal::forString($myString)")
        
        # Symbol
        td_symbol = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        self.assertEqual(to_scval(td_symbol, "mySymbol"), "XdrSCVal::forSymbol($mySymbol)")
        
        # Address
        td_address = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        self.assertEqual(to_scval(td_address, "myAddress"), "$myAddress->toXdrSCVal()")
        
        # Muxed Address
        td_muxed_address = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        self.assertEqual(to_scval(td_muxed_address, "myMuxedAddress"), "$myMuxedAddress->toXdrSCVal()")
        
        # Void
        td_void = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VOID)
        self.assertEqual(to_scval(td_void, "ignored"), "XdrSCVal::forVoid()")
    
    def test_from_scval_primitives(self):
        """Test conversion from XdrSCVal for primitive types."""
        # Boolean
        td_bool = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        self.assertEqual(from_scval(td_bool, "val"), "$val->b")
        
        # Integer types
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        self.assertEqual(from_scval(td_u32, "val"), "$val->u32")
        
        td_i64 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I64)
        self.assertEqual(from_scval(td_i64, "val"), "$val->i64")
        
        # String
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        self.assertEqual(from_scval(td_string, "val"), "$val->str")
        
        # Symbol
        td_symbol = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)
        self.assertEqual(from_scval(td_symbol, "val"), "$val->sym")
        
        # Bytes
        td_bytes = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        self.assertEqual(from_scval(td_bytes, "val"), "$val->bytes->getValue()")
        
        # Bytes_N
        td_bytes_n = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
        td_bytes_n.bytes_n = xdr.SCSpecTypeBytesN(n=xdr.Uint32(32))
        self.assertEqual(from_scval(td_bytes_n, "val"), "$val->bytes->getValue()")
        
        # Address
        td_address = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
        self.assertEqual(from_scval(td_address, "val"), "Address::fromXdrSCVal($val)")
        
        # Muxed Address (same as Address in PHP)
        td_muxed_address = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        self.assertEqual(from_scval(td_muxed_address, "val"), "Address::fromXdrSCVal($val)")
        
        # Void
        td_void = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VOID)
        self.assertEqual(from_scval(td_void, "val"), "null")
    
    def test_is_tuple_struct(self):
        """Test tuple struct detection."""
        # Create a regular struct
        regular_struct = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"RegularStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"field1",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"field2",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
                ),
            ]
        )
        self.assertFalse(is_tuple_struct(regular_struct))
        
        # Create a tuple struct
        tuple_struct = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"TupleStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"0",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"1",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
                ),
            ]
        )
        self.assertTrue(is_tuple_struct(tuple_struct))
    
    def test_render_enum(self):
        """Test enum rendering."""
        enum_entry = xdr.SCSpecUDTEnumV0(
            doc=b"Test enum",
            lib=b"",
            name=b"Color",
            cases=[
                xdr.SCSpecUDTEnumCaseV0(
                    doc=b"",
                    name=b"Red",
                    value=xdr.Uint32(0)
                ),
                xdr.SCSpecUDTEnumCaseV0(
                    doc=b"",
                    name=b"Green",
                    value=xdr.Uint32(1)
                ),
                xdr.SCSpecUDTEnumCaseV0(
                    doc=b"",
                    name=b"Blue",
                    value=xdr.Uint32(2)
                ),
            ]
        )
        
        result = render_enum(enum_entry, "TestContract")
        self.assertIn("enum TestContractColor: int", result)
        self.assertIn("case Red = 0;", result)
        self.assertIn("case Green = 1;", result)
        self.assertIn("case Blue = 2;", result)
        self.assertIn("public function toSCVal(): XdrSCVal", result)
        self.assertIn("public static function fromSCVal(XdrSCVal $val): self", result)
    
    def test_render_struct(self):
        """Test struct rendering."""
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"Test struct",
            lib=b"",
            name=b"Person",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"name",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"age",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
            ]
        )
        
        result = render_struct(struct_entry, "TestContract")
        self.assertIn("class TestContractPerson", result)
        self.assertIn("public string $name;", result)
        self.assertIn("public int $age;", result)
        self.assertIn("public function __construct(", result)
        self.assertIn("public function toSCVal(): XdrSCVal", result)
        self.assertIn("public static function fromSCVal(XdrSCVal $val): self", result)
    
    def test_generate_binding(self):
        """Test complete binding generation."""
        # Create a simple spec with an enum and a function
        enum_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0)
        enum_spec.udt_enum_v0 = xdr.SCSpecUDTEnumV0(
            doc=b"",
            lib=b"",
            name=b"Status",
            cases=[
                xdr.SCSpecUDTEnumCaseV0(
                    doc=b"",
                    name=b"Active",
                    value=xdr.Uint32(0)
                ),
                xdr.SCSpecUDTEnumCaseV0(
                    doc=b"",
                    name=b"Inactive",
                    value=xdr.Uint32(1)
                ),
            ]
        )
        
        function_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function_spec.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"Get status",
            name=xdr.SCSymbol(sc_symbol=b"get_status"),
            inputs=[],
            outputs=[xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)]
        )
        function_spec.function_v0.outputs[0].udt = xdr.SCSpecTypeUDT(name=b"Status")
        
        specs = [enum_spec, function_spec]
        
        result = generate_binding(specs, namespace="Test", contract_name="TestContract")
        
        self.assertIn("namespace Test;", result)
        self.assertIn("enum TestContractStatus: int", result)
        self.assertIn("class TestContract", result)
        self.assertIn("private SorobanClient $client;", result)
        self.assertIn("public static function forClientOptions(ClientOptions $options): self", result)
        self.assertIn("public function getStatus(", result)

    def test_generate_binding_ends_with_single_newline(self):
        """The generated file ends with exactly one trailing newline."""
        function_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function_spec.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"noop"),
            inputs=[],
            outputs=[],
        )
        result = generate_binding(
            [function_spec], namespace="Test", contract_name="TestContract"
        )
        self.assertTrue(result.endswith("\n"))
        self.assertFalse(result.endswith("\n\n"))
        self.assertFalse(any(line != line.rstrip() for line in result.splitlines()))

    def test_return_type_hints(self):
        """Test that functions have proper return type hints."""
        # Test function with void return
        void_function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        void_function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"do_something"),
            inputs=[],
            outputs=[]  # No outputs means void return
        )
        
        # Test function with int return
        int_function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        int_function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"get_count"),
            inputs=[],
            outputs=[xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)]
        )
        
        # Test function with string return (i128)
        bigint_function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        bigint_function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"get_balance"),
            inputs=[],
            outputs=[xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I128)]
        )
        
        # Test function with array return (vec type)
        vec_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VEC)
        vec_type.vec = xdr.SCSpecTypeVec(element_type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        array_function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        array_function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"get_list"),
            inputs=[],
            outputs=[vec_type]
        )
        
        specs = [void_function, int_function, bigint_function, array_function]
        result = generate_binding(specs, namespace="Test", contract_name="TestContract")
        
        # Check return type hints are present
        self.assertIn("public function doSomething(\n        ?MethodOptions $methodOptions = null\n    ): void {", result)
        self.assertIn("public function getCount(\n        ?MethodOptions $methodOptions = null\n    ): int {", result)
        self.assertIn("public function getBalance(\n        ?MethodOptions $methodOptions = null\n    ): string {", result)
        self.assertIn("public function getList(\n        ?MethodOptions $methodOptions = null\n    ): array {", result)
    
    def test_php_keyword_escaping_in_struct(self):
        """Test that PHP keywords are properly escaped in struct fields."""
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"TestStruct",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"class",  # PHP keyword
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"return",  # PHP keyword
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
                ),
            ]
        )
        
        result = render_struct(struct_entry, "TestContract")
        self.assertIn("class TestContractTestStruct", result)
        self.assertIn("public string $class_;", result)
        self.assertIn("public int $return_;", result)
        self.assertIn("string $class_", result)
        self.assertIn("int $return_", result)
    
    def test_utility_methods(self):
        """Test that utility methods (getOptions, getContractSpec) are generated correctly."""
        # Create a simple function for testing
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"test_func"),
            inputs=[],
            outputs=[]
        )
        
        specs = [function]
        result = generate_binding(specs, namespace="Test", contract_name="TestContract")
        
        # Check that getOptions method is present
        self.assertIn("public function getOptions(): ClientOptions", result)
        self.assertIn("return $this->client->getOptions();", result)
        
        # Check that getContractSpec method is present
        self.assertIn("public function getContractSpec(): ContractSpec", result)
        self.assertIn("return $this->client->getContractSpec();", result)
        
        # Check that ContractSpec is imported
        self.assertIn("use Soneso\\StellarSDK\\Soroban\\Contract\\ContractSpec;", result)
    
    def test_build_tx_methods(self):
        """Test that build transaction methods are generated correctly."""
        # Test function with parameters
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"Transfer tokens",
            name=xdr.SCSymbol(sc_symbol=b"transfer"),
            inputs=[
                xdr.SCSpecFunctionInputV0(
                    doc=b"",
                    name=b"from",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
                ),
                xdr.SCSpecFunctionInputV0(
                    doc=b"",
                    name=b"to", 
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)
                ),
                xdr.SCSpecFunctionInputV0(
                    doc=b"",
                    name=b"amount",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I128)
                ),
            ],
            outputs=[]
        )
        
        specs = [function]
        result = generate_binding(specs, namespace="Test", contract_name="TestContract")
        
        # Check that both regular method and build method are generated
        self.assertIn("public function transfer(", result)
        self.assertIn("public function buildTransferTx(", result)
        
        # Check build method signature
        self.assertIn("public function buildTransferTx(\n        Address $from,\n        Address $to,\n        string $amount,\n        ?MethodOptions $methodOptions = null\n    ): AssembledTransaction {", result)
        
        # Check build method implementation
        self.assertIn("return $this->client->buildInvokeMethodTx(", result)
        self.assertIn("name: 'transfer',", result)
        
        # Test function with no parameters
        simple_function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        simple_function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"get_info"),
            inputs=[],
            outputs=[xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)]
        )
        
        specs = [simple_function]
        result = generate_binding(specs, namespace="Test", contract_name="TestContract")
        
        # Check build method for function with no parameters
        self.assertIn("public function buildGetInfoTx(", result)
        self.assertIn("?MethodOptions $methodOptions = null\n    ): AssembledTransaction {", result)

    def test_to_scval_tuple_uses_for_vec(self):
        """Tuple-typed inputs must encode as SCV_VEC via forVec with real indices."""
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        td_tuple = _tuple_type(td_u32, td_string)

        result = to_scval(td_tuple, "myTuple")
        self.assertEqual(
            result,
            "XdrSCVal::forVec([XdrSCVal::forU32($myTuple[0]), XdrSCVal::forString($myTuple[1])])",
        )
        # The non-existent forTupleStruct helper must never be emitted.
        self.assertNotIn("forTupleStruct", result)

    def test_to_scval_map_uses_map_entry(self):
        """Map-typed inputs must build XdrSCMapEntry elements, not plain arrays.

        Entries are sorted ascending by key first (the host rejects unsorted
        ScMap); a string key sorts by byte order via strcmp.
        """
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        td_map = _map_type(td_string, td_u32)

        result = to_scval(td_map, "myMap")
        self.assertEqual(
            result,
            "XdrSCVal::forMap((function(array $m): array { "
            "uksort($m, fn($a, $b) => strcmp((string)$a, (string)$b)); "
            "return array_map(fn($k, $v) => new XdrSCMapEntry("
            "XdrSCVal::forString($k), XdrSCVal::forU32($v)), array_keys($m), $m); })($myMap))",
        )

    def test_from_scval_map_round_trip(self):
        """Map decode must read XdrSCMapEntry key/val, staying consistent with encode."""
        td_string = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        td_u32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        td_map = _map_type(td_string, td_u32)

        result = from_scval(td_map, "val")
        self.assertEqual(
            result,
            "array_combine(array_map(fn($entry) => $entry->key->str, $val->map), "
            "array_map(fn($entry) => $entry->val->u32, $val->map))",
        )

    def test_to_scval_result_raises(self):
        """RESULT-typed inputs must fail loudly rather than emit an error instance."""
        td_ok = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        td_result = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_RESULT)
        td_error = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        td_result.result = xdr.SCSpecTypeResult(ok_type=td_ok, error_type=td_error)

        with self.assertRaises(NotImplementedError):
            to_scval(td_result, "myResult")

    def test_render_error_enum_name_matches_reference(self):
        """An error enum declaration must use the same prefixed name UDT references emit."""
        error_enum = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0)
        error_enum.udt_error_enum_v0 = xdr.SCSpecUDTErrorEnumV0(
            doc=b"",
            lib=b"",
            name=b"MyError",
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(doc=b"", name=b"NotFound", value=xdr.Uint32(1)),
                xdr.SCSpecUDTErrorEnumCaseV0(doc=b"", name=b"Invalid", value=xdr.Uint32(2)),
            ],
        )

        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        error_input_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
        error_input_type.udt = xdr.SCSpecTypeUDT(name=b"MyError")
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"do_it"),
            inputs=[
                xdr.SCSpecFunctionInputV0(doc=b"", name=b"err", type=error_input_type)
            ],
            outputs=[],
        )

        result = generate_binding([error_enum, function], namespace="Test", contract_name="TestContract")

        # Declaration and reference must agree on the unsuffixed prefixed name.
        self.assertIn("enum TestContractMyError: int", result)
        self.assertNotIn("enum TestContractMyErrorError", result)
        # The function references the error enum as an argument type.
        self.assertIn("TestContractMyError $err", result)
        self.assertIn("$err->toSCVal()", result)

    def test_render_error_enum_direct(self):
        """render_error_enum must not append an Error suffix to the declaration."""
        error_enum = xdr.SCSpecUDTErrorEnumV0(
            doc=b"An error",
            lib=b"",
            name=b"MyError",
            cases=[
                xdr.SCSpecUDTErrorEnumCaseV0(doc=b"", name=b"NotFound", value=xdr.Uint32(1)),
            ],
        )
        result = render_error_enum(error_enum, "TestContract")
        self.assertIn("enum TestContractMyError: int", result)
        self.assertNotIn("TestContractMyErrorError", result)

    def test_empty_tuple_output_is_void_without_return(self):
        """An empty-tuple output resolves to void: no return statement, no $result binding."""
        td_empty_tuple = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_TUPLE)
        td_empty_tuple.tuple = xdr.SCSpecTypeTuple(value_types=[])
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"empty_tuple"),
            inputs=[],
            outputs=[td_empty_tuple],
        )
        result = generate_binding(
            [function], namespace="Test", contract_name="TestContract"
        )
        self.assertIn("public function emptyTuple(", result)
        self.assertIn("): void {", result)
        self.assertNotIn("return null;", result)
        self.assertNotIn("$result = ", result)

    def test_multi_output_raises(self):
        """Functions declaring more than one output must fail loudly.

        The XDR SCSpecFunctionV0 constructor caps outputs at 1, so a multi-output
        function can only be reached by mutating the parsed spec; the generator must
        still refuse it rather than emit the broken scalar-indexing conversion.
        """
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"multi"),
            inputs=[],
            outputs=[xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
        )
        function.function_v0.outputs = [
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
        ]

        with self.assertRaises(NotImplementedError):
            generate_binding([function], namespace="Test", contract_name="TestContract")

    def test_single_tuple_output_still_works(self):
        """A single tuple-typed output stays valid (decoded via ->vec indices)."""
        td_tuple = _tuple_type(
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
        )
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"get_pair"),
            inputs=[],
            outputs=[td_tuple],
        )

        result = generate_binding([function], namespace="Test", contract_name="TestContract")
        self.assertIn("public function getPair(", result)
        self.assertIn("[$result->vec[0]->u32, $result->vec[1]->str]", result)

    def test_header_contains_min_sdk_version(self):
        """The generated header must state the minimum required stellar-php-sdk version."""
        header = render_info()
        self.assertIn(MINIMUM_SDK_VERSION, header)
        self.assertIn("soneso/stellar-php-sdk", header)

        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"noop"),
            inputs=[],
            outputs=[],
        )
        result = generate_binding([function], namespace="Test", contract_name="TestContract")
        self.assertIn(MINIMUM_SDK_VERSION, result)

    def test_prefixed_type_name_preserves_primitive_and_sdk_names(self):
        """Primitive and SDK type names are never prefixed with the class name."""
        self.assertEqual(prefixed_type_name("Address", "TestContract"), "Address")
        self.assertEqual(prefixed_type_name("XdrSCVal", "TestContract"), "XdrSCVal")
        self.assertEqual(prefixed_type_name("string", "TestContract"), "string")
        self.assertEqual(prefixed_type_name("DataKey", "TestContract"), "TestContractDataKey")

    def test_to_php_type_val_result_and_bytes_n(self):
        """VAL maps to XdrSCVal, RESULT unwraps to its ok type, BYTES_N is a string."""
        td_val = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VAL)
        self.assertEqual(to_php_type(td_val), "XdrSCVal")
        self.assertEqual(to_php_type(td_val, nullable=True), "?XdrSCVal")

        td_result = _result_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        self.assertEqual(to_php_type(td_result), "int")
        self.assertEqual(to_php_type(td_result, nullable=True), "?int")

        td_bytes_n = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
        td_bytes_n.bytes_n = xdr.SCSpecTypeBytesN(n=xdr.Uint32(32))
        self.assertEqual(to_php_type(td_bytes_n), "string")

    def test_to_php_type_error_raises(self):
        td_error = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        with self.assertRaises(NotImplementedError):
            to_php_type(td_error)

    def test_unknown_spec_type_raises_in_all_converters(self):
        """A spec type without a mapping must fail loudly in every converter."""

        class UnknownTypeDef:
            type = object()

        td = UnknownTypeDef()
        with self.assertRaises(ValueError):
            to_php_type(td)
        with self.assertRaises(ValueError):
            to_scval(td, "x")
        with self.assertRaises(NotImplementedError):
            from_scval(td, "x")

    def test_to_scval_int_variants(self):
        """i32/u64/timepoint/duration use the matching XdrSCVal factory, exact casing."""
        td_i32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I32)
        self.assertEqual(to_scval(td_i32, "v"), "XdrSCVal::forI32($v)")
        td_u64 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U64)
        self.assertEqual(to_scval(td_u64, "v"), "XdrSCVal::forU64($v)")
        td_timepoint = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT)
        self.assertEqual(to_scval(td_timepoint, "v"), "XdrSCVal::forTimepoint($v)")
        td_duration = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_DURATION)
        self.assertEqual(to_scval(td_duration, "v"), "XdrSCVal::forDuration($v)")

    def test_to_scval_bigint_variants(self):
        """128/256-bit values encode through the BigInt factories (decimal strings)."""
        cases = [
            (xdr.SCSpecType.SC_SPEC_TYPE_U128, "XdrSCVal::forU128BigInt($v)"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I128, "XdrSCVal::forI128BigInt($v)"),
            (xdr.SCSpecType.SC_SPEC_TYPE_U256, "XdrSCVal::forU256BigInt($v)"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I256, "XdrSCVal::forI256BigInt($v)"),
        ]
        for spec_type, expected in cases:
            self.assertEqual(to_scval(xdr.SCSpecTypeDef(spec_type), "v"), expected)

    def test_to_scval_bytes_and_bytes_n(self):
        td_bytes = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        self.assertEqual(to_scval(td_bytes, "v"), "XdrSCVal::forBytes($v)")
        td_bytes_n = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
        td_bytes_n.bytes_n = xdr.SCSpecTypeBytesN(n=xdr.Uint32(32))
        self.assertEqual(to_scval(td_bytes_n, "v"), "XdrSCVal::forBytes($v)")

    def test_to_scval_val_passthrough(self):
        """A raw XdrSCVal argument passes through unwrapped, keeping an existing $ prefix."""
        td_val = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VAL)
        self.assertEqual(to_scval(td_val, "raw"), "$raw")
        self.assertEqual(to_scval(td_val, "$this->value[0]"), "$this->value[0]")

    def test_to_scval_error_raises(self):
        td_error = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        with self.assertRaises(NotImplementedError):
            to_scval(td_error, "v")

    def test_to_scval_vec(self):
        td_vec = _vec_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        self.assertEqual(
            to_scval(td_vec, "myVec"),
            "XdrSCVal::forVec(array_map(fn($item) => XdrSCVal::forU32($item), $myVec))",
        )

    def test_to_scval_nested_vec(self):
        """A vec inside a vec nests arrow functions; the inner $item shadows the outer."""
        td_vec = _vec_type(_vec_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)))
        self.assertEqual(
            to_scval(td_vec, "myVec"),
            "XdrSCVal::forVec(array_map(fn($item) => "
            "XdrSCVal::forVec(array_map(fn($item) => XdrSCVal::forU32($item), $item)), $myVec))",
        )

    def test_to_scval_udt_and_muxed_address_in_vec(self):
        td_udt = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
        td_udt.udt = xdr.SCSpecTypeUDT(name=b"DataKey")
        self.assertEqual(
            to_scval(_vec_type(td_udt), "keys", "TestContract"),
            "XdrSCVal::forVec(array_map(fn($item) => $item->toSCVal(), $keys))",
        )
        td_muxed = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        self.assertEqual(
            to_scval(_vec_type(td_muxed), "addrs"),
            "XdrSCVal::forVec(array_map(fn($item) => $item->toXdrSCVal(), $addrs))",
        )

    def test_to_scval_option(self):
        """An option encodes its inner value, or SCV_VOID when the PHP value is null."""
        td_opt = _option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        self.assertEqual(
            to_scval(td_opt, "myOpt"),
            "($myOpt !== null ? XdrSCVal::forU32($myOpt) : XdrSCVal::forVoid())",
        )

    def test_to_scval_option_in_containers(self):
        """Option encoding keeps the null check on the container element expression."""
        td_opt = _option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))

        self.assertEqual(
            to_scval(_vec_type(td_opt), "myVec"),
            "XdrSCVal::forVec(array_map(fn($item) => "
            "($item !== null ? XdrSCVal::forU32($item) : XdrSCVal::forVoid()), $myVec))",
        )

        td_muxed = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        self.assertEqual(
            to_scval(_tuple_type(td_opt, td_muxed), "t"),
            "XdrSCVal::forVec([($t[0] !== null ? XdrSCVal::forU32($t[0]) : XdrSCVal::forVoid()), "
            "$t[1]->toXdrSCVal()])",
        )

        td_map = _map_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32), td_opt)
        self.assertEqual(
            to_scval(td_map, "myMap"),
            "XdrSCVal::forMap((function(array $m): array { uksort($m, fn($a, $b) => $a <=> $b); "
            "return array_map(fn($k, $v) => new XdrSCMapEntry(XdrSCVal::forU32($k), "
            "($v !== null ? XdrSCVal::forU32($v) : XdrSCVal::forVoid())), array_keys($m), $m); })($myMap))",
        )

    def test_to_scval_empty_tuple_is_void(self):
        self.assertEqual(to_scval(_tuple_type(), "ignored"), "XdrSCVal::forVoid()")

    def test_from_scval_int_variants(self):
        """i32/u64/timepoint/duration decode from the matching XdrSCVal accessor."""
        td_i32 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_I32)
        self.assertEqual(from_scval(td_i32, "val"), "$val->i32")
        td_u64 = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U64)
        self.assertEqual(from_scval(td_u64, "val"), "$val->u64")
        td_timepoint = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT)
        self.assertEqual(from_scval(td_timepoint, "val"), "$val->timepoint")
        td_duration = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_DURATION)
        self.assertEqual(from_scval(td_duration, "val"), "$val->duration")

    def test_from_scval_bigint_variants(self):
        """128/256-bit values decode via toBigInt to a decimal string."""
        for spec_type in (
            xdr.SCSpecType.SC_SPEC_TYPE_U128,
            xdr.SCSpecType.SC_SPEC_TYPE_I128,
            xdr.SCSpecType.SC_SPEC_TYPE_U256,
            xdr.SCSpecType.SC_SPEC_TYPE_I256,
        ):
            self.assertEqual(
                from_scval(xdr.SCSpecTypeDef(spec_type), "val"),
                "gmp_strval($val->toBigInt())",
            )

    def test_from_scval_val_passthrough(self):
        td_val = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VAL)
        self.assertEqual(from_scval(td_val, "val"), "$val")

    def test_from_scval_error_raises(self):
        td_error = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        with self.assertRaises(NotImplementedError):
            from_scval(td_error, "val")

    def test_from_scval_result_unwraps_ok_type(self):
        td_result = _result_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        self.assertEqual(from_scval(td_result, "val"), "$val->u32")

    def test_from_scval_vec(self):
        td_vec = _vec_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        self.assertEqual(
            from_scval(td_vec, "val"),
            "array_map(fn($item) => $item->u32, $val->vec)",
        )

    def test_from_scval_udt_and_muxed_address_in_vec(self):
        td_udt = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
        td_udt.udt = xdr.SCSpecTypeUDT(name=b"DataKey")
        self.assertEqual(
            from_scval(_vec_type(td_udt), "val", "TestContract"),
            "array_map(fn($item) => TestContractDataKey::fromSCVal($item), $val->vec)",
        )
        td_muxed = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        self.assertEqual(
            from_scval(_vec_type(td_muxed), "val"),
            "array_map(fn($item) => Address::fromXdrSCVal($item), $val->vec)",
        )

    def test_from_scval_option(self):
        """Option decode compares the type's integer value against SCV_VOID.

        XdrSCVal->type is an XdrSCValType object; only its ->value is comparable
        to the int constant, so the guard must read it or a None option would
        never decode to null.
        """
        td_opt = _option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        result = from_scval(td_opt, "val")
        self.assertEqual(
            result,
            "($val->type->value !== XdrSCValType::SCV_VOID ? $val->u32 : null)",
        )

    def test_from_scval_option_in_containers(self):
        """Nested option decode keeps the inner conversion and null fallback per element."""
        td_opt = _option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))

        vec_result = from_scval(_vec_type(td_opt), "val")
        self.assertTrue(vec_result.startswith("array_map(fn($item) => ($item->type"))
        self.assertIn("? $item->u32 : null)", vec_result)
        self.assertTrue(vec_result.endswith(", $val->vec)"))

        td_muxed = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)
        tuple_result = from_scval(_tuple_type(td_opt, td_muxed), "val")
        self.assertIn("? $val->vec[0]->u32 : null)", tuple_result)
        self.assertIn("Address::fromXdrSCVal($val->vec[1])", tuple_result)

        map_result = from_scval(
            _map_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32), td_opt), "val"
        )
        self.assertIn("fn($entry) => $entry->key->u32", map_result)
        self.assertIn("? $entry->val->u32 : null)", map_result)

    def test_from_scval_empty_tuple_is_null(self):
        self.assertEqual(from_scval(_tuple_type(), "val"), "null")

    def test_from_scval_map_bigint_key(self):
        """A 128/256-bit map key decodes to a decimal-string array key via gmp_strval."""
        td_map = _map_type(
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U256),
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
        )
        self.assertEqual(
            from_scval(td_map, "val"),
            "array_combine(array_map(fn($entry) => gmp_strval($entry->key->toBigInt()), $val->map), "
            "array_map(fn($entry) => $entry->val->str, $val->map))",
        )

    def test_render_struct_option_field_has_single_nullable_marker(self):
        """An option-typed struct field declares exactly one leading ? on its type."""
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Config",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"memo",
                    type=_option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ),
            ],
        )
        result = render_struct(struct_entry, "TestContract")
        self.assertIn("public ?int $memo;", result)
        self.assertIn("?int $memo\n", result)
        self.assertNotIn("??", result)
        self.assertIn(
            "($this->memo !== null ? XdrSCVal::forU32($this->memo) : XdrSCVal::forVoid())",
            result,
        )

    def test_render_tuple_struct(self):
        """A tuple struct wraps an indexed array and encodes as SCV_VEC in field order."""
        entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Pair",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"0",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"1",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                ),
            ],
        )
        result = render_tuple_struct(entry, "TestContract")
        self.assertIn("class TestContractPair", result)
        self.assertIn("public array $value;", result)
        self.assertIn("@param array<int, string> $value", result)
        self.assertIn("public function __construct(array $value)", result)
        self.assertIn("XdrSCVal::forU32($this->value[0]),", result)
        self.assertIn("XdrSCVal::forString($this->value[1])", result)
        self.assertIn("$elements = $val->vec;", result)
        self.assertIn("$elements[0]->u32,", result)
        self.assertIn("$elements[1]->str", result)

    def test_render_union_option_tuple_case_constructor_single_nullable_marker(self):
        """An option-typed single-element tuple case keeps one nullable marker.

        to_php_type already yields a ?-prefixed type for options, so the
        constructor parameter must not prepend another.
        """
        entry = xdr.SCSpecUDTUnionCaseV0(
            kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
            tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                doc=b"",
                name=b"MaybeVal",
                type=[_option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
            ),
        )
        union = xdr.SCSpecUDTUnionV0(doc=b"", lib=b"", name=b"U", cases=[entry])
        result = render_union(union, "TestContract")
        self.assertIn("?int $maybe_val = null", result)
        self.assertNotIn("??int", result)

    def test_render_union(self):
        """A union encodes as SCV_VEC with a leading tag symbol; decode switches on it."""
        entry = xdr.SCSpecUDTUnionV0(
            doc=b"",
            lib=b"",
            name=b"MyUnion",
            cases=[
                xdr.SCSpecUDTUnionCaseV0(
                    kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                    void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=b"None"),
                ),
                xdr.SCSpecUDTUnionCaseV0(
                    kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                    tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                        doc=b"",
                        name=b"Some",
                        type=[xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)],
                    ),
                ),
                xdr.SCSpecUDTUnionCaseV0(
                    kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
                    tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(
                        doc=b"",
                        name=b"Pair",
                        type=[
                            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                        ],
                    ),
                ),
            ],
        )
        result = render_union(entry, "TestContract")

        self.assertIn("class TestContractMyUnion", result)
        self.assertIn("public const NONE = 'None', SOME = 'Some', PAIR = 'Pair';", result)
        self.assertIn("public string $kind;", result)
        # Single-type tuple case gets a typed property; multi-type falls back to array.
        self.assertIn("public ?int $some = null;", result)
        self.assertIn("public ?array $pair = null;", result)
        self.assertIn(
            "public function __construct(string $kind, ?int $some = null, ?array $pair = null)",
            result,
        )

        # Encode: leading tag symbol, then the case payload in order.
        self.assertIn("return XdrSCVal::forVec([XdrSCVal::forSymbol($this->kind)]);", result)
        self.assertIn("XdrSCVal::forU32($this->some)", result)
        self.assertIn("XdrSCVal::forU32($this->pair[0]),", result)
        self.assertIn("XdrSCVal::forString($this->pair[1])", result)
        self.assertIn('throw new Exception("Invalid union kind: {$this->kind}");', result)

        # Decode: dispatch on the tag symbol with an element-count guard per case.
        self.assertIn("$kind = $val->vec[0]->sym;", result)
        self.assertIn("return new self(self::NONE);", result)
        self.assertIn("if (count($val->vec) !== 2) {", result)
        self.assertIn("some: $val->vec[1]->u32", result)
        self.assertIn("if (count($val->vec) !== 3) {", result)
        self.assertIn("$val->vec[1]->u32,", result)
        self.assertIn("$val->vec[2]->str", result)
        self.assertIn('throw new Exception("Unknown union kind: $kind");', result)

    def test_generate_binding_dispatches_all_udt_kinds(self):
        """generate_binding routes struct, tuple struct, and union specs to their renderers."""
        struct_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        struct_spec.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Point",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"x",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
            ],
        )

        tuple_struct_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        tuple_struct_spec.udt_struct_v0 = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Pair",
            fields=[
                xdr.SCSpecUDTStructFieldV0(
                    doc=b"",
                    name=b"0",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
                ),
            ],
        )

        union_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0)
        union_spec.udt_union_v0 = xdr.SCSpecUDTUnionV0(
            doc=b"",
            lib=b"",
            name=b"Choice",
            cases=[
                xdr.SCSpecUDTUnionCaseV0(
                    kind=xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
                    void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=b"A"),
                ),
            ],
        )

        result = generate_binding(
            [struct_spec, tuple_struct_spec, union_spec],
            namespace="Test",
            contract_name="TestContract",
        )
        self.assertIn("class TestContractPoint", result)
        self.assertIn("public int $x;", result)
        self.assertIn("class TestContractPair", result)
        self.assertIn("public array $value;", result)
        self.assertIn("class TestContractChoice", result)
        self.assertIn("public const A = 'A';", result)
        # No function specs, so no client class is generated.
        self.assertNotIn("private SorobanClient $client;", result)

    def test_client_keyword_and_option_params(self):
        """Keyword-named params are escaped; option params are nullable end to end."""
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"register"),
            inputs=[
                xdr.SCSpecFunctionInputV0(
                    doc=b"",
                    name=b"list",
                    type=xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING),
                ),
                xdr.SCSpecFunctionInputV0(
                    doc=b"",
                    name=b"maybe",
                    type=_option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ),
            ],
            outputs=[_option_type(xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))],
        )

        result = generate_binding([function], namespace="Test", contract_name="TestContract")

        self.assertIn(" * @param string $list_", result)
        self.assertIn("string $list_,", result)
        self.assertIn("?int $maybe,", result)
        self.assertIn("): ?int {", result)
        self.assertIn("XdrSCVal::forString($list_),", result)
        self.assertIn(
            "($maybe !== null ? XdrSCVal::forU32($maybe) : XdrSCVal::forVoid())", result
        )
        # The option-typed result decodes with a null fallback.
        self.assertIn("? $result->u32 : null);", result)


class TestPHPMapKeySort(unittest.TestCase):
    """Map arguments are sorted ascending by key (host rejects unsorted ScMap)."""

    def _map(self, key_type):
        td_map = _map_type(
            xdr.SCSpecTypeDef(key_type),
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
        )
        return to_scval(td_map, "myMap")

    def test_int_keys_spaceship_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        self.assertIn("uksort($m, fn($a, $b) => $a <=> $b)", result)
        self.assertIn("})($myMap))", result)

    def test_bool_keys_spaceship_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        self.assertIn("uksort($m, fn($a, $b) => $a <=> $b)", result)

    def test_bigint_keys_gmp_numeric_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_I128)
        self.assertIn("uksort($m, fn($a, $b) => gmp_cmp((string)$a, (string)$b))", result)

    def test_string_keys_strcmp_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        self.assertIn("uksort($m, fn($a, $b) => strcmp((string)$a, (string)$b))", result)

    def test_bytes_keys_strcmp_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        self.assertIn("uksort($m, fn($a, $b) => strcmp((string)$a, (string)$b))", result)

    def test_bytes_n_keys_strcmp_byte_sort(self):
        result = self._map(xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N)
        self.assertIn("uksort($m, fn($a, $b) => strcmp((string)$a, (string)$b))", result)

    def test_muxed_address_keyed_map_raises(self):
        with self.assertRaises(NotImplementedError):
            self._map(xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS)

    def test_address_keyed_map_raises(self):
        # A PHP array cannot key by an object, so address-keyed maps are unsupported.
        with self.assertRaises(NotImplementedError):
            self._map(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS)

    def test_struct_keyed_map_raises_at_generation(self):
        key = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_UDT)
        key.udt = xdr.SCSpecTypeUDT(name=b"Point")
        td_map = _map_type(key, xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32))
        with self.assertRaises(NotImplementedError):
            to_scval(td_map, "myMap")

    def test_address_keyed_map_return_raises_at_generation(self):
        # A PHP array cannot key by an object. Decoding an address-keyed map would
        # array_combine an object key and fatal at runtime, so it must be rejected
        # at generation time.
        td_map = _map_type(
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS),
            xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32),
        )
        with self.assertRaises(NotImplementedError):
            from_scval(td_map, "result")


class TestPHPCommand(unittest.TestCase):
    """The php CLI command validates the contract ID, fetches specs, and writes the file."""

    CONTRACT_ID = StrKey.encode_contract(bytes(32))
    GET_SPECS = "stellar_contract_bindings.php.get_specs_by_contract_id"

    @staticmethod
    def _specs():
        function = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        function.function_v0 = xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(sc_symbol=b"hello"),
            inputs=[],
            outputs=[],
        )
        return [function]

    def test_rejects_invalid_contract_id(self):
        result = CliRunner().invoke(command, ["--contract-id", "not-a-contract"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid contract ID: not-a-contract", result.output)

    def test_aborts_when_spec_fetch_fails(self):
        with mock.patch(self.GET_SPECS, side_effect=Exception("rpc down")):
            result = CliRunner().invoke(command, ["--contract-id", self.CONTRACT_ID])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Get contract specs failed: rpc down", result.output)

    def test_writes_bindings_creating_output_dir(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with mock.patch(self.GET_SPECS, return_value=self._specs()) as get_specs:
                result = runner.invoke(
                    command,
                    [
                        "--contract-id", self.CONTRACT_ID,
                        "--rpc-url", "https://soroban-testnet.stellar.org",
                        "--output", os.path.join("out", "bindings"),
                        "--namespace", "Hello",
                        "--class-name", "HelloContract",
                    ],
                )
            self.assertEqual(result.exit_code, 0, result.output)
            get_specs.assert_called_once_with(
                self.CONTRACT_ID, "https://soroban-testnet.stellar.org"
            )
            path = os.path.join("out", "bindings", "HelloContract.php")
            self.assertIn(f"Generated PHP bindings to {path}", result.output)
            with open(path) as f:
                content = f.read()
            self.assertIn("namespace Hello;", content)
            self.assertIn("class HelloContract", content)
            self.assertIn("public function hello(", content)

    def test_defaults_output_to_current_directory(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with mock.patch(self.GET_SPECS, return_value=self._specs()):
                result = runner.invoke(command, ["--contract-id", self.CONTRACT_ID])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(os.path.exists("ContractClient.php"))


if __name__ == "__main__":
    unittest.main()
