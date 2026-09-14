"""Tests for the Java binding generator that need no JDK.

They check what the generator decides (names, types, codec expressions,
diagnostics) by reading the generated text. Whether that text compiles and
behaves is covered by test_java_compile.py.
"""

import re

import pytest
from click.testing import CliRunner
from stellar_sdk import xdr

from stellar_contract_bindings import java
from stellar_contract_bindings.java import (
    build_model,
    generate_binding,
    generate_binding_with_diagnostics,
    java_identifier,
    java_string_literal,
    javadoc_lines,
    to_camel_case,
    to_pascal_case,
)
from stellar_contract_bindings.metadata import get_token_sc_spec_entry

from .reference_contract import specs as python_contract_specs
from .java_spec_helpers import (
    DATA,
    MAP_FORMAT,
    SINGLE,
    TOPIC,
    VEC_FORMAT,
    address,
    bytes_n,
    enum,
    error,
    error_enum,
    event,
    function,
    i128,
    map_of,
    option,
    result,
    scalar,
    struct,
    tuple_case,
    tuple_of,
    u32,
    udt,
    union,
    vec,
    void,
    void_case,
)


def _generate(specs, **kwargs) -> str:
    return generate_binding(specs, package="org.example", **kwargs)


def _section(text: str, start: str) -> str:
    """The text from ``start`` to the end of the declaration it opens."""
    index = text.index(start)
    depth = 0
    for i in range(index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[index : i + 1]
    raise AssertionError(f"unterminated declaration at {start!r}")


class TestIdentifiers:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("plain", "plain"),
            ("class", "class_"),
            ("_", "unnamed"),
            ("", "unnamed"),
            ("9lives", "_9lives"),
            ("a-b", "a_b"),
            ("dollar$sign", "dollar_sign"),
            ("中文", "unnamed"),
            ("mixed中文name", "mixed__name"),
            ("var", "var_"),
            ("record", "record_"),
        ],
    )
    def test_java_identifier(self, name, expected):
        assert java_identifier(name) == expected

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("set_admin", "setAdmin"),
            ("u32_", "u32"),
            ("u32_fail_on_even", "u32FailOnEven"),
            ("hello", "hello"),
            ("HTTP_URL", "httpUrl"),
            ("AlreadyCamel", "alreadyCamel"),
            ("class", "class_"),
            ("new", "new_"),
            ("_leading", "leading"),
            ("", "unnamed"),
            ("__", "unnamed"),
            ("1st", "_1st"),
        ],
    )
    def test_to_camel_case(self, name, expected):
        assert to_camel_case(name) == expected

    @pytest.mark.parametrize(
        "name, expected",
        [
            ("transfer", "Transfer"),
            ("set_admin", "SetAdmin"),
            ("TransferWithMuxedString", "TransferWithMuxedString"),
            ("ID", "Id"),
            ("", "Unnamed"),
        ],
    )
    def test_to_pascal_case(self, name, expected):
        assert to_pascal_case(name) == expected


class TestStringLiterals:
    def test_quote_and_backslash_are_escaped(self):
        assert java_string_literal('a", "b') == '"a\\", \\"b"'
        assert java_string_literal("back\\slash") == '"back\\\\slash"'

    def test_control_characters_take_octal_escapes(self):
        # Three digits always, so a following digit cannot extend the escape.
        assert java_string_literal("\x07" + "1") == '"\\0071"'

    def test_unicode_escapes_are_not_used_below_u0080(self):
        """javac translates \\uXXXX before lexing, so one could close the literal."""
        assert "\\u00" not in java_string_literal("\x00\x1f\x7f")

    def test_non_ascii_is_escaped(self):
        assert java_string_literal("中") == '"\\u4e2d"'
        assert java_string_literal("\U0001f48e") == '"\\ud83d\\udc8e"'
        assert java_string_literal("中文 \U0001f48e").isascii()


class TestJavadoc:
    def test_html_and_tags_are_escaped(self):
        assert javadoc_lines("Vec<u32> & @param") == ["Vec&lt;u32&gt; &amp; &#64;param"]

    def test_comment_terminator_is_broken_up(self):
        assert "*/" not in javadoc_lines("a */ b")[0]

    def test_backslash_cannot_form_a_unicode_escape(self):
        # */ would be translated to */ by javac, comments included.
        assert "\\" not in javadoc_lines("\\u002a\\u002f")[0]

    def test_lines_are_kept_and_non_ascii_becomes_entities(self):
        assert javadoc_lines("one\r\ntwo\n中") == ["one", "two", "&#20013;"]


class TestOutputIsAscii:
    def test_hostile_names_and_docs_leave_the_file_ascii(self):
        specs = [
            struct(
                "中文".encode(), [("字段".encode(), u32(), "文档 */ @tag".encode())]
            ),
            function(
                'go", null); //'.encode(),
                [("参数".encode(), udt("中文".encode()))],
                [],
                doc="doc with \\u002a\\u002f and \x00 control".encode(),
            ),
            event(b"ev\x07ent", [b'pre"fix'], [(b"p", u32(), TOPIC)]),
        ]
        generated = _generate(specs)
        assert generated.isascii()
        assert "*/ @tag" not in generated
        assert '"pre\\"fix"' in generated


class TestGenerationIsPure:
    def test_the_specs_are_not_modified_and_output_is_stable(self):
        specs = python_contract_specs()
        before = [s.to_xdr_bytes() for s in specs]
        first = _generate(specs)
        second = _generate(specs)
        assert first == second
        assert [s.to_xdr_bytes() for s in specs] == before


class TestHeader:
    def test_header_names_the_generators_and_the_package(self):
        generated = _generate([function(b"f", [], [])])
        first, second, third = generated.split("\n")[:3]
        assert first.startswith(
            "// This file was generated by stellar_contract_bindings v"
        )
        assert "stellar-sdk" in second
        assert third == "package org.example;"

    def test_imports_are_only_what_is_used_and_sorted(self):
        generated = _generate([function(b"f", [(b"a", u32())], [u32()])])
        imports = re.findall(r"^import (.+);$", generated, re.MULTILINE)
        assert imports == sorted(imports)
        assert "org.stellar.sdk.scval.Scv" in imports
        assert "java.math.BigInteger" not in imports
        assert "org.stellar.sdk.xdr.ContractEvent" not in imports

    def test_the_class_name_is_configurable(self):
        generated = _generate([function(b"f", [], [])], class_name="Token")
        assert "public class Token extends ContractClient {" in generated
        assert (
            "public Token(String contractId, String rpcUrl, Network network)"
            in generated
        )
        assert "class Client" not in generated


class TestTypeMapping:
    @pytest.mark.parametrize(
        "spec_type, java_type",
        [
            (xdr.SCSpecType.SC_SPEC_TYPE_VAL, "SCVal"),
            (xdr.SCSpecType.SC_SPEC_TYPE_BOOL, "boolean"),
            (xdr.SCSpecType.SC_SPEC_TYPE_VOID, "Void"),
            (xdr.SCSpecType.SC_SPEC_TYPE_U32, "long"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I32, "int"),
            (xdr.SCSpecType.SC_SPEC_TYPE_U64, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I64, "long"),
            (xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_DURATION, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_U128, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I128, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_U256, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_I256, "BigInteger"),
            (xdr.SCSpecType.SC_SPEC_TYPE_BYTES, "byte[]"),
            (xdr.SCSpecType.SC_SPEC_TYPE_STRING, "byte[]"),
            (xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL, "String"),
            (xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS, "Address"),
            (xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS, "Address"),
            (xdr.SCSpecType.SC_SPEC_TYPE_ERROR, "SCError"),
        ],
    )
    def test_scalars(self, spec_type, java_type):
        generated = _generate([struct(b"S", [(b"v", scalar(spec_type))])])
        assert f"        {java_type} v;" in generated

    def test_scalars_are_boxed_where_they_can_be_null_or_generic(self):
        i32 = scalar(xdr.SCSpecType.SC_SPEC_TYPE_I32)
        i64 = scalar(xdr.SCSpecType.SC_SPEC_TYPE_I64)
        boolean = scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        generated = _generate(
            [
                struct(
                    b"S",
                    [
                        (b"a", option(u32())),
                        (b"b", vec(boolean)),
                        (b"c", map_of(i32, option(i64))),
                    ],
                ),
                function(b"f", [(b"x", u32())], [u32()]),
            ]
        )
        assert "        Long a;" in generated
        assert "        List<Boolean> b;" in generated
        assert "        Map<Integer, Long> c;" in generated
        assert "public AssembledTransaction<Long> f(long x) {" in generated

    def test_strings_are_raw_bytes(self):
        """An SCV_STRING is any bytes, so no charset is involved either way."""
        text = scalar(xdr.SCSpecType.SC_SPEC_TYPE_STRING)
        generated = _generate([struct(b"S", [(b"s", text)])])
        assert "        byte[] s;" in generated
        assert 'fields.put(Scv.toSymbol("s"), Scv.toString(this.s));' in generated
        assert 'Scv.fromString(Codec.structField(fields, "s"))' in generated
        assert "getBytes(" not in generated

    def test_containers(self):
        generated = _generate(
            [
                struct(
                    b"S",
                    [
                        (b"a", option(u32())),
                        (b"b", vec(u32())),
                        (b"c", map_of(u32(), option(vec(address())))),
                        (b"d", tuple_of(u32(), i128())),
                        (b"e", tuple_of()),
                        (b"f", bytes_n(32)),
                        (b"g", result(u32(), error())),
                    ],
                )
            ]
        )
        assert "        Long a;" in generated
        assert "        List<Long> b;" in generated
        assert "        Map<Long, List<Address>> c;" in generated
        assert "        Tuple2<Long, BigInteger> d;" in generated
        assert "        Void e;" in generated
        assert "        byte[] f;" in generated
        assert "        Result<Long, SCError> g;" in generated

    def test_bytes_n_length_is_checked_both_ways(self):
        generated = _generate([struct(b"S", [(b"f", bytes_n(32))])])
        assert "Scv.toBytes(Codec.bytesN(this.f, 32))" in generated
        assert (
            'Codec.bytesN(Scv.fromBytes(Codec.structField(fields, "f")), 32)'
            in generated
        )

    def test_udt_references_use_the_generated_name(self):
        generated = _generate(
            [
                struct(b"class", [(b"v", u32())]),
                struct(b"Holder", [(b"thing", udt(b"class"))]),
            ]
        )
        assert "public static class class_ {" in generated
        assert "        class_ thing;" in generated


class TestCodecExpressions:
    def test_nested_lambdas_get_distinct_parameters(self):
        """Java forbids a lambda parameter shadowing an enclosing one."""
        generated = _generate([function(b"f", [(b"a", vec(vec(option(u32()))))], [])])
        assert (
            "Codec.encodeVec(a, element -> Codec.encodeVec(element, element1 -> "
            "Codec.encodeOption(element1, some2 -> Scv.toUint32(some2))))" in generated
        )

    def test_lambda_parameters_cannot_shadow_a_functions_parameters(self):
        """Java forbids a lambda parameter shadowing a method parameter.

        The names the codec lambdas take are reserved when a function's
        parameters are named, so a contract parameter that would clash moves
        aside instead; the same holds for the setters of an event's topic
        filter, which encode the topic inline.
        """
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                function(
                    b"f",
                    [
                        (b"element", vec(u32())),
                        (b"some", option(u32())),
                        (b"scVal", u32()),
                        (b"mapKey", u32()),
                        (b"element1", u32()),
                    ],
                    [map_of(u32(), u32())],
                ),
                event(
                    b"e",
                    [b"e"],
                    [(b"element", vec(u32()), TOPIC), (b"some", u32(), DATA)],
                ),
            ],
            package="org.example",
        )
        # Only the names this function's own lambdas take are reserved: no
        # lambda here nests two deep, so element1 is left alone.
        assert (
            "return f(element2, some2, scVal2, mapKey2, element1, this.defaultOptions);"
            in generated
        )
        assert (
            "Codec.encodeVec(element2, element -> Scv.toUint32(element))" in generated
        )
        assert (
            "scVal -> Codec.decodeMap(scVal, mapKey -> Scv.fromUint32(mapKey), mapValue -> Scv.fromUint32(mapValue))"
            in generated
        )
        assert "public TopicFilterBuilder element2(List<Long> element2)" in generated
        # A data parameter is only ever decoded in a static method with fixed
        # parameters, so nothing has to move for it.
        assert "long some;" in generated
        assert "parameter f.'element' is generated as element2" in diagnostics
        assert "parameter EEvent.'element' is generated as element2" in diagnostics
        assert "parameter EEvent.'some' is generated" not in " ".join(diagnostics)

    def test_fields_named_after_generated_locals_are_read_through_this(self):
        """A struct's fields may take any name its methods use for locals."""
        generated = _generate(
            [
                struct(
                    b"S",
                    [(b"fields", u32()), (b"element", vec(u32())), (b"scVal", u32())],
                )
            ]
        )
        assert (
            'fields.put(Scv.toSymbol("fields"), Scv.toUint32(this.fields));'
            in generated
        )
        assert (
            "Codec.encodeVec(this.element, element -> Scv.toUint32(element))"
            in generated
        )

    def test_enum_fields_move_aside_for_a_case_of_the_same_name(self):
        generated = _generate(
            [
                enum(b"E", [(b"value", 1)]),
                union(b"U", [void_case(b"symbol")]),
            ]
        )
        assert "private final long value2;" in generated
        assert "return this.value2;" in generated
        assert "private final String symbol2;" in generated
        assert 'symbol("symbol");' in generated

    def test_generated_helpers_live_in_a_nested_class(self):
        """So a contract function may take any helper's name."""
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"Codec", [(b"v", u32())]),
                function(b"bytes_n", [(b"v", bytes_n(9))], []),
                function(
                    b"decode_void",
                    [(b"v", scalar(xdr.SCSpecType.SC_SPEC_TYPE_VAL))],
                    [],
                ),
            ],
            package="org.example",
        )
        assert diagnostics == []
        assert "public AssembledTransaction<Void> bytesN(byte[] v) {" in generated
        assert "public AssembledTransaction<Void> decodeVoid(SCVal v) {" in generated
        assert "private static final class Codec2 {" in generated
        assert "Scv.toBytes(Codec2.bytesN(v, 9))" in generated

    def test_map_encoding_relies_on_the_sdk_to_sort_keys(self):
        generated = _generate([struct(b"S", [(b"m", map_of(u32(), u32()))])])
        assert "return Scv.toMap(encoded);" in generated
        assert "TreeMap" not in generated

    def test_tuples_decode_with_an_exact_size_check(self):
        generated = _generate([function(b"f", [], [tuple_of(u32(), u32())])])
        assert (
            "Codec.decodeTuple(scVal, 2, tupleValues -> new Tuple2<>("
            "Scv.fromUint32(tupleValues.get(0)), Scv.fromUint32(tupleValues.get(1))))"
            in generated
        )
        assert "elements.size() != size" in generated

    def test_helpers_are_emitted_only_when_used(self):
        helpers = (
            "encodeVec",
            "decodeVec",
            "encodeMap",
            "decodeMap",
            "decodeTuple",
            "encodeOption",
            "decodeOption",
            "encodeResult",
            "decodeResult",
            "structField",
            "contractError",
            "contractErrorCode",
            "bytesN",
            "decodeVoid",
        )
        plain = _generate([function(b"f", [(b"a", u32())], [u32()])])
        assert not any(f" {helper}(" in plain for helper in helpers)
        with_vec = _generate([function(b"f", [(b"a", vec(u32()))], [])])
        assert "private static <T> SCVal encodeVec(" in with_vec
        assert "decodeVec(" not in with_vec


class TestFunctions:
    def test_each_function_gets_a_defaults_overload_and_an_options_overload(self):
        generated = _generate(
            [
                function(
                    b"set_admin",
                    [(b"new_admin", address())],
                    [],
                    doc=b"Sets the admin.",
                )
            ]
        )
        assert (
            "public AssembledTransaction<Void> setAdmin(Address newAdmin) {"
            in generated
        )
        assert "return setAdmin(newAdmin, this.defaultOptions);" in generated
        assert (
            "public AssembledTransaction<Void> setAdmin(Address newAdmin, MethodOptions options) {"
            in generated
        )
        assert '"set_admin",' in generated
        assert "Arrays.asList(Scv.toAddress(newAdmin))," in generated
        assert " * Sets the admin." in generated

    def test_a_function_without_inputs(self):
        generated = _generate([function(b"decimals", [], [u32()])])
        assert "public AssembledTransaction<Long> decimals() {" in generated
        assert "return decimals(this.defaultOptions);" in generated
        assert "Arrays.asList()," in generated
        assert "scVal -> Scv.fromUint32(scVal));" in generated

    def test_a_function_without_output_decodes_to_null(self):
        generated = _generate([function(b"void", [], [])])
        assert "public AssembledTransaction<Void> void_() {" in generated
        assert "scVal -> null);" in generated

    def test_a_result_output_is_unwrapped_to_its_ok_arm(self):
        """Returning Err traps, so AssembledTransaction<T> never sees a Result."""
        generated = _generate(
            [
                error_enum(b"Code", [(b"Bad", 1)]),
                function(b"get", [], [result(u32(), udt(b"Code"))]),
            ]
        )
        assert "public AssembledTransaction<Long> get() {" in generated
        assert "class Result<T, E>" not in generated

    def test_constructor_functions_are_skipped(self):
        generated = _generate([function(b"__constructor", [(b"admin", address())], [])])
        assert "__constructor" not in generated
        assert "constructor(" not in generated

    def test_inherited_method_names_are_not_overridden(self):
        """A zero-argument close() would override ContractClient.close()."""
        generated, diagnostics = generate_binding_with_diagnostics(
            [function(b"close", [], []), function(b"hash_code", [], [u32()])],
            package="org.example",
        )
        assert "public AssembledTransaction<Void> close2() {" in generated
        assert "public AssembledTransaction<Long> hashCode2() {" in generated
        assert "function 'close' is generated as close2" in diagnostics
        assert "function 'hash_code' is generated as hashCode2" in diagnostics

    def test_parameter_names_avoid_the_options_parameter(self):
        generated = _generate([function(b"f", [(b"options", u32())], [])])
        assert "f(long options2, MethodOptions options)" in generated

    def test_duplicate_function_names_are_kept_apart(self):
        generated = _generate(
            [function(b"f", [], []), function(b"f", [(b"a", u32())], [])]
        )
        assert "public AssembledTransaction<Void> f() {" in generated
        assert "public AssembledTransaction<Void> f2(long a) {" in generated

    def test_docs_are_rendered_with_param_tags(self):
        generated = _generate(
            [
                function(
                    b"f",
                    [(b"a", u32(), b"the first"), (b"b", u32())],
                    [],
                    doc=b"Does things.\n\nWith <care> & @home.",
                )
            ]
        )
        assert (
            " * Does things.\n     *\n     * With &lt;care&gt; &amp; &#64;home.\n"
            in generated
        )
        assert " * @param a the first" in generated
        assert "@param b" not in generated
        assert " * @param options how to assemble the transaction" in generated


class TestStructs:
    def test_struct_encodes_as_a_map_keyed_by_wire_names(self):
        generated = _generate(
            [
                struct(
                    b"S", [(b"first_field", u32()), (b"class", u32())], doc=b"A struct."
                )
            ]
        )
        section = _section(generated, "public static class S {")
        assert "long firstField;" in section
        assert "long class_;" in section
        assert (
            'fields.put(Scv.toSymbol("first_field"), Scv.toUint32(this.firstField));'
            in section
        )
        assert (
            'fields.put(Scv.toSymbol("class"), Scv.toUint32(this.class_));' in section
        )
        assert 'Scv.fromUint32(Codec.structField(fields, "first_field"))' in section
        assert (
            " * A struct.\n     *\n     * Build one with {@code S.builder()} or the constructor.\n     */\n"
            '    @Value\n    @Builder(builderClassName = "Builder")\n    @AllArgsConstructor\n'
            "    public static class S {" in generated
        )

    def test_fields_that_share_a_getter_are_kept_apart(self):
        """Lombok derives getFoo() from both foo and Foo."""
        generated, diagnostics = generate_binding_with_diagnostics(
            [struct(b"S", [(b"foo", u32()), (b"Foo", u32())])], package="org.example"
        )
        assert "long foo;" in generated
        assert "long foo2;" in generated
        assert "field S.'Foo' is generated as foo2" in diagnostics

    def test_tuple_struct_encodes_as_a_vector(self):
        generated = _generate([struct(b"Pair", [(b"0", u32()), (b"1", address())])])
        section = _section(generated, "public static class Pair {")
        assert "long value0;" in section
        assert "Address value1;" in section
        # Positional, so no builder.
        assert (
            "@Builder"
            not in generated.split("public static class Pair {")[0].splitlines()[-2]
        )
        assert "return Scv.toVec(Arrays.asList(" in section
        assert "Codec.decodeTuple(scVal, 2, tupleValues -> new Pair(" in section

    def test_an_empty_struct(self):
        generated = _generate([struct(b"Empty", [])])
        section = _section(generated, "public static class Empty {")
        assert "return new Empty();" in section


class TestEnums:
    def test_enum_carries_its_values(self):
        generated = _generate([enum(b"Card", [(b"Jack", 11), (b"Queen", 12)])])
        section = _section(generated, "public enum Card {")
        assert "Jack(11L)," in section
        assert "Queen(12L);" in section
        assert "return Scv.toUint32(this.value);" in section
        assert "return fromValue(Scv.fromUint32(scVal));" in section

    def test_error_enum_encodes_as_a_contract_error(self):
        generated = _generate([error_enum(b"Code", [(b"Bad", 7)])])
        section = _section(generated, "public enum Code {")
        assert "return Codec.contractError(this.value);" in section
        assert "return fromValue(Codec.contractErrorCode(scVal));" in section
        assert "SCErrorType.SCE_CONTRACT" in generated
        assert "Scv.toUint32(this.value)" not in section

    def test_keyword_cases_are_renamed(self):
        generated = _generate(
            [enum(b"None", [(b"elif", 0), (b"new", 1), (b"true", 2)])]
        )
        section = _section(generated, "public enum None {")
        assert "elif(0L)," in section
        assert "new_(1L)," in section
        assert "true_(2L);" in section

    def test_an_empty_enum_still_compiles_syntactically(self):
        generated = _generate([enum(b"Nothing", [])])
        assert "public enum Nothing {\n        ;" in generated


class TestUnions:
    def setup_method(self):
        self.generated = _generate(
            [
                struct(b"Thing", [(b"v", u32())]),
                union(
                    b"Choice",
                    [
                        void_case(b"none"),
                        tuple_case(b"one", udt(b"Thing")),
                        tuple_case(b"pair", u32(), address()),
                        void_case(b"set_admin"),
                    ],
                    doc=b"A choice.",
                ),
            ]
        )
        self.section = _section(self.generated, "public abstract static class Choice {")

    def test_one_class_per_case(self):
        assert "public static final class none extends Choice {" in self.section
        assert "public static class one extends Choice {" in self.section
        assert "public static class pair extends Choice {" in self.section
        assert "Thing value0;" in self.section
        assert "long value0;\n            Address value1;" in self.section

    def test_match_takes_one_function_per_case(self):
        assert (
            "public abstract <R> R match(\n"
            "                Function<none, R> none,\n"
            "                Function<one, R> one,\n"
            "                Function<pair, R> pair,\n"
            "                Function<set_admin, R> setAdmin);"
        ) in self.section
        assert "return setAdmin.apply(this);" in self.section
        assert self.section.count("public <R> R match(") == 4

    def test_kind_enum_carries_the_wire_symbols(self):
        kind = _section(self.section, "public enum Kind {")
        assert 'none("none"),' in kind
        assert 'set_admin("set_admin");' in kind
        assert "public String getSymbol()" in kind

    def test_decoding_dispatches_on_the_wire_symbol(self):
        assert 'if (symbol.equals("pair")) {' in self.section
        assert "if (elements.size() != 3) {" in self.section
        assert (
            "return new pair(Scv.fromUint32(elements.get(1)), Scv.fromAddress(elements.get(2)));"
            in self.section
        )
        assert (
            'if (symbol.equals("none")) {\n                return new none();'
            in self.section
        )

    def test_encoding_prefixes_the_symbol(self):
        assert (
            'return Scv.toVec(Collections.singletonList(Scv.toSymbol("none")));'
            in self.section
        )
        assert (
            'Scv.toSymbol("pair"),\n                    Scv.toUint32(this.value0),\n                    Scv.toAddress(this.value1)));'
            in self.section
        )

    def test_a_case_cannot_take_the_unions_name_or_shadow_a_type(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"Thing", [(b"v", u32())]),
                union(
                    b"U",
                    [
                        void_case(b"U"),
                        tuple_case(b"Thing", udt(b"Thing")),
                        void_case(b"Kind"),
                    ],
                ),
            ],
            package="org.example",
        )
        section = _section(generated, "public abstract static class U {")
        assert "class U2 extends U" in section
        assert "class Thing2 extends U" in section
        assert "Thing value0;" in section
        # The case named Kind keeps its name; the enum moves aside.
        assert "class Kind extends U" in section
        assert "public enum Kind2 {" in section
        assert "public abstract Kind2 getKind();" in section
        assert "case U.'U' is generated as U2" in diagnostics
        assert "case U.'Thing' is generated as Thing2" in diagnostics


class TestNameCollisions:
    def test_spec_text_in_error_messages_is_escaped(self):
        """A quote in a wire name must not end the literal it is quoted in."""
        generated = _generate(
            [
                union(b"U", [tuple_case(b'a", "b', u32())]),
                event(b"e", [b"e"], [(b'k", "v', u32(), DATA)], MAP_FORMAT),
            ]
        )
        assert '"case a\\", \\"b expects 1 value(s), got "' in generated
        assert '"event data map is missing the entry k\\", \\"v"' in generated
        assert 'entry k", "v"' not in generated

    def test_boolean_fields_share_lombok_is_getters(self):
        """Lombok derives isReady() from both a boolean ready and a boolean isReady."""
        boolean = scalar(xdr.SCSpecType.SC_SPEC_TYPE_BOOL)
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"S", [(b"is_ready", boolean), (b"ready", boolean)]),
                # A boxed Boolean gets getReady(), which does not clash.
                struct(b"T", [(b"is_ready", boolean), (b"ready", option(boolean))]),
                event(
                    b"e",
                    [b"e"],
                    [(b"is_done", boolean, DATA), (b"done", boolean, TOPIC)],
                ),
            ],
            package="org.example",
        )
        assert "boolean isReady;\n        boolean ready2;" in generated
        assert "boolean isReady;\n        Boolean ready;" in generated
        assert "boolean done2;" in generated
        assert "field S.'ready' is generated as ready2" in diagnostics
        assert "parameter EEvent.'done' is generated as done2" in diagnostics

    def test_tuple_elements_use_the_lambda_names_reserved_for_them(self):
        generated = _generate(
            [function(b"f", [(b"element", tuple_of(vec(u32())))], [])]
        )
        assert "f(Tuple1<List<Long>> element)" in generated
        assert (
            "Codec.encodeVec(element.getValue0(), element1 -> Scv.toUint32(element1))"
            in generated
        )

    def test_a_client_named_after_an_sdk_type_is_spelled_in_full(self):
        generated = _generate([function(b"f", [], [])], class_name="ContractClient")
        assert (
            "public class ContractClient extends org.stellar.sdk.contract.ContractClient {"
            in generated
        )
        assert "import org.stellar.sdk.contract.ContractClient;" not in generated

    def test_match_type_parameter_avoids_a_case_of_that_name(self):
        generated = _generate([union(b"U", [void_case(b"R"), tuple_case(b"S", u32())])])
        assert (
            "public abstract <R2> R2 match(Function<R, R2> r, Function<S, R2> s);"
            in generated
        )
        assert (
            "public <R2> R2 match(Function<R, R2> r, Function<S, R2> s) {" in generated
        )

    def test_builder_setters_avoid_object_wait(self):
        """A long field called wait would give the builder wait(long)."""
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"S", [(b"wait", u32()), (b"notify", u32())]),
                # Not a long, so wait(Address) is a plain overload.
                struct(b"T", [(b"wait", address())]),
                # A tuple struct has no builder.
                struct(b"P", [(b"0", u32())]),
                event(
                    b"e", [b"e"], [(b"wait", u32(), TOPIC), (b"notify", u32(), DATA)]
                ),
                event(b"d", [b"d"], [(b"wait", u32(), DATA)]),
            ],
            package="org.example",
        )
        assert "long wait2;\n        long notify;" in generated
        assert "Address wait;" in generated
        assert "public TopicFilterBuilder wait2(long wait2)" in generated
        assert "field S.'wait' is generated as wait2" in diagnostics
        assert "parameter EEvent.'wait' is generated as wait2" in diagnostics
        assert "parameter DEvent.'wait'" not in " ".join(diagnostics)

    def test_enum_constants_cannot_shadow_the_qualifiers_the_enum_uses(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                error_enum(
                    b"E", [(b"Codec", 1), (b"Optional", 2), (b"Scv", 3), (b"org", 4)]
                ),
                enum(b"F", [(b"Scv", 1)]),
            ],
            package="org.example",
        )
        assert (
            "Codec2(1L),\n        Optional2(2L),\n        Scv2(3L),\n        org2(4L);"
            in generated
        )
        assert "return Codec.contractError(this.value);" in generated
        assert "case E.'Codec' is generated as Codec2" in diagnostics

    def test_a_type_named_like_a_variable_is_reached_through_the_client(self):
        """scVal -> scVal.fromSCVal(scVal) would read the lambda parameter."""
        generated = _generate(
            [
                struct(b"scVal", [(b"v", u32())]),
                struct(b"data", [(b"v", u32())]),
                struct(b"Holder", [(b"data", udt(b"data"))]),
                function(b"f", [], [udt(b"scVal")]),
                event(b"e", [b"e"], [(b"data", udt(b"data"), DATA)]),
            ]
        )
        assert "scVal -> Client.scVal.fromSCVal(scVal));" in generated
        assert 'Client.data.fromSCVal(Codec.structField(fields, "data"))' in generated
        assert "Client.data.fromSCVal(event.getData())" in generated
        # A capitalized name cannot be a variable, so it stays bare.
        assert "Client.Holder" not in generated

    def test_the_options_builder_avoids_the_client_and_its_types(self):
        # The client called Builder also shadows lombok.Builder itself.
        generated = _generate([function(b"f", [], [])], class_name="Builder")
        assert (
            '@lombok.Builder(builderClassName = "Builder2", toBuilder = true)'
            in generated
        )
        # So does a contract type called Builder.
        generated = _generate([struct(b"Builder", [(b"v", u32())])])
        assert (
            '@lombok.Builder(builderClassName = "Builder2", toBuilder = true)'
            in generated
        )
        assert '@lombok.Builder(builderClassName = "Builder2")' in generated

    def test_package_roots_are_never_taken_by_spec_names(self):
        """A variable or type called java or org hides the package from every
        name spelled in full, Lombok's own java.lang.Object included."""
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"Roots", [(b"org", u32()), (b"lombok", u32())]),
                struct(b"java", [(b"v", u32())]),
                union(b"U", [void_case(b"java"), tuple_case(b"org", u32())]),
                enum(b"E", [(b"java", 1)]),
                function(b"f", [(b"org", u32()), (b"java", u32())], []),
                event(b"e", [b"e"], [(b"java", u32(), TOPIC), (b"org", u32(), DATA)]),
            ],
            package="org.example",
        )
        assert "public static class java2 {" in generated
        assert "long org2;\n        long lombok2;" in generated
        # The case avoids the root and the struct that took the next name.
        assert (
            "class java3 extends U" in generated and "class org2 extends U" in generated
        )
        assert "java2(1L);" in generated
        assert "f(long org2, long java2)" in generated
        assert "long java2;\n        long org2;" in generated
        assert "type 'java' is generated as java2" in diagnostics
        assert "parameter f.'org' is generated as org2" in diagnostics

    def test_keyword_type_names(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"import", [(b"v", u32())]),
                function(b"f", [(b"x", udt(b"import"))], []),
            ],
            package="org.example",
        )
        assert "public static class import_ {" in generated
        assert "f(import_ x)" in generated
        assert "type 'import' is generated as import_" in diagnostics

    def test_module_qualified_names_prefer_the_bare_segment(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"a::b::Thing", [(b"v", u32())]),
                struct(b"c::Thing", [(b"v", u32())]),
                struct(b"d::Other", [(b"v", u32())]),
                function(
                    b"f", [(b"x", udt(b"a::b::Thing")), (b"y", udt(b"d::Other"))], []
                ),
            ],
            package="org.example",
        )
        assert "public static class a_b_Thing {" in generated
        assert "public static class c_Thing {" in generated
        assert "public static class Other {" in generated
        assert "f(a_b_Thing x, Other y)" in generated

    def test_two_types_with_one_java_name_are_kept_apart(self):
        generated = _generate(
            [struct(b"a-b", [(b"v", u32())]), struct(b"a_b", [(b"v", u32())])]
        )
        assert "public static class a_b {" in generated
        assert "public static class a_b2 {" in generated

    def test_a_repeated_declaration_is_dropped_with_a_note(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [struct(b"S", [(b"v", u32())]), struct(b"S", [(b"w", u32())])],
            package="org.example",
        )
        assert generated.count("public static class S {") == 1
        assert "long v;" in generated and "long w;" not in generated
        assert any("declared more than once" in note for note in diagnostics)

    def test_the_client_class_name_is_reserved(self):
        generated = _generate([struct(b"Client", [(b"v", u32())])])
        assert "public static class Client2 {" in generated

    def test_union_cases_displace_the_generated_helpers(self):
        """A case nested in a union would hide a helper from its siblings."""
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                union(
                    b"U",
                    [
                        tuple_case(b"Result", u32()),
                        tuple_case(b"Other", result(u32(), error())),
                    ],
                )
            ],
            package="org.example",
        )
        assert diagnostics == []
        assert "public static class Result extends U {" in generated
        assert "Result2<Long, SCError> value0;" in generated
        assert "public static final class Result2<T, E> {" in generated

    def test_contract_types_displace_the_generated_helpers(self):
        specs = [
            struct(b"MethodOptions", [(b"v", u32())]),
            struct(b"Result", [(b"r", result(u32(), error()))]),
            struct(b"Tuple2", [(b"t", tuple_of(u32(), u32()))]),
            struct(b"Event", [(b"v", u32())]),
            struct(b"DecodedEvent", [(b"v", u32())]),
            struct(b"UnparsedEventException", [(b"v", u32())]),
            struct(b"TopicFilterBuilder", [(b"v", u32())]),
            event(b"ping", [b"ping"], [(b"who", u32(), TOPIC)]),
            function(b"parse_event", [], []),
        ]
        generated = _generate(specs)
        for own in (
            "MethodOptions",
            "Result",
            "Tuple2",
            "Event",
            "DecodedEvent",
            "UnparsedEventException",
            "TopicFilterBuilder",
        ):
            assert f"public static class {own} {{" in generated
        assert "public static class MethodOptions2 {" in generated
        assert "public static final class Result2<T, E> {" in generated
        assert "Result2<Long, SCError> r;" in generated
        assert "public static class Tuple22<T0, T1> {" in generated
        assert "Tuple22<Long, Long> t;" in generated
        assert "public interface Event2 {" in generated
        assert "public static class DecodedEvent2 {" in generated
        assert (
            "class UnparsedEventException2 extends IllegalArgumentException"
            in generated
        )
        assert "public static TopicFilterBuilder2 topicFilter()" in generated
        assert "public AssembledTransaction<Void> parseEvent() {" in generated
        assert (
            "public static Optional<Event2> parseEvent2(DecodedEvent2 event)"
            in generated
        )

    def test_contract_types_shadowing_sdk_types_are_spelled_in_full(self):
        specs = [
            struct(b"Address", [(b"v", u32())]),
            struct(b"Scv", [(b"v", u32())]),
            struct(b"String", [(b"v", u32())]),
            struct(b"List", [(b"v", u32())]),
            struct(b"Value", [(b"v", u32())]),
            struct(
                b"Holder",
                [
                    (b"a", address()),
                    (b"s", scalar(xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL)),
                    (b"l", vec(u32())),
                ],
            ),
            function(b"f", [(b"x", udt(b"Address"))], []),
        ]
        generated = _generate(specs)
        assert "public static class Address {" in generated
        assert "f(Address x)" in generated
        assert "org.stellar.sdk.Address a;" in generated
        assert "org.stellar.sdk.scval.Scv.toAddress(this.a)" in generated
        assert "java.lang.String s;" in generated
        assert "java.util.List<Long> l;" in generated
        assert "@lombok.Value" in generated
        assert "\n@Value" not in generated
        for fqn in (
            "org.stellar.sdk.Address",
            "org.stellar.sdk.scval.Scv",
            "java.util.List",
            "lombok.Value",
        ):
            assert f"import {fqn};" not in generated

    def test_a_union_case_shadowing_a_jdk_type_is_spelled_in_full_everywhere(self):
        generated = _generate(
            [
                union(b"U", [void_case(b"Void")]),
                function(b"f", [], [void()]),
            ]
        )
        assert "public static final class Void extends U" in generated
        assert "public AssembledTransaction<java.lang.Void> f() {" in generated

    def test_an_event_named_like_a_type_is_renamed(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [
                struct(b"TransferEvent", [(b"v", u32())]),
                event(b"transfer", [b"transfer"], []),
            ],
            package="org.example",
        )
        assert "public static class TransferEvent {" in generated
        assert "public static class TransferEvent2 implements Event" in generated
        assert "event 'transfer' is generated as TransferEvent2" in diagnostics

    def test_events_whose_names_normalize_alike_are_kept_apart(self):
        generated = _generate(
            [
                event(b"foo_bar", [b"a"], []),
                event(b"FooBar", [b"b"], []),
                event(b"foo_bar", [b"c"], []),
            ]
        )
        assert "class FooBarEvent implements" in generated
        assert "class FooBarEvent2 implements" in generated
        assert "class FooBarEvent3 implements" in generated


class TestResults:
    def test_a_result_value_keeps_both_arms(self):
        generated = _generate(
            [
                error_enum(b"Code", [(b"Bad", 1)]),
                struct(b"S", [(b"r", result(u32(), udt(b"Code")))]),
            ]
        )
        assert "Result<Long, Code> r;" in generated
        assert (
            "Codec.encodeResult(this.r, ok -> Scv.toUint32(ok), err -> err.toSCVal())"
            in generated
        )
        assert (
            'Codec.decodeResult(Codec.structField(fields, "r"), ok -> Scv.fromUint32(ok), err -> Code.fromSCVal(err))'
            in generated
        )
        section = _section(generated, "public static final class Result<T, E> {")
        assert "public static <T, E> Result<T, E> ok(T value)" in section
        assert "public static <T, E> Result<T, E> err(E error)" in section
        assert "public T getValue()" in section and "public E getError()" in section

    def test_the_result_class_is_only_emitted_when_used(self):
        assert "class Result<" not in _generate([function(b"f", [], [u32()])])

    @pytest.mark.parametrize(
        "arm, extra, message",
        [
            (u32(), [], "SC_SPEC_TYPE_U32"),
            (udt(b"Thing"), [struct(b"Thing", [(b"v", u32())])], "the type Thing"),
        ],
    )
    def test_an_error_arm_that_is_not_an_error_is_refused(self, arm, extra, message):
        with pytest.raises(NotImplementedError) as info:
            _generate(extra + [struct(b"Holder", [(b"r", result(u32(), arm))])])
        assert message in str(info.value)
        assert "SCV_ERROR" in str(info.value)

    def test_error_and_error_enum_arms_are_accepted(self):
        _generate([struct(b"A", [(b"r", result(u32(), error()))])])
        _generate(
            [
                error_enum(b"Code", [(b"Bad", 1)]),
                struct(b"B", [(b"r", result(u32(), udt(b"Code")))]),
            ]
        )

    def test_a_function_output_is_not_checked(self):
        generated = _generate([function(b"get", [], [result(u32(), u32())])])
        assert "public AssembledTransaction<Long> get() {" in generated


class TestTuples:
    def test_only_the_arities_in_use_are_emitted(self):
        generated = _generate(
            [
                struct(
                    b"S",
                    [(b"a", tuple_of(u32(), u32())), (b"b", tuple_of(*[u32()] * 12))],
                )
            ]
        )
        assert "public static class Tuple2<T0, T1> {" in generated
        assert (
            "public static class Tuple12<T0, T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11> {"
            in generated
        )
        assert "class Tuple3<" not in generated
        assert "javatuples" not in generated

    def test_a_union_case_of_several_values_needs_no_tuple_class(self):
        generated = _generate([union(b"U", [tuple_case(b"pair", u32(), u32())])])
        assert "class Tuple" not in generated


class TestEvents:
    def test_event_class_shape(self):
        generated = _generate(
            [
                event(
                    b"transfer",
                    [b"transfer"],
                    [
                        (b"from", address(), TOPIC),
                        (b"to", address(), TOPIC),
                        (b"amount", i128(), DATA),
                    ],
                    doc=b"Moved tokens.",
                )
            ]
        )
        section = _section(
            generated, "public static class TransferEvent implements Event {"
        )
        assert 'public static final String EVENT_NAME = "transfer";' in section
        assert (
            "Address from;\n        Address to;\n        BigInteger amount;" in section
        )
        assert "/** Moved tokens. */" in generated
        assert 'this.topicValues.put("from", Scv.toAddress(from));' in section
        assert 'row.add(Codec.encodeTopic(Scv.toSymbol("transfer")));' in section
        assert 'row.add(Codec.topicOrWildcard(this.topicValues, "from"));' in section
        assert 'row.add("**");' in section
        assert "if (topics.size() < 3) {" in section
        assert 'if (!Codec.staticTopicMatches(topics.get(0), "transfer")) {' in section
        assert (
            "Scv.fromAddress(topics.get(1)),\n                Scv.fromAddress(topics.get(2)),\n                Scv.fromInt128(event.getData()));"
            in section
        )

    def test_single_value_without_data_requires_void_data(self):
        generated = _generate([event(b"ping", [b"ping"], [])])
        assert "decodeVoid(event.getData());" in generated
        assert "return new PingEvent();" in generated

    def test_vec_data_is_exact_in_size(self):
        generated = _generate(
            [
                event(
                    b"pair",
                    [b"pair"],
                    [(b"a", u32(), DATA), (b"b", u32(), DATA)],
                    VEC_FORMAT,
                )
            ]
        )
        assert "if (data.size() != 2) {" in generated
        assert (
            "return new PairEvent(Scv.fromUint32(data.get(0)), Scv.fromUint32(data.get(1)));"
            in generated
        )

    def test_map_data_requires_every_non_optional_entry(self):
        generated = _generate(
            [
                event(
                    b"mapped",
                    [b"mapped"],
                    [(b"required", u32(), DATA), (b"optional", option(u32()), DATA)],
                    MAP_FORMAT,
                )
            ]
        )
        assert 'if (!data.containsKey("required")) {' in generated
        assert 'containsKey("optional")) {' not in generated
        assert (
            'data.containsKey("optional") ? Codec.decodeOption(data.get("optional"), some -> Scv.fromUint32(some)) : null'
            in generated
        )
        assert "Codec.eventDataMap(" in generated

    def test_a_single_value_event_with_two_data_parameters_is_rejected(self):
        with pytest.raises(ValueError):
            _generate(
                [
                    event(
                        b"bad",
                        [b"bad"],
                        [(b"a", u32(), DATA), (b"b", u32(), DATA)],
                        SINGLE,
                    )
                ]
            )

    def test_dispatch_order_is_most_specific_first(self):
        generated = _generate(
            [
                event(b"short", [b"act"], []),
                event(
                    b"generic",
                    [b"x"],
                    [(b"any", scalar(xdr.SCSpecType.SC_SPEC_TYPE_VAL), TOPIC)],
                ),
                event(b"long", [b"act"], [(b"who", u32(), TOPIC)]),
                event(b"specific", [b"x", b"y"], []),
            ]
        )
        dispatcher = _section(
            generated, "public static Optional<Event> parseEvent(DecodedEvent event) {"
        )
        # Two static topics beat one static topic plus a parameter; at equal
        # shape, spec order is kept; a single topic comes last.
        order = ("SpecificEvent", "GenericEvent", "LongEvent", "ShortEvent")
        positions = [dispatcher.index(f"{name}.matches") for name in order]
        assert positions == sorted(positions)
        assert "} else if (" not in dispatcher
        assert dispatcher.count("catch (RuntimeException e)") == 4

    def test_no_event_scaffolding_without_events(self):
        generated = _generate([function(b"f", [], [])])
        for name in (
            "parseEvent",
            "DecodedEvent",
            "UnparsedEventException",
            "interface Event",
        ):
            assert name not in generated

    def test_topic_parameters_named_after_builder_members_still_work(self):
        generated = _generate(
            [
                event(
                    b"e",
                    [b"e"],
                    [
                        (b"row", u32(), TOPIC),
                        (b"build", u32(), TOPIC),
                        (b"foo_set", u32(), TOPIC),
                        (b"foo", u32(), TOPIC),
                    ],
                )
            ]
        )
        builder = _section(generated, "public static final class TopicFilterBuilder {")
        assert "public TopicFilterBuilder build(long build)" in builder
        assert "public TopicFilterBuilder row(long row)" in builder
        assert "public List<String> build() {" in builder
        assert 'this.topicValues.put("row", Scv.toUint32(row));' in builder
        assert 'row.add(Codec.topicOrWildcard(this.topicValues, "row"));' in builder

    def test_parameters_that_are_keywords_or_empty(self):
        generated = _generate(
            [
                event(
                    b"e",
                    [b"e"],
                    [
                        (b"class", u32(), TOPIC),
                        (b"", u32(), DATA),
                        (b"_", u32(), TOPIC),
                    ],
                )
            ]
        )
        section = _section(generated, "public static class EEvent implements Event {")
        assert "long class_;" in section
        assert "long unnamed;" in section
        assert "long unnamed2;" in section

    def test_every_event_answers_its_name(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            [event(b"e", [b"e"], [(b"event_name", u32(), DATA)])], package="org.example"
        )
        assert "String getEventName();" in generated
        assert (
            "public String getEventName() {\n            return EVENT_NAME;"
            in generated
        )
        assert "long eventName2;" in generated
        assert "parameter EEvent.'event_name' is generated as eventName2" in diagnostics


class TestRealSpecs:
    def test_stellar_asset_contract(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            get_token_sc_spec_entry(), package="org.example"
        )
        assert diagnostics == []
        assert (
            "public AssembledTransaction<BigInteger> balance(Address id) {" in generated
        )
        assert "public static class TransferEvent implements Event {" in generated
        assert (
            "public static class TransferWithMuxedStringEvent implements Event {"
            in generated
        )

    def test_the_test_contract(self):
        generated, diagnostics = generate_binding_with_diagnostics(
            python_contract_specs(), package="org.example"
        )
        assert diagnostics == ["type 'import' is generated as import_"]
        assert "public abstract static class ComplexEnum {" in generated
        assert (
            "public AssembledTransaction<Long> u32FailOnEven(long u32) {" in generated
        )
        assert (
            "public static Optional<Error> fromSimulationError(SimulationFailedException failure)"
            in generated
        )
        assert " * This is from the rust doc above the struct SimpleStruct" in generated
        assert "/** Please provide an odd number */" in generated

    def test_the_model_is_exposed(self):
        model = build_model(python_contract_specs(), "org.example")
        assert model.udt_names["SimpleStruct"] == "SimpleStruct"
        assert model.tuples == {2: "Tuple2"}
        assert {f.name for f in model.functions if f.wire == "void"} == {"void_"}


class TestValidation:
    def test_generate_binding_rejects_invalid_names(self):
        with pytest.raises(ValueError):
            generate_binding([], package="com.class")
        with pytest.raises(ValueError):
            generate_binding([], package="org.example", class_name="a b")
        # A lowercase name could be hidden by a variable of the same name.
        with pytest.raises(ValueError):
            generate_binding([], package="org.example", class_name="client")
        generate_binding([], package="org.example", class_name="Token")


class TestCli:
    def test_writes_a_file_named_after_the_class(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            java,
            "get_specs_by_contract_id",
            lambda contract_id, rpc_url: python_contract_specs(),
        )
        runner = CliRunner()
        contract = "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF"
        outcome = runner.invoke(
            java.command,
            [
                "--contract-id",
                contract,
                "--output",
                str(tmp_path),
                "--package",
                "com.acme",
                "--class-name",
                "Token",
            ],
        )
        assert outcome.exit_code == 0, outcome.output
        written = (tmp_path / "Token.java").read_text()
        assert "package com.acme;" in written
        assert "public class Token extends ContractClient {" in written
        assert "Note: type 'import' is generated as import_" in outcome.output

    def test_reports_a_spec_it_cannot_generate(self, tmp_path, monkeypatch):
        """A Result with an error arm the decoder cannot recognise is refused."""
        monkeypatch.setattr(
            java,
            "get_specs_by_contract_id",
            lambda contract_id, rpc_url: [struct(b"S", [(b"r", result(u32(), u32()))])],
        )
        outcome = CliRunner().invoke(
            java.command,
            [
                "--contract-id",
                "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF",
                "--output",
                str(tmp_path),
            ],
        )
        assert outcome.exit_code != 0
        assert "Cannot generate bindings for this contract" in outcome.output
        assert "Traceback" not in outcome.output
        assert not (tmp_path / "Client.java").exists()

    @pytest.mark.parametrize(
        "option, value",
        [
            ("--package", "com.class"),
            ("--package", "a..b"),
            ("--class-name", "a.b"),
            ("--class-name", "client"),
            ("--class-name", "9x"),
            ("--class-name", "enum"),
        ],
    )
    def test_rejects_invalid_java_names(self, tmp_path, monkeypatch, option, value):
        monkeypatch.setattr(
            java, "get_specs_by_contract_id", lambda contract_id, rpc_url: []
        )
        outcome = CliRunner().invoke(
            java.command,
            [
                "--contract-id",
                "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF",
                "--output",
                str(tmp_path),
                option,
                value,
            ],
        )
        assert outcome.exit_code != 0
