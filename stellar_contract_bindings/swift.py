import os
from typing import List

import click
from jinja2 import Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id


def is_swift_keyword(word: str) -> bool:
    """Check if a word is a Swift reserved keyword."""
    return word in [
        "associatedtype", "class", "deinit", "enum", "extension", "fileprivate",
        "func", "import", "init", "inout", "internal", "let", "open", "operator",
        "private", "protocol", "public", "static", "struct", "subscript", "typealias",
        "var", "break", "case", "continue", "default", "defer", "do", "else",
        "fallthrough", "for", "guard", "if", "in", "repeat", "return", "switch",
        "where", "while", "as", "Any", "catch", "false", "is", "nil", "rethrows",
        "super", "self", "Self", "throw", "throws", "true", "try", "#available",
        "#colorLiteral", "#column", "#else", "#elseif", "#endif", "#file",
        "#fileLiteral", "#function", "#if", "#imageLiteral", "#line", "#selector",
        "#sourceLocation", "associativity", "convenience", "dynamic", "didSet",
        "final", "get", "infix", "indirect", "lazy", "left", "mutating", "none",
        "nonmutating", "optional", "override", "postfix", "precedence", "prefix",
        "Protocol", "required", "right", "set", "Type", "unowned", "weak", "willSet",
        "actor", "async", "await", "nonisolated", "isolated", "some"
    ]


def is_tuple_struct(entry: xdr.SCSpecUDTStructV0) -> bool:
    """Check if a struct is a tuple struct (fields are numeric)."""
    return all(f.name.isdigit() for f in entry.fields)


def snake_to_pascal(text: str) -> str:
    """Convert snake_case to PascalCase."""
    parts = text.split("_")
    return "".join(part.capitalize() for part in parts)


def snake_to_camel(text: str) -> str:
    """Convert snake_case to camelCase."""
    parts = text.split("_")
    return parts[0].lower() + "".join(part.capitalize() for part in parts[1:])


def camel_to_snake(text: str) -> str:
    """Convert CamelCase to snake_case."""
    result = text[0].lower()
    for char in text[1:]:
        if char.isupper():
            result += "_" + char.lower()
        else:
            result += char
    return result


def escape_keyword(name: str) -> str:
    """Escape Swift keywords by wrapping in backticks."""
    if is_swift_keyword(name):
        return f"`{name}`"
    return name


def prefixed_type_name(type_name: str, class_name: str) -> str:
    """Prefix a type name with the class name to avoid conflicts.
    
    Args:
        type_name: The original type name from the contract spec
        class_name: The class name to use as prefix
    
    Returns:
        The prefixed type name (e.g., "DataKey" -> "HelloContractDataKey")
    """
    # Don't prefix primitive types or SDK types
    if type_name in ['String', 'Bool', 'Data', 'SCAddressXDR', 'SCValXDR', 
                     'UInt32', 'UInt64', 'Int32', 'Int64', 'UInt128', 'Int128', 'UInt256', 'Int256']:
        return type_name
    return f"{class_name}{type_name}"


def to_swift_type(td: xdr.SCSpecTypeDef, nullable: bool = False, class_name: str = "") -> str:
    """Convert Soroban type to Swift type."""
    t = td.type
    nullable_suffix = "?" if nullable else ""
    
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"SCValXDR{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"Bool{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "Void"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"UInt32{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"Int32{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"UInt64{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"Int64{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"UInt64{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"UInt64{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"String{nullable_suffix}"  # BigInt as String
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"String{nullable_suffix}"  # BigInt as String
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"String{nullable_suffix}"  # BigInt as String
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"String{nullable_suffix}"  # BigInt as String
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"Data{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"String{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"String{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"SCAddressXDR{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"SCAddressXDR{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return to_swift_type(td.option.value_type, nullable=True, class_name=class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return to_swift_type(ok_t, nullable, class_name=class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        inner_type = to_swift_type(td.vec.element_type, class_name=class_name)
        return f"[{inner_type}]{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_type = to_swift_type(td.map.key_type, class_name=class_name)
        val_type = to_swift_type(td.map.value_type, class_name=class_name)
        return f"[{key_type}: {val_type}]{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "Void"
        types = [to_swift_type(t, class_name=class_name) for t in td.tuple.value_types]
        return f"({', '.join(types)}){nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"Data{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        udt_name = td.udt.name.decode()
        return f"{prefixed_type_name(udt_name, class_name)}{nullable_suffix}"
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "") -> str:
    """Generate Swift code to convert a value to SCValXDR."""
    t = td.type
    
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return name
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"SCValXDR.bool({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"SCValXDR.void"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"SCValXDR.u32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"SCValXDR.i32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"SCValXDR.u64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"SCValXDR.i64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"SCValXDR.timepoint({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"SCValXDR.duration({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        # Use SDK's built-in string to u128 conversion
        return f"try SCValXDR.u128(stringValue: {name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        # Use SDK's built-in string to i128 conversion
        return f"try SCValXDR.i128(stringValue: {name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        # Use SDK's built-in string to u256 conversion
        return f"try SCValXDR.u256(stringValue: {name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        # Use SDK's built-in string to i256 conversion
        return f"try SCValXDR.i256(stringValue: {name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"SCValXDR.bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"SCValXDR.string({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"SCValXDR.symbol({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"SCValXDR.address({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"SCValXDR.address({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        inner = to_scval(td.option.value_type, f"{name}!", class_name)
        return f"({name} != nil ? {inner} : SCValXDR.void)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return NotImplementedError("SC_SPEC_TYPE_RESULT is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        element_conversion = to_scval(td.vec.element_type, "$0", class_name)
        return f"SCValXDR.vec(try {name}.map {{ {element_conversion} }})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_conv = to_scval(td.map.key_type, "$0.key", class_name)
        val_conv = to_scval(td.map.value_type, "$0.value", class_name)
        return f"SCValXDR.map(try {name}.map {{ SCMapEntryXDR(key: {key_conv}, val: {val_conv}) }})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "SCValXDR.void"
        conversions = [to_scval(td.tuple.value_types[i], f"{name}.{i}", class_name) for i in range(len(td.tuple.value_types))]
        return f"SCValXDR.vec([{', '.join(conversions)}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"SCValXDR.bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"try {name}.toSCVal()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "", throw_on_missing: bool = False) -> str:
    """Generate Swift code to convert from SCValXDR to a Swift value.
    
    Args:
        td: The type definition
        name: The variable name
        class_name: The class name for prefixing types
        throw_on_missing: If True, throw errors instead of using default values
    """
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return name
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        if throw_on_missing:
            return f"try {name}.bool ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid bool value\") }}()"
        return f"{name}.bool ?? false"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        if throw_on_missing:
            return f"try {name}.u32 ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid u32 value\") }}()"
        return f"{name}.u32 ?? 0"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        if throw_on_missing:
            return f"try {name}.i32 ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid i32 value\") }}()"
        return f"{name}.i32 ?? 0"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        if throw_on_missing:
            return f"try {name}.u64 ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid u64 value\") }}()"
        return f"{name}.u64 ?? 0"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        if throw_on_missing:
            return f"try {name}.i64 ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid i64 value\") }}()"
        return f"{name}.i64 ?? 0"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        if throw_on_missing:
            return f"try {name}.timepoint ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid timepoint value\") }}()"
        return f"{name}.timepoint ?? 0"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        if throw_on_missing:
            return f"try {name}.duration ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid duration value\") }}()"
        return f"{name}.duration ?? 0"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        if throw_on_missing:
            return f"try {name}.u128String ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid u128 value\") }}()"
        return f"{name}.u128String ?? \"0\""
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        if throw_on_missing:
            return f"try {name}.i128String ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid i128 value\") }}()"
        return f"{name}.i128String ?? \"0\""
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        if throw_on_missing:
            return f"try {name}.u256String ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid u256 value\") }}()"
        return f"{name}.u256String ?? \"0\""
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        if throw_on_missing:
            return f"try {name}.i256String ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid i256 value\") }}()"
        return f"{name}.i256String ?? \"0\""
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        if throw_on_missing:
            return f"try {name}.bytes ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid bytes value\") }}()"
        return f"{name}.bytes ?? Data()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        if throw_on_missing:
            return f"try {name}.string ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid string value\") }}()"
        return f"{name}.string ?? \"\""
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        if throw_on_missing:
            return f"try {name}.symbol ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid symbol value\") }}()"
        return f"{name}.symbol ?? \"\""
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        if throw_on_missing:
            return f"try {name}.address ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid address value\") }}()"
        return f"{name}.address!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        if throw_on_missing:
            return f"try {name}.address ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid muxed address value\") }}()"
        return f"{name}.address!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        inner = from_scval(td.option.value_type, name, class_name, throw_on_missing)
        # Use conditional to check for void
        return f"(if case .void = {name} {{ nil }} else {{ {inner} }})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return from_scval(ok_t, name, class_name, throw_on_missing)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        element_conversion = from_scval(td.vec.element_type, "$0", class_name, throw_on_missing)
        # Check if element conversion needs 'try'
        if "try" in element_conversion:
            return f"try {name}.vec?.compactMap {{ {element_conversion} }} ?? []"
        else:
            return f"{name}.vec?.map {{ {element_conversion} }} ?? []"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_conv = from_scval(td.map.key_type, "$0.key", class_name, throw_on_missing)
        val_conv = from_scval(td.map.value_type, "$0.val", class_name, throw_on_missing)
        # Check if conversions need 'try'
        if "try" in key_conv or "try" in val_conv:
            return f"try Dictionary(uniqueKeysWithValues: {name}.map?.compactMap {{ ({key_conv}, {val_conv}) }} ?? [])"
        else:
            return f"Dictionary(uniqueKeysWithValues: {name}.map?.map {{ ({key_conv}, {val_conv}) }} ?? [])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "()"
        vec_name = f"{name}.vec!"
        conversions = [from_scval(td.tuple.value_types[i], f"{vec_name}[{i}]", class_name, throw_on_missing) for i in range(len(td.tuple.value_types))]
        return f"({', '.join(conversions)})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        if throw_on_missing:
            return f"try {name}.bytes ?? {{ throw {class_name}Error.conversionFailed(message: \"Missing or invalid bytes value\") }}()"
        return f"{name}.bytes ?? Data()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        # UDT conversion always needs try as fromSCVal might throw
        udt_name = td.udt.name.decode()
        return f"try {prefixed_type_name(udt_name, class_name)}.fromSCVal({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_info():
    """Generate file header comment."""
    return f"""//
// This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version}
// and stellar_sdk v{stellar_sdk_version}.
//
// @generated
//
"""


def render_imports():
    """Generate Swift import statements."""
    return """
import Foundation
import stellarsdk
"""


def render_enum(entry: xdr.SCSpecUDTEnumV0, class_name: str):
    """Generate Swift enum."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/// {{ entry.doc.decode() if entry.doc else 'Generated enum ' + type_name }}
public enum {{ type_name }}: UInt32, CaseIterable {
    {%- for case in entry.cases %}
    case {{ escape_keyword(case.name.decode()) }} = {{ case.value.uint32 }}
    {%- endfor %}
    
    public func toSCVal() throws -> SCValXDR {
        return .u32(self.rawValue)
    }
    
    /// Converts an SCVal XDR value to a {{ type_name }} enum case
    /// - Parameter val: The SCVal to convert
    /// - Returns: The corresponding {{ type_name }} case
    /// - Throws: {{ class_name }}Error.conversionFailed if the SCVal is not a u32 or the value doesn't match any case
    public static func fromSCVal(_ val: SCValXDR) throws -> {{ type_name }} {
        guard case .u32(let value) = val else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid SCVal type for {{ type_name }}")
        }
        guard let enumCase = {{ type_name }}(rawValue: value) else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid value for {{ type_name }}: \\(value)")
        }
        return enumCase
    }
}
"""
    return Template(template).render(entry=entry, type_name=type_name, escape_keyword=escape_keyword, class_name=class_name)


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0, class_name: str):
    """Generate Swift error enum."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/// {{ entry.doc.decode() if entry.doc else 'Generated error enum ' + type_name }}
public enum {{ type_name }}Error: UInt32, Error, CaseIterable {
    {%- for case in entry.cases %}
    case {{ escape_keyword(case.name.decode()) }} = {{ case.value.uint32 }}
    {%- endfor %}
    
    public func toSCVal() throws -> SCValXDR {
        return .u32(self.rawValue)
    }
    
    /// Converts an SCVal XDR value to a {{ type_name }}Error enum case
    /// - Parameter val: The SCVal to convert
    /// - Returns: The corresponding {{ type_name }}Error case
    /// - Throws: {{ class_name }}Error.conversionFailed if the SCVal is not a u32 or the value doesn't match any case
    public static func fromSCVal(_ val: SCValXDR) throws -> {{ type_name }}Error {
        guard case .u32(let value) = val else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid SCVal type for {{ type_name }}Error")
        }
        guard let errorCase = {{ type_name }}Error(rawValue: value) else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid value for {{ type_name }}Error: \\(value)")
        }
        return errorCase
    }
}
"""
    return Template(template).render(entry=entry, type_name=type_name, escape_keyword=escape_keyword, class_name=class_name)


def render_struct(entry: xdr.SCSpecUDTStructV0, class_name: str):
    """Generate Swift struct."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    
    # Create wrapper functions with class_name bound
    def to_swift_type_bound(td, nullable=False):
        return to_swift_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        # For struct fields, we want to throw on missing values to avoid force unwrapping
        return from_scval(td, name, class_name, throw_on_missing=True)
    
    template = """
/// {{ entry.doc.decode() if entry.doc else 'Generated struct ' + type_name }}
public struct {{ type_name }}: Codable {
    {%- for field in entry.fields %}
    public let {{ escape_keyword(field.name.decode()) }}: {{ to_swift_type(field.type) }}
    {%- endfor %}
    
    public init(
        {%- for field in entry.fields %}
        {{ escape_keyword(field.name.decode()) }}: {{ to_swift_type(field.type) }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    ) {
        {%- for field in entry.fields %}
        self.{{ escape_keyword(field.name.decode()) }} = {{ escape_keyword(field.name.decode()) }}
        {%- endfor %}
    }
    
    public func toSCVal() throws -> SCValXDR {
        var mapEntries: [SCMapEntryXDR] = []
        {%- for field in entry.fields %}
        mapEntries.append(SCMapEntryXDR(
            key: .symbol("{{ field.name.decode() }}"),
            val: {{ to_scval(field.type, escape_keyword(field.name.decode())) }}
        ))
        {%- endfor %}
        return .map(mapEntries)
    }
    
    /// Converts an SCVal XDR value to a {{ type_name }} struct
    /// - Parameter val: The SCVal to convert (must be a map)
    /// - Returns: A new {{ type_name }} instance
    /// - Throws: {{ class_name }}Error.conversionFailed if the SCVal is not a map or required fields are missing
    public static func fromSCVal(_ val: SCValXDR) throws -> {{ type_name }} {
        guard case .map(let mapEntries) = val else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid SCVal type for {{ type_name }}")
        }
        
        var map: [String: SCValXDR] = [:]
        for entry in mapEntries ?? [] {
            if case .symbol(let key) = entry.key {
                map[key] = entry.val
            }
        }
        
        {%- for field in entry.fields %}
        guard let field_{{ loop.index0 }}_val = map["{{ field.name.decode() }}"] else {
            throw {{ class_name }}Error.conversionFailed(message: "Missing required field '{{ field.name.decode() }}' in {{ type_name }}")
        }
        {%- endfor %}
        
        return {{ type_name }}(
            {%- for field in entry.fields %}
            {{ escape_keyword(field.name.decode()) }}: {{ from_scval(field.type, 'field_' ~ loop.index0 ~ '_val') }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        )
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        to_swift_type=to_swift_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        escape_keyword=escape_keyword,
        class_name=class_name
    )


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0, class_name: str):
    """Generate Swift tuple struct."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    
    # Create wrapper functions with class_name bound
    def to_swift_type_bound(td, nullable=False):
        return to_swift_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        return from_scval(td, name, class_name, throw_on_missing=False)
    
    template = """
/// {{ entry.doc.decode() if entry.doc else 'Generated tuple struct ' + type_name }}
public struct {{ type_name }}: Codable {
    public let value: ({% for f in entry.fields %}{{ to_swift_type(f.type) }}{% if not loop.last %}, {% endif %}{% endfor %})
    
    public init(value: ({% for f in entry.fields %}{{ to_swift_type(f.type) }}{% if not loop.last %}, {% endif %}{% endfor %})) {
        self.value = value
    }
    
    public func toSCVal() throws -> SCValXDR {
        return .vec([
            {%- for f in entry.fields %}
            {{ to_scval(f.type, 'value.' ~ f.name.decode()) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ])
    }
    
    /// Converts an SCVal XDR value to a {{ type_name }} tuple struct
    /// - Parameter val: The SCVal to convert (must be a vec)
    /// - Returns: A new {{ type_name }} instance
    /// - Throws: {{ class_name }}Error.conversionFailed if the SCVal is not a vec or has wrong number of elements
    public static func fromSCVal(_ val: SCValXDR) throws -> {{ type_name }} {
        guard case .vec(let elements) = val, let elements = elements else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid SCVal type for {{ type_name }}")
        }
        
        return {{ type_name }}(value: (
            {%- for f in entry.fields %}
            {{ from_scval(f.type, 'elements[' ~ f.name.decode() ~ ']') }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ))
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        to_swift_type=to_swift_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        class_name=class_name
    )


def render_union(entry: xdr.SCSpecUDTUnionV0, class_name: str):
    """Generate Swift enum for union."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    
    # Create wrapper functions with class_name bound
    def to_swift_type_bound(td, nullable=False):
        return to_swift_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        # For union conversions, we want to throw on missing values instead of using defaults/force unwrapping
        return from_scval(td, name, class_name, throw_on_missing=True)
    
    template = """
/// {{ entry.doc.decode() if entry.doc else 'Generated union ' + type_name }}
public enum {{ type_name }} {
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
    case {{ escape_keyword(case.void_case.name.decode()) }}
    {%- else %}
    {%- if len(case.tuple_case.type) == 1 %}
    case {{ escape_keyword(case.tuple_case.name.decode()) }}({{ to_swift_type(case.tuple_case.type[0]) }})
    {%- else %}
    case {{ escape_keyword(case.tuple_case.name.decode()) }}({% for t in case.tuple_case.type %}{{ to_swift_type(t) }}{% if not loop.last %}, {% endif %}{% endfor %})
    {%- endif %}
    {%- endif %}
    {%- endfor %}
    
    public func toSCVal() throws -> SCValXDR {
        switch self {
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        case .{{ escape_keyword(case.void_case.name.decode()) }}:
            return .vec([.symbol("{{ case.void_case.name.decode() }}")])
        {%- else %}
        {%- if len(case.tuple_case.type) == 1 %}
        case .{{ escape_keyword(case.tuple_case.name.decode()) }}(let value):
            return .vec([
                .symbol("{{ case.tuple_case.name.decode() }}"),
                {{ to_scval(case.tuple_case.type[0], 'value') }}
            ])
        {%- else %}
        case .{{ escape_keyword(case.tuple_case.name.decode()) }}({% for i in range(len(case.tuple_case.type)) %}let value{{ i }}{% if not loop.last %}, {% endif %}{% endfor %}):
            return .vec([
                .symbol("{{ case.tuple_case.name.decode() }}"),
                {%- for i, t in enumerate(case.tuple_case.type) %}
                {{ to_scval(t, 'value' ~ i|string) }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            ])
        {%- endif %}
        {%- endif %}
        {%- endfor %}
        }
    }
    
    /// Converts an SCVal XDR value to a {{ type_name }} union
    /// - Parameter val: The SCVal to convert (must be a vec with discriminant as first element)
    /// - Returns: The corresponding {{ type_name }} case
    /// - Throws: {{ class_name }}Error.conversionFailed if:
    ///   - The SCVal is not a vec
    ///   - The vec is empty or missing the discriminant
    ///   - The discriminant is not a symbol or is unknown
    ///   - The number of elements doesn't match the expected case
    public static func fromSCVal(_ val: SCValXDR) throws -> {{ type_name }} {
        guard case .vec(let vec) = val, let vec = vec, vec.count >= 1 else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid union value: expected vec with at least 1 element")
        }
        
        guard case .symbol(let kind) = vec[0] else {
            throw {{ class_name }}Error.conversionFailed(message: "Invalid union discriminant")
        }
        
        switch kind {
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        case "{{ case.void_case.name.decode() }}":
            return .{{ escape_keyword(case.void_case.name.decode()) }}
        {%- else %}
        case "{{ case.tuple_case.name.decode() }}":
            {%- if len(case.tuple_case.type) == 1 %}
            guard vec.count == 2 else {
                throw {{ class_name }}Error.conversionFailed(message: "Invalid union value for {{ case.tuple_case.name.decode() }}: expected 2 elements")
            }
            return .{{ escape_keyword(case.tuple_case.name.decode()) }}({{ from_scval(case.tuple_case.type[0], 'vec[1]') }})
            {%- else %}
            guard vec.count == {{ len(case.tuple_case.type) + 1 }} else {
                throw {{ class_name }}Error.conversionFailed(message: "Invalid union value for {{ case.tuple_case.name.decode() }}: expected {{ len(case.tuple_case.type) + 1 }} elements")
            }
            return .{{ escape_keyword(case.tuple_case.name.decode()) }}(
                {%- for i, t in enumerate(case.tuple_case.type) %}
                {{ from_scval(t, 'vec[' ~ (i + 1)|string ~ ']') }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            )
            {%- endif %}
        {%- endif %}
        {%- endfor %}
        default:
            throw {{ class_name }}Error.conversionFailed(message: "Unknown union kind: \\(kind)")
        }
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        to_swift_type=to_swift_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        xdr=xdr,
        len=len,
        class_name=class_name,
        enumerate=enumerate,
        escape_keyword=escape_keyword
    )


def render_client(entries: List[xdr.SCSpecFunctionV0], class_name: str):
    """Generate Swift client class."""
    template = '''
/// Generated contract client for {{ class_name }}
public class {{ class_name }} {
    
    /// The underlying SorobanClient instance
    private let client: SorobanClient
    
    /// Private constructor that wraps a SorobanClient
    private init(client: SorobanClient) {
        self.client = client
    }
    
    /// Creates a new {{ class_name }} for the given client options
    /// - Parameter options: Client options for the contract
    /// - Returns: A new {{ class_name }} instance
    public static func forClientOptions(options: ClientOptions) async throws -> {{ class_name }} {
        let client = try await SorobanClient.forClientOptions(options: options)
        return {{ class_name }}(client: client)
    }
    
    /// Gets the contract ID
    /// - Returns: The contract ID as a string
    public var contractId: String {
        return client.contractId
    }
    
    /// Gets the spec entries of the contract
    /// - Returns: Array of SCSpecEntryXDR
    public var specEntries: [SCSpecEntryXDR] {
        return client.specEntries
    }
    
    /// Gets the method names of the contract
    /// - Returns: Array of method names
    public var methodNames: [String] {
        return client.methodNames
    }
    {%- for entry in entries %}
    
    /// {{ entry.doc.decode() if entry.doc else 'Invoke the ' + entry.name.sc_symbol.decode() + ' method' }}
    /// {%- for param in entry.inputs %}
    /// - Parameter {{ escape_keyword(param.name.decode()) }}: {{ param.doc.decode() if param.doc else to_swift_type(param.type) }}
    {%- endfor %}
    /// - Parameter methodOptions: Options for transaction (optional)
    /// - Parameter force: Force signing and sending even if it's a read call (default: false)
    /// - Returns: {{ parse_result_type(entry.outputs) }}
    public func {{ snake_to_camel(entry.name.sc_symbol.decode()) }}(
        {%- for param in entry.inputs %}
        {{ escape_keyword(param.name.decode()) }}: {{ to_swift_type(param.type) }},
        {%- endfor %}
        methodOptions: MethodOptions? = nil,
        force: Bool = false
    ) async throws{{ return_type_hint(entry.outputs) }} {
        let args: [SCValXDR] = [
            {%- for param in entry.inputs %}
            {{ to_scval(param.type, escape_keyword(param.name.decode())) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ]
        
        let result = try await client.invokeMethod(
            name: "{{ entry.name.sc_symbol.decode() }}",
            args: args,
            force: force,
            methodOptions: methodOptions
        )
        {%- if len(entry.outputs) > 0 %}
        return {{ parse_result_conversion(entry.outputs) }}
        {%- endif %}
    }
    
    /// Build an AssembledTransaction for the {{ entry.name.sc_symbol.decode() }} method.
    /// This is useful if you need to manipulate the transaction before signing and sending.
    /// {%- for param in entry.inputs %}
    /// - Parameter {{ escape_keyword(param.name.decode()) }}: {{ param.doc.decode() if param.doc else to_swift_type(param.type) }}
    {%- endfor %}
    /// - Parameter methodOptions: Options for transaction (optional)
    /// - Returns: AssembledTransaction
    public func build{{ snake_to_pascal(entry.name.sc_symbol.decode()) }}Tx(
        {%- for param in entry.inputs %}
        {{ escape_keyword(param.name.decode()) }}: {{ to_swift_type(param.type) }},
        {%- endfor %}
        methodOptions: MethodOptions? = nil
    ) async throws -> AssembledTransaction {
        let args: [SCValXDR] = [
            {%- for param in entry.inputs %}
            {{ to_scval(param.type, escape_keyword(param.name.decode())) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ]
        
        return try await client.buildInvokeMethodTx(
            name: "{{ entry.name.sc_symbol.decode() }}",
            args: args,
            methodOptions: methodOptions
        )
    }
    {%- endfor %}
}

// MARK: - Error Types

/// Custom errors for {{ class_name }} operations
/// These errors are thrown when:
/// - Converting between Swift types and SCVal XDR types fails
/// - Type validation fails during deserialization
/// - Contract invocation fails
enum {{ class_name }}Error: Error {
    /// Thrown when converting from SCVal to Swift types fails.
    /// This typically happens when:
    /// - The SCVal type doesn't match the expected type
    /// - Required fields are missing in structs
    /// - Union discriminants are unknown
    /// - Enum values are out of range
    case conversionFailed(message: String)
    
    /// Thrown when a contract method invocation fails.
    /// This can happen when:
    /// - The contract returns an error
    /// - The transaction fails to submit
    /// - Network or RPC errors occur
    case invokeFailed(message: String)
}
'''
    
    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "Void"
        elif len(output) == 1:
            return to_swift_type(output[0], class_name=class_name)
        else:
            types = [to_swift_type(t, class_name=class_name) for t in output]
            return f"({', '.join(types)})"
    
    def return_type_hint(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return ""
        result_type = parse_result_type(output)
        return f" -> {result_type}"
    
    def parse_result_conversion(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return ""
        elif len(output) == 1:
            # Use throw_on_missing=True for method return values
            conversion = from_scval(output[0], "result", class_name, throw_on_missing=True)
            # Only wrap in try if the conversion actually needs it
            if "try" in conversion:
                return conversion
            else:
                return conversion
        else:
            # Use throw_on_missing=True for method return values
            vec_conversions = [from_scval(output[i], f"resultVec[{i}]", class_name, throw_on_missing=True) for i in range(len(output))]
            # Need to use the contract-specific error type here
            # We'll pass it through template rendering
            return f"""guard let resultVec = result.vec else {{
            throw {{{{ class_name }}}}Error.conversionFailed(message: "Expected tuple result")
        }}
        return ({', '.join(vec_conversions)})"""
    
    # Create wrapper functions with class_name bound
    def to_swift_type_bound(td, nullable=False):
        return to_swift_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        return from_scval(td, name, class_name, throw_on_missing=False)
    
    return Template(template).render(
        entries=entries,
        class_name=class_name,
        to_swift_type=to_swift_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        parse_result_type=parse_result_type,
        return_type_hint=return_type_hint,
        parse_result_conversion=parse_result_conversion,
        escape_keyword=escape_keyword,
        snake_to_camel=snake_to_camel,
        snake_to_pascal=snake_to_pascal,
        len=len
    )


def generate_binding(specs: List[xdr.SCSpecEntry], class_name: str = "ContractClient") -> str:
    """Generate complete Swift binding file."""
    generated = []
    generated.append(render_info())
    generated.append(render_imports())
    
    # Generate types
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            generated.append(render_enum(spec.udt_enum_v0, class_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            generated.append(render_error_enum(spec.udt_error_enum_v0, class_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            if is_tuple_struct(spec.udt_struct_v0):
                generated.append(render_tuple_struct(spec.udt_struct_v0, class_name))
            else:
                generated.append(render_struct(spec.udt_struct_v0, class_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            generated.append(render_union(spec.udt_union_v0, class_name))
    
    # Generate client
    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    
    if function_specs:
        generated.append(render_client(function_specs, class_name))
    
    return "\n".join(generated)


@click.command(name="swift")
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
    "--class-name",
    default="ContractClient",
    help="Name for the generated client class",
)
def command(contract_id: str, rpc_url: str, output: str, class_name: str):
    """Generate Swift bindings for a Soroban contract"""
    if not StrKey.is_valid_contract(contract_id):
        click.echo(f"Invalid contract ID: {contract_id}", err=True)
        raise click.Abort()

    # Use current directory if output is not specified
    if output is None:
        output = os.getcwd()
    
    try:
        specs = get_specs_by_contract_id(contract_id, rpc_url)
    except Exception as e:
        click.echo(f"Get contract specs failed: {e}", err=True)
        raise click.Abort()

    click.echo("Generating Swift bindings")
    generated = generate_binding(specs, class_name=class_name)
    
    # Check if output is a file or directory
    if output.endswith('.swift'):
        # It's a file path
        output_path = output
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
    else:
        # It's a directory path
        if not os.path.exists(output):
            os.makedirs(output)
        output_path = os.path.join(output, f"{class_name}.swift")
    
    with open(output_path, "w") as f:
        f.write(generated)
    
    click.echo(f"Generated Swift bindings to {output_path}")


if __name__ == "__main__":
    command()