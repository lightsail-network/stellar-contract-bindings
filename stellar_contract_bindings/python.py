import os
from typing import List

import click
from jinja2 import Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.metadata import parse_contract_metadata
from stellar_contract_bindings.utils import (
    get_wasm_hash_by_contract_id,
    get_contract_wasm_by_hash,
)


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


def to_py_type(td: xdr.SCSpecTypeDef, input_type: bool = False):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return "xdr.SCVal"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return "bool"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "None"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
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
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return "Union[Address, str]" if input_type else "Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"Optional[{to_py_type(td.option.value_type, input_type)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return to_py_type(ok_t, input_type)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List[{to_py_type(td.vec.element_type, input_type)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Dict[{to_py_type(td.map.key_type, input_type)}, {to_py_type(td.map.value_type, input_type)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            # () equivalent to None in Python
            return "None"
        types = [to_py_type(t, input_type) for t in td.tuple.value_types]
        return f"Tuple[{', '.join(types)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"bytes"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return td.udt.name.decode()
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"scval.to_bool({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"scval.to_void()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
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
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"scval.to_address({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{to_scval(td.option.value_type, name)} if {name} is not None else scval.to_void()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return NotImplementedError("SC_SPEC_TYPE_RESULT is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"scval.to_vec([{to_scval(td.vec.element_type, 'e')} for e in {name}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"scval.to_map({{{to_scval(td.map.key_type, 'k')}: {to_scval(td.map.value_type, 'v')} for k, v in {name}.items()}})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        types = [
            to_scval(t, f"{name}[{i}]") for i, t in enumerate(td.tuple.value_types)
        ]
        return f"scval.to_tuple_struct([{', '.join(types)}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"scval.to_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.to_scval()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"scval.from_bool({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"scval.from_void()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
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
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS:
        return f"scval.from_address({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{from_scval(td.option.value_type, name)} if {name}.type != xdr.SCValType.SCV_VOID else scval.from_void({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return f"{from_scval(ok_t, name)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return (
            f"[{from_scval(td.vec.element_type, 'e')} for e in scval.from_vec({name})]"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"{{{from_scval(td.map.key_type, 'k')}: {from_scval(td.map.value_type, 'v')} for k, v in scval.from_map({name}).items()}}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "None"
        elements = f"scval.from_tuple_struct({name})"
        types = [
            from_scval(t, f"{elements}[{i}]")
            for i, t in enumerate(td.tuple.value_types)
        ]
        return f"({', '.join(types)})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"scval.from_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{td.udt.name.decode()}.from_scval({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_info():
    return (
        f"# This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version} and stellar_sdk v{stellar_sdk_version}.\n"
        f"# Client is used to interact with the contract on the Stellar network synchronously,\n"
        f"# while ClientAsync is used to interact with the contract on the Stellar network asynchronously.\n"
        f"# If you don't need to interact with the contract asynchronously, you can remove the ClientAsync class and its methods."
    )


def render_imports(client_type: str = "both"):
    template = """
from enum import IntEnum, Enum
from typing import Dict, List, Tuple, Optional, Union

from stellar_sdk import scval, xdr, Address, MuxedAccount, Keypair
{%- if client_type == "sync" or client_type == "both" %}
from stellar_sdk.contract import AssembledTransaction, ContractClient
{%- endif %}
{%- if client_type == "async" or client_type == "both" %}
from stellar_sdk.contract import AssembledTransactionAsync, ContractClientAsync
{%- endif %}

NULL_ACCOUNT = "GAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWHF"
"""
    rendered_code = Template(template).render(client_type=client_type)
    return rendered_code


def render_enum(entry: xdr.SCSpecUDTEnumV0):
    template = """
class {{ entry.name.decode() }}(IntEnum):
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

    rendered_code = Template(template).render(entry=entry)
    return rendered_code


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0):
    template = """
class {{ entry.name.decode() }}(IntEnum):
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

    rendered_code = Template(template).render(entry=entry)
    return rendered_code


def render_struct(entry: xdr.SCSpecUDTStructV0):
    template = """
class {{ entry.name.decode() }}:
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
            '{{ field.name.decode() }}': {{ to_scval(field.type, 'self.' ~ field.name.decode()) }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        })

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_struct(val)
        return cls(
            {%- for index, field in enumerate(entry.fields) %}
            {{ from_scval(field.type, 'elements["' ~ field.name.decode() ~ '"]') }}{% if not loop.last %},{% endif %}
            {%- endfor %}
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, {{ entry.name.decode() }}):
            return NotImplemented
        return {% for field in entry.fields %}self.{{ field.name.decode() }} == other.{{ field.name.decode() }}{% if not loop.last %} and {% endif %}{% endfor %}

    def __hash__(self) -> int:
        return hash(({% for field in entry.fields %}self.{{ field.name.decode() }}{% if not loop.last %}, {% endif %}{% endfor %}))
"""

    rendered_code = Template(template).render(
        entry=entry,
        to_py_type=to_py_type,
        to_scval=to_scval,
        from_scval=from_scval,
        enumerate=enumerate,
    )
    return rendered_code


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0):
    template = """
class {{ entry.name.decode() }}:
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
        if not isinstance(other, {{ entry.name.decode() }}):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)
"""

    rendered_code = Template(template).render(
        entry=entry, to_py_type=to_py_type, to_scval=to_scval, from_scval=from_scval
    )
    return rendered_code


def render_union(entry: xdr.SCSpecUDTUnionV0):
    kind_enum_template = """
class {{ entry.name.decode() }}Kind(Enum):
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
    {{ case.void_case.name.decode() }} = '{{ case.void_case.name.decode() }}'
    {%- else %}
    {{ case.tuple_case.name.decode() }} = '{{ case.tuple_case.name.decode() }}'
    {%- endif %}
    {%- endfor %}
"""

    kind_enum_rendered_code = Template(kind_enum_template).render(entry=entry, xdr=xdr)

    template = """
class {{ entry.name.decode() }}:
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}
    def __init__(self,
        kind: {{ entry.name.decode() }}Kind,
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
        if self.kind == {{ entry.name.decode() }}Kind.{{ case.void_case.name.decode() }}:
            return scval.to_enum(self.kind.name, None)
        {%- else %}
        if self.kind == {{ entry.name.decode() }}Kind.{{ case.tuple_case.name.decode() }}:
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
    
    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_enum(val)
        kind = {{ entry.name.decode() }}Kind(elements[0])
        
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        if kind == {{ entry.name.decode() }}Kind.{{ case.void_case.name.decode() }}:
            return cls(kind)
        {%- else %}
        if kind == {{ entry.name.decode() }}Kind.{{ case.tuple_case.name.decode() }}:
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
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, {{ entry.name.decode() }}):
            return NotImplemented
        if self.kind != other.kind:
            return False
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
        if self.kind == {{ entry.name.decode() }}Kind.{{ case.tuple_case.name.decode() }}:
            return self.{{ camel_to_snake(case.tuple_case.name.decode()) }} == other.{{ camel_to_snake(case.tuple_case.name.decode()) }}
        {%- endif %}
        {%- endfor %}
        return True

    def __hash__(self) -> int:
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
        if self.kind == {{ entry.name.decode() }}Kind.{{ case.tuple_case.name.decode() }}:
            return hash((self.kind, self.{{ camel_to_snake(case.tuple_case.name.decode()) }}))
        {%- endif %}
        {%- endfor %}
        return hash(self.kind)
"""
    union_rendered_code = Template(template).render(
        entry=entry,
        to_py_type=to_py_type,
        to_scval=to_scval,
        from_scval=from_scval,
        xdr=xdr,
        len=len,
        camel_to_snake=camel_to_snake,
        enumerate=enumerate,
    )
    return kind_enum_rendered_code + "\n" + union_rendered_code


def render_client(entries: List[xdr.SCSpecFunctionV0], client_type: str):
    template = '''
{%- if client_type == "sync" or client_type == "both" %}
class Client(ContractClient):
    {%- for entry in entries %}
    def {{ entry.name.sc_symbol.decode() }}(self, {% for param in entry.inputs %}{{ param.name.decode() }}: {{ to_py_type(param.type, True) }}, {% endfor %} source: Union[str, MuxedAccount] = NULL_ACCOUNT, signer: Optional[Keypair] = None, base_fee: int = 100, transaction_timeout: int = 300, submit_timeout: int = 30, simulate: bool = True, restore: bool = True) -> AssembledTransaction[{{ parse_result_type(entry.outputs) }}]:
        {%- if entry.doc %}
        """{{ entry.doc.decode() }}"""
        {%- endif %}
        return self.invoke('{{ entry.name.sc_symbol.decode() }}', [{% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}], parse_result_xdr_fn={{ parse_result_xdr_fn(entry.outputs) }}, source = source, signer = signer, base_fee = base_fee, transaction_timeout = transaction_timeout, submit_timeout = submit_timeout, simulate = simulate, restore = restore)
    {%- endfor %}
{%- endif %}

{%- if client_type == "async" or client_type == "both" %}
class ClientAsync(ContractClientAsync):
    {%- for entry in entries %}
    async def {{ entry.name.sc_symbol.decode() }}(self, {% for param in entry.inputs %}{{ param.name.decode() }}: {{ to_py_type(param.type, True) }}, {% endfor %} source: Union[str, MuxedAccount] = NULL_ACCOUNT, signer: Optional[Keypair] = None, base_fee: int = 100, transaction_timeout: int = 300, submit_timeout: int = 30, simulate: bool = True, restore: bool = True) -> AssembledTransactionAsync[{{ parse_result_type(entry.outputs) }}]:
        {%- if entry.doc %}
        """{{ entry.doc.decode() }}"""
        {%- endif %}
        return await self.invoke('{{ entry.name.sc_symbol.decode() }}', [{% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}], parse_result_xdr_fn={{ parse_result_xdr_fn(entry.outputs) }}, source = source, signer = signer, base_fee = base_fee, transaction_timeout = transaction_timeout, submit_timeout = submit_timeout, simulate = simulate, restore = restore)
    {%- endfor %}
{%- endif %}
'''

    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "None"
        elif len(output) == 1:
            return to_py_type(output[0])
        else:
            return f"Tuple[{', '.join([to_py_type(t) for t in output])}]"

    def parse_result_xdr_fn(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "lambda _: None"
        elif len(output) == 1:
            return f'lambda v: {from_scval(output[0], "v")}'
        else:
            raise NotImplementedError(
                "Tuple return type is not supported, please report this issue"
            )

    client_rendered_code = Template(template).render(
        entries=entries,
        to_py_type=to_py_type,
        to_scval=to_scval,
        parse_result_type=parse_result_type,
        parse_result_xdr_fn=parse_result_xdr_fn,
        client_type=client_type,
    )
    return client_rendered_code


def generate_binding(wasm: bytes, client_type: str) -> str:
    generated = []
    generated.append(render_info())

    metadata = parse_contract_metadata(wasm)
    specs = metadata.spec

    generated.append(render_imports(client_type))

    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            generated.append(render_enum(spec.udt_enum_v0))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            generated.append(render_error_enum(spec.udt_error_enum_v0))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            if is_tuple_struct(spec.udt_struct_v0):
                generated.append(render_tuple_struct(spec.udt_struct_v0))
            else:
                generated.append(render_struct(spec.udt_struct_v0))
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            generated.append(render_union(spec.udt_union_v0))

    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    generated.append(render_client(function_specs, client_type))
    return "\n".join(generated)


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
        wasm_id = get_wasm_hash_by_contract_id(contract_id, rpc_url)
        click.echo(f"Got wasm id: {wasm_id.hex()}")
        wasm_code = get_contract_wasm_by_hash(wasm_id, rpc_url)
        click.echo(f"Got wasm code")
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Abort()

    click.echo("Generating Python bindings")
    generated = generate_binding(wasm_code, client_type=client_type)
    if not os.path.exists(output):
        os.makedirs(output)
    output_path = os.path.join(output, "bindings.py")
    with open(output_path, "w") as f:
        f.write(generated)
    click.echo(f"Generated Python bindings to {output_path}")
    click.echo(
        f"We recommend running `black {output_path}` to format the generated code."
    )


if __name__ == "__main__":
    wasm_file = "/Users/overcat/repo/lightsail/stellar-contract-bindings/tests/contracts/target/wasm32-unknown-unknown/release/python.wasm"
    with open(wasm_file, "rb") as f:
        wasm = f.read()
    generated_code = generate_binding(wasm, "both")
    print(generated_code)
