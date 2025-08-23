import os
import re
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
        "assert",
        "boolean",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extends",
        "final",
        "finally",
        "float",
        "for",
        "goto",
        "if",
        "implements",
        "import",
        "instanceof",
        "int",
        "interface",
        "long",
        "native",
        "new",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "static",
        "strictfp",
        "super",
        "switch",
        "synchronized",
        "this",
        "throw",
        "throws",
        "transient",
        "try",
        "void",
        "volatile",
        "while",
        "true",
        "false",
        "null",
    ]


def is_tuple_struct(entry: xdr.SCSpecUDTStructV0) -> bool:
    # ex. <SCSpecUDTStructV0 [doc=b'', lib=b'', name=b'TupleStruct', fields=[<SCSpecUDTStructFieldV0 [doc=b'', name=b'0', type=<SCSpecTy...>, <SCSpecUDTStructFieldV0 [doc=b'', name=b'1', type=<SCSpecTypeDef [type=2000, udt=<SCSpecTypeUDT [name=b'SimpleEnum']>]>]>]]>
    return all(f.name.isdigit() for f in entry.fields)


def convert_name(text: bytes, first_letter_lower=False) -> bytes:
    text = text.decode()
    if first_letter_lower:
        text = text[0].lower() + text[1:]
    # Convert snake_case to camelCase
    text = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), text)
    if is_keywords(text):
        return f"{text}_".encode()
    return text.encode()


def get_tuple_class_name(amount: int) -> str:
    if amount < 1 or amount > 10:
        raise ValueError("amount should be between 1 and 10")
    return [
        "Unit",
        "Pair",
        "Triplet",
        "Quartet",
        "Quintet",
        "Sextet",
        "Septet",
        "Octet",
        "Ennead",
        "Decade",
    ][amount - 1]


def to_java_type(td: xdr.SCSpecTypeDef, input_type: bool = False):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return "SCVal"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return "Boolean"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "Void"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError("SC_SPEC_TYPE_ERROR is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U32:
        return "Long"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I32:
        return "Integer"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U64:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I64:
        return "Long"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_DURATION:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U128:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I128:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_U256:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_I256:
        return "BigInteger"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES:
        return "byte[]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_STRING:
        return "byte[]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL:
        return "String"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS or t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return "Address"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        raise NotImplementedError("SC_SPEC_TYPE_MUXED_ADDRESS is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return to_java_type(td.option.value_type, input_type)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return to_java_type(ok_t, input_type)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List<{to_java_type(td.vec.element_type, input_type)}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"LinkedHashMap<{to_java_type(td.map.key_type, input_type)}, {to_java_type(td.map.value_type, input_type)}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            # () equivalent to None in Java
            return "Void"
        types = [to_java_type(t, input_type) for t in td.tuple.value_types]
        return f"{get_tuple_class_name(len(types))}<{', '.join(types)}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"byte[]"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return td.udt.name.decode()
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"Scv.toBoolean({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"Scv.toVoid()"
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
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS or t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"Scv.toAddress({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        raise NotImplementedError("SC_SPEC_TYPE_MUXED_ADDRESS is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{name} == null ? Scv.toVoid() : {to_scval(td.option.value_type, name)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return NotImplementedError("SC_SPEC_TYPE_RESULT is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"Scv.toVec({name}.stream().map(e -> {to_scval(td.vec.element_type, 'e')}).collect(Collectors.toList()))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Scv.toMap({name}.entrySet().stream().collect(LinkedHashMap::new, (m, e) -> m.put({to_scval(td.map.key_type, 'e.getKey()')}, {to_scval(td.map.value_type, 'e.getValue()')}), LinkedHashMap::putAll))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        return f"Scv.toVec(Arrays.asList({', '.join([to_scval(t, f'{name}.getValue{i}()') for i, t in enumerate(td.tuple.value_types)])}))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"Scv.toBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.toSCVal()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_BOOL:
        return f"Scv.fromBoolean({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return f"Scv.fromVoid()"
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
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS or t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        return f"Scv.fromAddress({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS:
        raise NotImplementedError("SC_SPEC_TYPE_MUXED_ADDRESS is not supported")
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{name}.getDiscriminant() != SCValType.SCV_VOID ? {from_scval(td.option.value_type, name)} : null"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        ok_t = td.result.ok_type
        return f"{from_scval(ok_t, name)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"Scv.fromVec({name}).stream().map(e -> {from_scval(td.vec.element_type, 'e')}).collect(Collectors.toList())"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return f"Scv.fromMap({name}).entrySet().stream().collect(LinkedHashMap::new, (m, e) -> m.put({from_scval(td.map.key_type, 'e.getKey()')}, {from_scval(td.map.value_type, 'e.getValue()')}), LinkedHashMap::putAll)"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "null"
        return f"new {get_tuple_class_name(len(td.tuple.value_types))}<>({', '.join([from_scval(t, f'Scv.fromVec({name}).toArray(new SCVal[0])[{index}]') for index, t in enumerate(td.tuple.value_types)])})"

    if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
        return f"Scv.fromBytes({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{td.udt.name.decode()}.fromSCVal({name})"
    raise NotImplementedError(f"Unsupported SCValType: {t}")


def render_imports(client_ty):
    template = """
// https://mvnrepository.com/artifact/org.projectlombok/lombok
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.Value;

// https://mvnrepository.com/artifact/org.javatuples/javatuples
import org.javatuples.Unit;
import org.javatuples.Pair;
import org.javatuples.Triplet;
import org.javatuples.Quartet;
import org.javatuples.Quintet;
import org.javatuples.Sextet;
import org.javatuples.Septet;
import org.javatuples.Octet;
import org.javatuples.Ennead;
import org.javatuples.Decade;

import org.stellar.sdk.contract.AssembledTransaction;
import org.stellar.sdk.contract.ContractClient;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.SCVal;
import org.stellar.sdk.xdr.SCValType;

import java.math.BigInteger;
import java.util.*;
import java.util.stream.Collectors;
"""
    rendered_code = Template(template).render()
    return rendered_code


def render_enum(entry: xdr.SCSpecUDTEnumV0):
    template = """
@Getter
@AllArgsConstructor
public enum {{ entry.name.decode() }} {
    {%- for case in entry.cases %}
    {{ case.name.decode() }}({{ case.value.uint32 }}){% if loop.last %};{% else %},{% endif %}
    {%- endfor %}

    private final long value;
    
    public static {{ entry.name.decode() }} fromValue(long value) {
        for ({{ entry.name.decode()  }} card : {{ entry.name.decode() }}.values()) {
            if (card.value == value) {
                return card;
            }
        }
        throw new IllegalArgumentException("Unknown value: " + value);
    }

    public SCVal toSCVal() {
        return Scv.toUint32(value);
    }

    public static {{ entry.name.decode() }} fromSCVal(SCVal scVal) {
        return fromValue(Scv.fromUint32(scVal));
    }
}
"""

    rendered_code = Template(template).render(entry=entry)
    return rendered_code


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0):
    template = """
@Getter
@AllArgsConstructor
public enum {{ entry.name.decode() }} {
    {%- for case in entry.cases %}
    {{ case.name.decode() }}({{ case.value.uint32 }}){% if loop.last %};{% else %},{% endif %}
    {%- endfor %}

    private final long value;
    
    public static {{ entry.name.decode() }} fromValue(long value) {
        for ({{ entry.name.decode() }} card : {{ entry.name.decode() }}.values()) {
            if (card.value == value) {
                return card;
            }
        }
        throw new IllegalArgumentException("Unknown value: " + value);
    }

    public SCVal toSCVal() {
        return Scv.toUint32(value);
    }

    public static {{ entry.name.decode() }} fromSCVal(SCVal scVal) {
        return fromValue(Scv.fromUint32(scVal));
    }
}"""

    rendered_code = Template(template).render(entry=entry)
    return rendered_code


def render_struct(entry: xdr.SCSpecUDTStructV0):
    template = """
@Value
public static class {{ entry.name.decode() }} {
    {%- for field in entry.fields %}
    {{ to_java_type(field.type) }} {{ field.name.decode() }};
    {%- endfor %}
    
    public SCVal toSCVal() {
        TreeMap<String, SCVal> fields = new TreeMap<>();
        {%- for field in entry.fields %}
        fields.put("{{ field.name_r.decode() if field.name_r else field.name.decode() }}", {{ to_scval(field.type, 'this.' ~ field.name.decode()) }});
        {%- endfor %}
        LinkedHashMap<SCVal, SCVal> map = fields.entrySet().stream()
                .collect(LinkedHashMap::new, (m, e) -> m.put(Scv.toSymbol(e.getKey()), e.getValue()), LinkedHashMap::putAll);
        return Scv.toMap(map);
    }
    
    public static {{ entry.name.decode() }} fromSCVal(SCVal scVal) {
        LinkedHashMap<SCVal, SCVal> map = Scv.fromMap(scVal);
        return new {{ entry.name.decode() }}(
            {%- for index, field in enumerate(entry.fields) %}
            {{ from_scval(field.type, 'map.get(Scv.toSymbol("' ~ (field.name_r.decode() if field.name_r else field.name.decode()) ~ '"))') }}{% if not loop.last %},{% endif %}
            {%- endfor %}        
        );
    }
}"""

    rendered_code = Template(template).render(
        entry=entry,
        to_java_type=to_java_type,
        to_scval=to_scval,
        from_scval=from_scval,
        enumerate=enumerate,
    )
    return rendered_code


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0):
    template = """
@Value
public static class {{ entry.name.decode() }} {
    {% for f in entry.fields %}
    {{ to_java_type(f.type, True) }} value{{ f.name.decode() }};
    {% endfor %}

    public SCVal toSCVal() {
        return Scv.toVec(
                Arrays.asList(
                    {% for f in entry.fields %}{{ to_scval(f.type, 'value' ~ f.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}
                )
        );
    }

    public static {{ entry.name.decode() }} fromSCVal(SCVal val) {
        List<SCVal> elements = new ArrayList<>(Scv.fromVec(val));
        return new {{ entry.name.decode() }}(
            {% for f in entry.fields %}{{ from_scval(f.type, 'elements.get(' ~ f.name.decode() ~ ')') }}{% if not loop.last %}, {% endif %}{% endfor %}
        );
    }
}"""

    rendered_code = Template(template).render(
        entry=entry, to_java_type=to_java_type, to_scval=to_scval, from_scval=from_scval
    )
    return rendered_code


def render_union(entry: xdr.SCSpecUDTUnionV0):
    template = """
@Value
@Builder
public static class {{ entry.name.decode() }} {
    Kind kind;
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
    {%- if len(case.tuple_case.type) == 1 %}
    {{ to_java_type(case.tuple_case.type[0], True) }} {{ convert_name(case.tuple_case.name, True).decode() }};
    {%- else %}
    {{ get_tuple_class_name(len(case.tuple_case.type)) }}<{% for f in case.tuple_case.type %}{{ to_java_type(f, True) }}{% if not loop.last %}, {% endif %}{% endfor %}> {{ convert_name(case.tuple_case.name, True).decode() }};
    {%- endif %}
    {%- endif %}
    {%- endfor %}

    public SCVal toSCVal() {
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        if (this.kind == Kind.{{ case.void_case.name.decode() }}) {
            return Scv.toVec(Collections.singletonList(Scv.toSymbol(this.kind.value)));
        }
        {%- else %}
        if (this.kind == Kind.{{ case.tuple_case.name.decode() }}) {
        {%- if len(case.tuple_case.type) == 1 %}
            return Scv.toVec(Arrays.asList(Scv.toSymbol(this.kind.value), {{ to_scval(case.tuple_case.type[0], 'this.' ~ convert_name(case.tuple_case.name, True).decode()) }}));        
        {%- else %}
            return Scv.toVec(Arrays.asList(
                Scv.toSymbol(this.kind.value),
                {%- for t in case.tuple_case.type %}
                {{ to_scval(t, 'this.' + convert_name(case.tuple_case.name, True).decode() + '.getValue' + loop.index0|string + '()') }}{% if not loop.last %}, {% endif %}
                {%- endfor %}
            ));
        {%- endif %}
        }
        {%- endif %}
        {%- endfor %} 

        throw new IllegalArgumentException("Unknown kind: " + this.kind);
    }


    public static {{ entry.name.decode() }} fromSCVal(SCVal scVal) {
        SCVal[] elements = Scv.fromVec(scVal).toArray(new SCVal[0]);
        Kind kind = Kind.fromValue(Scv.fromSymbol(elements[0]));

        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        if (kind == Kind.{{ case.void_case.name.decode() }}) {
            return {{ entry.name.decode() }}.builder().kind(kind).build();
        }
        {%- else %}
        if (kind == Kind.{{ case.tuple_case.name.decode() }}) {
        {%- if len(case.tuple_case.type) == 1 %}
            return {{ entry.name.decode() }}.builder().kind(kind).{{ convert_name(case.tuple_case.name, True).decode() }}({{ from_scval(case.tuple_case.type[0], 'elements[1]') }}).build();
        {%- else %}
            return {{ entry.name.decode() }}.builder().kind(kind)
                .{{ convert_name(case.tuple_case.name, True).decode() }}(
                new {{ get_tuple_class_name(len(case.tuple_case.type)) }}<>(
                    {%- for i, t in enumerate(case.tuple_case.type, 1) %}
                    {{ from_scval(t, 'elements[' + i|string + ']') }}{% if not loop.last %},{% endif %} 
                    {%- endfor %}
                )).build();
        {%- endif %}
        }
        {%- endif %}
        {%- endfor %}
        throw new IllegalArgumentException("Unknown kind: " + kind);
    }

    @Getter
    @AllArgsConstructor
    public enum Kind {
        {%- for case in entry.cases %}
        {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0 %}
        {{ case.void_case.name.decode() }}("{{ case.void_case.name_r.decode() if case.void_case.name_r else case.void_case.name.decode() }}"){% if loop.last %};{% else %},{% endif %}
        {%- else %}
        {{ case.tuple_case.name.decode() }}("{{ case.tuple_case.name.decode() if case.tuple_case.name_r else case.tuple_case.name.decode() }}"){% if loop.last %};{% else %},{% endif %}
        {%- endif %}
        {%- endfor %}

        private final String value;

        public static Kind fromValue(String value) {
            for (Kind kind : Kind.values()) {
                if (kind.value.equals(value)) {
                    return kind;
                }
            }
            throw new IllegalArgumentException("Unknown value: " + value);
        }
    }
}
"""
    union_rendered_code = Template(template).render(
        entry=entry,
        to_java_type=to_java_type,
        to_scval=to_scval,
        from_scval=from_scval,
        xdr=xdr,
        len=len,
        convert_name=convert_name,
        enumerate=enumerate,
        get_tuple_class_name=get_tuple_class_name,
    )
    return union_rendered_code


def render_functions(entries: List[xdr.SCSpecFunctionV0]):
    template = """
    /**
     * Creates a new {@link Client} with the given contract ID, RPC URL, and network.
     *
     * @param contractId The contract ID to interact with.
     * @param rpcUrl     The RPC URL of the Soroban server.
     * @param network    The network to interact with.
     */
    public Client(String contractId, String rpcUrl, Network network) {
        super(contractId, rpcUrl, network);
    }
    
    
    {%- for entry in entries %}
    public AssembledTransaction<{{ parse_result_type(entry.outputs) }}> {{ entry.name.sc_symbol.decode() }}({% for param in entry.inputs %}{{ to_java_type(param.type, True) }} {{ param.name.decode() }}, {% endfor %}String source, KeyPair signer, int baseFee) {
        return {{ entry.name.sc_symbol.decode() }}({% for param in entry.inputs %}{{ param.name.decode() }}, {% endfor %} source, signer, baseFee, 300, 30, true, true);
    }
    public AssembledTransaction<{{ parse_result_type(entry.outputs) }}> {{ entry.name.sc_symbol.decode() }}({% for param in entry.inputs %}{{ to_java_type(param.type, True) }} {{ param.name.decode() }}, {% endfor %}String source, KeyPair signer, int baseFee, int transactionTimeout, int submitTimeout, boolean simulate, boolean restore) {
        return invoke("{{ entry.name.sc_symbol_r.decode() if entry.name.sc_symbol_r else entry.name.sc_symbol.decode() }}", Arrays.asList({% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}), source, signer, {{ parse_result_xdr_fn(entry.outputs) }}, baseFee, transactionTimeout, submitTimeout, simulate, restore);
    }
    {%- endfor %} 

"""

    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "Void"
        elif len(output) == 1:
            return to_java_type(output[0])
        else:
            return f"{get_tuple_class_name}<{', '.join([to_java_type(t) for t in output])}>"

    def parse_result_xdr_fn(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "v -> null"
        elif len(output) == 1:
            return f'v -> {from_scval(output[0], "v")}'
        else:
            raise NotImplementedError(
                "Tuple return type is not supported, please report this issue"
            )

    client_rendered_code = Template(template).render(
        entries=entries,
        to_java_type=to_java_type,
        to_scval=to_scval,
        parse_result_type=parse_result_type,
        parse_result_xdr_fn=parse_result_xdr_fn,
    )
    return client_rendered_code


# append _ to keyword
def append_underscore(specs: List[xdr.SCSpecEntry]):
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            assert spec.udt_struct_v0 is not None
            spec.udt_struct_v0.name_r = spec.udt_struct_v0.name  # type: ignore[attr-defined]
            spec.udt_struct_v0.name = convert_name(spec.udt_struct_v0.name)
            for field in spec.udt_struct_v0.fields:
                field.name_r = field.name  # type: ignore[attr-defined]
                field.name = convert_name(field.name)
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            assert spec.udt_union_v0 is not None
            spec.udt_union_v0.name_r = spec.udt_union_v0.name  # type: ignore[attr-defined]
            spec.udt_union_v0.name = convert_name(spec.udt_union_v0.name)
            for union_case in spec.udt_union_v0.cases:
                if (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
                ):
                    union_case.tuple_case.name_r = union_case.tuple_case.name  # type: ignore[attr-defined]
                    union_case.tuple_case.name = convert_name(
                        union_case.tuple_case.name
                    )
                elif (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
                ):
                    union_case.void_case.name_r = union_case.void_case.name  # type: ignore[attr-defined]
                    union_case.void_case.name = convert_name(union_case.void_case.name)
                else:
                    raise ValueError(f"Unsupported union case kind: {union_case.kind}")
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            assert spec.function_v0 is not None
            spec.function_v0.name.sc_symbol_r = spec.function_v0.name.sc_symbol  # type: ignore[attr-defined]
            spec.function_v0.name.sc_symbol = convert_name(
                spec.function_v0.name.sc_symbol
            )
            for param in spec.function_v0.inputs:
                param.name = convert_name(param.name)
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            assert spec.udt_enum_v0 is not None
            spec.udt_enum_v0.name_r = spec.udt_enum_v0.name  # type: ignore[attr-defined]
            spec.udt_enum_v0.name = convert_name(spec.udt_enum_v0.name)
            for enum_case in spec.udt_enum_v0.cases:
                enum_case.name = convert_name(enum_case.name)
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            assert spec.udt_error_enum_v0 is not None
            spec.udt_error_enum_v0.name_r = spec.udt_error_enum_v0.name  # type: ignore[attr-defined]
            spec.udt_error_enum_v0.name = convert_name(spec.udt_error_enum_v0.name)
            for error_enum_case in spec.udt_error_enum_v0.cases:
                error_enum_case.name = convert_name(error_enum_case.name)


def generate_binding(specs: List[xdr.SCSpecEntry], package: str) -> str:
    append_underscore(specs)

    generated = []
    generated.append(
        f"// This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version} and stellar_sdk v{stellar_sdk_version}."
    )
    generated.append(f"package {package};")
    generated.append(render_imports(package))
    generated.append("public class Client extends ContractClient {")

    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    generated.append(render_functions(function_specs))

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

    generated.append("}")
    return "\n".join(generated)


@click.command(name="java")
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
    default="org.stellar",
    help="Package name for generated bindings",
)
def command(contract_id: str, rpc_url: str, output: str, package: str):
    """Generate Java bindings for a Soroban contract"""
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

    click.echo("Generating Java bindings")
    generated = generate_binding(specs, package=package)

    if not os.path.exists(output):
        os.makedirs(output)
    output_path = os.path.join(output, "Client.java")
    with open(output_path, "w") as f:
        f.write(generated)
    click.echo(f"Generated Java bindings to {output_path}")


if __name__ == "__main__":
    from stellar_contract_bindings.metadata import parse_contract_metadata

    wasm_file = "/Users/overcat/repo/lightsail/stellar-contract-bindings/tests/contracts/target/wasm32-unknown-unknown/release/python.wasm"
    with open(wasm_file, "rb") as f:
        wasm = f.read()

    specs = parse_contract_metadata(wasm).spec
    generated = generate_binding(specs, package="org.stellar.sdk")
    print(generated)
