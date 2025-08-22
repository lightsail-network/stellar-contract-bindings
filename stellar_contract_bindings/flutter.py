import os
from typing import List

import click
from jinja2 import Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id


def is_keywords(word: str) -> bool:
    return word in [
        "abstract",
        "as",
        "assert",
        "async",
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "covariant",
        "default",
        "deferred",
        "do",
        "dynamic",
        "else",
        "enum",
        "export",
        "extends",
        "extension",
        "external",
        "factory",
        "false",
        "final",
        "finally",
        "for",
        "Function",
        "get",
        "hide",
        "if",
        "implements",
        "import",
        "in",
        "interface",
        "is",
        "late",
        "library",
        "mixin",
        "new",
        "null",
        "on",
        "operator",
        "part",
        "rethrow",
        "required",
        "return",
        "set",
        "show",
        "static",
        "super",
        "switch",
        "sync",
        "this",
        "throw",
        "true",
        "try",
        "typedef",
        "var",
        "void",
        "while",
        "with",
        "yield",
    ]


def is_tuple_struct(entry: xdr.SCSpecUDTStructV0) -> bool:
    return all(f.name.isdigit() for f in entry.fields)


def prefixed_type_name(type_name: str, class_name: str) -> str:
    """Prefix a type name with the class name to avoid conflicts.
    
    Args:
        type_name: The original type name from the contract spec
        class_name: The class name to use as prefix
    
    Returns:
        The prefixed type name if it's a UDT, or the original if it's a built-in type
    """
    # Don't prefix built-in types
    if type_name in ['bool', 'int', 'BigInt', 'String', 'Uint8List', 'Address', 'Map', 'List', 
                     'XdrSCVal', 'void']:
        return type_name
    return f"{class_name}{type_name}"


def snake_to_camel(text: str, first_letter_lower: bool = True) -> str:
    parts = text.split("_")
    if first_letter_lower:
        return parts[0].lower() + "".join(part.capitalize() for part in parts[1:])
    else:
        return "".join(part.capitalize() for part in parts)

def camel_to_snake(text: str) -> str:
    result = text[0].lower()
    for char in text[1:]:
        if char.isupper():
            result += "_" + char.lower()
        else:
            result += char
    return result

def to_dart_type(td: xdr.SCSpecTypeDef, nullable: bool = False, class_name: str = "") -> str:
    t = td.type
    nullable_suffix = "?" if nullable else ""

    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"XdrSCVal{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"bool{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "void"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"int{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"int{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"int{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"int{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"int{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"int{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"BigInt{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"BigInt{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"BigInt{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"BigInt{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"Uint8List{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"String{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"String{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"Address{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"Address{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return to_dart_type(td.option.value_type, nullable=True, class_name=class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return to_dart_type(ok_t, nullable, class_name=class_name)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List<{to_dart_type(td.vec.element_type, class_name=class_name)}>{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Map<{to_dart_type(td.map.key_type, class_name=class_name)}, {to_dart_type(td.map.value_type, class_name=class_name)}>{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "void"
        types = [to_dart_type(t, class_name=class_name) for t in td.tuple.value_types]
        return f"({', '.join(types)}){nullable_suffix}"  # Using Dart 3 records
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"Uint8List{nullable_suffix}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        udt_name = td.udt.name.decode()
        return f"{prefixed_type_name(udt_name, class_name)}{nullable_suffix}"
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "") -> str:
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"XdrSCVal.forBool({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"XdrSCVal.forVoid()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"XdrSCVal.forU32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"XdrSCVal.forI32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"XdrSCVal.forU64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"XdrSCVal.forI64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"XdrSCVal.forTimePoint({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"XdrSCVal.forDuration({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"XdrSCVal.forU128BigInt({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"XdrSCVal.forI128BigInt({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"XdrSCVal.forU256BigInt({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"XdrSCVal.forI256BigInt({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"XdrSCVal.forBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"XdrSCVal.forString({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"XdrSCVal.forSymbol({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"{name}.toXdrSCVal()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"{name}.toXdrSCVal()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{name} == null ? XdrSCVal.forVoid() : {to_scval(td.option.value_type, name, class_name)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return NotImplementedError("SC_SPEC_TYPE_RESULT is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"XdrSCVal.forVec({name}.map((e) => {to_scval(td.vec.element_type, 'e', class_name)}).toList())"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"XdrSCVal.forMap(Map.fromEntries({name}.entries.map((e) => MapEntry({to_scval(td.map.key_type, 'e.key', class_name)}, {to_scval(td.map.value_type, 'e.value', class_name)}))))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        types = [
            to_scval(t, f"{name}.${{i+1}}", class_name) for i, t in enumerate(td.tuple.value_types)
        ]
        return f"XdrSCVal.forVec([{', '.join(types)}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"XdrSCVal.forBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.toScVal()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str, class_name: str = "") -> str:
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"{name}.b!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"null"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"{name}.u32!.uint32"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"{name}.i32!.int32"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"BigInt.from({name}.u64!.uint64)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"{name}.i64!.int64"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"BigInt.from({name}.u64!.uint64)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"BigInt.from({name}.u64!.uint64)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"{name}.toBigInt()!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"{name}.toBigInt()!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"{name}.toBigInt()!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"{name}.toBigInt()!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"{name}.bytes!.dataValue"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"{name}.str!"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"{name}.sym!.toString()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"Address.fromXdrSCVal({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"Address.fromXdrSCVal({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{name}.discriminant == XdrSCValType.SCV_VOID ? null : {from_scval(td.option.value_type, name, class_name)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return f"{from_scval(ok_t, name, class_name)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return (
            f"{name}.vec!.map((e) => {from_scval(td.vec.element_type, 'e', class_name)}).toList()"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Map.fromEntries({name}.map!.entries.map((e) => MapEntry({from_scval(td.map.key_type, 'e.key', class_name)}, {from_scval(td.map.value_type, 'e.val', class_name)})))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "null"
        elements = f"{name}.vec!"
        types = [
            from_scval(t, f"{elements}[{i}]", class_name)
            for i, t in enumerate(td.tuple.value_types)
        ]
        return f"({', '.join(types)})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"{name}.bytes!.dataValue"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        udt_name = td.udt.name.decode()
        return f"{prefixed_type_name(udt_name, class_name)}.fromScVal({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_info():
    return f"// This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version} and stellar_sdk v{stellar_sdk_version}."


def render_imports():
    template = """
import 'dart:typed_data';
import 'package:stellar_flutter_sdk/stellar_flutter_sdk.dart';
"""
    return Template(template).render()


def render_enum(entry: xdr.SCSpecUDTEnumV0, class_name: str):
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/// {{ entry.doc.decode() if entry.doc else type_name + ' enum' }}
enum {{ type_name }} {
  {%- for case in entry.cases %}
  {{ snake_to_camel(case.name.decode(), False) }}({{ case.value.uint32 }}){% if loop.last %};{% else %},{% endif %}
  {%- endfor %}

  final int value;
  
  const {{ type_name }}(this.value);
  
  factory {{ type_name }}.fromValue(int value) {
    return {{ type_name }}.values.firstWhere(
      (e) => e.value == value,
      orElse: () => throw ArgumentError('Unknown {{ type_name }} value: $value'),
    );
  }
  
  XdrSCVal toScVal() {
    return XdrSCVal.forU32(value);
  }
  
  static {{ type_name }} fromScVal(XdrSCVal val) {
    return {{ type_name }}.fromValue(val.u32!.uint32);
  }
}
"""
    rendered_code = Template(template).render(
        entry=entry, type_name=type_name, snake_to_camel=snake_to_camel
    )
    return rendered_code


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0, class_name: str):
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    template = """
/// {{ entry.doc.decode() if entry.doc else type_name + ' error enum' }}
enum {{ type_name }} {
  {%- for case in entry.cases %}
  {{ snake_to_camel(case.name.decode(), False) }}({{ case.value.uint32 }}){% if loop.last %};{% else %},{% endif %}
  {%- endfor %}

  final int value;
  
  const {{ type_name }}(this.value);
  
  factory {{ type_name }}.fromValue(int value) {
    return {{ type_name }}.values.firstWhere(
      (e) => e.value == value,
      orElse: () => throw ArgumentError('Unknown {{ type_name }} value: $value'),
    );
  }
  
  XdrSCVal toScVal() {
    return XdrSCVal.forU32(value);
  }
  
  static {{ type_name }} fromScVal(XdrSCVal val) {
    return {{ type_name }}.fromValue(val.u32!.uint32);
  }
}
"""
    rendered_code = Template(template).render(
        entry=entry, type_name=type_name, snake_to_camel=snake_to_camel
    )
    return rendered_code


def render_struct(entry: xdr.SCSpecUDTStructV0, class_name: str):
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    
    # Create wrapper functions with class_name bound
    def to_dart_type_bound(td, nullable=False):
        return to_dart_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)
    
    template = """
/// {{ entry.doc.decode() if entry.doc else type_name + ' struct' }}
class {{ type_name }} {
  {%- for field in entry.fields %}
  final {{ to_dart_type(field.type) }} {{ snake_to_camel(field.name.decode()) }};
  {%- endfor %}

  const {{ type_name }}({
    {%- for field in entry.fields %}
    required this.{{ snake_to_camel(field.name.decode()) }},
    {%- endfor %}
  });

  XdrSCVal toScVal() {
    final fields = <XdrSCMapEntry>[];
    {%- for field in entry.fields %}
    fields.add(XdrSCMapEntry(
      XdrSCVal.forSymbol('{{ field.name_r.decode() if field.name_r else field.name.decode() }}'),
      {{ to_scval(field.type, snake_to_camel(field.name.decode())) }},
    ));
    {%- endfor %}
    return XdrSCVal.forMap(fields);
  }

  factory {{ type_name }}.fromScVal(XdrSCVal val) {
    final map = val.map!;
    final fieldsMap = <String, XdrSCVal>{};
    for (final entry in map) {
      fieldsMap[entry.key.sym!.toString()] = entry.val;
    }
    
    return {{ type_name }}(
      {%- for field in entry.fields %}
      {{ snake_to_camel(field.name.decode()) }}: {{ from_scval(field.type, 'fieldsMap["' ~ (field.name_r.decode() if field.name_r else field.name.decode()) ~ '"]!') }},
      {%- endfor %}
    );
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is {{ type_name }} &&
          {%- for field in entry.fields %}
          {{ snake_to_camel(field.name.decode()) }} == other.{{ snake_to_camel(field.name.decode()) }}{% if not loop.last %} &&{% endif %}
          {%- endfor %};

  @override
  int get hashCode => Object.hash(
      {%- for field in entry.fields %}
      {{ snake_to_camel(field.name.decode()) }}{% if not loop.last %},{% endif %}
      {%- endfor %}
  );
}
"""
    rendered_code = Template(template).render(
        entry=entry,
        type_name=type_name,
        to_dart_type=to_dart_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        snake_to_camel=snake_to_camel,
    )
    return rendered_code


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0, class_name: str):
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    
    # Create wrapper functions with class_name bound
    def to_dart_type_bound(td, nullable=False):
        return to_dart_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)
    
    template = """
/// {{ entry.doc.decode() if entry.doc else type_name + ' tuple struct' }}
class {{ type_name }} {
  final ({% for f in entry.fields %}{{ to_dart_type(f.type) }}{% if not loop.last %}, {% endif %}{% endfor %}) value;

  const {{ type_name }}(this.value);

  XdrSCVal toScVal() {
    return XdrSCVal.forVec([
      {%- for f in entry.fields %}
      {{ to_scval(f.type, 'value.$' + (loop.index0 + 1)|string) }}{% if not loop.last %},{% endif %}
      {%- endfor %}
    ]);
  }

  factory {{ type_name }}.fromScVal(XdrSCVal val) {
    final vec = val.vec!;
    return {{ type_name }}((
      {%- for f in entry.fields %}
      {{ from_scval(f.type, 'vec[' + loop.index0|string + ']') }}{% if not loop.last %},{% endif %}
      {%- endfor %}
    ));
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is {{ type_name }} && value == other.value;

  @override
  int get hashCode => value.hashCode;
}
"""
    rendered_code = Template(template).render(
        entry=entry,
        type_name=type_name,
        to_dart_type=to_dart_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound
    )
    return rendered_code


def render_union(entry: xdr.SCSpecUDTUnionV0, class_name: str):
    type_name = prefixed_type_name(entry.name.decode(), class_name)
    
    # Create wrapper functions with class_name bound
    def to_dart_type_bound(td, nullable=False):
        return to_dart_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)
    
    kind_enum_template = """
/// Kind enum for {{ type_name }}
enum {{ type_name }}Kind {
  {%- for case in entry.cases %}
  {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
  {{ snake_to_camel(case.void_case.name.decode(), False) }}('{{ case.void_case.name_r.decode() if case.void_case.name_r else case.void_case.name.decode() }}'){% if loop.last %};{% else %},{% endif %}
  {%- else %}
  {{ snake_to_camel(case.tuple_case.name.decode(), False) }}('{{ case.tuple_case.name.decode() if case.tuple_case.name_r else case.tuple_case.name.decode() }}'){% if loop.last %};{% else %},{% endif %}
  {%- endif %}
  {%- endfor %}

  final String value;
  
  const {{ type_name }}Kind(this.value);
  
  factory {{ type_name }}Kind.fromValue(String value) {
    return {{ type_name }}Kind.values.firstWhere(
      (e) => e.value == value,
      orElse: () => throw ArgumentError('Unknown {{ type_name }}Kind value: $value'),
    );
  }
}
"""
    kind_enum_rendered_code = Template(kind_enum_template).render(
        entry=entry, type_name=type_name, xdr=xdr, snake_to_camel=snake_to_camel
    )

    template = """
/// {{ entry.doc.decode() if entry.doc else type_name + ' union' }}
class {{ type_name }} {
  final {{ type_name }}Kind kind;
  {%- for case in entry.cases %}
  {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
  {%- if len(case.tuple_case.type) == 1 %}
  final {{ to_dart_type(case.tuple_case.type[0], nullable=True) }} {{ snake_to_camel(case.tuple_case.name.decode()) }};
  {%- else %}
  final ({% for f in case.tuple_case.type %}{{ to_dart_type(f) }}{% if not loop.last %}, {% endif %}{% endfor %})? {{ snake_to_camel(case.tuple_case.name.decode()) }};
  {%- endif %}
  {%- endif %}
  {%- endfor %}

  const {{ type_name }}._({
    required this.kind,
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
    this.{{ snake_to_camel(case.tuple_case.name.decode()) }},
    {%- endif %}
    {%- endfor %}
  });

  {%- for case in entry.cases %}
  {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
  factory {{ type_name }}.{{ snake_to_camel(case.void_case.name.decode()) }}() {
    return {{ type_name }}._(kind: {{ type_name }}Kind.{{ snake_to_camel(case.void_case.name.decode(), False) }});
  }
  {%- else %}
  {%- if len(case.tuple_case.type) == 1 %}
  factory {{ type_name }}.{{ snake_to_camel(case.tuple_case.name.decode()) }}({{ to_dart_type(case.tuple_case.type[0]) }} value) {
    return {{ type_name }}._(
      kind: {{ type_name }}Kind.{{ snake_to_camel(case.tuple_case.name.decode(), False) }},
      {{ snake_to_camel(case.tuple_case.name.decode()) }}: value,
    );
  }
  {%- else %}
  factory {{ type_name }}.{{ snake_to_camel(case.tuple_case.name.decode()) }}(({% for f in case.tuple_case.type %}{{ to_dart_type(f) }}{% if not loop.last %}, {% endif %}{% endfor %}) value) {
    return {{ type_name }}._(
      kind: {{ type_name }}Kind.{{ snake_to_camel(case.tuple_case.name.decode(), False) }},
      {{ snake_to_camel(case.tuple_case.name.decode()) }}: value,
    );
  }
  {%- endif %}
  {%- endif %}
  {%- endfor %}

  XdrSCVal toScVal() {
    switch (kind) {
      {%- for case in entry.cases %}
      {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.void_case.name.decode(), False) }}:
        return XdrSCVal.forVec([XdrSCVal.forSymbol(kind.value)]);
      {%- else %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.tuple_case.name.decode(), False) }}:
        {%- if len(case.tuple_case.type) == 1 %}
        return XdrSCVal.forVec([
          XdrSCVal.forSymbol(kind.value),
          {{ to_scval(case.tuple_case.type[0], snake_to_camel(case.tuple_case.name.decode()) + '!') }},
        ]);
        {%- else %}
        final tuple = {{ snake_to_camel(case.tuple_case.name.decode()) }}!;
        return XdrSCVal.forVec([
          XdrSCVal.forSymbol(kind.value),
          {%- for t in case.tuple_case.type %}
          {{ to_scval(t, 'tuple.$' + (loop.index)|string) }}{% if not loop.last %},{% endif %}
          {%- endfor %}
        ]);
        {%- endif %}
      {%- endif %}
      {%- endfor %}
    }
  }

  factory {{ type_name }}.fromScVal(XdrSCVal val) {
    final vec = val.vec!;
    final kind = {{ type_name }}Kind.fromValue(vec[0].sym!.toString());
    
    switch (kind) {
      {%- for case in entry.cases %}
      {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.void_case.name.decode(), False) }}:
        return {{ type_name }}.{{ snake_to_camel(case.void_case.name.decode()) }}();
      {%- else %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.tuple_case.name.decode(), False) }}:
        {%- if len(case.tuple_case.type) == 1 %}
        return {{ type_name }}.{{ snake_to_camel(case.tuple_case.name.decode()) }}(
          {{ from_scval(case.tuple_case.type[0], 'vec[1]') }}
        );
        {%- else %}
        return {{ type_name }}.{{ snake_to_camel(case.tuple_case.name.decode()) }}((
          {%- for i, t in enumerate(case.tuple_case.type) %}
          {{ from_scval(t, 'vec[' + (i + 1)|string + ']') }}{% if not loop.last %},{% endif %}
          {%- endfor %}
        ));
        {%- endif %}
      {%- endif %}
      {%- endfor %}
    }
  }

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    if (other is! {{ type_name }}) return false;
    if (kind != other.kind) return false;
    
    switch (kind) {
      {%- for case in entry.cases %}
      {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.void_case.name.decode(), False) }}:
        return true;
      {%- else %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.tuple_case.name.decode(), False) }}:
        return {{ snake_to_camel(case.tuple_case.name.decode()) }} == other.{{ snake_to_camel(case.tuple_case.name.decode()) }};
      {%- endif %}
      {%- endfor %}
    }
  }

  @override
  int get hashCode {
    switch (kind) {
      {%- for case in entry.cases %}
      {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.void_case.name.decode(), False) }}:
        return kind.hashCode;
      {%- else %}
      case {{ type_name }}Kind.{{ snake_to_camel(case.tuple_case.name.decode(), False) }}:
        return Object.hash(kind, {{ snake_to_camel(case.tuple_case.name.decode()) }});
      {%- endif %}
      {%- endfor %}
    }
  }
}
"""
    union_rendered_code = Template(template).render(
        entry=entry,
        type_name=type_name,
        to_dart_type=to_dart_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        xdr=xdr,
        len=len,
        snake_to_camel=snake_to_camel,
        enumerate=enumerate,
    )
    return kind_enum_rendered_code + "\n" + union_rendered_code


def render_client(entries: List[xdr.SCSpecFunctionV0], class_name: str):
    template = """
/// Client for interacting with the {{ class_name }} contract
class {{ class_name }} {
  /// The underlying SorobanClient instance
  final SorobanClient _client;

  /// Creates a new {{ class_name }} for the given contract ID
  static Future<{{ class_name }}> forContractId({
    required KeyPair sourceAccountKeyPair,
    required String contractId,
    required Network network,
    required String rpcUrl,
    bool enableServerLogging = false,
  }) async {
    final options = ClientOptions(
      sourceAccountKeyPair: sourceAccountKeyPair,
      contractId: contractId,
      network: network,
      rpcUrl: rpcUrl,
      enableServerLogging: enableServerLogging,
    );
    
    final client = await SorobanClient.forClientOptions(options: options);
    return {{ class_name }}._(client);
  }
  
  /// Private constructor that wraps a SorobanClient
  {{ class_name }}._(this._client);

  /// Gets the contract ID
  String getContractId() => _client.getContractId();

  /// Gets the client options
  ClientOptions getOptions() => _client.getOptions();

  /// Gets the contract specification
  ContractSpec getContractSpec() => _client.getContractSpec();
      
  {%- for entry in entries %}
  
  /// {{ entry.doc.decode() if entry.doc else 'Invokes the ' + entry.name.sc_symbol.decode() + ' method' }}
  {%- if parse_result_type(entry.outputs) == 'void' %}
  Future<void> {{ snake_to_camel(entry.name.sc_symbol.decode()) }}({
  {%- else %}
  Future<{{ parse_result_type(entry.outputs) }}> {{ snake_to_camel(entry.name.sc_symbol.decode()) }}({
  {%- endif %}
    {%- for param in entry.inputs %}
    required {{ to_dart_type(param.type) }} {{ snake_to_camel(param.name.decode()) }},
    {%- endfor %}
    KeyPair? signer,
    int baseFee = 100,
    int transactionTimeout = 300,
    int submitTimeout = 30,
    bool simulate = true,
    bool restore = true,
    bool force = false,
  }) async {
    final List<XdrSCVal> args = [
      {%- for param in entry.inputs %}
      {{ to_scval(param.type, snake_to_camel(param.name.decode())) }},
      {%- endfor %}
    ];
    
    final methodOptions = MethodOptions();
    // You can customize method options here if needed
    
    final result = await _client.invokeMethod(
      name: '{{ entry.name.sc_symbol_r.decode() if entry.name.sc_symbol_r else entry.name.sc_symbol.decode() }}',
      args: args,
      force: force,
      methodOptions: methodOptions,
    );
    
    {%- if parse_result_type(entry.outputs) != 'void' %}
    return {{ parse_result_from_scval(entry.outputs, 'result') }};
    {%- endif %}
  }
  
  /// Builds an AssembledTransaction for the {{ entry.name.sc_symbol.decode() }} method.
  /// This is useful if you need to manipulate the transaction before signing and sending.
  Future<AssembledTransaction> build{{ snake_to_camel(entry.name.sc_symbol.decode(), False) }}Tx({
    {%- for param in entry.inputs %}
    required {{ to_dart_type(param.type) }} {{ snake_to_camel(param.name.decode()) }},
    {%- endfor %}
    MethodOptions? methodOptions,
  }) async {
    final List<XdrSCVal> args = [
      {%- for param in entry.inputs %}
      {{ to_scval(param.type, snake_to_camel(param.name.decode())) }},
      {%- endfor %}
    ];
    
    return await _client.buildInvokeMethodTx(
      name: '{{ entry.name.sc_symbol_r.decode() if entry.name.sc_symbol_r else entry.name.sc_symbol.decode() }}',
      args: args,
      methodOptions: methodOptions,
    );
  }
  {%- endfor %}
}
"""

    # Create wrapper functions with class_name bound
    def to_dart_type_bound(td, nullable=False):
        return to_dart_type(td, nullable, class_name)
    
    def to_scval_bound(td, name):
        return to_scval(td, name, class_name)
    
    def from_scval_bound(td, name):
        return from_scval(td, name, class_name)
    
    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "void"
        elif len(output) == 1:
            return to_dart_type_bound(output[0])
        else:
            types = [to_dart_type_bound(t) for t in output]
            return f"({', '.join(types)})"

    def parse_result_xdr(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return ""
        elif len(output) == 1:
            return from_scval_bound(output[0], "result")
        else:
            # Handle tuple return
            results = []
            for i, t in enumerate(output):
                results.append(from_scval_bound(t, f"result.vec![{i}]"))
            return f"({', '.join(results)})"

    def parse_result_from_scval(output: List[xdr.SCSpecTypeDef], var_name: str):
        if len(output) == 0:
            return ""
        elif len(output) == 1:
            return from_scval_bound(output[0], var_name)
        else:
            # Handle tuple return
            results = []
            for i, t in enumerate(output):
                results.append(from_scval_bound(t, f"{var_name}.vec![{i}]"))
            return f"({', '.join(results)})"

    client_rendered_code = Template(template).render(
        entries=entries,
        to_dart_type=to_dart_type_bound,
        to_scval=to_scval_bound,
        from_scval=from_scval_bound,
        parse_result_type=parse_result_type,
        parse_result_xdr=parse_result_xdr,
        parse_result_from_scval=parse_result_from_scval,
        snake_to_camel=snake_to_camel,
        class_name=class_name,
    )
    return client_rendered_code


def append_underscore(specs: List[xdr.SCSpecEntry]):
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            assert spec.udt_struct_v0 is not None
            if is_keywords(spec.udt_struct_v0.name.decode()):
                spec.udt_struct_v0.name_r = spec.udt_struct_v0.name  # type: ignore[attr-defined]
                spec.udt_struct_v0.name = spec.udt_struct_v0.name + b"_"
            for field in spec.udt_struct_v0.fields:
                if is_keywords(field.name.decode()):
                    field.name_r = field.name  # type: ignore[attr-defined]
                    field.name = field.name + b"_"
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            assert spec.udt_union_v0 is not None
            if is_keywords(spec.udt_union_v0.name.decode()):
                spec.udt_union_v0.name_r = spec.udt_union_v0.name  # type: ignore[attr-defined]
                spec.udt_union_v0.name = spec.udt_union_v0.name + b"_"
            for union_case in spec.udt_union_v0.cases:
                if (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
                ):
                    if is_keywords(union_case.tuple_case.name.decode()):
                        union_case.tuple_case.name_r = union_case.tuple_case.name  # type: ignore[attr-defined]
                        union_case.tuple_case.name = union_case.tuple_case.name + b"_"
                elif (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
                ):
                    if is_keywords(union_case.void_case.name.decode()):
                        union_case.void_case.name_r = union_case.void_case.name  # type: ignore[attr-defined]
                        union_case.void_case.name = union_case.void_case.name + b"_"
                else:
                    raise ValueError(f"Unsupported union case kind: {union_case.kind}")
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            assert spec.function_v0 is not None
            if is_keywords(spec.function_v0.name.sc_symbol.decode()):
                spec.function_v0.name.sc_symbol_r = spec.function_v0.name.sc_symbol  # type: ignore[attr-defined]
                spec.function_v0.name.sc_symbol = spec.function_v0.name.sc_symbol + b"_"
            for param in spec.function_v0.inputs:
                if is_keywords(param.name.decode()):
                    param.name = param.name + b"_"
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            assert spec.udt_enum_v0 is not None
            if is_keywords(spec.udt_enum_v0.name.decode()):
                spec.udt_enum_v0.name_r = spec.udt_enum_v0.name  # type: ignore[attr-defined]
                spec.udt_enum_v0.name = spec.udt_enum_v0.name + b"_"
            for enum_case in spec.udt_enum_v0.cases:
                if is_keywords(enum_case.name.decode()):
                    enum_case.name = enum_case.name + b"_"
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            assert spec.udt_error_enum_v0 is not None
            if is_keywords(spec.udt_error_enum_v0.name.decode()):
                spec.udt_error_enum_v0.name_r = spec.udt_error_enum_v0.name  # type: ignore[attr-defined]
                spec.udt_error_enum_v0.name = spec.udt_error_enum_v0.name + b"_"
            for error_enum_case in spec.udt_error_enum_v0.cases:
                if is_keywords(error_enum_case.name.decode()):
                    error_enum_case.name = error_enum_case.name + b"_"


def generate_binding(specs: List[xdr.SCSpecEntry], class_name: str) -> str:
    append_underscore(specs)

    generated = []
    generated.append(render_info())
    generated.append(render_imports())

    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            generated.append(render_enum(spec.udt_enum_v0, class_name))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            generated.append(render_error_enum(spec.udt_error_enum_v0, class_name))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            if is_tuple_struct(spec.udt_struct_v0):
                generated.append(render_tuple_struct(spec.udt_struct_v0, class_name))
            else:
                generated.append(render_struct(spec.udt_struct_v0, class_name))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            generated.append(render_union(spec.udt_union_v0, class_name))

    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    generated.append(render_client(function_specs, class_name))
    return "\n".join(generated)


@click.command(name="flutter")
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
    default="Contract",
    help="Class name prefix for generated bindings, defaults to 'Contract'",
)
def command(contract_id: str, rpc_url: str, output: str, class_name: str):
    """Generate Flutter/Dart bindings for a Soroban contract"""
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

    click.echo("Generating Flutter bindings")
    generated = generate_binding(specs, class_name=class_name)

    if not os.path.exists(output):
        os.makedirs(output)
    output_path = os.path.join(
        output, f"{camel_to_snake(class_name)}_client.dart"
    )
    with open(output_path, "w") as f:
        f.write(generated)
    click.echo(f"Generated Flutter bindings to {output_path}")


if __name__ == "__main__":
    command()
