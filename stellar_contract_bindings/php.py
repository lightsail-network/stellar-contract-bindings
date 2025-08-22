import os
from typing import List

import click
from jinja2 import Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id


def is_php_keyword(word: str) -> bool:
    """Check if a word is a PHP reserved keyword."""
    return word.lower() in [
        "abstract", "and", "array", "as", "break", "callable", "case", "catch",
        "class", "clone", "const", "continue", "declare", "default", "die", "do",
        "echo", "else", "elseif", "empty", "enddeclare", "endfor", "endforeach",
        "endif", "endswitch", "endwhile", "eval", "exit", "extends", "final",
        "finally", "fn", "for", "foreach", "function", "global", "goto", "if",
        "implements", "include", "include_once", "instanceof", "insteadof",
        "interface", "isset", "list", "match", "namespace", "new", "or", "print",
        "private", "protected", "public", "readonly", "require", "require_once",
        "return", "static", "switch", "throw", "trait", "try", "unset", "use",
        "var", "while", "xor", "yield", "yield_from",
        "__halt_compiler", "__class__", "__dir__", "__file__", "__function__",
        "__line__", "__method__", "__namespace__", "__trait__",
        "int", "float", "bool", "string", "true", "false", "null", "void",
        "iterable", "object", "resource", "mixed", "never"
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


def escape_keyword(name: str, context: str = "property") -> str:
    """Escape PHP keywords by appending underscore."""
    if is_php_keyword(name):
        return f"{name}_"
    return name


def prefixed_type_name(type_name: str, class_name: str) -> str:
    """Prefix a type name with the class name to avoid conflicts.
    
    Args:
        type_name: The original type name from the contract spec
        class_name: The class name to use as prefix
    
    Returns:
        The prefixed type name (e.g., "DataKey" -> "TokenContractDataKey")
    """
    # Don't prefix primitive types or SDK types
    if type_name in ['string', 'bool', 'int', 'float', 'array', 'Address', 
                     'XdrSCVal', 'XdrSCMapEntry', 'XdrSCValType']:
        return type_name
    return f"{class_name}{type_name}"


def to_php_type(td: xdr.SCSpecTypeDef, nullable: bool = False, class_name: str = "") -> str:
    """Convert Soroban type to PHP type hint."""
    t = td.type
    nullable_prefix = "?" if nullable else ""
    
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{nullable_prefix}XdrSCVal"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"{nullable_prefix}bool"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "void"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t in [xdr.SCSpecType.SC_SPEC_TYPE_U32, xdr.SCSpecType.SC_SPEC_TYPE_I32,
             xdr.SCSpecType.SC_SPEC_TYPE_U64, xdr.SCSpecType.SC_SPEC_TYPE_I64,
             xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT, xdr.SCSpecType.SC_SPEC_TYPE_DURATION]:
        return f"{nullable_prefix}int"
    if t in [xdr.SCSpecType.SC_SPEC_TYPE_U128, xdr.SCSpecType.SC_SPEC_TYPE_I128,
             xdr.SCSpecType.SC_SPEC_TYPE_U256, xdr.SCSpecType.SC_SPEC_TYPE_I256]:
        return f"{nullable_prefix}string" 
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"{nullable_prefix}string"  # PHP uses string for bytes
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"{nullable_prefix}string"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"{nullable_prefix}string"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"{nullable_prefix}Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"{nullable_prefix}Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return to_php_type(td.option.value_type, nullable=True, class_name=class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return to_php_type(ok_t, nullable, class_name=class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        inner_type = to_php_type(td.vec.element_type, class_name=class_name)
        return f"{nullable_prefix}array"  # PHP arrays
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"{nullable_prefix}array"  # PHP associative arrays
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "void"
        return f"{nullable_prefix}array"  # PHP arrays for tuples
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"{nullable_prefix}string"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        udt_name = td.udt.name.decode()
        return f"{nullable_prefix}{prefixed_type_name(udt_name, class_name)}"
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "") -> str:
    """Generate PHP code to convert a value to XdrSCVal."""
    t = td.type
    # Add $ prefix only if name doesn't already start with $ or this->
    if name.startswith('$') or name.startswith('this->'):
        var_name = name
    else:
        var_name = f"${name}"
    
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return var_name
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"XdrSCVal::forBool({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"XdrSCVal::forVoid()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"XdrSCVal::forU32({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"XdrSCVal::forI32({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"XdrSCVal::forU64({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"XdrSCVal::forI64({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"XdrSCVal::forTimepoint({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"XdrSCVal::forDuration({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"XdrSCVal::forU128BigInt({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"XdrSCVal::forI128BigInt({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"XdrSCVal::forU256BigInt({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"XdrSCVal::forI256BigInt({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"XdrSCVal::forBytes({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"XdrSCVal::forString({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"XdrSCVal::forSymbol({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"{var_name}->toXdrSCVal()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"{var_name}->toXdrSCVal()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        inner = to_scval(td.option.value_type, name, class_name)
        return f"({var_name} !== null ? {inner} : XdrSCVal::forVoid())"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return NotImplementedError("SC_SPEC_TYPE_RESULT is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        element_conversion = to_scval(td.vec.element_type, "item", class_name)
        return f"XdrSCVal::forVec(array_map(fn($item) => {element_conversion}, {var_name}))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_conv = to_scval(td.map.key_type, "k", class_name)
        val_conv = to_scval(td.map.value_type, "v", class_name)
        return f"XdrSCVal::forMap(array_map(fn($k, $v) => [{key_conv}, {val_conv}], array_keys({var_name}), {var_name}))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "XdrSCVal::forVoid()"
        conversions = [to_scval(td.tuple.value_types[i], f"{name}[{i}]", class_name) for i in range(len(td.tuple.value_types))]
        return f"XdrSCVal::forTupleStruct([{', '.join(conversions)}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"XdrSCVal::forBytes({var_name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{var_name}->toSCVal()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "") -> str:
    """Generate PHP code to convert from XdrSCVal to a PHP value."""
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"${name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"${name}->b"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"null"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"${name}->u32"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"${name}->i32"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"${name}->u64"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"${name}->i64"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"${name}->timepoint"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"${name}->duration"
    if t in [xdr.SCSpecType.SC_SPEC_TYPE_U128, xdr.SCSpecType.SC_SPEC_TYPE_I128]:
        return f"gmp_strval(${name}->toBigInt())"
    if t in [xdr.SCSpecType.SC_SPEC_TYPE_U256, xdr.SCSpecType.SC_SPEC_TYPE_I256]:
        return f"gmp_strval(${name}->toBigInt())"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"${name}->bytes->getValue()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"${name}->str"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"${name}->sym"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"Address::fromXdrSCVal(${name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"Address::fromXdrSCVal(${name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        inner = from_scval(td.option.value_type, name, class_name)
        return f"(${name}->type !== XdrSCValType::SCV_VOID ? {inner} : null)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return from_scval(ok_t, name, class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        element_conversion = from_scval(td.vec.element_type, "item", class_name)
        return f"array_map(fn($item) => {element_conversion}, ${name}->vec)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        key_conv = from_scval(td.map.key_type, "entry->key", class_name)
        val_conv = from_scval(td.map.value_type, "entry->val", class_name)
        return f"array_combine(array_map(fn($entry) => {key_conv}, ${name}->map), array_map(fn($entry) => {val_conv}, ${name}->map))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "null"
        conversions = [from_scval(td.tuple.value_types[i], f"{name}->vec[{i}]", class_name) for i in range(len(td.tuple.value_types))]
        return f"[{', '.join(conversions)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"${name}->bytes->getValue()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        udt_name = td.udt.name.decode()
        return f"{prefixed_type_name(udt_name, class_name)}::fromSCVal(${name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_info():
    """Generate file header comment."""
    return f"""<?php

/**
 * This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version}
 * and stellar_sdk v{stellar_sdk_version}.
 * 
 * @generated
 */
"""


def render_imports(namespace: str = "GeneratedContracts"):
    """Generate PHP namespace and use statements."""
    template = """
declare(strict_types=1);

namespace {{ namespace }};

use Exception;
use GuzzleHttp\\Exception\\GuzzleException;
use Soneso\\StellarSDK\\Crypto\\KeyPair;
use Soneso\\StellarSDK\\Soroban\\Address;
use Soneso\\StellarSDK\\Soroban\\Contract\\AssembledTransaction;
use Soneso\\StellarSDK\\Soroban\\Contract\\ClientOptions;
use Soneso\\StellarSDK\\Soroban\\Contract\\ContractSpec;
use Soneso\\StellarSDK\\Soroban\\Contract\\MethodOptions;
use Soneso\\StellarSDK\\Soroban\\Contract\\SorobanClient;
use Soneso\\StellarSDK\\Xdr\\XdrSCMapEntry;
use Soneso\\StellarSDK\\Xdr\\XdrSCVal;
use Soneso\\StellarSDK\\Xdr\\XdrSCValType;
"""
    return Template(template).render(namespace=namespace)


def render_enum(entry: xdr.SCSpecUDTEnumV0, class_name: str):
    """Generate PHP enum class."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
{%- if entry.doc %}
 * {{ entry.doc.decode() }}
{%- else %}
 * Generated enum {{ type_name }}
{%- endif %}
 */
enum {{ type_name }}: int
{
    {%- for case in entry.cases %}
    case {{ case.name.decode() }} = {{ case.value.uint32 }};
    {%- endfor %}

    public function toSCVal(): XdrSCVal
    {
        return XdrSCVal::forU32($this->value);
    }

    public static function fromSCVal(XdrSCVal $val): self
    {
        return self::from($val->u32);
    }
}
"""
    return Template(template).render(entry=entry, type_name=type_name)


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0, class_name: str):
    """Generate PHP error enum class."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
{%- if entry.doc %}
 * {{ entry.doc.decode() }} (Error enum)
{%- else %}
 * Generated error enum {{ type_name }}
{%- endif %}
 */
enum {{ type_name }}Error: int
{
    {%- for case in entry.cases %}
    case {{ case.name.decode() }} = {{ case.value.uint32 }};
    {%- endfor %}

    public function toSCVal(): XdrSCVal
    {
        return XdrSCVal::forU32($this->value);
    }

    public static function fromSCVal(XdrSCVal $val): self
    {
        return self::from($val->u32);
    }
}
"""
    return Template(template).render(entry=entry, type_name=type_name)


def render_struct(entry: xdr.SCSpecUDTStructV0, class_name: str):
    """Generate PHP class for struct."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
{%- if entry.doc %}
 * {{ entry.doc.decode() }}
{%- else %}
 * Generated struct {{ type_name }}
{%- endif %}
 */
class {{ type_name }}
{
    {%- for field in entry.fields %}
    public {{ to_php_type(field.type, False, class_name) }} ${{ escape_keyword(field.name.decode()) }};
    {%- endfor %}

    public function __construct(
        {%- for field in entry.fields %}
        {{ to_php_type(field.type, False, class_name) }} ${{ escape_keyword(field.name.decode()) }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    ) {
        {%- for field in entry.fields %}
        $this->{{ escape_keyword(field.name.decode()) }} = ${{ escape_keyword(field.name.decode()) }};
        {%- endfor %}
    }

    public function toSCVal(): XdrSCVal
    {
        $mapEntries = [];
        {%- for field in entry.fields %}
        $mapEntries[] = new XdrSCMapEntry(
            XdrSCVal::forSymbol('{{ field.name.decode() }}'),
            {{ to_scval(field.type, '$this->' ~ escape_keyword(field.name.decode()), class_name) }}
        );
        {%- endfor %}
        return XdrSCVal::forMap($mapEntries);
    }

    public static function fromSCVal(XdrSCVal $val): self
    {
        $map = [];
        foreach ($val->map as $entry) {
            $map[$entry->key->sym] = $entry->val;
        }
        return new self(
            {%- for field in entry.fields %}
            {{ escape_keyword(field.name.decode()) }}: {{ from_scval(field.type, 'map["' ~ field.name.decode() ~ '"]', class_name) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        );
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        class_name=class_name,
        to_php_type=to_php_type,
        to_scval=to_scval,
        from_scval=from_scval,
        escape_keyword=escape_keyword
    )


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0, class_name: str):
    """Generate PHP class for tuple struct."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
{%- if entry.doc %}
 * {{ entry.doc.decode() }}
{%- else %}
 * Generated tuple struct {{ type_name }}
{%- endif %}
 */
class {{ type_name }}
{
    public array $value;

    /**
     * @param array{%- for f in entry.fields %}{% if loop.first %}<{% endif %}{{ to_php_type(f.type, False, class_name) }}{% if not loop.last %}, {% else %}>{% endif %}{% endfor %} $value
     */
    public function __construct(array $value)
    {
        $this->value = $value;
    }

    public function toSCVal(): XdrSCVal
    {
        return XdrSCVal::forVec([
            {%- for f in entry.fields %}
            {{ to_scval(f.type, '$this->value[' ~ f.name.decode() ~ ']', class_name) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ]);
    }

    public static function fromSCVal(XdrSCVal $val): self
    {
        $elements = $val->vec;
        return new self([
            {%- for f in entry.fields %}
            {{ from_scval(f.type, 'elements[' ~ f.name.decode() ~ ']', class_name) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ]);
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        class_name=class_name,
        to_php_type=to_php_type,
        to_scval=to_scval,
        from_scval=from_scval
    )


def render_union(entry: xdr.SCSpecUDTUnionV0, class_name: str):
    """Generate PHP class for union."""
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/**
{%- if entry.doc %}
 * {{ entry.doc.decode() }}
{%- else %}
 * Generated union {{ type_name }}
{%- endif %}
 */
class {{ type_name }}
{
    public const {% for case in entry.cases -%}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 -%}
    {{ case.void_case.name.decode().upper() }} = '{{ case.void_case.name.decode() }}'
    {%- else -%}
    {{ case.tuple_case.name.decode().upper() }} = '{{ case.tuple_case.name.decode() }}'
    {%- endif -%}
    {%- if not loop.last %}, {% else %};{% endif -%}
    {%- endfor %}

    public string $kind;
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
    {%- if len(case.tuple_case.type) == 1 %}
    public {{ to_php_type(case.tuple_case.type[0], nullable=True, class_name=class_name) }} ${{ camel_to_snake(case.tuple_case.name.decode()) }} = null;
    {%- else %}
    public ?array ${{ camel_to_snake(case.tuple_case.name.decode()) }} = null;
    {%- endif %}
    {%- endif %}
    {%- endfor %}

    public function __construct(string $kind{% for case in entry.cases -%}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 -%}
    {%- if len(case.tuple_case.type) == 1 -%}
    , ?{{ to_php_type(case.tuple_case.type[0], False, class_name) }} ${{ camel_to_snake(case.tuple_case.name.decode()) }} = null
    {%- else -%}
    , ?array ${{ camel_to_snake(case.tuple_case.name.decode()) }} = null
    {%- endif -%}
    {%- endif -%}
    {%- endfor %})
    {
        $this->kind = $kind;
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
        $this->{{ camel_to_snake(case.tuple_case.name.decode()) }} = ${{ camel_to_snake(case.tuple_case.name.decode()) }};
        {%- endif %}
        {%- endfor %}
    }

    public function toSCVal(): XdrSCVal
    {
        switch ($this->kind) {
            {%- for case in entry.cases %}
            {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
            case self::{{ case.void_case.name.decode().upper() }}:
                return XdrSCVal::forVec([XdrSCVal::forSymbol($this->kind)]);
            {%- else %}
            case self::{{ case.tuple_case.name.decode().upper() }}:
                {%- if len(case.tuple_case.type) == 1 %}
                return XdrSCVal::forVec([
                    XdrSCVal::forSymbol($this->kind),
                    {{ to_scval(case.tuple_case.type[0], '$this->' ~ camel_to_snake(case.tuple_case.name.decode()), class_name) }}
                ]);
                {%- else %}
                return XdrSCVal::forVec([
                    XdrSCVal::forSymbol($this->kind),
                    {%- for i, t in enumerate(case.tuple_case.type) %}
                    {{ to_scval(t, '$this->' ~ camel_to_snake(case.tuple_case.name.decode()) ~ '[' ~ i|string ~ ']', class_name) }}{% if not loop.last %},{% endif %}
                    {%- endfor %}
                ]);
                {%- endif %}
            {%- endif %}
            {%- endfor %}
            default:
                throw new Exception("Invalid union kind: {$this->kind}");
        }
    }

    public static function fromSCVal(XdrSCVal $val): self
    {
        if ($val->vec === null || count($val->vec) < 1) {
            throw new Exception("Invalid union value: expected vec with at least 1 element");
        }
        
        $kind = $val->vec[0]->sym;
        
        switch ($kind) {
            {%- for case in entry.cases %}
            {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
            case '{{ case.void_case.name.decode() }}':
                return new self(self::{{ case.void_case.name.decode().upper() }});
            {%- else %}
            case '{{ case.tuple_case.name.decode() }}':
                {%- if len(case.tuple_case.type) == 1 %}
                if (count($val->vec) !== 2) {
                    throw new Exception("Invalid union value for {{ case.tuple_case.name.decode() }}: expected 2 elements");
                }
                return new self(
                    self::{{ case.tuple_case.name.decode().upper() }},
                    {{ camel_to_snake(case.tuple_case.name.decode()) }}: {{ from_scval(case.tuple_case.type[0], 'val->vec[1]', class_name) }}
                );
                {%- else %}
                if (count($val->vec) !== {{ len(case.tuple_case.type) + 1 }}) {
                    throw new Exception("Invalid union value for {{ case.tuple_case.name.decode() }}: expected {{ len(case.tuple_case.type) + 1 }} elements");
                }
                return new self(
                    self::{{ case.tuple_case.name.decode().upper() }},
                    {{ camel_to_snake(case.tuple_case.name.decode()) }}: [
                        {%- for i, t in enumerate(case.tuple_case.type) %}
                        {{ from_scval(t, 'val->vec[' ~ (i + 1)|string ~ ']', class_name) }}{% if not loop.last %},{% endif %}
                        {%- endfor %}
                    ]
                );
                {%- endif %}
            {%- endif %}
            {%- endfor %}
            default:
                throw new Exception("Unknown union kind: $kind");
        }
    }
}
"""
    return Template(template).render(
        entry=entry,
        type_name=type_name,
        class_name=class_name,
        to_php_type=to_php_type,
        to_scval=to_scval,
        from_scval=from_scval,
        xdr=xdr,
        len=len,
        camel_to_snake=camel_to_snake,
        enumerate=enumerate
    )


def render_client(entries: List[xdr.SCSpecFunctionV0], contract_name: str):
    """Generate PHP client class."""
    template = '''
/**
 * Generated contract client for {{ contract_name }}
 */
class {{ contract_name }}
{
    /**
     * The underlying SorobanClient instance
     * @var SorobanClient
     */
    private SorobanClient $client;

    /**
     * Private constructor that wraps a SorobanClient
     * @param SorobanClient $client
     */
    private function __construct(SorobanClient $client)
    {
        $this->client = $client;
    }

    /**
     * Creates a new {{ contract_name }} for the given contract ID
     * @param ClientOptions $options Client options for the contract
     * @return {{ contract_name }}
     * @throws Exception
     * @throws GuzzleException
     */
    public static function forClientOptions(ClientOptions $options): self
    {
        $client = SorobanClient::forClientOptions($options);
        return new self($client);
    }

    /**
     * Gets the contract ID
     * @return string
     */
    public function getContractId(): string
    {
        return $this->client->getContractId();
    }

    /**
     * Gets the client options
     * @return ClientOptions
     */
    public function getOptions(): ClientOptions
    {
        return $this->client->getOptions();
    }

    /**
     * Gets the contract specification
     * @return ContractSpec
     */
    public function getContractSpec(): ContractSpec
    {
        return $this->client->getContractSpec();
    }
    {%- for entry in entries %}

    /**
    {%- if entry.doc %}
     * {{ entry.doc.decode() }}
    {%- else %}
     * Invoke the {{ entry.name.sc_symbol.decode() }} method
    {%- endif %}
     *
    {%- for param in entry.inputs %}
     * @param {{ to_php_type(param.type, False, contract_name) }} ${{ escape_keyword(param.name.decode()) }}
    {%- endfor %}
     * @param MethodOptions|null $methodOptions Options for transaction
     * @return {{ parse_result_type(entry.outputs) }}
     * @throws Exception
     * @throws GuzzleException
     */
    public function {{ snake_to_camel(entry.name.sc_symbol.decode()) }}(
        {%- for param in entry.inputs %}
        {{ to_php_type(param.type, False, contract_name) }} ${{ escape_keyword(param.name.decode()) }},
        {%- endfor %}
        ?MethodOptions $methodOptions = null
    ){{ return_type_hint(entry.outputs) }} {
        $args = [
            {%- for param in entry.inputs %}
            {{ to_scval(param.type, escape_keyword(param.name.decode()), contract_name) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ];
        
        $result = $this->client->invokeMethod(
            name: '{{ entry.name.sc_symbol.decode() }}',
            args: $args,
            methodOptions: $methodOptions
        );
        {%- if len(entry.outputs) > 0 %}
        return {{ parse_result_conversion(entry.outputs) }};
        {%- endif %}
    }

    /**
     * Build an AssembledTransaction for the {{ entry.name.sc_symbol.decode() }} method.
     * This is useful if you need to manipulate the transaction before signing and sending.
     *
    {%- for param in entry.inputs %}
     * @param {{ to_php_type(param.type, False, contract_name) }} ${{ escape_keyword(param.name.decode()) }}
    {%- endfor %}
     * @param MethodOptions|null $methodOptions Options for transaction
     * @return AssembledTransaction
     * @throws Exception
     * @throws GuzzleException
     */
    public function build{{ snake_to_pascal(entry.name.sc_symbol.decode()) }}Tx(
        {%- for param in entry.inputs %}
        {{ to_php_type(param.type, False, contract_name) }} ${{ escape_keyword(param.name.decode()) }},
        {%- endfor %}
        ?MethodOptions $methodOptions = null
    ): AssembledTransaction {
        $args = [
            {%- for param in entry.inputs %}
            {{ to_scval(param.type, escape_keyword(param.name.decode()), contract_name) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        ];
        
        return $this->client->buildInvokeMethodTx(
            name: '{{ entry.name.sc_symbol.decode() }}',
            args: $args,
            methodOptions: $methodOptions
        );
    }
    {%- endfor %}
}
'''
    
    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "void"
        elif len(output) == 1:
            return to_php_type(output[0], False, contract_name)
        else:
            return "array"
    
    def return_type_hint(output: List[xdr.SCSpecTypeDef]):
        result_type = parse_result_type(output)
        if result_type:
            # Add colon and return type
            return f": {result_type}"
        else:
            return ""
    
    def parse_result_conversion(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return ""
        elif len(output) == 1:
            return from_scval(output[0], "result", contract_name)
        else:
            conversions = [from_scval(output[i], f"result[{i}]", contract_name) for i in range(len(output))]
            return f"[{', '.join(conversions)}]"
    
    return Template(template).render(
        entries=entries,
        contract_name=contract_name,
        to_php_type=to_php_type,
        to_scval=to_scval,
        from_scval=from_scval,
        parse_result_type=parse_result_type,
        return_type_hint=return_type_hint,
        parse_result_conversion=parse_result_conversion,
        escape_keyword=escape_keyword,
        snake_to_camel=snake_to_camel,
        snake_to_pascal=snake_to_pascal,
        len=len
    )


def generate_binding(specs: List[xdr.SCSpecEntry], namespace: str = "GeneratedContracts", contract_name: str = "Contract") -> str:
    """Generate complete PHP binding file."""
    generated = []
    generated.append(render_info())
    generated.append(render_imports(namespace))
    
    # Generate types
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            generated.append(render_enum(spec.udt_enum_v0, contract_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            generated.append(render_error_enum(spec.udt_error_enum_v0, contract_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            if is_tuple_struct(spec.udt_struct_v0):
                generated.append(render_tuple_struct(spec.udt_struct_v0, contract_name))
            else:
                generated.append(render_struct(spec.udt_struct_v0, contract_name))
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            generated.append(render_union(spec.udt_union_v0, contract_name))
    
    # Generate client
    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    
    if function_specs:
        generated.append(render_client(function_specs, contract_name))
    
    return "\n".join(generated)


@click.command(name="php")
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
    "--namespace",
    default="GeneratedContracts",
    help="PHP namespace for generated classes",
)
@click.option(
    "--class-name",
    default="ContractClient",
    help="Name for the generated client class",
)
def command(contract_id: str, rpc_url: str, output: str, namespace: str, class_name: str):
    """Generate PHP bindings for a Soroban contract"""
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

    click.echo("Generating PHP bindings")
    generated = generate_binding(specs, namespace=namespace, contract_name=class_name)
    
    if not os.path.exists(output):
        os.makedirs(output)
    
    output_path = os.path.join(output, f"{class_name}.php")
    with open(output_path, "w") as f:
        f.write(generated)
    
    click.echo(f"Generated PHP bindings to {output_path}")


if __name__ == "__main__":
    command()