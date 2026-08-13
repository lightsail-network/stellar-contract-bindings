import builtins
import keyword
import os
import re
import unicodedata
from typing import Callable, List, Tuple

import black

import click
from jinja2 import Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id

UdtNameResolver = Callable[[str], str]

_GENERATED_MODULE_NAMES = {
    "Address",
    "AssembledTransaction",
    "AssembledTransactionAsync",
    "Client",
    "ClientAsync",
    "ContractClient",
    "ContractClientAsync",
    "Dict",
    "EllipsisType",
    "Enum",
    "EventInfo",
    "IntEnum",
    "Keypair",
    "List",
    "MuxedAccount",
    "NULL_ACCOUNT",
    "Optional",
    "Sequence",
    "Tuple",
    "Union",
    "UnparsedEventError",
    "_EVENTS",
    "_coerce_event_scval",
    "_event_topics_and_data",
    "_from_error_scval",
    "_logger",
    "_static_topic_matches",
    "logging",
    "parse_event",
    "scval",
    "xdr",
}
_RESERVED_MODULE_NAMES = frozenset(dir(builtins)) | _GENERATED_MODULE_NAMES


def _udt_spec_name(spec: xdr.SCSpecEntry) -> str | None:
    if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
        return spec.udt_struct_v0.name.decode()
    if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
        return spec.udt_enum_v0.name.decode()
    if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
        return spec.udt_error_enum_v0.name.decode()
    if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
        return spec.udt_union_v0.name.decode()
    return None


def resolve_udt_names(specs: List[xdr.SCSpecEntry]) -> dict[str, str]:
    """Map each UDT spec name to a unique Python class name.

    Spec names may be module-qualified (``pkg::mod::Type``), which is not a
    valid identifier. The bare last segment is preferred, so bindings for the
    common unqualified case keep the name the contract uses. The full path,
    flattened with underscores, is used only when several modules claim the
    same bare name; a numeric suffix breaks any remaining tie, including with
    the names the generator itself emits.
    """
    spec_names = list(
        dict.fromkeys(
            name for spec in specs if (name := _udt_spec_name(spec)) is not None
        )
    )
    union_names = {
        spec.udt_union_v0.name.decode()
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0
    }

    claimants: dict[str, int] = {}
    for spec_name in spec_names:
        bare = _default_udt_name(spec_name)
        claimants[bare] = claimants.get(bare, 0) + 1

    used: set[str] = set(_RESERVED_MODULE_NAMES)
    resolved: dict[str, str] = {}
    for spec_name in spec_names:
        bare = _default_udt_name(spec_name)
        if claimants[bare] == 1:
            base = bare
        else:
            segments = [segment for segment in spec_name.split("::") if segment]
            base = python_identifier("_".join(segments) if segments else spec_name)
        name = base
        suffix = 2
        # A union also emits a companion "<name>Kind" enum, so both have to be
        # free before the name can be claimed.
        while name in used or (spec_name in union_names and f"{name}Kind" in used):
            name = f"{base}{suffix}"
            suffix += 1
        used.add(name)
        if spec_name in union_names:
            used.add(f"{name}Kind")
        resolved[spec_name] = name
    return resolved


def _udt_reference_resolver(names: dict[str, str]) -> UdtNameResolver:
    # A spec may reference a UDT it does not declare; fall back to the bare
    # name so the reference at least renders as a valid identifier.
    return lambda spec_name: names.get(spec_name) or _default_udt_name(spec_name)


def is_tuple_struct(entry: xdr.SCSpecUDTStructV0) -> bool:
    # ex. <SCSpecUDTStructV0 [doc=b'', lib=b'', name=b'TupleStruct', fields=[<SCSpecUDTStructFieldV0 [doc=b'', name=b'0', type=<SCSpecTy...>, <SCSpecUDTStructFieldV0 [doc=b'', name=b'1', type=<SCSpecTypeDef [type=2000, udt=<SCSpecTypeUDT [name=b'SimpleEnum']>]>]>]]>
    return all(f.name.isdigit() for f in entry.fields)


def camel_to_snake(text: str) -> str:
    result = text[0].lower()
    for char in text[1:]:
        if char.isupper():
            result += "_" + char.lower()
        else:
            result += char
    return result


def _default_udt_name(spec_name: str) -> str:
    segments = [segment for segment in spec_name.split("::") if segment]
    return python_identifier(segments[-1] if segments else spec_name)


def to_py_type(
    td: xdr.SCSpecTypeDef,
    input_type: bool = False,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return "xdr.SCVal"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return "bool"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "None"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        return "xdr.SCError"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return "int"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return "bytes"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return "bytes"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return "str"
    if (
        t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS
        or t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS
    ):
        return "Union[Address, str]" if input_type else "Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        raise NotImplementedError("SC_SPEC_TYPE_MUXED_ADDRESS is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"Optional[{to_py_type(td.option.value_type, input_type, resolve_udt_name)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        error_t = td.result.error_type
        return (
            f"Union[{to_py_type(ok_t, input_type, resolve_udt_name)}, "
            f"{to_py_type(error_t, input_type, resolve_udt_name)}]"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List[{to_py_type(td.vec.element_type, input_type, resolve_udt_name)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Dict[{to_py_type(td.map.key_type, input_type, resolve_udt_name)}, {to_py_type(td.map.value_type, input_type, resolve_udt_name)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            # () equivalent to None in Python
            return "None"
        types = [
            to_py_type(t, input_type, resolve_udt_name) for t in td.tuple.value_types
        ]
        return f"Tuple[{', '.join(types)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"bytes"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return resolve_udt_name(td.udt.name.decode())
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(
    td: xdr.SCSpecTypeDef,
    name: str,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"scval.to_bool({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"scval.to_void()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        return f"xdr.SCVal(xdr.SCValType.SCV_ERROR, error={name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"scval.to_uint32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"scval.to_int32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"scval.to_uint64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"scval.to_int64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"scval.to_timepoint({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"scval.to_duration({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"scval.to_uint128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"scval.to_int128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"scval.to_uint256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"scval.to_int256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"scval.to_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"scval.to_string({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"scval.to_symbol({name})"
    if (
        t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS
        or t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS
    ):
        return f"scval.to_address({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        raise NotImplementedError("SC_SPEC_TYPE_MUXED_ADDRESS is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{to_scval(td.option.value_type, name, resolve_udt_name)} if {name} is not None else scval.to_void()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        error_t = td.result.error_type
        error_py_type = to_py_type(
            error_t, input_type=True, resolve_udt_name=resolve_udt_name
        )
        error_test = (
            f"isinstance({name}, xdr.SCError)"
            if error_t.type == xdr.SCSpecType.SC_SPEC_TYPE_ERROR
            else f"isinstance({name}, {error_py_type})"
        )
        return (
            f"{to_scval(error_t, name, resolve_udt_name)} if {error_test} "
            f"else {to_scval(td.result.ok_type, name, resolve_udt_name)}"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"scval.to_vec([{to_scval(td.vec.element_type, 'e', resolve_udt_name)} for e in {name}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"scval.to_map({{{to_scval(td.map.key_type, 'k', resolve_udt_name)}: {to_scval(td.map.value_type, 'v', resolve_udt_name)} for k, v in {name}.items()}})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        types = [
            to_scval(t, f"{name}[{i}]", resolve_udt_name)
            for i, t in enumerate(td.tuple.value_types)
        ]
        return f"scval.to_tuple_struct([{', '.join(types)}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"scval.to_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.to_scval()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(
    td: xdr.SCSpecTypeDef,
    name: str,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"scval.from_bool({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"scval.from_void({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        return f"_from_error_scval({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return f"scval.from_uint32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return f"scval.from_int32({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return f"scval.from_uint64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return f"scval.from_int64({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return f"scval.from_timepoint({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return f"scval.from_duration({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return f"scval.from_uint128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return f"scval.from_int128({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return f"scval.from_uint256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return f"scval.from_int256({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return f"scval.from_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return f"scval.from_string({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return f"scval.from_symbol({name})"
    if (
        t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS
        or t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS
    ):
        return f"scval.from_address({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        raise NotImplementedError("SC_SPEC_TYPE_MUXED_ADDRESS is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{from_scval(td.option.value_type, name, resolve_udt_name)} if {name}.type != xdr.SCValType.SCV_VOID else scval.from_void({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        error_t = td.result.error_type
        return (
            f"{from_scval(error_t, name, resolve_udt_name)} "
            f"if {name}.type == xdr.SCValType.SCV_ERROR else "
            f"{from_scval(ok_t, name, resolve_udt_name)}"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"[{from_scval(td.vec.element_type, 'e', resolve_udt_name)} for e in scval.from_vec({name})]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"{{{from_scval(td.map.key_type, 'k', resolve_udt_name)}: {from_scval(td.map.value_type, 'v', resolve_udt_name)} for k, v in scval.from_map({name}).items()}}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "None"
        elements = f"scval.from_tuple_struct({name})"
        types = [
            from_scval(t, f"{elements}[{i}]", resolve_udt_name)
            for i, t in enumerate(td.tuple.value_types)
        ]
        return f"({', '.join(types)})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"scval.from_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{resolve_udt_name(td.udt.name.decode())}.from_scval({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_info():
    return f"# This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version} and stellar_sdk v{stellar_sdk_version}."


def render_imports(client_type: str = "both", has_events: bool = False):
    template = """
from __future__ import annotations

{%- if has_events %}
import logging
from types import EllipsisType
{%- endif %}
from enum import IntEnum, Enum
{#- Sequence is only used by the event input types. #}
from typing import Dict, List, {% if has_events %}Sequence, {% endif %}Tuple, Optional, Union

from stellar_sdk import scval, xdr, Address, MuxedAccount, Keypair
{%- if client_type == "sync" or client_type == "both" %}
from stellar_sdk.contract import AssembledTransaction, ContractClient
{%- endif %}
{%- if client_type == "async" or client_type == "both" %}
from stellar_sdk.contract import AssembledTransactionAsync, ContractClientAsync
{%- endif %}
{%- if has_events %}
from stellar_sdk.soroban_rpc import EventInfo
{%- endif %}

NULL_ACCOUNT = "GAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWHF"
"""
    rendered_code = Template(template).render(
        client_type=client_type, has_events=has_events
    )
    return rendered_code


def render_scval_helpers():
    return """
def _from_error_scval(value: xdr.SCVal) -> xdr.SCError:
    if value.type != xdr.SCValType.SCV_ERROR or value.error is None:
        raise ValueError(f"expected SCV_ERROR, got {value.type}")
    return value.error
"""


def render_enum(entry: xdr.SCSpecUDTEnumV0, class_name: str | None = None):
    class_name = class_name or _default_udt_name(entry.name.decode())
    template = """
class {{ class_name }}(IntEnum):
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}
    {%- for case in entry.cases %}
    {{ case.name.decode() }} = {{ case.value.uint32 }}
    {%- endfor %}
    def to_scval(self) -> xdr.SCVal:
        return scval.to_uint32(self.value)

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        return cls(scval.from_uint32(val))
"""

    rendered_code = Template(template).render(entry=entry, class_name=class_name)
    return rendered_code


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0, class_name: str | None = None):
    class_name = class_name or _default_udt_name(entry.name.decode())
    template = """
class {{ class_name }}(IntEnum):
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}
    {%- for case in entry.cases %}
    {{ case.name.decode() }} = {{ case.value.uint32 }}
    {%- endfor %}
    def to_scval(self) -> xdr.SCVal:
        return xdr.SCVal(
            xdr.SCValType.SCV_ERROR,
            error=xdr.SCError(
                xdr.SCErrorType.SCE_CONTRACT,
                contract_code=xdr.Uint32(self.value),
            ),
        )

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        error = _from_error_scval(val)
        if error.type != xdr.SCErrorType.SCE_CONTRACT or error.contract_code is None:
            raise ValueError("expected an SCE_CONTRACT error")
        return cls(error.contract_code.uint32)
    """

    rendered_code = Template(template).render(entry=entry, class_name=class_name)
    return rendered_code


def render_struct(
    entry: xdr.SCSpecUDTStructV0,
    class_name: str | None = None,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    class_name = class_name or _default_udt_name(entry.name.decode())
    template = """
class {{ class_name }}:
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}
    {%- for field in entry.fields %}
    {{ field.name.decode() }}: {{ to_py_type(field.type) }}
    {%- endfor %}

    def __init__(self, {% for field in entry.fields %}{{ field.name.decode() }}: {{ to_py_type(field.type, True) }}{% if not loop.last %}, {% endif %}{% endfor %}):
        {%- for field in entry.fields %}
        self.{{ field.name.decode() }} = {{ field.name.decode() }}
        {%- endfor %}

    def to_scval(self) -> xdr.SCVal:
        return scval.to_struct({
            {%- for field in entry.fields %}
            '{{ field.name_r.decode() if field.name_r else field.name.decode() }}': {{ to_scval(field.type, 'self.' ~ field.name.decode()) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        })

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_struct(val)
        return cls(
            {%- for index, field in enumerate(entry.fields) %}
            {{ from_scval(field.type, 'elements["' ~ (field.name_r.decode() if field.name_r else field.name.decode()) ~ '"]') }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, {{ class_name }}):
            return NotImplemented
        return {% for field in entry.fields %}self.{{ field.name.decode() }} == other.{{ field.name.decode() }}{% if not loop.last %} and {% endif %}{% endfor %}

    def __hash__(self) -> int:
        return hash(({% for field in entry.fields %}self.{{ field.name.decode() }}{% if not loop.last %}, {% endif %}{% endfor %}))
"""

    rendered_code = Template(template).render(
        entry=entry,
        class_name=class_name,
        to_py_type=lambda td, input_type=False: to_py_type(
            td, input_type, resolve_udt_name
        ),
        to_scval=lambda td, name: to_scval(td, name, resolve_udt_name),
        from_scval=lambda td, name: from_scval(td, name, resolve_udt_name),
        enumerate=enumerate,
    )
    return rendered_code


def render_tuple_struct(
    entry: xdr.SCSpecUDTStructV0,
    class_name: str | None = None,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    class_name = class_name or _default_udt_name(entry.name.decode())
    template = """
class {{ class_name }}:
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}

    def __init__(self, value: Tuple[{% for f in entry.fields %}{{ to_py_type(f.type, True) }}{% if not loop.last %}, {% endif %}{% endfor %}]):
        self.value = value

    def to_scval(self) -> xdr.SCVal:
        return scval.to_tuple_struct([{% for f in entry.fields %}{{ to_scval(f.type, 'self.value[' ~ f.name.decode() ~ ']') }}{% if not loop.last %}, {% endif %}{% endfor %}]) 
    
    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_tuple_struct(val)
        values = ({% for f in entry.fields %}{{ from_scval(f.type, 'elements[' ~ f.name.decode() ~ ']') }}, {% endfor %})
        return cls(values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, {{ class_name }}):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)
"""

    rendered_code = Template(template).render(
        entry=entry,
        class_name=class_name,
        to_py_type=lambda td, input_type=False: to_py_type(
            td, input_type, resolve_udt_name
        ),
        to_scval=lambda td, name: to_scval(td, name, resolve_udt_name),
        from_scval=lambda td, name: from_scval(td, name, resolve_udt_name),
    )
    return rendered_code


def render_union(
    entry: xdr.SCSpecUDTUnionV0,
    class_name: str | None = None,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    class_name = class_name or _default_udt_name(entry.name.decode())
    kind_enum_template = """
class {{ class_name }}Kind(Enum):
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
    {{ case.void_case.name.decode() }} = '{{ case.void_case.name_r.decode() if case.void_case.name_r else case.void_case.name.decode() }}'
    {%- else %}
    {{ case.tuple_case.name.decode() }} = '{{ case.tuple_case.name.decode() if case.tuple_case.name_r else case.tuple_case.name.decode() }}'
    {%- endif %}
    {%- endfor %}
"""

    kind_enum_rendered_code = Template(kind_enum_template).render(
        entry=entry, class_name=class_name, xdr=xdr
    )

    template = """
class {{ class_name }}:
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}
    def __init__(self,
        kind: {{ class_name }}Kind,
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
        {%- if len(case.tuple_case.type) == 1 %}
        {{ camel_to_snake(case.tuple_case.name.decode()) }}: Optional[{{ to_py_type(case.tuple_case.type[0], True) }}] = None,
        {%- else %}
        {{ camel_to_snake(case.tuple_case.name.decode()) }}: Optional[Tuple[{% for f in case.tuple_case.type %}{{ to_py_type(f, True) }}{% if not loop.last %}, {% endif %}{% endfor %}]] = None,
        {%- endif %}
        {%- endif %}
        {%- endfor %}
    ):
        self.kind = kind
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %} 
        self.{{ camel_to_snake(case.tuple_case.name.decode()) }} = {{ camel_to_snake(case.tuple_case.name.decode()) }}
        {%- endif %}
        {%- endfor %}

    def to_scval(self) -> xdr.SCVal:
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        if self.kind == {{ class_name }}Kind.{{ case.void_case.name.decode() }}:
            return scval.to_enum(self.kind.name, None)
        {%- else %}
        if self.kind == {{ class_name }}Kind.{{ case.tuple_case.name.decode() }}:
        {%- if len(case.tuple_case.type) == 1 %}
            assert self.{{ camel_to_snake(case.tuple_case.name.decode()) }} is not None
            return scval.to_enum(self.kind.name, {{ to_scval(case.tuple_case.type[0], 'self.' ~ camel_to_snake(case.tuple_case.name.decode())) }})
        {%- else %}
            assert isinstance(self.{{ camel_to_snake(case.tuple_case.name.decode()) }}, tuple)
            return scval.to_enum(self.kind.name, [
                {%- for t in case.tuple_case.type %}
                {{ to_scval(t, 'self.' + camel_to_snake(case.tuple_case.name.decode()) + '[' + loop.index0|string + ']') }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            ])
        {%- endif %}
        {%- endif %}
        {%- endfor %}
        raise ValueError(f"Invalid kind: {self.kind}")
    
    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_enum(val)
        kind = {{ class_name }}Kind(elements[0])
        
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        if kind == {{ class_name }}Kind.{{ case.void_case.name.decode() }}:
            return cls(kind)
        {%- else %}
        if kind == {{ class_name }}Kind.{{ case.tuple_case.name.decode() }}:
        {%- if len(case.tuple_case.type) == 1 %}
            assert elements[1] is not None and isinstance(elements[1], xdr.SCVal)
            return cls(kind, {{ camel_to_snake(case.tuple_case.name.decode()) }}={{ from_scval(case.tuple_case.type[0], 'elements[1]') }})
        {%- else %}
            assert elements[1] is not None and isinstance(elements[1], list)
            return cls(kind, {{ camel_to_snake(case.tuple_case.name.decode()) }}=(
                {%- for i, t in enumerate(case.tuple_case.type) %}
                {{ from_scval(t, 'elements[1][' + loop.index0|string + ']') }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            ))
        {%- endif %}
        {%- endif %}
        {%- endfor %}
        raise ValueError(f"Invalid kind: {kind}")
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, {{ class_name }}):
            return NotImplemented
        if self.kind != other.kind:
            return False
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
        if self.kind == {{ class_name }}Kind.{{ case.tuple_case.name.decode() }}:
            return self.{{ camel_to_snake(case.tuple_case.name.decode()) }} == other.{{ camel_to_snake(case.tuple_case.name.decode()) }}
        {%- endif %}
        {%- endfor %}
        return True

    def __hash__(self) -> int:
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
        if self.kind == {{ class_name }}Kind.{{ case.tuple_case.name.decode() }}:
            return hash((self.kind, self.{{ camel_to_snake(case.tuple_case.name.decode()) }}))
        {%- endif %}
        {%- endfor %}
        return hash(self.kind)
"""
    union_rendered_code = Template(template).render(
        entry=entry,
        class_name=class_name,
        to_py_type=lambda td, input_type=False: to_py_type(
            td, input_type, resolve_udt_name
        ),
        to_scval=lambda td, name: to_scval(td, name, resolve_udt_name),
        from_scval=lambda td, name: from_scval(td, name, resolve_udt_name),
        xdr=xdr,
        len=len,
        camel_to_snake=camel_to_snake,
        enumerate=enumerate,
    )
    return kind_enum_rendered_code + "\n" + union_rendered_code


def python_identifier(name: str) -> str:
    """Return a valid Python identifier while preserving as much text as possible."""
    name = unicodedata.normalize("NFKC", name)
    candidate = "".join(char if ("a" + char).isidentifier() else "_" for char in name)
    if not candidate:
        candidate = "_"
    if not (candidate[0] == "_" or candidate[0].isidentifier()):
        candidate = "_" + candidate
    if keyword.iskeyword(candidate) or (
        candidate.startswith("__") and candidate.endswith("__")
    ):
        candidate += "_"
    return candidate


def event_class_name(name: str) -> str:
    sanitized = python_identifier(name)
    parts = [part for part in re.split(r"_+", sanitized) if part]
    pascal = "".join(part[:1].upper() + part[1:] for part in parts) or "Event"
    pascal = python_identifier(pascal)
    return pascal if pascal.endswith("Event") else pascal + "Event"


def render_event_helpers():
    return '''
_logger = logging.getLogger(__name__)


def _coerce_event_scval(value: Union[xdr.SCVal, str, bytes]) -> xdr.SCVal:
    if isinstance(value, xdr.SCVal):
        return value
    if isinstance(value, bytes):
        return xdr.SCVal.from_xdr_bytes(value)
    return xdr.SCVal.from_xdr(value)


def _event_topics_and_data(
    event: Union[
        xdr.ContractEvent,
        EventInfo,
        Tuple[
            Sequence[Union[xdr.SCVal, str, bytes]],
            Union[xdr.SCVal, str, bytes],
        ],
    ],
) -> Tuple[List[xdr.SCVal], xdr.SCVal]:
    """Normalize transaction-meta, RPC, or raw-XDR event input."""
    if isinstance(event, xdr.ContractEvent):
        if event.body.v0 is None:
            raise ValueError("contract event has no v0 body")
        return list(event.body.v0.topics), event.body.v0.data
    if isinstance(event, EventInfo):
        return (
            [_coerce_event_scval(topic) for topic in event.topic],
            _coerce_event_scval(event.value),
        )
    if isinstance(event, tuple) and len(event) == 2:
        topics, data = event
        return (
            [_coerce_event_scval(topic) for topic in topics],
            _coerce_event_scval(data),
        )
    raise TypeError(
        "event must be ContractEvent, EventInfo, or a (topics, data) tuple"
    )


def _static_topic_matches(topic: xdr.SCVal, expected: str) -> bool:
    """SEP-48: when matching, parsers should tolerate static topics being of
    the SCVal type SCV_SYMBOL or SCV_STRING."""
    if topic.type == xdr.SCValType.SCV_SYMBOL:
        return scval.from_symbol(topic) == expected
    if topic.type == xdr.SCValType.SCV_STRING:
        return scval.from_string(topic) == expected.encode()
    return False


class UnparsedEventError(ValueError):
    """The event's topics matched one or more declared events, but none of the
    candidate classes could parse it.

    This usually means the on-chain event format has drifted from the contract
    spec these bindings were generated from (e.g. a contract upgrade or a
    protocol change). ``failures`` holds each candidate class and the exception
    its ``parse()`` raised.
    """

    def __init__(self, message: str, failures: List[Tuple[type, Exception]]):
        super().__init__(message)
        self.failures = failures
'''


def declared_topic_count(entry: xdr.SCSpecEventV0) -> int:
    return len(entry.prefix_topics) + sum(
        1
        for p in entry.params
        if p.location
        == xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
    )


def _declared_type_names(
    specs: List[xdr.SCSpecEntry], udt_names: dict[str, str] | None = None
) -> set[str]:
    if udt_names is None:
        udt_names = resolve_udt_names(specs)
    used = set(udt_names.values())
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            used.add(udt_names[spec.udt_union_v0.name.decode()] + "Kind")
    return used


def resolve_event_names(
    specs: List[xdr.SCSpecEntry],
    event_specs: List[xdr.SCSpecEventV0],
    udt_names: dict[str, str] | None = None,
) -> Tuple[List[str], str]:
    """Assign a unique module-level class name to each event entry.

    Collisions — with UDT type names (including the generated ``<Union>Kind``
    enums) or between events whose names normalize identically (``foo`` and
    ``foo_event``) — are resolved by appending underscores. The generated
    event-union alias is allocated from the same namespace, so a UDT or event
    named ``Event`` cannot overwrite another generated symbol.
    """
    used = _declared_type_names(specs, udt_names) | set(_RESERVED_MODULE_NAMES)
    union_name = "Event"
    while union_name in used:
        union_name += "_"
    used.add(union_name)

    class_names = []
    for event_spec in event_specs:
        name = event_class_name(event_spec.name.sc_symbol.decode())
        while name in used:
            name += "_"
        used.add(name)
        class_names.append(name)
    return class_names, union_name


def event_diagnostics(
    event_specs: List[xdr.SCSpecEventV0], class_names: List[str]
) -> List[str]:
    """Describe every event whose class name is not the obvious one.

    Two declarations can share an event name, and a name can collide with a
    generated type, so the class name alone does not always identify which
    declaration it came from. Each message is ready to print.
    """
    declaration_counts: dict[str, int] = {}
    for event_spec in event_specs:
        raw_name = event_spec.name.sc_symbol.decode()
        declaration_counts[raw_name] = declaration_counts.get(raw_name, 0) + 1

    occurrences: dict[str, int] = {}
    messages = []
    for event_spec, class_name in zip(event_specs, class_names):
        raw_name = event_spec.name.sc_symbol.decode()
        occurrence = occurrences.get(raw_name, 0) + 1
        occurrences[raw_name] = occurrence
        declarations = declaration_counts[raw_name]
        reasons = []
        if declarations > 1:
            reasons.append(
                f"declaration {occurrence} of {declarations} with this event name"
            )
        if class_name != event_class_name(raw_name):
            reasons.append("renamed to avoid a generated-name collision")
        if reasons:
            messages.append(
                f"Event binding note: {raw_name!r} -> {class_name} "
                f"({'; '.join(reasons)})"
            )
    return messages


def resolve_event_param_names(entry: xdr.SCSpecEventV0) -> List[str]:
    """Allocate valid, unique constructor/attribute names for an event."""
    used = {"self", "cls"}
    names = []
    for param in entry.params:
        name = python_identifier(param.name.decode())
        while unicodedata.normalize("NFKC", name) in used:
            name += "_"
        used.add(unicodedata.normalize("NFKC", name))
        names.append(name)
    return names


def _event_doc(entry: xdr.SCSpecEventV0, param_names: List[str]) -> str:
    lines = []
    if entry.doc:
        lines.append(entry.doc.decode())

    documented_params = [
        (param, param_name)
        for param, param_name in zip(entry.params, param_names)
        if param.doc
    ]
    if documented_params:
        if lines:
            lines.append("")
        lines.append("Attributes:")
        for param, param_name in documented_params:
            wire_name = param.name.decode()
            name_note = f" (wire name {wire_name!r})" if param_name != wire_name else ""
            lines.append(f"    {param_name}{name_note}: {param.doc.decode()}")
    return "\n".join(lines)


def render_event(
    entry: xdr.SCSpecEventV0,
    class_name: str,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    prefix_symbols = [s.sc_symbol.decode() for s in entry.prefix_topics]
    data_format = entry.data_format
    data_params = [
        param
        for param in entry.params
        if param.location
        == xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_DATA
    ]
    if (
        data_format == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
        and len(data_params) > 1
    ):
        raise ValueError(
            "SINGLE_VALUE events may declare at most one data parameter; "
            f"{entry.name.sc_symbol.decode()!r} declares {len(data_params)}"
        )

    param_names = resolve_event_param_names(entry)
    params = []
    topic_params = []
    required_data_keys: List[str] = []
    topic_index = len(prefix_symbols)
    data_index = 0
    for p, py_name in zip(entry.params, param_names):
        chain_name = p.name.decode()
        py_type = to_py_type(p.type, resolve_udt_name=resolve_udt_name)
        if (
            p.location
            == xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
        ):
            parse_expr = from_scval(p.type, f"topics[{topic_index}]", resolve_udt_name)
            topic_index += 1
            topic_params.append(
                {
                    "py_name": py_name,
                    "input_type": to_py_type(
                        p.type, input_type=True, resolve_udt_name=resolve_udt_name
                    ),
                    "filter_expr": to_scval(p.type, py_name, resolve_udt_name),
                }
            )
        elif (
            data_format
            == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
        ):
            parse_expr = from_scval(p.type, "data", resolve_udt_name)
        elif data_format == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC:
            parse_expr = from_scval(p.type, f"_data[{data_index}]", resolve_udt_name)
            data_index += 1
        elif data_format == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP:
            # SEP-48 requires the map to carry every declared parameter, but an
            # emitter may omit one declared as an option: SEP-41 permits SAC
            # ``to_muxed_id`` to be absent when there is no muxed ID, and the
            # SAC spec indeed declares it as an option. Absent optionals become
            # None; a missing required entry is rejected in parse() instead of
            # silently yielding a half-populated event.
            value_expr = f"_data[{chain_name!r}]"
            if p.type.type == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
                parse_expr = (
                    f"({from_scval(p.type, value_expr, resolve_udt_name)}) "
                    f"if {chain_name!r} in _data else None"
                )
            else:
                parse_expr = from_scval(p.type, value_expr, resolve_udt_name)
                required_data_keys.append(chain_name)
        else:
            raise ValueError(f"Unsupported event data format: {data_format}")
        params.append(
            {
                "py_name": py_name,
                "py_type": py_type,
                "parse_expr": parse_expr,
            }
        )
    has_vec_data = data_format == (
        xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC
    )
    has_map_data = data_format == (
        xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP
    )
    validate_void_data = (
        data_format == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
        and not data_params
    )
    event_doc = _event_doc(entry, param_names)

    template = """
class {{ class_name }}:
    {%- if event_doc %}
    __doc__ = {{ event_doc }}
    {%- endif %}
    EVENT_NAME = {{ event_name }}

    {%- for p in params %}
    {{ p.py_name }}: {{ p.py_type }}
    {%- endfor %}

    def __init__(self{% for p in params %}, {{ p.py_name }}: {{ p.py_type }}{% endfor %}):
        {%- for p in params %}
        self.{{ p.py_name }} = {{ p.py_name }}
        {%- else %}
        pass
        {%- endfor %}

    @classmethod
    def topic_filter(
        cls{% if topic_params %},
        *,
        {%- for p in topic_params %}
        {{ p.py_name }}: Union[{{ p.input_type }}, EllipsisType] = ...,
        {%- endfor %}
        {%- endif %}
    ) -> List[str]:
        '''Build one topics row for ``SorobanServer.get_events``.

        Omitted topic parameters are emitted as ``"*"`` wildcards. The row ends
        with ``"**"`` so that, like ``matches()``, it also selects events
        carrying extra trailing topics beyond the SEP-48 declaration. Without
        it the RPC matches on the exact topic count and such events are
        silently skipped. ``"**"`` requires stellar-rpc v23.0.0 or newer, which
        is also the release that introduced SEP-48 event specs; it is excluded
        from the four-segment filter limit.
        '''
        return [
            {%- for s in prefix_symbols %}
            scval.to_symbol({{ s }}).to_xdr(),
            {%- endfor %}
            {%- for p in topic_params %}
            "*" if {{ p.py_name }} is ... else ({{ p.filter_expr }}).to_xdr(),
            {%- endfor %}
            "**",
        ]

    @classmethod
    def matches(cls, event: {{ event_input_type }}) -> bool:
        '''Returns True if the event topics match this event's shape.

        Extra trailing topics beyond the declared parameters are ignored:
        on-chain events may append topics that are not part of the SEP-48
        declaration (e.g. Stellar Asset Contract events append the SEP-11
        asset string).
        '''
        try:
            topics, _ = _event_topics_and_data(event)
        except Exception:
            return False
        if len(topics) < {{ total_topics }}:
            return False
        {%- for s in prefix_symbols %}
        if not _static_topic_matches(topics[{{ loop.index0 }}], {{ s }}):
            return False
        {%- endfor %}
        return True

    @classmethod
    def parse(cls, event: {{ event_input_type }}) -> {{ class_name }}:
        '''Parse the event into a {{ class_name }}.

        :raises ValueError: If the event does not match this event's shape.
        '''
        # Decode once and hand matches() the normalized pair; matches() would
        # otherwise decode the raw event a second time.
        topics, data = _event_topics_and_data(event)
        if not cls.matches((topics, data)):
            raise ValueError('event does not match {{ class_name }}')
        {%- if validate_void_data %}
        scval.from_void(data)
        {%- endif %}
        {%- if has_vec_data %}
        _data = scval.from_vec(data)
        if len(_data) < {{ data_param_count }}:
            raise ValueError("event data vector has fewer values than declared")
        {%- endif %}
        {%- if has_map_data %}
        _data = scval.from_struct(data)
        {%- if required_data_keys %}
        _missing = [_k for _k in [{{ required_data_keys | join(', ') }}] if _k not in _data]
        if _missing:
            raise ValueError(f"event data map is missing required entries: {_missing}")
        {%- endif %}
        {%- endif %}
        return cls(
            {%- for p in params %}
            {{ p.py_name }}={{ p.parse_expr }},
            {%- endfor %}
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, {{ class_name }}):
            return NotImplemented
        return {% for p in params %}self.{{ p.py_name }} == other.{{ p.py_name }}{% if not loop.last %} and {% endif %}{% else %}True{% endfor %}

    def __hash__(self) -> int:
        return hash(({% for p in params %}self.{{ p.py_name }}, {% endfor %}))

    def __repr__(self):
        return f"<{{ class_name }} [{% for p in params %}{{ p.py_name }}={self.{{ p.py_name }}}{% if not loop.last %}, {% endif %}{% endfor %}]>"
"""
    rendered_code = Template(template).render(
        class_name=class_name,
        event_doc=repr(event_doc) if event_doc else None,
        event_name=repr(entry.name.sc_symbol.decode()),
        prefix_symbols=[repr(symbol) for symbol in prefix_symbols],
        total_topics=declared_topic_count(entry),
        params=params,
        topic_params=topic_params,
        event_input_type=(
            "Union[xdr.ContractEvent, EventInfo, "
            "Tuple[Sequence[Union[xdr.SCVal, str, bytes]], "
            "Union[xdr.SCVal, str, bytes]]]"
        ),
        has_vec_data=has_vec_data,
        has_map_data=has_map_data,
        required_data_keys=[repr(key) for key in required_data_keys],
        validate_void_data=validate_void_data,
        data_param_count=len(data_params),
    )
    return rendered_code


def render_event_dispatcher(
    entries: List[xdr.SCSpecEventV0], class_names: List[str], union_name: str = "Event"
):
    # Try the most specific declaration (most declared topics) first, so a
    # shorter declaration sharing the same prefix cannot swallow events of a
    # longer one via the extra-trailing-topics tolerance. Ties keep spec order.
    ordered_names = [
        name
        for _, name in sorted(
            zip(entries, class_names),
            key=lambda pair: -declared_topic_count(pair[0]),
        )
    ]
    template = """
{{ union_name }} = Union[{{ class_names | join(', ') }}]

_EVENTS = [{{ ordered_names | join(', ') }}]

def parse_event(
    event: {{ event_input_type }},
    raise_on_unparsed: bool = False,
) -> Optional[{{ union_name }}]:
    '''Parse an event emitted by this contract into a typed event object.

    Candidates are tried most-specific first (most declared topics), then in
    spec order; failures of intermediate candidates are part of that normal
    disambiguation flow. Returns None if no declared event matches the topics.

    If the topics match at least one declared event but every candidate fails
    to parse, the event format has likely drifted from the spec these bindings
    were generated from. That state is reported: a warning is logged by
    default, or :class:`UnparsedEventError` is raised when ``raise_on_unparsed``
    is True.
    '''
    failures: List[Tuple[type, Exception]] = []
    # Decode the event once here rather than once per candidate: RPC events
    # arrive as base64 XDR, and every candidate would otherwise re-decode all
    # of the topics before rejecting them on the first one.
    try:
        _decoded = _event_topics_and_data(event)
    except Exception:
        return None
    for _event_cls in _EVENTS:
        if _event_cls.matches(_decoded):
            try:
                return _event_cls.parse(_decoded)
            except Exception as exc:
                failures.append((_event_cls, exc))
    if failures:
        details = "; ".join(f"{cls.__name__}: {exc!r}" for cls, exc in failures)
        message = (
            f"event topics matched {len(failures)} declared event(s) but none parsed "
            f"successfully ({details}); the on-chain event format may have drifted "
            f"from the spec these bindings were generated from"
        )
        if raise_on_unparsed:
            raise UnparsedEventError(message, failures) from failures[-1][1]
        _logger.warning(message)
    return None
"""
    rendered_code = Template(template).render(
        class_names=class_names,
        ordered_names=ordered_names,
        union_name=union_name,
        event_input_type=(
            "Union[xdr.ContractEvent, EventInfo, "
            "Tuple[Sequence[Union[xdr.SCVal, str, bytes]], "
            "Union[xdr.SCVal, str, bytes]]]"
        ),
    )
    return rendered_code


def render_client(
    entries: List[xdr.SCSpecFunctionV0],
    client_type: str,
    resolve_udt_name: UdtNameResolver = _default_udt_name,
):
    template = '''
{%- if client_type == "sync" or client_type == "both" %}
class Client(ContractClient):
    {%- for entry in entries %}
    def {{ entry.name.sc_symbol.decode() }}(self, {% for param in entry.inputs %}{{ param.name.decode() }}: {{ to_py_type(param.type, True) }}, {% endfor %} source: Union[str, MuxedAccount] = NULL_ACCOUNT, signer: Optional[Keypair] = None, base_fee: int = 100, transaction_timeout: int = 300, submit_timeout: int = 30, simulate: bool = True, restore: bool = True) -> AssembledTransaction[{{ parse_result_type(entry.outputs) }}]:
        {%- if entry.doc %}
        """{{ entry.doc.decode() }}"""
        {%- endif %}
        return self.invoke('{{ entry.name.sc_symbol_r.decode() if entry.name.sc_symbol_r else entry.name.sc_symbol.decode() }}', [{% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}], parse_result_xdr_fn={{ parse_result_xdr_fn(entry.outputs) }}, source = source, signer = signer, base_fee = base_fee, transaction_timeout = transaction_timeout, submit_timeout = submit_timeout, simulate = simulate, restore = restore)
    {%- else %}
    pass
    {%- endfor %}
{%- endif %}

{%- if client_type == "async" or client_type == "both" %}
class ClientAsync(ContractClientAsync):
    {%- for entry in entries %}
    async def {{ entry.name.sc_symbol.decode() }}(self, {% for param in entry.inputs %}{{ param.name.decode() }}: {{ to_py_type(param.type, True) }}, {% endfor %} source: Union[str, MuxedAccount] = NULL_ACCOUNT, signer: Optional[Keypair] = None, base_fee: int = 100, transaction_timeout: int = 300, submit_timeout: int = 30, simulate: bool = True, restore: bool = True) -> AssembledTransactionAsync[{{ parse_result_type(entry.outputs) }}]:
        {%- if entry.doc %}
        """{{ entry.doc.decode() }}"""
        {%- endif %}
        return await self.invoke('{{ entry.name.sc_symbol_r.decode() if entry.name.sc_symbol_r else entry.name.sc_symbol.decode() }}', [{% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}], parse_result_xdr_fn={{ parse_result_xdr_fn(entry.outputs) }}, source = source, signer = signer, base_fee = base_fee, transaction_timeout = transaction_timeout, submit_timeout = submit_timeout, simulate = simulate, restore = restore)
    {%- else %}
    pass
    {%- endfor %}
{%- endif %}
'''

    def function_output(td: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
        """Strip a top-level Result wrapper from a function's return type.

        A contract function declared ``Result<T, E>`` never hands back an
        SCV_ERROR on success: returning ``Err`` traps the invocation, and the
        SDK surfaces that as an exception (e.g. SimulationFailedError). So the
        value reaching parse_result_xdr_fn is always the Ok arm. Nested Result
        values keep both arms, since those really can carry an SCV_ERROR.
        """
        if td.type == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            return td.result.ok_type
        return td

    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "None"
        elif len(output) == 1:
            return to_py_type(
                function_output(output[0]), resolve_udt_name=resolve_udt_name
            )
        else:
            return f"Tuple[{', '.join([to_py_type(function_output(t), resolve_udt_name=resolve_udt_name) for t in output])}]"

    def parse_result_xdr_fn(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "lambda _: None"
        elif len(output) == 1:
            return f'lambda v: {from_scval(function_output(output[0]), "v", resolve_udt_name)}'
        else:
            raise NotImplementedError(
                "Tuple return type is not supported, please report this issue"
            )

    client_rendered_code = Template(template).render(
        entries=entries,
        to_py_type=lambda td, input_type=False: to_py_type(
            td, input_type, resolve_udt_name
        ),
        to_scval=lambda td, name: to_scval(td, name, resolve_udt_name),
        parse_result_type=parse_result_type,
        parse_result_xdr_fn=parse_result_xdr_fn,
        client_type=client_type,
    )
    return client_rendered_code


# append _ to keyword
def append_underscore(specs: List[xdr.SCSpecEntry]):
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            assert spec.udt_struct_v0 is not None
            if keyword.iskeyword(spec.udt_struct_v0.name.decode()):
                spec.udt_struct_v0.name_r = spec.udt_struct_v0.name  # type: ignore[attr-defined]
                spec.udt_struct_v0.name = spec.udt_struct_v0.name + b"_"
            for field in spec.udt_struct_v0.fields:
                if keyword.iskeyword(field.name.decode()):
                    field.name_r = field.name  # type: ignore[attr-defined]
                    field.name = field.name + b"_"
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            assert spec.udt_union_v0 is not None
            if keyword.iskeyword(spec.udt_union_v0.name.decode()):
                spec.udt_union_v0.name_r = spec.udt_union_v0.name  # type: ignore[attr-defined]
                spec.udt_union_v0.name = spec.udt_union_v0.name + b"_"
            for union_case in spec.udt_union_v0.cases:
                if (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
                ):
                    if keyword.iskeyword(union_case.tuple_case.name.decode()):
                        union_case.tuple_case.name_r = union_case.tuple_case.name  # type: ignore[attr-defined]
                        union_case.tuple_case.name = union_case.tuple_case.name + b"_"
                elif (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
                ):
                    if keyword.iskeyword(union_case.void_case.name.decode()):
                        union_case.void_case.name_r = union_case.void_case.name  # type: ignore[attr-defined]
                        union_case.void_case.name = union_case.void_case.name + b"_"
                else:
                    raise ValueError(f"Unsupported union case kind: {union_case.kind}")
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            assert spec.function_v0 is not None
            if keyword.iskeyword(spec.function_v0.name.sc_symbol.decode()):
                spec.function_v0.name.sc_symbol_r = spec.function_v0.name.sc_symbol  # type: ignore[attr-defined]
                spec.function_v0.name.sc_symbol = spec.function_v0.name.sc_symbol + b"_"
            for param in spec.function_v0.inputs:
                if keyword.iskeyword(param.name.decode()):
                    param.name = param.name + b"_"
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            assert spec.udt_enum_v0 is not None
            if keyword.iskeyword(spec.udt_enum_v0.name.decode()):
                spec.udt_enum_v0.name_r = spec.udt_enum_v0.name  # type: ignore[attr-defined]
                spec.udt_enum_v0.name = spec.udt_enum_v0.name + b"_"
            for enum_case in spec.udt_enum_v0.cases:
                if keyword.iskeyword(enum_case.name.decode()):
                    enum_case.name = enum_case.name + b"_"
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            assert spec.udt_error_enum_v0 is not None
            if keyword.iskeyword(spec.udt_error_enum_v0.name.decode()):
                spec.udt_error_enum_v0.name_r = spec.udt_error_enum_v0.name  # type: ignore[attr-defined]
                spec.udt_error_enum_v0.name = spec.udt_error_enum_v0.name + b"_"
            for error_enum_case in spec.udt_error_enum_v0.cases:
                if keyword.iskeyword(error_enum_case.name.decode()):
                    error_enum_case.name = error_enum_case.name + b"_"


def generate_binding_with_diagnostics(
    specs: List[xdr.SCSpecEntry], client_type: str
) -> Tuple[str, List[str]]:
    """Generate bindings plus printable notes about duplicate or renamed events.

    ``client_type`` is "sync", "async" or "both"; anything else (the tests and
    the corpus checker pass "none") skips client generation entirely.
    """
    append_underscore(specs)

    event_specs: List[xdr.SCSpecEventV0] = [
        spec.event_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0
    ]
    udt_names = resolve_udt_names(specs)
    resolve_udt_name = _udt_reference_resolver(udt_names)

    generated = []
    diagnostics: List[str] = []

    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            name = udt_names[spec.udt_enum_v0.name.decode()]
            generated.append(render_enum(spec.udt_enum_v0, name))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            name = udt_names[spec.udt_error_enum_v0.name.decode()]
            generated.append(render_error_enum(spec.udt_error_enum_v0, name))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            name = udt_names[spec.udt_struct_v0.name.decode()]
            if is_tuple_struct(spec.udt_struct_v0):
                generated.append(
                    render_tuple_struct(spec.udt_struct_v0, name, resolve_udt_name)
                )
            else:
                generated.append(
                    render_struct(spec.udt_struct_v0, name, resolve_udt_name)
                )
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            name = udt_names[spec.udt_union_v0.name.decode()]
            generated.append(render_union(spec.udt_union_v0, name, resolve_udt_name))

    if event_specs:
        event_class_names, event_union_name = resolve_event_names(
            specs, event_specs, udt_names
        )
        diagnostics = event_diagnostics(event_specs, event_class_names)
        generated.append(render_event_helpers())
        for event_spec, event_cls_name in zip(event_specs, event_class_names):
            generated.append(render_event(event_spec, event_cls_name, resolve_udt_name))
        generated.append(
            render_event_dispatcher(
                event_specs, event_class_names, union_name=event_union_name
            )
        )

    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    generated.append(render_client(function_specs, client_type, resolve_udt_name))

    body = "\n".join(generated)
    header = [
        render_info(),
        render_imports(client_type, has_events=bool(event_specs)),
    ]
    # Error enums and SC_SPEC_TYPE_ERROR values are the only users of the
    # error helper, and both are rare; emit it only when the body calls it.
    if "_from_error_scval(" in body:
        header.append(render_scval_helpers())
    return "\n".join(header + [body]), diagnostics


def generate_binding(specs: List[xdr.SCSpecEntry], client_type: str) -> str:
    return generate_binding_with_diagnostics(specs, client_type)[0]


@click.command(name="python")
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
    "--client-type",
    type=click.Choice(["sync", "async", "both"], case_sensitive=False),
    default="both",
    help="Client type to generate, defaults to both sync and async",
)
def command(contract_id: str, rpc_url: str, output: str, client_type: str):
    """Generate Python bindings for a Soroban contract"""
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

    click.echo("Generating Python bindings")
    generated, diagnostics = generate_binding_with_diagnostics(
        specs, client_type=client_type
    )
    for diagnostic in diagnostics:
        click.echo(diagnostic, err=True)
    try:
        generated = black.format_str(generated, mode=black.Mode())
    except Exception as e:
        click.echo(
            f"formatting failed, there may be issues with the generated binding, please report to us: {e}",
            err=True,
        )
        raise click.Abort()

    if not os.path.exists(output):
        os.makedirs(output)
    output_path = os.path.join(output, "bindings.py")
    with open(output_path, "w") as f:
        f.write(generated)
    click.echo(f"Generated Python bindings to {output_path}")


if __name__ == "__main__":
    from stellar_contract_bindings.utils import get_specs_by_wasm_file

    wasm_file = "/Users/overcat/repo/lightsail/stellar-contract-bindings/tests/contracts/target/wasm32v1-none/release/python.wasm"
    specs = get_specs_by_wasm_file(wasm_file)
    generated = generate_binding(specs, client_type="both")
    print(black.format_str(generated, mode=black.Mode()))
