from typing import List

from jinja2 import Template
from stellar_sdk import xdr

from metadata import parse_contract_metadata


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


def to_py_type(td: xdr.SCSpecTypeDef):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        # TODO: u64?
        return "int"
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
        return "Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"Optional[{to_py_type(td.option.value_type)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        t = td.result.ok_type
        return to_py_type(t)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List[{to_py_type(td.vec.element_type)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Dict[{to_py_type(td.map.key_type)}, {to_py_type(td.map.value_type)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        types = [to_py_type(t) for t in td.tuple.value_types]
        return f"Tuple[{', '.join(types)}]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"bytes"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return td.udt.name.decode()
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        raise NotImplementedError("SC_SPEC_TYPE_VAL is not supported")
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
        types = [to_scval(t, f"{name}[{i}]") for i, t in enumerate(td.tuple.value_types)]
        return f"scval.to_tuple_struct([{', '.join(types)}])"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"scval.to_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.to_scval()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        raise NotImplementedError("SC_SPEC_TYPE_VAL is not supported")
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
        return f"[{from_scval(td.vec.element_type, 'e')} for e in scval.from_vec({name})]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"{{{from_scval(td.map.key_type, 'k')}: {from_scval(td.map.value_type, 'v')} for k, v in scval.from_map({name}).items()}}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        elements = f"scval.from_tuple_struct({name})"
        types = [from_scval(t, f"{elements}[{i}]") for i, t in enumerate(td.tuple.value_types)]
        return f"({', '.join(types)})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"scval.from_bytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{td.udt.name.decode()}.from_scval({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_imports():
    template = """
from enum import IntEnum, Enum
from typing import Dict, List, Tuple, Optional

from stellar_sdk import scval, xdr, Address
from stellar_sdk.contract import AssembledTransaction, ContractClient
"""
    print(template)


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

    template = Template(template)
    rendered_code = template.render(entry=entry)
    print(rendered_code)


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

    template = Template(template)
    rendered_code = template.render(entry=entry)
    print(rendered_code)


def render_struct(entry: xdr.SCSpecUDTStructV0):
    template = """
class {{ entry.name.decode() }}:
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}
    {%- for field in entry.fields %}
    {{ field.name.decode() }}: {{ to_py_type(field.type) }}
    {%- endfor %}

    def __init__(self, {% for field in entry.fields %}{{ field.name.decode() }}: {{ to_py_type(field.type) }}{% if not loop.last %}, {% endif %}{% endfor %}):
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

    template = Template(template)
    rendered_code = template.render(
        entry=entry, to_py_type=to_py_type, to_scval=to_scval, from_scval=from_scval, enumerate=enumerate
    )
    print(rendered_code)


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0):
    template = """
class {{ entry.name.decode() }}:
    {%- if entry.doc %}
    '''{{ entry.doc.decode() }}'''
    {%- endif %}

    def __init__(self, value: Tuple[{% for f in entry.fields %}{{ to_py_type(f.type) }}{% if not loop.last %}, {% endif %}{% endfor %}]):
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

    template = Template(template)
    rendered_code = template.render(
        entry=entry, to_py_type=to_py_type, to_scval=to_scval, from_scval=from_scval
    )
    print(rendered_code)


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

    kind_enum_template = Template(kind_enum_template)
    rendered_code = kind_enum_template.render(entry=entry, xdr=xdr)
    print(rendered_code)

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
        {{ camel_to_snake(case.tuple_case.name.decode()) }}: Optional[{{ to_py_type(case.tuple_case.type[0]) }}] = None,
        {%- else %}
        {{ camel_to_snake(case.tuple_case.name.decode()) }}: Optional[Tuple[{% for f in case.tuple_case.type %}{{ to_py_type(f) }}{% if not loop.last %}, {% endif %}{% endfor %}]] = None,
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
            return scval.to_enum(self.kind.name, {{ to_scval(case.tuple_case.type[0], 'self.' ~ camel_to_snake(case.tuple_case.name.decode())) }})
        {%- else %}
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
            return cls(kind, {{ camel_to_snake(case.tuple_case.name.decode()) }}={{ from_scval(case.tuple_case.type[0], 'elements[1]') }})
        {%- else %}
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
    template = Template(template)
    rendered_code = template.render(
        entry=entry,
        to_py_type=to_py_type,
        to_scval=to_scval,
        from_scval=from_scval,
        xdr=xdr,
        len=len,
        camel_to_snake=camel_to_snake,
        enumerate=enumerate
    )
    print(rendered_code)


def render_client(entries: List[xdr.SCSpecFunctionV0]):
    template = '''
class Client(ContractClient):
    {%- for entry in entries %}
    def {{ entry.name.sc_symbol.decode() }}(self, {% for param in entry.inputs %}{{ param.name.decode() }}: {{ to_py_type(param.type) }}{% if not loop.last %}, {% endif %}{% endfor %}) -> AssembledTransaction[{{ parse_result_type(entry.outputs) }}]:
        {%- if entry.doc %}
        """{{ entry.doc.decode() }}"""
        {%- endif %}
        return self.invoke('{{ entry.name.sc_symbol.decode() }}', [{% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}], parse_result_xdr_fn={{ parse_result_xdr_fn(entry.outputs) }})
    {%- endfor %}
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
            raise NotImplementedError("Tuple return type is not supported, please report this issue")

    template = Template(template)
    rendered_code = template.render(
        entries=entries,
        to_py_type=to_py_type,
        to_scval=to_scval,
        parse_result_type=parse_result_type,
        parse_result_xdr_fn=parse_result_xdr_fn
    )
    print(rendered_code)


if __name__ == "__main__":
    wasm_file = "/Users/overcat/repo/lightsail/stellar-contract-bindings/contracts/target/wasm32-unknown-unknown/release/python.wasm"
    with open(wasm_file, "rb") as f:
        wasm = f.read()
    metadata = parse_contract_metadata(wasm)
    specs = metadata.spec

    render_imports()

    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            render_enum(spec.udt_enum_v0)
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            render_error_enum(spec.udt_error_enum_v0)
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            if is_tuple_struct(spec.udt_struct_v0):
                render_tuple_struct(spec.udt_struct_v0)
            else:
                render_struct(spec.udt_struct_v0)
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            render_union(spec.udt_union_v0)

    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
    ]
    render_client(function_specs)
