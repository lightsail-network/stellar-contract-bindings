import tempfile
import os
from pathlib import Path

import pytest
from stellar_sdk import xdr

from stellar_contract_bindings.flutter import (
    generate_binding,
    to_dart_type,
    to_scval,
    from_scval,
    snake_to_camel,
    is_keywords,
    render_enum,
    render_struct,
    render_tuple_struct,
    render_union,
    command,
)
from stellar_contract_bindings.metadata import parse_contract_metadata


class TestFlutterGenerator:
    @classmethod
    def setup_class(cls):
        # Load test contract specs from wasm file
        wasm_file = Path(__file__).parent / "contracts" / "target" / "wasm32-unknown-unknown" / "release" / "python.wasm"
        if wasm_file.exists():
            with open(wasm_file, "rb") as f:
                wasm = f.read()
            cls.specs = parse_contract_metadata(wasm).spec
        else:
            cls.specs = []

    def test_snake_to_camel(self):
        assert snake_to_camel("hello_world") == "helloWorld"
        assert snake_to_camel("test_case", first_letter_lower=False) == "TestCase"
        assert snake_to_camel("simple") == "simple"
        assert snake_to_camel("a_b_c_d") == "aBCD"

    def test_is_keywords(self):
        assert is_keywords("class") == True
        assert is_keywords("if") == True
        assert is_keywords("async") == True
        assert is_keywords("hello") == False
        assert is_keywords("world") == False

    def test_to_dart_type(self):
        # Test basic types
        bool_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert to_dart_type(bool_type) == "bool"
        assert to_dart_type(bool_type, nullable=True) == "bool?"

        u32_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert to_dart_type(u32_type) == "int"

        u64_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U64)
        assert to_dart_type(u64_type) == "int"  # U64 is int in Flutter, not BigInt

        string_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert to_dart_type(string_type) == "String"

        bytes_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert to_dart_type(bytes_type) == "Uint8List"

        # Test option type
        option_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_OPTION)
        option_type.option = xdr.SCSpecTypeOption(bool_type)
        assert to_dart_type(option_type) == "bool?"

        # Test vector type
        vec_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_VEC)
        vec_type.vec = xdr.SCSpecTypeVec(u32_type)
        assert to_dart_type(vec_type) == "List<int>"

        # Test map type
        map_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_MAP)
        map_type.map = xdr.SCSpecTypeMap(string_type, u32_type)
        assert to_dart_type(map_type) == "Map<String, int>"

    def test_to_scval(self):
        bool_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert to_scval(bool_type, "value") == "XdrSCVal.forBool(value)"

        u32_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert to_scval(u32_type, "value") == "XdrSCVal.forU32(value)"

        string_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert to_scval(string_type, "value") == "XdrSCVal.forString(value)"

        bytes_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BYTES)
        assert to_scval(bytes_type, "value") == "XdrSCVal.forBytes(value)"

    def test_from_scval(self):
        bool_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        assert from_scval(bool_type, "val") == "val.b!"

        u32_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        assert from_scval(u32_type, "val") == "val.u32!.uint32"

        string_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        assert from_scval(string_type, "val") == "val.str!"  # Flutter SDK now returns string directly

    def test_render_enum(self):
        # Create a mock enum entry
        case1 = xdr.SCSpecUDTEnumCaseV0(
            doc=b"",
            name=b"First",
            value=xdr.Uint32(0)
        )
        case2 = xdr.SCSpecUDTEnumCaseV0(
            doc=b"",
            name=b"Second",
            value=xdr.Uint32(1)
        )
        enum_entry = xdr.SCSpecUDTEnumV0(
            doc=b"Test enum",
            lib=b"",
            name=b"TestEnum",
            cases=[case1, case2]
        )

        result = render_enum(enum_entry, "TestContract")
        
        assert "enum TestContractTestEnum {" in result
        assert "First(0)," in result
        assert "Second(1);" in result
        assert "factory TestContractTestEnum.fromValue(int value)" in result
        assert "XdrSCVal toScVal()" in result
        assert "static TestContractTestEnum fromScVal(XdrSCVal val)" in result

    def test_render_struct(self):
        # Create a mock struct entry
        field1_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        field2_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        
        field1 = xdr.SCSpecUDTStructFieldV0(
            doc=b"",
            name=b"field_one",
            type=field1_type
        )
        field2 = xdr.SCSpecUDTStructFieldV0(
            doc=b"",
            name=b"field_two",
            type=field2_type
        )
        
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"Test struct",
            lib=b"",
            name=b"TestStruct",
            fields=[field1, field2]
        )

        result = render_struct(struct_entry, "TestContract")
        
        assert "class TestContractTestStruct {" in result
        assert "final int fieldOne;" in result
        assert "final bool fieldTwo;" in result
        assert "const TestContractTestStruct({" in result
        assert "required this.fieldOne," in result
        assert "required this.fieldTwo," in result
        assert "XdrSCVal toScVal()" in result
        assert "factory TestContractTestStruct.fromScVal(XdrSCVal val)" in result

    def test_generate_binding_basic(self):
        if not self.specs:
            pytest.skip("No test contract specs available")
        
        generated = generate_binding(self.specs, "TestContract")
        
        # Check that the generated code contains expected elements
        assert "// This file was generated by stellar_contract_bindings" in generated
        assert "import 'dart:typed_data';" in generated
        assert "import 'package:stellar_flutter_sdk/stellar_flutter_sdk.dart';" in generated
        assert "class TestContract {" in generated
        assert "static Future<TestContract> forContractId(" in generated

    def test_generate_binding_with_complex_types(self):
        # Create a more complex spec with various types
        # Enum
        enum_case1 = xdr.SCSpecUDTEnumCaseV0(
            doc=b"",
            name=b"Option1",
            value=xdr.Uint32(0)
        )
        enum_case2 = xdr.SCSpecUDTEnumCaseV0(
            doc=b"",
            name=b"Option2",
            value=xdr.Uint32(1)
        )
        enum_entry = xdr.SCSpecUDTEnumV0(
            doc=b"",
            lib=b"",
            name=b"Status",
            cases=[enum_case1, enum_case2]
        )
        
        enum_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0)
        enum_spec.udt_enum_v0 = enum_entry
        
        # Struct
        field_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        field = xdr.SCSpecUDTStructFieldV0(
            doc=b"",
            name=b"name",
            type=field_type
        )
        struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"Person",
            fields=[field]
        )
        
        struct_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0)
        struct_spec.udt_struct_v0 = struct_entry
        
        # Function
        param_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        param = xdr.SCSpecFunctionInputV0(
            doc=b"",
            name=b"input",
            type=param_type
        )
        
        return_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        
        func_name = xdr.SCSymbol(sc_symbol=b"test_function")
        func_entry = xdr.SCSpecFunctionV0(
            doc=b"",
            name=func_name,
            inputs=[param],
            outputs=[return_type]
        )
        
        func_spec = xdr.SCSpecEntry(xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0)
        func_spec.function_v0 = func_entry
        
        specs = [enum_spec, struct_spec, func_spec]
        generated = generate_binding(specs, "TestContract")
        
        # Check enum generation with prefixed names
        assert "enum TestContractStatus {" in generated
        assert "Option1(0)," in generated
        assert "Option2(1);" in generated
        
        # Check struct generation with prefixed names
        assert "class TestContractPerson {" in generated
        assert "final String name;" in generated
        
        # Check client generation
        assert "class TestContract {" in generated
        assert "Future<int> testFunction({" in generated
        assert "required String input," in generated

    def test_command_function(self):
        """Test the CLI command function with mocked dependencies"""
        # This is a basic test to ensure the command function can be called
        # In a real scenario, you'd want to mock the dependencies
        try:
            # Test invalid contract ID
            from click.testing import CliRunner
            runner = CliRunner()
            
            result = runner.invoke(command, ['--contract-id', 'invalid'])
            assert result.exit_code != 0
            assert "Invalid contract ID" in result.output
        except ImportError:
            pytest.skip("Click testing not available")

    def test_tuple_struct_rendering(self):
        # Create a tuple struct (fields with numeric names)
        field1_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        field2_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        
        field1 = xdr.SCSpecUDTStructFieldV0(
            doc=b"",
            name=b"0",  # Numeric name indicates tuple
            type=field1_type
        )
        field2 = xdr.SCSpecUDTStructFieldV0(
            doc=b"",
            name=b"1",
            type=field2_type
        )
        
        tuple_struct_entry = xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=b"TupleStruct",
            fields=[field1, field2]
        )

        result = render_tuple_struct(tuple_struct_entry, "TestContract")
        
        assert "class TestContractTupleStruct {" in result
        assert "final (int, bool) value;" in result
        assert "const TestContractTupleStruct(this.value);" in result
        assert "XdrSCVal toScVal()" in result
        assert "factory TestContractTupleStruct.fromScVal(XdrSCVal val)" in result

    def test_union_rendering(self):
        # Create a union with void and tuple cases
        void_case = xdr.SCSpecUDTUnionCaseV0(xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0)
        void_case.void_case = xdr.SCSpecUDTUnionCaseVoidV0(
            doc=b"",
            name=b"None"
        )
        
        tuple_case = xdr.SCSpecUDTUnionCaseV0(xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0)
        tuple_type = xdr.SCSpecTypeDef(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        tuple_case.tuple_case = xdr.SCSpecUDTUnionCaseTupleV0(
            doc=b"",
            name=b"Some",
            type=[tuple_type]
        )
        
        union_entry = xdr.SCSpecUDTUnionV0(
            doc=b"",
            lib=b"",
            name=b"Option",
            cases=[void_case, tuple_case]
        )
        
        result = render_union(union_entry, "TestContract")
        
        assert "enum TestContractOptionKind {" in result
        assert "None(" in result
        assert "Some(" in result
        assert "class TestContractOption {" in result
        assert "final TestContractOptionKind kind;" in result
        assert "factory TestContractOption.none()" in result
        assert "factory TestContractOption.some(int value)" in result

    def test_file_output(self):
        """Test that generated code can be written to a file"""
        if not self.specs:
            pytest.skip("No test contract specs available")
            
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = generate_binding(self.specs, "TestContract")
            
            output_path = os.path.join(tmpdir, "test_contract_client.dart")
            with open(output_path, "w") as f:
                f.write(generated)
            
            # Verify file was created and contains expected content
            assert os.path.exists(output_path)
            
            with open(output_path, "r") as f:
                content = f.read()
            
            assert "class TestContract {" in content
            assert "import 'dart:typed_data';" in content