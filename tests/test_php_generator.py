import unittest
from stellar_sdk import xdr
from stellar_contract_bindings.php import (
    is_php_keyword,
    is_tuple_struct,
    snake_to_pascal,
    snake_to_camel,
    camel_to_snake,
    escape_keyword,
    to_php_type,
    to_scval,
    from_scval,
    render_enum,
    render_struct,
    render_tuple_struct,
    generate_binding,
)


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
        self.assertEqual(escape_keyword("return", "property"), "return_")
    
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


if __name__ == "__main__":
    unittest.main()