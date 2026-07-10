import os
import re
from typing import List

import click
from jinja2 import Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id


# Minimum kmp-stellar-sdk version whose ContractClient surface the generated
# bindings depend on. The spec-free positional invoke/buildInvoke overloads and
# the forContractWithoutSpec factory are introduced in this release.
MINIMUM_SDK_VERSION = "1.9.0"

# Simple names the generated file references unqualified: SDK imports plus the Kotlin
# built-in types the templates emit. A client class with one of these names would
# shadow the referenced type inside its own file and the output would not compile,
# so generation fails instead. Keep this set in sync with render_imports and with any
# unqualified simple name a template emits.
RESERVED_CLASS_NAMES = frozenset(
    {
        # SDK imports
        "Address",
        "AssembledTransaction",
        "BigInteger",
        "ContractClient",
        "KeyPair",
        "Network",
        "Scv",
        "SCValXdr",
        "SCValTypeXdr",
        "XdrWriter",
        # Kotlin built-ins emitted by the templates
        "Boolean",
        "ByteArray",
        "Comparator",
        "Int",
        "LinkedHashMap",
        "List",
        "Long",
        "Map",
        "Pair",
        "String",
        "Triple",
        "UInt",
        "ULong",
        "Unit",
    }
)


def is_kotlin_keyword(word: str) -> bool:
    """Check if a word is a Kotlin reserved word that cannot be used as a bare identifier.

    Covers the hard keywords plus the soft keywords that are unsafe as declaration or
    reference identifiers in the positions the generator emits. Backticks are the Kotlin
    idiom for escaping any of these.
    """
    return word in [
        # Hard keywords
        "as", "break", "class", "continue", "do", "else", "false", "for", "fun",
        "if", "in", "interface", "is", "null", "object", "package", "return",
        "super", "this", "throw", "true", "try", "typealias", "typeof", "val",
        "var", "when", "while",
        # Soft keywords that break as identifiers in the emitted positions
        "by", "catch", "constructor", "delegate", "dynamic", "field", "file",
        "finally", "get", "import", "init", "param", "property", "receiver",
        "set", "setparam", "value", "where",
        # Not a keyword, but Kotlin's implicit lambda parameter: a contract
        # identifier named `it` is escaped so its declarations read unambiguously
        # in the lambda-heavy generated code.
        "it",
    ]


def is_tuple_struct(entry: xdr.SCSpecUDTStructV0) -> bool:
    """Check if a struct is a tuple struct (all field names are numeric)."""
    return all(f.name.isdigit() for f in entry.fields)


def snake_to_pascal(text: str) -> str:
    """Convert snake_case to PascalCase."""
    parts = text.split("_")
    return "".join(part.capitalize() for part in parts)


def snake_to_camel(text: str) -> str:
    """Convert snake_case to camelCase."""
    parts = text.split("_")
    return parts[0].lower() + "".join(part.capitalize() for part in parts[1:])


def escape_keyword(name: str) -> str:
    """Escape Kotlin reserved words by wrapping them in backticks."""
    if is_kotlin_keyword(name):
        return f"`{name}`"
    return name


def prefixed_type_name(type_name: str, class_name: str) -> str:
    """Prefix a UDT type name with the class name to avoid collisions.

    Error enums use the same plain prefixed name as every other UDT, so a reference to an
    error enum resolves naturally without any extra suffix or name threading.
    """
    return escape_keyword(f"{class_name}{type_name}")


def to_kotlin_type(td: xdr.SCSpecTypeDef, class_name: str = "") -> str:
    """Convert a Soroban type to the corresponding Kotlin type."""
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return "SCValXdr"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return "Boolean"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "Unit"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return "UInt"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return "Int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return "ULong"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return "Long"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return "ULong"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return "ULong"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return "ByteArray"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return "String"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return "String"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return "Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return "Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{to_kotlin_type(td.option.value_type, class_name)}?"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return to_kotlin_type(td.result.ok_type, class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List<{to_kotlin_type(td.vec.element_type, class_name)}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_type = to_kotlin_type(td.map.key_type, class_name)
        val_type = to_kotlin_type(td.map.value_type, class_name)
        return f"Map<{key_type}, {val_type}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        types = [to_kotlin_type(vt, class_name) for vt in td.tuple.value_types]
        if len(types) == 0:
            return "Unit"
        if len(types) == 2:
            return f"Pair<{types[0]}, {types[1]}>"
        if len(types) == 3:
            return f"Triple<{types[0]}, {types[1]}, {types[2]}>"
        raise NotImplementedError(
            f"Only 2- and 3-element tuples are supported (Kotlin provides Pair and "
            f"Triple); got a {len(types)}-element tuple"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return "ByteArray"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return prefixed_type_name(td.udt.name.decode(), class_name)
    raise ValueError(f"Unsupported SCValType: {t}")


_MAP_KEY_NUMERIC_TYPES = (
    xdr.SCSpecType.SC_SPEC_TYPE_U32,
    xdr.SCSpecType.SC_SPEC_TYPE_I32,
    xdr.SCSpecType.SC_SPEC_TYPE_U64,
    xdr.SCSpecType.SC_SPEC_TYPE_I64,
    xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT,
    xdr.SCSpecType.SC_SPEC_TYPE_DURATION,
    xdr.SCSpecType.SC_SPEC_TYPE_U128,
    xdr.SCSpecType.SC_SPEC_TYPE_I128,
    xdr.SCSpecType.SC_SPEC_TYPE_U256,
    xdr.SCSpecType.SC_SPEC_TYPE_I256,
    xdr.SCSpecType.SC_SPEC_TYPE_BOOL,
)
_MAP_KEY_STRING_TYPES = (
    xdr.SCSpecType.SC_SPEC_TYPE_STRING,
    xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL,
)
_MAP_KEY_BYTES_TYPES = (
    xdr.SCSpecType.SC_SPEC_TYPE_BYTES,
    xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N,
)
_MAP_KEY_ADDRESS_TYPES = (
    xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS,
    xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS,
)


def map_key_sort_comparator(key_td: xdr.SCSpecTypeDef) -> str:
    """Return a Kotlin comparator that sorts map entries ascending by key.

    Soroban's host rejects an ScMap whose entries are not sorted ascending by key in the
    host's ScVal ordering, so the generated encode must sort before building the map. The
    key type is statically known, so a type-appropriate comparison is emitted:
    numbers/bool by natural order, strings/symbols/bytes/addresses by unsigned byte order.
    """
    kt = key_td.type
    if kt in _MAP_KEY_NUMERIC_TYPES:
        return "compareBy { it.key }"
    if kt in _MAP_KEY_STRING_TYPES:
        return (
            "Comparator { a, b -> "
            "compareUnsignedByteArrays(a.key.encodeToByteArray(), b.key.encodeToByteArray()) }"
        )
    if kt in _MAP_KEY_BYTES_TYPES:
        return "Comparator { a, b -> compareUnsignedByteArrays(a.key, b.key) }"
    if kt in _MAP_KEY_ADDRESS_TYPES:
        return (
            "Comparator { a, b -> "
            "compareUnsignedByteArrays(scAddressXdrBytes(a.key), scAddressXdrBytes(b.key)) }"
        )
    raise NotImplementedError(f"Map key type {kt} is not supported for sorting")


def to_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "", depth: int = 0) -> str:
    """Generate Kotlin code that converts a native value to an SCValXdr.

    ``depth`` numbers the lambda parameters emitted for nested container conversions
    (v/e/k/o + depth, e.g. v0, k1); explicit per-depth names are used because nested
    lambdas cannot each use Kotlin's implicit ``it``. Depth is incremented exactly when
    the emitted expression opens a new lambda scope, so tuple accessors (plain property
    reads) pass it through unchanged.
    """
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return name
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"Scv.toBoolean({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "Scv.toVoid()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"Scv.toUint32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"Scv.toInt32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"Scv.toUint64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"Scv.toInt64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"Scv.toTimePoint({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"Scv.toDuration({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"Scv.toUint128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"Scv.toInt128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"Scv.toUint256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"Scv.toInt256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"Scv.toBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"Scv.toString({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"Scv.toSymbol({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"{name}.toSCVal()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"{name}.toSCVal()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        # The else branch relies on Kotlin smart-casting the subject to non-null, which
        # is only permitted for stable values (locals, parameters, same-class vals). A
        # dotted subject is a cross-module property access (a Pair/Triple tuple
        # accessor), so it is bound to a local first.
        if "." in name:
            opt_var = f"o{depth}"
            inner = to_scval(td.option.value_type, opt_var, class_name, depth + 1)
            return (
                f"{name}.let {{ {opt_var} -> "
                f"if ({opt_var} == null) Scv.toVoid() else {inner} }}"
            )
        inner = to_scval(td.option.value_type, name, class_name, depth)
        return f"if ({name} == null) Scv.toVoid() else {inner}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        raise NotImplementedError("SC_SPEC_TYPE_RESULT is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        elem_var = f"v{depth}"
        inner = to_scval(td.vec.element_type, elem_var, class_name, depth + 1)
        return f"Scv.toVec({name}.map {{ {elem_var} -> {inner} }})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_var = f"k{depth}"
        val_var = f"v{depth}"
        key_conv = to_scval(td.map.key_type, key_var, class_name, depth + 1)
        val_conv = to_scval(td.map.value_type, val_var, class_name, depth + 1)
        comparator = map_key_sort_comparator(td.map.key_type)
        # Soroban rejects an unsorted ScMap, so the entries are sorted ascending by key
        # before the LinkedHashMap preserves that order for Scv.toMap.
        return (
            f"Scv.toMap(LinkedHashMap<SCValXdr, SCValXdr>().apply {{ "
            f"{name}.entries.sortedWith({comparator}).forEach {{ ({key_var}, {val_var}) -> "
            f"put({key_conv}, {val_conv}) }} }})"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        value_types = td.tuple.value_types
        if len(value_types) == 0:
            return "Scv.toVoid()"
        accessors = ["first", "second", "third"]
        if len(value_types) not in (2, 3):
            raise NotImplementedError(
                f"Only 2- and 3-element tuples are supported (Kotlin provides Pair and "
                f"Triple); got a {len(value_types)}-element tuple"
            )
        conversions = [
            to_scval(value_types[i], f"{name}.{accessors[i]}", class_name, depth)
            for i in range(len(value_types))
        ]
        return f"Scv.toVec(listOf({', '.join(conversions)}))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"Scv.toBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.toSCVal()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "", depth: int = 0) -> str:
    """Generate Kotlin code that converts an SCValXdr to a native value.

    ``depth`` numbers the lambda parameters emitted for nested container conversions
    (v/e/k/t + depth, e.g. e0, t1); explicit per-depth names are used because nested
    lambdas cannot each use Kotlin's implicit ``it``. Depth is incremented exactly when
    the emitted expression opens a new lambda scope, which includes the tuple branch
    (it binds the decoded element list via ``.let``).
    """
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return name
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"Scv.fromBoolean({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "Unit"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"Scv.fromUint32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"Scv.fromInt32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"Scv.fromUint64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"Scv.fromInt64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"Scv.fromTimePoint({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"Scv.fromDuration({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"Scv.fromUint128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"Scv.fromInt128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"Scv.fromUint256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"Scv.fromInt256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"Scv.fromBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"Scv.fromString({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"Scv.fromSymbol({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"Address.fromSCVal({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"Address.fromSCVal({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        # An absent option is encoded as SCV_VOID, so a void discriminant decodes to null.
        inner = from_scval(td.option.value_type, name, class_name, depth)
        return f"if ({name}.discriminant == SCValTypeXdr.SCV_VOID) null else {inner}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return from_scval(td.result.ok_type, name, class_name, depth)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        elem_var = f"e{depth}"
        inner = from_scval(td.vec.element_type, elem_var, class_name, depth + 1)
        return f"Scv.fromVec({name}).map {{ {elem_var} -> {inner} }}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_var = f"k{depth}"
        val_var = f"v{depth}"
        key_conv = from_scval(td.map.key_type, key_var, class_name, depth + 1)
        val_conv = from_scval(td.map.value_type, val_var, class_name, depth + 1)
        # An if-else key conversion (an option-typed key) must be parenthesized:
        # otherwise the else branch would swallow the infix `to`.
        if key_conv.startswith("if "):
            key_conv = f"({key_conv})"
        return (
            f"Scv.fromMap({name}).entries.associate {{ ({key_var}, {val_var}) -> "
            f"{key_conv} to {val_conv} }}"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        value_types = td.tuple.value_types
        if len(value_types) == 0:
            return "Unit"
        if len(value_types) not in (2, 3):
            raise NotImplementedError(
                f"Only 2- and 3-element tuples are supported (Kotlin provides Pair and "
                f"Triple); got a {len(value_types)}-element tuple"
            )
        tuple_ctor = "Pair" if len(value_types) == 2 else "Triple"
        tuple_var = f"t{depth}"
        conversions = [
            from_scval(value_types[i], f"{tuple_var}[{i}]", class_name, depth + 1)
            for i in range(len(value_types))
        ]
        return f"Scv.fromVec({name}).let {{ {tuple_var} -> {tuple_ctor}({', '.join(conversions)}) }}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"Scv.fromBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{prefixed_type_name(td.udt.name.decode(), class_name)}.fromSCVal({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def _scan_type(
    td: xdr.SCSpecTypeDef,
    flags: dict,
    decode_reachable: bool = True,
    encode_reachable: bool = True,
):
    """Recursively record which conditional imports and helpers a type requires.

    ``decode_reachable`` is True when the type occurs in a position the generated code
    decodes (function outputs, plus struct fields and union case types, which decode in
    fromSCVal); ``encode_reachable`` is True when the generated code encodes it (function
    inputs, plus struct fields and union case types, which encode in toSCVal). The
    SCValTypeXdr import is emitted only for a decode-reachable Option, since Option
    decoding is its sole use. The map key comparator helpers are emitted only for an
    encode-reachable map, since only encoding sorts entries; decoding never references
    them.

    UDT references are deliberately not followed: every UDT's own spec entry is scanned
    with both flags set in collect_import_flags, which also keeps reference cycles from
    recursing.
    """
    t = td.type
    if t in (
        xdr.SCSpecType.SC_SPEC_TYPE_U128,
        xdr.SCSpecType.SC_SPEC_TYPE_I128,
        xdr.SCSpecType.SC_SPEC_TYPE_U256,
        xdr.SCSpecType.SC_SPEC_TYPE_I256,
    ):
        flags["bigint"] = True
    elif t in (
        xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS,
        xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS,
    ):
        flags["address"] = True
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        if decode_reachable:
            flags["option"] = True
        _scan_type(td.option.value_type, flags, decode_reachable, encode_reachable)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        _scan_type(td.result.ok_type, flags, decode_reachable, encode_reachable)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        _scan_type(td.vec.element_type, flags, decode_reachable, encode_reachable)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        if encode_reachable:
            kt = td.map.key_type.type
            if kt in _MAP_KEY_STRING_TYPES or kt in _MAP_KEY_BYTES_TYPES:
                flags["map_byte_cmp"] = True
            elif kt in _MAP_KEY_ADDRESS_TYPES:
                flags["map_byte_cmp"] = True
                flags["map_address_cmp"] = True
        _scan_type(td.map.key_type, flags, decode_reachable, encode_reachable)
        _scan_type(td.map.value_type, flags, decode_reachable, encode_reachable)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        for vt in td.tuple.value_types:
            _scan_type(vt, flags, decode_reachable, encode_reachable)


def collect_import_flags(specs: List[xdr.SCSpecEntry]) -> dict:
    """Determine which conditional imports the generated binding needs."""
    flags = {
        "address": False,
        "bigint": False,
        "option": False,
        "map_byte_cmp": False,
        "map_address_cmp": False,
    }
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            for param in spec.function_v0.inputs:
                _scan_type(param.type, flags, decode_reachable=False, encode_reachable=True)
            for output in spec.function_v0.outputs:
                _scan_type(output, flags, decode_reachable=True, encode_reachable=False)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            for field in spec.udt_struct_v0.fields:
                _scan_type(field.type, flags, decode_reachable=True, encode_reachable=True)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            for case in spec.udt_union_v0.cases:
                if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0:
                    for ty in case.tuple_case.type:
                        _scan_type(ty, flags, decode_reachable=True, encode_reachable=True)
    return flags


def render_info(flags: dict) -> str:
    """Generate the file header comment."""
    lines = [
        "//",
        f"// This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version}",
        f"// and stellar_sdk v{stellar_sdk_version}.",
        "//",
        f"// This code requires kmp-stellar-sdk (Soneso) v{MINIMUM_SDK_VERSION} or later.",
    ]
    if flags["bigint"]:
        lines += [
            "//",
            "// The BigInteger-typed 128/256-bit integer parameters and return values use",
            "// com.ionspin.kotlin:bignum, which the SDK re-exports through its public API.",
        ]
    lines += [
        "//",
        "// @generated",
        "//",
    ]
    return "\n".join(lines) + "\n"


def render_imports(flags: dict) -> str:
    """Generate the Kotlin import statements needed by the binding."""
    imports = ["import com.soneso.stellar.sdk.KeyPair", "import com.soneso.stellar.sdk.Network"]
    if flags["address"]:
        imports.append("import com.soneso.stellar.sdk.Address")
    imports += [
        "import com.soneso.stellar.sdk.contract.AssembledTransaction",
        "import com.soneso.stellar.sdk.contract.ContractClient",
        "import com.soneso.stellar.sdk.scval.Scv",
        "import com.soneso.stellar.sdk.xdr.SCValXdr",
    ]
    if flags["option"]:
        imports.append("import com.soneso.stellar.sdk.xdr.SCValTypeXdr")
    if flags.get("map_address_cmp"):
        imports.append("import com.soneso.stellar.sdk.xdr.XdrWriter")
    if flags["bigint"]:
        imports.append("import com.ionspin.kotlin.bignum.integer.BigInteger")
    return "\n".join(imports) + "\n"


def render_helpers(flags: dict) -> str:
    """Generate file-private helpers used by map-key sorting, when needed.

    Byte-oriented map keys require an unsigned lexicographic byte comparison to match the
    host's ScVal ordering; address keys are compared by their SCAddress XDR bytes.
    """
    parts = []
    if flags.get("map_byte_cmp"):
        parts.append(
            "/**\n"
            " * Compare two byte arrays lexicographically as sequences of unsigned bytes.\n"
            " *\n"
            " * Soroban requires ScMap entries sorted ascending by key in the host's ScVal\n"
            " * ordering; for byte-oriented keys that ordering is an unsigned byte compare.\n"
            " */\n"
            "private fun compareUnsignedByteArrays(a: ByteArray, b: ByteArray): Int {\n"
            "    val minLength = minOf(a.size, b.size)\n"
            "    for (i in 0 until minLength) {\n"
            "        val cmp = (a[i].toInt() and 0xFF).compareTo(b[i].toInt() and 0xFF)\n"
            "        if (cmp != 0) return cmp\n"
            "    }\n"
            "    return a.size.compareTo(b.size)\n"
            "}\n"
        )
    if flags.get("map_address_cmp"):
        parts.append(
            "/**\n"
            " * Serialize an [Address] to the XDR bytes of its SCAddress, whose unsigned byte\n"
            " * order matches the host's ScVal ordering for address-typed map keys.\n"
            " */\n"
            "private fun scAddressXdrBytes(address: Address): ByteArray {\n"
            "    val writer = XdrWriter()\n"
            "    address.toSCAddress().encode(writer)\n"
            "    return writer.toByteArray()\n"
            "}\n"
        )
    return "\n".join(parts)


def render_enum(entry: xdr.SCSpecUDTEnumV0, class_name: str) -> str:
    """Generate a Kotlin enum class for a contract enum."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
 * {{ entry.doc.decode() if entry.doc else 'Generated enum ' + type_name }}
 */
enum class {{ type_name }}(val value: UInt) {
    {%- for case in entry.cases %}
    {{ escape_keyword(case.name.decode()) }}({{ case.value.uint32 }}u){% if loop.last %};{% else %},{% endif %}
    {%- endfor %}

    fun toSCVal(): SCValXdr = Scv.toUint32(value)

    companion object {
        fun fromValue(value: UInt): {{ type_name }} =
            {{ type_name }}.entries.firstOrNull { it.value == value }
                ?: throw IllegalArgumentException("Unknown {{ type_name }} value: $value")

        fun fromSCVal(scVal: SCValXdr): {{ type_name }} = fromValue(Scv.fromUint32(scVal))
    }
}
"""
    return Template(template).render(
        entry=entry, type_name=type_name, escape_keyword=escape_keyword
    )


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0, class_name: str) -> str:
    """Generate a Kotlin enum class for a contract error enum.

    The declaration uses the plain prefixed name, matching every other UDT reference, so a
    reference to the error enum resolves without any suffix.
    """
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
 * {{ entry.doc.decode() if entry.doc else 'Generated error enum ' + type_name }}
 */
enum class {{ type_name }}(val value: UInt) {
    {%- for case in entry.cases %}
    {{ escape_keyword(case.name.decode()) }}({{ case.value.uint32 }}u){% if loop.last %};{% else %},{% endif %}
    {%- endfor %}

    fun toSCVal(): SCValXdr = Scv.toUint32(value)

    companion object {
        fun fromValue(value: UInt): {{ type_name }} =
            {{ type_name }}.entries.firstOrNull { it.value == value }
                ?: throw IllegalArgumentException("Unknown {{ type_name }} value: $value")

        fun fromSCVal(scVal: SCValXdr): {{ type_name }} = fromValue(Scv.fromUint32(scVal))
    }
}
"""
    return Template(template).render(
        entry=entry, type_name=type_name, escape_keyword=escape_keyword
    )


def render_struct(entry: xdr.SCSpecUDTStructV0, class_name: str) -> str:
    """Generate a Kotlin data class for a contract struct.

    Structs with named fields encode as an SCV_MAP with symbol keys in spec field order.
    """
    type_name = prefixed_type_name(entry.name.decode(), class_name)

    def to_kotlin_type_bound(td):
        return to_kotlin_type(td, class_name)

    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)

    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)

    # Struct fields encode as SCV_MAP entries in spec field order, which the
    # contract spec already provides sorted ascending by field name, so the map
    # entries need no explicit sort (unlike map arguments).
    template = """
/**
 * {{ entry.doc.decode() if entry.doc else 'Generated struct ' + type_name }}
 */
data class {{ type_name }}(
    {%- for field in entry.fields %}
    val {{ escape_keyword(field.name.decode()) }}: {{ to_kotlin_type(field.type) }}{% if not loop.last %},{% endif %}
    {%- endfor %}
) {
    fun toSCVal(): SCValXdr {
        val map = LinkedHashMap<SCValXdr, SCValXdr>()
        {%- for field in entry.fields %}
        map[Scv.toSymbol("{{ field.name.decode() }}")] = {{ to_scval(field.type, escape_keyword(field.name.decode())) }}
        {%- endfor %}
        return Scv.toMap(map)
    }

    companion object {
        fun fromSCVal(scVal: SCValXdr): {{ type_name }} {
            val map = Scv.fromMap(scVal)
            return {{ type_name }}(
                {%- for field in entry.fields %}
                {{ escape_keyword(field.name.decode()) }} = {{ from_scval(field.type, 'map[Scv.toSymbol("' ~ field.name.decode() ~ '")]!!') }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            )
        }
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        to_kotlin_type=to_kotlin_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        escape_keyword=escape_keyword,
    )


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0, class_name: str) -> str:
    """Generate a Kotlin data class for a tuple struct.

    Tuple structs (all field names numeric) encode as an SCV_VEC with the fields ordered
    by their numeric name, not declaration order.
    """
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    sorted_fields = sorted(entry.fields, key=lambda f: int(f.name))

    def to_kotlin_type_bound(td):
        return to_kotlin_type(td, class_name)

    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)

    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)

    template = """
/**
 * {{ entry.doc.decode() if entry.doc else 'Generated tuple struct ' + type_name }}
 */
data class {{ type_name }}(
    {%- for field in sorted_fields %}
    val value{{ field.name.decode() }}: {{ to_kotlin_type(field.type) }}{% if not loop.last %},{% endif %}
    {%- endfor %}
) {
    fun toSCVal(): SCValXdr = Scv.toVec(
        listOf(
            {%- for field in sorted_fields %}
            {{ to_scval(field.type, 'value' ~ field.name.decode()) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        )
    )

    companion object {
        fun fromSCVal(scVal: SCValXdr): {{ type_name }} {
            val elements = Scv.fromVec(scVal)
            return {{ type_name }}(
                {%- for field in sorted_fields %}
                value{{ field.name.decode() }} = {{ from_scval(field.type, 'elements[' ~ loop.index0 ~ ']') }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            )
        }
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        sorted_fields=sorted_fields,
        to_kotlin_type=to_kotlin_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
    )


def render_union(entry: xdr.SCSpecUDTUnionV0, class_name: str) -> str:
    """Generate a Kotlin sealed class for a contract union.

    Unions encode as an SCV_VEC with the case-tag symbol as the first element, followed by
    the encoded tuple values (if any).
    """
    type_name = prefixed_type_name(entry.name.decode(), class_name)

    def to_kotlin_type_bound(td):
        return to_kotlin_type(td, class_name)

    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)

    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)

    template = """
/**
 * {{ entry.doc.decode() if entry.doc else 'Generated union ' + type_name }}
 */
sealed class {{ type_name }} {
    abstract fun toSCVal(): SCValXdr
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}

    object {{ escape_keyword(case.void_case.name.decode()) }} : {{ type_name }}() {
        override fun toSCVal(): SCValXdr = Scv.toVec(listOf(Scv.toSymbol("{{ case.void_case.name.decode() }}")))
    }
    {%- else %}

    data class {{ escape_keyword(case.tuple_case.name.decode()) }}(
        {%- for i in range(len(case.tuple_case.type)) %}
        val value{{ i }}: {{ to_kotlin_type(case.tuple_case.type[i]) }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    ) : {{ type_name }}() {
        override fun toSCVal(): SCValXdr = Scv.toVec(
            listOf(
                Scv.toSymbol("{{ case.tuple_case.name.decode() }}"),
                {%- for i in range(len(case.tuple_case.type)) %}
                {{ to_scval(case.tuple_case.type[i], 'value' ~ i|string) }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            )
        )
    }
    {%- endif %}
    {%- endfor %}

    companion object {
        fun fromSCVal(scVal: SCValXdr): {{ type_name }} {
            val elements = Scv.fromVec(scVal)
            return when (val tag = Scv.fromSymbol(elements[0])) {
                {%- for case in entry.cases %}
                {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
                "{{ case.void_case.name.decode() }}" -> {{ escape_keyword(case.void_case.name.decode()) }}
                {%- else %}
                "{{ case.tuple_case.name.decode() }}" -> {{ escape_keyword(case.tuple_case.name.decode()) }}(
                    {%- for i in range(len(case.tuple_case.type)) %}
                    {{ from_scval(case.tuple_case.type[i], 'elements[' ~ (i + 1)|string ~ ']') }}{% if not loop.last %},{% endif %}
                    {%- endfor %}
                )
                {%- endif %}
                {%- endfor %}
                else -> throw IllegalArgumentException("Unknown {{ type_name }} tag: $tag")
            }
        }
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        to_kotlin_type=to_kotlin_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        escape_keyword=escape_keyword,
        xdr=xdr,
        len=len,
    )


def render_client(entries: List[xdr.SCSpecFunctionV0], class_name: str) -> str:
    """Generate the Kotlin client class wrapping ContractClient."""

    def parse_result_type(outputs: List[xdr.SCSpecTypeDef]) -> str:
        if len(outputs) == 0:
            return "Unit"
        if len(outputs) == 1:
            return to_kotlin_type(outputs[0], class_name)
        raise NotImplementedError("Tuple return type is not supported")

    def is_void(outputs: List[xdr.SCSpecTypeDef]) -> bool:
        return parse_result_type(outputs) == "Unit"

    def parse_result_fn(outputs: List[xdr.SCSpecTypeDef]) -> str:
        if is_void(outputs):
            return "{ }"
        return "{ result -> " + from_scval(outputs[0], "result", class_name) + " }"

    def encoded_params(inputs) -> str:
        return ", ".join(
            to_scval(param.type, escape_keyword(snake_to_camel(param.name.decode())), class_name)
            for param in inputs
        )

    def param_name(param) -> str:
        return escape_keyword(snake_to_camel(param.name.decode()))

    def doc_param_name(param) -> str:
        # KDoc @param tags take the plain identifier; backticks belong only at
        # declaration and reference sites.
        return snake_to_camel(param.name.decode())

    template = '''
/**
 * Generated contract client for {{ class_name }}.
 *
 * The constructor is internal so same-module tests can inject a preconfigured
 * [ContractClient]; use [forContract] to create instances.
 */
class {{ class_name }} internal constructor(val client: ContractClient) {

    companion object {
        /**
         * Create a client for a deployed contract without loading its spec from the network.
         *
         * The generated methods encode and decode all values themselves, so the on-chain
         * spec download would be a wasted round-trip.
         *
         * @param contractId The contract ID (C... address)
         * @param rpcUrl The Soroban RPC server URL
         * @param network The network the contract is deployed on
         */
        fun forContract(contractId: String, rpcUrl: String, network: Network): {{ class_name }} =
            {{ class_name }}(ContractClient.forContractWithoutSpec(contractId, rpcUrl, network))
    }
    {%- for entry in entries %}

    /**
     * {{ entry.doc.decode() if entry.doc else 'Invoke the ' + entry.name.sc_symbol.decode() + ' contract function.' }}
     {%- for param in entry.inputs %}
     * @param {{ doc_param_name(param) }} {{ param.doc.decode() if param.doc else to_kotlin_type(param.type, class_name) }}
     {%- endfor %}
     * @param source The source account (G... or M... address)
     * @param signer KeyPair for signing; null for read-only calls
     {%- if not is_void(entry.outputs) %}
     * @return {{ parse_result_type(entry.outputs) }}
     {%- endif %}
     */
    {%- if is_void(entry.outputs) %}
    suspend fun {{ escape_keyword(snake_to_camel(entry.name.sc_symbol.decode())) }}(
        {%- for param in entry.inputs %}
        {{ param_name(param) }}: {{ to_kotlin_type(param.type, class_name) }},
        {%- endfor %}
        source: String,
        signer: KeyPair?
    ) {
        client.invoke(
            functionName = "{{ entry.name.sc_symbol.decode() }}",
            parameters = listOf({{ encoded_params(entry.inputs) }}),
            source = source,
            signer = signer,
            parseResultXdrFn = { }
        )
    }
    {%- else %}
    suspend fun {{ escape_keyword(snake_to_camel(entry.name.sc_symbol.decode())) }}(
        {%- for param in entry.inputs %}
        {{ param_name(param) }}: {{ to_kotlin_type(param.type, class_name) }},
        {%- endfor %}
        source: String,
        signer: KeyPair?
    ): {{ parse_result_type(entry.outputs) }} =
        client.invoke(
            functionName = "{{ entry.name.sc_symbol.decode() }}",
            parameters = listOf({{ encoded_params(entry.inputs) }}),
            source = source,
            signer = signer,
            parseResultXdrFn = {{ parse_result_fn(entry.outputs) }}
        )
    {%- endif %}

    /**
     * Build an [AssembledTransaction] for the {{ entry.name.sc_symbol.decode() }} contract function.
     *
     * Use this when you need to inspect or manipulate the transaction (memos, additional
     * signatures, preconditions) before signing and submitting.
     {%- for param in entry.inputs %}
     * @param {{ doc_param_name(param) }} {{ param.doc.decode() if param.doc else to_kotlin_type(param.type, class_name) }}
     {%- endfor %}
     * @param source The source account (G... or M... address)
     * @param signer KeyPair for signing; null for read-only calls
     */
    suspend fun build{{ snake_to_pascal(entry.name.sc_symbol.decode()) }}Tx(
        {%- for param in entry.inputs %}
        {{ param_name(param) }}: {{ to_kotlin_type(param.type, class_name) }},
        {%- endfor %}
        source: String,
        signer: KeyPair?
    ): AssembledTransaction<{{ parse_result_type(entry.outputs) }}> =
        client.buildInvoke(
            functionName = "{{ entry.name.sc_symbol.decode() }}",
            parameters = listOf({{ encoded_params(entry.inputs) }}),
            source = source,
            signer = signer,
            parseResultXdrFn = {{ parse_result_fn(entry.outputs) }}
        )
    {%- endfor %}
}
'''
    return Template(template).render(
        entries=entries,
        class_name=class_name,
        to_kotlin_type=to_kotlin_type,
        parse_result_type=parse_result_type,
        parse_result_fn=parse_result_fn,
        is_void=is_void,
        encoded_params=encoded_params,
        param_name=param_name,
        doc_param_name=doc_param_name,
        escape_keyword=escape_keyword,
        snake_to_camel=snake_to_camel,
        snake_to_pascal=snake_to_pascal,
    )


def generate_binding(
    specs: List[xdr.SCSpecEntry], package: str, class_name: str = "Contract"
) -> str:
    """Generate a complete Kotlin binding file."""
    if class_name in RESERVED_CLASS_NAMES:
        raise ValueError(
            f"Class name {class_name} collides with a type the generated code imports "
            f"or references; choose a different --class-name"
        )
    flags = collect_import_flags(specs)

    generated = [render_info(flags)]
    generated.append(f"package {package}")
    generated.append("")
    generated.append(render_imports(flags))

    helpers = render_helpers(flags)
    if helpers:
        generated.append(helpers)

    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            generated.append(render_enum(spec.udt_enum_v0, class_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            generated.append(render_error_enum(spec.udt_error_enum_v0, class_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            if not spec.udt_struct_v0.fields:
                raise NotImplementedError(
                    f"Struct {spec.udt_struct_v0.name.decode()} has no fields; Kotlin "
                    f"data classes require at least one property"
                )
            if is_tuple_struct(spec.udt_struct_v0):
                generated.append(render_tuple_struct(spec.udt_struct_v0, class_name))
            else:
                generated.append(render_struct(spec.udt_struct_v0, class_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            generated.append(render_union(spec.udt_union_v0, class_name))

    # Double-underscore names are reserved lifecycle exports (e.g. __constructor),
    # not callable contract functions.
    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]

    if function_specs:
        generated.append(render_client(function_specs, class_name))

    code = "\n".join(generated)
    code = re.sub(r"[ \t]+$", "", code, flags=re.MULTILINE)
    return code.rstrip("\n") + "\n"


@click.command(name="kmp")
@click.option(
    "--contract-id", required=True, help="The contract ID to generate bindings for"
)
@click.option(
    "--rpc-url", default="https://mainnet.sorobanrpc.com", help="Soroban RPC URL"
)
@click.option(
    "--output",
    default=None,
    help="Output directory for generated bindings, defaults to current directory",
)
@click.option(
    "--package",
    required=True,
    help="Package name for generated bindings (e.g. com.example.bindings)",
)
@click.option(
    "--class-name",
    default="Contract",
    help="Name for the generated client class, defaults to 'Contract'",
)
def command(contract_id: str, rpc_url: str, output: str, package: str, class_name: str):
    """Generate Kotlin Multiplatform bindings for a Soroban contract"""
    if not StrKey.is_valid_contract(contract_id):
        click.echo(f"Invalid contract ID: {contract_id}", err=True)
        raise click.Abort()

    if output is None:
        output = os.getcwd()

    try:
        specs = get_specs_by_contract_id(contract_id, rpc_url)
    except Exception as e:
        click.echo(f"Get contract specs failed: {e}", err=True)
        raise click.Abort()

    click.echo("Generating Kotlin Multiplatform bindings")
    generated = generate_binding(specs, package=package, class_name=class_name)

    package_dir = os.path.join(output, *package.split("."))
    if not os.path.exists(package_dir):
        os.makedirs(package_dir)
    output_path = os.path.join(package_dir, f"{class_name}.kt")
    with open(output_path, "w") as f:
        f.write(generated)
    click.echo(f"Generated Kotlin Multiplatform bindings to {output_path}")


if __name__ == "__main__":
    command()
