import os
import re
from typing import List, Tuple

import click
from jinja2 import Environment, Template
from stellar_sdk import __version__ as stellar_sdk_version, StrKey
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id


# https://docs.oracle.com/javase/specs/jls/se21/html/jls-3.html#jls-3.9
_JAVA_KEYWORDS = frozenset(
    """
    abstract assert boolean break byte case catch char class const continue
    default do double else enum extends final finally float for goto if
    implements import instanceof int interface long native new package private
    protected public return short static strictfp super switch synchronized
    this throw throws transient try void volatile while true false null
    """.split()
)


# Characters with a named escape in a Java string literal. The backslash is
# listed first only for readability; the loop below checks membership, so the
# ordering that matters is that this table is consulted before any other rule.
_JAVA_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def java_string_literal(text: str) -> str:
    """Render spec text as a Java string literal, quotes included.

    Names arrive in the contract spec, so a contract can publish one that
    closes the literal and continues with code of its own. Escaping the
    backslash and the quote is what stops that.

    The remaining rules are about Java specifically. Unicode escapes are
    processed in a translation phase *before* lexing (JLS 3.3), so a
    ``\\uXXXX`` that decodes to a quote would close the literal even though it
    sits inside one. Unicode escapes are therefore only used for characters at
    or above U+0080, which can never be syntactically significant; control
    characters take an octal escape instead, which the lexer reads. Always
    three octal digits, so a following digit cannot extend the escape.

    Everything at or above U+0080 is escaped rather than emitted directly, so
    the generated file is pure ASCII and its meaning does not depend on the
    encoding javac happens to read it with.
    """
    out = ['"']
    for char in text:
        if char in _JAVA_ESCAPES:
            out.append(_JAVA_ESCAPES[char])
        elif " " <= char <= "~":
            out.append(char)
        elif char < "\u0080":
            out.append(f"\\{ord(char):03o}")
        else:
            units = char.encode("utf-16-be")
            for i in range(0, len(units), 2):
                out.append(f"\\u{units[i] << 8 | units[i + 1]:04x}")
    out.append('"')
    return "".join(out)


def is_keywords(word: str) -> bool:
    return word in _JAVA_KEYWORDS


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


# SCSpecTypeTuple declares valueTypes<12>, so twelve is the most a spec can
# hold. The previous javatuples mapping stopped at ten.
_MAX_TUPLE_ARITY = 12


def get_tuple_class_name(amount: int) -> str:
    if amount < 1 or amount > _MAX_TUPLE_ARITY:
        raise ValueError(f"amount should be between 1 and {_MAX_TUPLE_ARITY}")
    return f"Tuple{amount}"


def java_identifier(name: str, first_letter_lower: bool = False) -> str:
    """Return a valid Java identifier, keeping as much of the name as possible.

    Spec names are only length-limited, so they can hold characters Java does
    not accept in an identifier, or be empty. Anything unusable becomes an
    underscore rather than being dropped, so two different names stay
    different; keywords and the empty case get a trailing underscore.
    """
    candidate = "".join(
        char if (char.isalnum() or char in "_$") and char.isascii() else "_"
        for char in name
    )
    if not candidate or candidate[0].isdigit():
        candidate = "_" + candidate
    if first_letter_lower:
        candidate = candidate[:1].lower() + candidate[1:]
    if is_keywords(candidate):
        candidate += "_"
    return candidate


def event_class_name(name: str) -> str:
    """Turn an event's declared name into a PascalCase Java class name."""
    parts = [part for part in re.split(r"_+", java_identifier(name)) if part]
    pascal = "".join(part[:1].upper() + part[1:] for part in parts) or "Event"
    pascal = java_identifier(pascal)
    return pascal if pascal.endswith("Event") else pascal + "Event"


def declared_topic_count(entry: xdr.SCSpecEventV0) -> int:
    return len(entry.prefix_topics) + sum(
        1
        for p in entry.params
        if p.location
        == xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
    )


# Nested-class names the generator itself needs, in allocation order. Every UDT
# is emitted as a nested class of Client, so a contract type can occupy any of
# these; each is therefore resolved against the declared type names rather than
# assumed free.
_EVENT_HELPER_NAMES = ("Event", "DecodedEvent", "UnparsedEventException")


def resolve_event_names(
    specs: List[xdr.SCSpecEntry], event_specs: List[xdr.SCSpecEventV0]
) -> Tuple[List[str], List[str], str]:
    """Name the event classes and the scaffolding, uniquely within Client.

    Every UDT is emitted as a nested class of Client, so an event class or a
    generated helper sharing a UDT's name would not compile. Both are allocated
    from the declared type names, so a contract type called ``DecodedEvent``
    pushes the helper aside rather than colliding with it.

    Returns the helper names in ``_EVENT_HELPER_NAMES`` order, the per-event
    class names, and the marker interface name (the first helper).
    """
    used = {"Client"}
    for spec in specs:
        for kind, attr in (
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0, "udt_enum_v0"),
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0, "udt_error_enum_v0"),
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0, "udt_struct_v0"),
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0, "udt_union_v0"),
        ):
            if spec.kind == kind:
                used.add(getattr(spec, attr).name.decode())

    helper_names = []
    for helper in _EVENT_HELPER_NAMES:
        while helper in used:
            helper += "_"
        used.add(helper)
        helper_names.append(helper)

    class_names = []
    for event_spec in event_specs:
        name = event_class_name(event_spec.name.sc_symbol.decode())
        while name in used:
            name += "_"
        used.add(name)
        class_names.append(name)
    return helper_names, class_names, helper_names[0]


def resolve_event_param_names(entry: xdr.SCSpecEventV0) -> List[str]:
    """Allocate valid, unique Java field names for one event's parameters."""
    used = set()
    names = []
    for param in entry.params:
        name = java_identifier(convert_name(param.name, True).decode(), True)
        while name in used:
            name += "_"
        used.add(name)
        names.append(name)
    return names


def _udt_member_types(specs: List[xdr.SCSpecEntry]) -> dict:
    """Map each UDT's declared name to the types it holds.

    Needed to look past a UDT reference: a struct field or union case can be a
    type an event must not carry, and the reference alone does not show it.
    """
    members: dict = {}
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            entry = spec.udt_struct_v0
            members[entry.name.decode()] = [
                (field.name.decode(), field.type) for field in entry.fields
            ]
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            entry = spec.udt_union_v0
            cases = []
            for case in entry.cases:
                if case.tuple_case is not None:
                    for index, value_type in enumerate(case.tuple_case.type):
                        cases.append(
                            (f"{case.tuple_case.name.decode()}.{index}", value_type)
                        )
            members[entry.name.decode()] = cases
    return members


def _reject_unsupported_event_type(
    td: xdr.SCSpecTypeDef,
    event: str,
    param: str,
    path: str = "",
    udt_members: dict = None,
    seen: frozenset = frozenset(),
) -> None:
    """Refuse to generate an event field this generator cannot decode faithfully.

    ``to_java_type`` reduces ``Result<T, E>`` to ``T``, which is defensible for a
    successful function result but not for an event: an event may carry the Err
    arm, and the generated decoder would read it as an Ok. ``Error`` has no Java
    representation here at all. Both are rejected with the path that reached
    them rather than silently mis-decoding.
    """
    t = td.type
    if t in (xdr.SCSpecType.SC_SPEC_TYPE_ERROR, xdr.SCSpecType.SC_SPEC_TYPE_RESULT):
        where = f"{event}.{param}{path}"
        raise NotImplementedError(
            f"event parameter {where} is declared {t.name}, which the Java "
            f"generator cannot decode; only the Ok arm would be read"
        )

    def recur(inner, suffix, seen=seen):
        _reject_unsupported_event_type(
            inner, event, param, path + suffix, udt_members, seen
        )

    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        recur(td.option.value_type, "?")
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        recur(td.vec.element_type, "[]")
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        recur(td.map.key_type, ".key")
        recur(td.map.value_type, ".value")
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        for index, value_type in enumerate(td.tuple.value_types):
            recur(value_type, f".{index}")
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_UDT and udt_members is not None:
        # A UDT hides its members behind a name, and its generated decoder has
        # the same blind spot as an inline one would. Recursive types are
        # possible, so each name is only descended into once.
        name = td.udt.name.decode()
        if name not in seen:
            for member_name, member_type in udt_members.get(name, []):
                recur(member_type, f".{member_name}", seen | {name})


# Scalar SCSpecTypes whose Scv helpers are named symmetrically, so that
# to_scval emits Scv.to<Codec> and from_scval emits Scv.from<Codec>.
_SCV_CODECS = {
    xdr.SCSpecType.SC_SPEC_TYPE_BOOL: "Boolean",
    xdr.SCSpecType.SC_SPEC_TYPE_U32: "Uint32",
    xdr.SCSpecType.SC_SPEC_TYPE_I32: "Int32",
    xdr.SCSpecType.SC_SPEC_TYPE_U64: "Uint64",
    xdr.SCSpecType.SC_SPEC_TYPE_I64: "Int64",
    xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT: "TimePoint",
    xdr.SCSpecType.SC_SPEC_TYPE_DURATION: "Duration",
    xdr.SCSpecType.SC_SPEC_TYPE_U128: "Uint128",
    xdr.SCSpecType.SC_SPEC_TYPE_I128: "Int128",
    xdr.SCSpecType.SC_SPEC_TYPE_U256: "Uint256",
    xdr.SCSpecType.SC_SPEC_TYPE_I256: "Int256",
    xdr.SCSpecType.SC_SPEC_TYPE_BYTES: "Bytes",
    xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N: "Bytes",
    xdr.SCSpecType.SC_SPEC_TYPE_STRING: "String",
    xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL: "Symbol",
    xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS: "Address",
    xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS: "Address",
}

# Scalar SCSpecTypes that map to a fixed Java type.
_JAVA_TYPES = {
    xdr.SCSpecType.SC_SPEC_TYPE_VAL: "SCVal",
    xdr.SCSpecType.SC_SPEC_TYPE_BOOL: "Boolean",
    xdr.SCSpecType.SC_SPEC_TYPE_VOID: "Void",
    xdr.SCSpecType.SC_SPEC_TYPE_U32: "Long",
    xdr.SCSpecType.SC_SPEC_TYPE_I32: "Integer",
    xdr.SCSpecType.SC_SPEC_TYPE_U64: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_I64: "Long",
    xdr.SCSpecType.SC_SPEC_TYPE_TIMEPOINT: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_DURATION: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_U128: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_I128: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_U256: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_I256: "BigInteger",
    xdr.SCSpecType.SC_SPEC_TYPE_BYTES: "byte[]",
    xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N: "byte[]",
    xdr.SCSpecType.SC_SPEC_TYPE_STRING: "byte[]",
    xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL: "String",
    xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS: "Address",
    xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS: "Address",
}


def _lambda_var(depth: int) -> str:
    """Name the lambda parameter for a collection at this nesting depth.

    A nested collection puts one lambda inside another, and Java forbids
    shadowing a lambda parameter, so every level needs its own name.
    """
    return f"e{depth}"


_UNSUPPORTED_ERROR = "SC_SPEC_TYPE_ERROR is not supported"


# Templates are compiled once at import rather than on every render call, and
# the names every template reaches for live on the environment instead of being
# repeated in each render() call. The default Undefined is deliberate: the
# templates test optional spec attributes such as ``field.name_r``, which
# StrictUndefined would turn into an error rather than a falsy value.
_ENV = Environment()


def _template(source: str) -> Template:
    return _ENV.from_string(source)


def to_java_type(td: xdr.SCSpecTypeDef):
    t = td.type
    if t in _JAVA_TYPES:
        return _JAVA_TYPES[t]
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError(_UNSUPPORTED_ERROR)
    # An Option is a plain nullable reference, and a Result is only ever seen
    # as its Ok arm, so both collapse to the type they wrap.
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return to_java_type(td.option.value_type)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return to_java_type(td.result.ok_type)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        return f"List<{to_java_type(td.vec.element_type)}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        return (
            f"LinkedHashMap<{to_java_type(td.map.key_type)}, "
            f"{to_java_type(td.map.value_type)}>"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            # () equivalent to None in Java
            return "Void"
        types = [to_java_type(v) for v in td.tuple.value_types]
        return f"{get_tuple_class_name(len(types))}<{', '.join(types)}>"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        # append_underscore() rewrites the declaration's name; a reference
        # has to be spelled the same way or it names a class that is not there.
        return convert_name(td.udt.name).decode()
    raise ValueError(f"Unsupported SCValType: {t}")


def to_scval(td: xdr.SCSpecTypeDef, name: str, depth: int = 0):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        return "Scv.toVoid()"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError(_UNSUPPORTED_ERROR)
    if t in _SCV_CODECS:
        return f"Scv.to{_SCV_CODECS[t]}({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        return f"{name} == null ? Scv.toVoid() : {to_scval(td.option.value_type, name, depth)}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        # to_java_type() and from_scval() both reduce Result<T, E> to its Ok
        # arm, so the Java value in hand is already a T and encodes as one.
        return to_scval(td.result.ok_type, name, depth)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        var = _lambda_var(depth)
        element = to_scval(td.vec.element_type, var, depth + 1)
        return (
            f"Scv.toVec({name}.stream().map({var} -> {element})"
            f".collect(Collectors.toList()))"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        var = _lambda_var(depth)
        key = to_scval(td.map.key_type, f"{var}.getKey()", depth + 1)
        value = to_scval(td.map.value_type, f"{var}.getValue()", depth + 1)
        return (
            f"Scv.toMap({name}.entrySet().stream().collect(LinkedHashMap::new, "
            f"(m{depth}, {var}) -> m{depth}.put({key}, {value}), LinkedHashMap::putAll))"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        values = [
            to_scval(v, f"{name}.getValue{i}()", depth)
            for i, v in enumerate(td.tuple.value_types)
        ]
        return f"Scv.toVec(Arrays.asList({', '.join(values)}))"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{name}.toSCVal()"
    raise ValueError(f"Unsupported SCValType: {t}")


def from_scval(td: xdr.SCSpecTypeDef, name: str, depth: int = 0):
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
        return f"{name}"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
        # Scv.fromVoid is `void fromVoid(SCVal)`, so it cannot be used where a
        # value is expected; the generated decodeVoid wraps it. Returning a
        # bare "null" instead would accept any SCVal as a declared void.
        return f"decodeVoid({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
        raise NotImplementedError(_UNSUPPORTED_ERROR)
    if t in _SCV_CODECS:
        return f"Scv.from{_SCV_CODECS[t]}({name})"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        inner = from_scval(td.option.value_type, name, depth)
        return f"{name}.getDiscriminant() != SCValType.SCV_VOID ? {inner} : null"
    if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return from_scval(td.result.ok_type, name, depth)
    if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        var = _lambda_var(depth)
        element = from_scval(td.vec.element_type, var, depth + 1)
        return (
            f"Scv.fromVec({name}).stream().map({var} -> {element})"
            f".collect(Collectors.toList())"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        var = _lambda_var(depth)
        key = from_scval(td.map.key_type, f"{var}.getKey()", depth + 1)
        value = from_scval(td.map.value_type, f"{var}.getValue()", depth + 1)
        return (
            f"Scv.fromMap({name}).entrySet().stream().collect(LinkedHashMap::new, "
            f"(m{depth}, {var}) -> m{depth}.put({key}, {value}), LinkedHashMap::putAll)"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        if len(td.tuple.value_types) == 0:
            return "null"
        values = [
            from_scval(v, f"Scv.fromVec({name}).toArray(new SCVal[0])[{i}]", depth)
            for i, v in enumerate(td.tuple.value_types)
        ]
        return (
            f"new {get_tuple_class_name(len(td.tuple.value_types))}<>"
            f"({', '.join(values)})"
        )
    if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
        return f"{convert_name(td.udt.name).decode()}.fromSCVal({name})"
    raise ValueError(f"Unsupported SCValType: {t}")


# Registered here rather than beside _ENV, since the type mappers below
# have to exist first.
_ENV.globals.update(
    java_string_literal=java_string_literal,
    convert_name=convert_name,
    enumerate=enumerate,
    from_scval=from_scval,
    get_tuple_class_name=get_tuple_class_name,
    len=len,
    to_java_type=to_java_type,
    to_scval=to_scval,
    xdr=xdr,
)


_TUPLE_CLASS_TEMPLATE = _template(
    """
    /** A {{ arity }}-element tuple, for a spec type Java has no equivalent of. */
    @Value
    public static class {{ get_tuple_class_name(arity) }}<{% for i in range(arity) %}T{{ i }}{% if not loop.last %}, {% endif %}{% endfor %}> {
        {%- for i in range(arity) %}
        T{{ i }} value{{ i }};
        {%- endfor %}
    }
"""
)


def _tuple_arities(specs: List[xdr.SCSpecEntry]) -> List[int]:
    """Collect every tuple size the spec actually uses.

    Only the sizes in use are emitted, so a contract with no tuples carries no
    tuple classes at all.
    """
    arities = set()

    def walk(td: xdr.SCSpecTypeDef) -> None:
        t = td.type
        if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
            walk(td.option.value_type)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            walk(td.result.ok_type)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
            walk(td.vec.element_type)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
            walk(td.map.key_type)
            walk(td.map.value_type)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
            # An empty tuple maps to Void, so it needs no class.
            if td.tuple.value_types:
                arities.add(len(td.tuple.value_types))
            for value_type in td.tuple.value_types:
                walk(value_type)

    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            for param in spec.function_v0.inputs:
                walk(param.type)
            for output in spec.function_v0.outputs:
                walk(output)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            for field in spec.udt_struct_v0.fields:
                walk(field.type)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            for case in spec.udt_union_v0.cases:
                if case.tuple_case is None:
                    continue
                # A single-value case is emitted as that value's type; only a
                # multi-value case needs a tuple.
                if len(case.tuple_case.type) > 1:
                    arities.add(len(case.tuple_case.type))
                for value_type in case.tuple_case.type:
                    walk(value_type)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0:
            for param in spec.event_v0.params:
                walk(param.type)
    return sorted(arities)


def render_tuple_classes(specs: List[xdr.SCSpecEntry]) -> str:
    """Emit the tuple classes this spec needs, checking none is displaced.

    They are nested in Client alongside every UDT, so a contract type of the
    same name would be emitted twice under one name; that is reported rather
    than producing a file which does not compile.
    """
    arities = _tuple_arities(specs)
    if not arities:
        return ""
    wanted = {get_tuple_class_name(arity) for arity in arities}
    declared = {
        convert_name(getattr(spec, attr).name).decode()
        for spec in specs
        for kind, attr in (
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0, "udt_enum_v0"),
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0, "udt_error_enum_v0"),
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0, "udt_struct_v0"),
            (xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0, "udt_union_v0"),
        )
        if spec.kind == kind
    }
    clash = sorted(wanted & declared)
    if clash:
        raise NotImplementedError(
            f"contract declares {', '.join(clash)}, which collides with the "
            f"tuple class the generator needs for the same arity"
        )
    return "\n".join(_TUPLE_CLASS_TEMPLATE.render(arity=arity) for arity in arities)


_IMPORTS_TEMPLATE = _template(
    """
// https://mvnrepository.com/artifact/org.projectlombok/lombok
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.Value;

import org.stellar.sdk.Address;
import org.stellar.sdk.KeyPair;
import org.stellar.sdk.Network;
import org.stellar.sdk.contract.AssembledTransaction;
import org.stellar.sdk.contract.ContractClient;
import org.stellar.sdk.responses.sorobanrpc.GetEventsResponse;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.ContractEvent;
import org.stellar.sdk.xdr.SCVal;
import org.stellar.sdk.xdr.SCValType;

import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.stream.Collectors;
"""
)


def render_imports(client_ty):
    return _IMPORTS_TEMPLATE.render()


_ENUM_TEMPLATE = _template(
    """
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
)


def render_enum(entry: xdr.SCSpecUDTEnumV0):
    return _ENUM_TEMPLATE.render(entry=entry)


_ERROR_ENUM_TEMPLATE = _template(
    """
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
)


def render_error_enum(entry: xdr.SCSpecUDTErrorEnumV0):
    return _ERROR_ENUM_TEMPLATE.render(entry=entry)


_STRUCT_TEMPLATE = _template(
    """
@Value
public static class {{ entry.name.decode() }} {
    {%- for field in entry.fields %}
    {{ to_java_type(field.type) }} {{ field.name.decode() }};
    {%- endfor %}
    
    public SCVal toSCVal() {
        TreeMap<String, SCVal> fields = new TreeMap<>();
        {%- for field in entry.fields %}
        fields.put({{ java_string_literal(field.name_r.decode() if field.name_r else field.name.decode()) }}, {{ to_scval(field.type, 'this.' ~ field.name.decode()) }});
        {%- endfor %}
        LinkedHashMap<SCVal, SCVal> map = fields.entrySet().stream()
                .collect(LinkedHashMap::new, (m, e) -> m.put(Scv.toSymbol(e.getKey()), e.getValue()), LinkedHashMap::putAll);
        return Scv.toMap(map);
    }
    
    public static {{ entry.name.decode() }} fromSCVal(SCVal scVal) {
        LinkedHashMap<SCVal, SCVal> map = Scv.fromMap(scVal);
        return new {{ entry.name.decode() }}(
            {%- for index, field in enumerate(entry.fields) %}
            {{ from_scval(field.type, 'map.get(Scv.toSymbol(' ~ java_string_literal(field.name_r.decode() if field.name_r else field.name.decode()) ~ '))') }}{% if not loop.last %},{% endif %}
            {%- endfor %}        
        );
    }
}"""
)


def render_struct(entry: xdr.SCSpecUDTStructV0):
    return _STRUCT_TEMPLATE.render(
        entry=entry,
    )


_TUPLE_STRUCT_TEMPLATE = _template(
    """
@Value
public static class {{ entry.name.decode() }} {
    {% for f in entry.fields %}
    {{ to_java_type(f.type) }} value{{ f.name.decode() }};
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
)


def render_tuple_struct(entry: xdr.SCSpecUDTStructV0):
    return _TUPLE_STRUCT_TEMPLATE.render(entry=entry)


_UNION_TEMPLATE = _template(
    """
@Value
@Builder
public static class {{ entry.name.decode() }} {
    Kind kind;
    {%- for case in entry.cases %}
    {%- if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0 %}
    {%- if len(case.tuple_case.type) == 1 %}
    {{ to_java_type(case.tuple_case.type[0]) }} {{ convert_name(case.tuple_case.name, True).decode() }};
    {%- else %}
    {{ get_tuple_class_name(len(case.tuple_case.type)) }}<{% for f in case.tuple_case.type %}{{ to_java_type(f) }}{% if not loop.last %}, {% endif %}{% endfor %}> {{ convert_name(case.tuple_case.name, True).decode() }};
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
        {{ case.void_case.name.decode() }}({{ java_string_literal(case.void_case.name_r.decode() if case.void_case.name_r else case.void_case.name.decode()) }}){% if loop.last %};{% else %},{% endif %}
        {%- else %}
        {{ case.tuple_case.name.decode() }}({{ java_string_literal(case.tuple_case.name_r.decode() if case.tuple_case.name_r else case.tuple_case.name.decode()) }}){% if loop.last %};{% else %},{% endif %}
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
)


def render_union(entry: xdr.SCSpecUDTUnionV0):
    return _UNION_TEMPLATE.render(
        entry=entry,
    )


_FUNCTIONS_TEMPLATE = _template(
    """
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

    /**
     * Decodes a value the spec declares as void.
     *
     * <p>A void carries no data, but the SCVal still has to be a void one.
     * {@link Scv#fromVoid} performs that check and returns {@code void}, so it
     * cannot be called where a value is expected; this wraps it.
     *
     * @param scVal the value to check
     * @return null, the only value of {@link Void}
     */
    private static Void decodeVoid(SCVal scVal) {
        Scv.fromVoid(scVal);
        return null;
    }
    
    
    {%- for entry in entries %}
    public AssembledTransaction<{{ parse_result_type(entry.outputs) }}> {{ entry.name.sc_symbol.decode() }}({% for param in entry.inputs %}{{ to_java_type(param.type) }} {{ param.name.decode() }}, {% endfor %}String source, KeyPair signer, int baseFee) {
        return {{ entry.name.sc_symbol.decode() }}({% for param in entry.inputs %}{{ param.name.decode() }}, {% endfor %} source, signer, baseFee, 300, 30, true, true);
    }
    public AssembledTransaction<{{ parse_result_type(entry.outputs) }}> {{ entry.name.sc_symbol.decode() }}({% for param in entry.inputs %}{{ to_java_type(param.type) }} {{ param.name.decode() }}, {% endfor %}String source, KeyPair signer, int baseFee, int transactionTimeout, int submitTimeout, boolean simulate, boolean restore) {
        return invoke({{ java_string_literal(entry.name.sc_symbol_r.decode() if entry.name.sc_symbol_r else entry.name.sc_symbol.decode()) }}, Arrays.asList({% for param in entry.inputs %}{{ to_scval(param.type, param.name.decode()) }}{% if not loop.last %}, {% endif %}{% endfor %}), source, signer, {{ parse_result_xdr_fn(entry.outputs) }}, baseFee, transactionTimeout, submitTimeout, simulate, restore);
    }
    {%- endfor %} 

"""
)


def render_functions(entries: List[xdr.SCSpecFunctionV0]):
    def parse_result_type(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "Void"
        elif len(output) == 1:
            return to_java_type(output[0])
        else:
            # Unreachable: SCSpecFunctionV0 declares outputs<1>. The sibling
            # parse_result_xdr_fn already raises here; this used to interpolate
            # the function object itself into the generated source.
            raise NotImplementedError(
                "Tuple return type is not supported, please report this issue"
            )

    def parse_result_xdr_fn(output: List[xdr.SCSpecTypeDef]):
        if len(output) == 0:
            return "v -> null"
        elif len(output) == 1:
            return f'v -> {from_scval(output[0], "v")}'
        else:
            raise NotImplementedError(
                "Tuple return type is not supported, please report this issue"
            )

    return _FUNCTIONS_TEMPLATE.render(
        entries=entries,
        parse_result_type=parse_result_type,
        parse_result_xdr_fn=parse_result_xdr_fn,
    )


# append _ to keyword
_EVENT_HELPERS_TEMPLATE = _template(
    """
    /** Every event this contract declares. */
    public interface {{ union }} {}

    /**
     * An event's topics and data, decoded once.
     *
     * <p>parseEvent offers the same instance to every candidate; decoding per
     * candidate would re-parse the base64 an RPC event arrives as, once per
     * declaration that does not match.
     */
    @Value
    public static class {{ decoded }} {
        List<SCVal> topics;
        SCVal data;

        /** Decodes an event carried in transaction meta. */
        public static {{ decoded }} of(ContractEvent event) {
            if (event.getBody() == null || event.getBody().getV0() == null) {
                throw new IllegalArgumentException("contract event has no v0 body");
            }
            return new {{ decoded }}(
                Arrays.asList(event.getBody().getV0().getTopics()),
                event.getBody().getV0().getData());
        }

        /** Decodes an event as returned by getEvents, whose fields are base64 XDR. */
        public static {{ decoded }} of(GetEventsResponse.EventInfo event) {
            List<SCVal> topics = event.parseTopic();
            SCVal data = event.parseValue();
            if (topics == null || data == null) {
                throw new IllegalArgumentException("event is missing topics or value");
            }
            return new {{ decoded }}(topics, data);
        }
    }

    /**
     * Thrown when an event's topics match a declared event but no candidate
     * could decode it, which usually means the on-chain format has drifted
     * from the spec these bindings were generated from.
     */
    public static class {{ unparsed }} extends IllegalArgumentException {
        public {{ unparsed }}(String message) {
            super(message);
        }
    }

    /**
     * SEP-48: a static topic may be published as either a symbol or a string,
     * and parsers are expected to accept both.
     */
    private static boolean staticTopicMatches(SCVal topic, String expected) {
        if (topic.getDiscriminant() == SCValType.SCV_SYMBOL) {
            return expected.equals(Scv.fromSymbol(topic));
        }
        if (topic.getDiscriminant() == SCValType.SCV_STRING) {
            return Arrays.equals(
                Scv.fromString(topic), expected.getBytes(StandardCharsets.UTF_8));
        }
        return false;
    }

    /**
     * Encodes one topic of a getEvents filter row.
     *
     * <p>SCVal.toXdrBase64 declares IOException, but it is writing to memory:
     * a failure is a bug here, not something a caller can act on.
     */
    private static String encodeTopic(SCVal topic) {
        try {
            return topic.toXdrBase64();
        } catch (IOException e) {
            throw new IllegalStateException("could not encode topic filter", e);
        }
    }

    /** Reads a symbol-keyed data map into something the decoders can look up. */
    private static LinkedHashMap<String, SCVal> eventDataMap(SCVal data) {
        LinkedHashMap<String, SCVal> out = new LinkedHashMap<>();
        for (Map.Entry<SCVal, SCVal> entry : Scv.fromMap(data).entrySet()) {
            out.put(Scv.fromSymbol(entry.getKey()), entry.getValue());
        }
        return out;
    }
"""
)


_EVENT_TEMPLATE = _template(
    """
    @Value
    public static class {{ class_name }} implements {{ union }} {
        /** The name this event is declared under in the contract spec. */
        public static final String EVENT_NAME = {{ event_name }};

        {%- for p in params %}
        {{ p.java_type }} {{ p.java_name }};
        {%- endfor %}
        {%- if not params %}

        // No declared parameters; the topics alone identify this event.
        {%- endif %}

        /**
         * Starts one topics row for
         * {@link org.stellar.sdk.requests.sorobanrpc.GetEventsRequest.EventFilter}.
         *
         * <p>A topic left unset is filtered as a wildcard. That is distinct from
         * setting it to null, which matches only an explicit void.
         */
        public static TopicFilterBuilder topicFilter() {
            return new TopicFilterBuilder();
        }

        public static final class TopicFilterBuilder {
            {%- for p in topic_params %}
            private {{ p.java_type }} {{ p.java_name }};
            private boolean {{ p.set_flag }};
            {%- endfor %}

            {%- for p in topic_params %}

            public TopicFilterBuilder {{ p.java_name }}({{ p.java_type }} {{ p.java_name }}) {
                this.{{ p.java_name }} = {{ p.java_name }};
                this.{{ p.set_flag }} = true;
                return this;
            }
            {%- endfor %}

            /**
             * Builds the row.
             *
             * <p>It ends with "**" so that, like {@code matches}, it also selects
             * events carrying topics beyond the declared ones; without it the RPC
             * matches on exact topic count and those events are skipped. "**"
             * needs stellar-rpc v23.0.0 or newer, the release that introduced
             * SEP-48 event specs, and does not count towards the filter's four
             * segments.
             */
            public List<String> build() {
                List<String> row = new ArrayList<>();
                {%- for symbol in prefix_symbols %}
                row.add(encodeTopic(Scv.toSymbol({{ symbol }})));
                {%- endfor %}
                {%- for p in topic_params %}
                row.add({{ p.set_flag }} ? encodeTopic({{ p.filter_expr }}) : "*");
                {%- endfor %}
                row.add("**");
                return Collections.unmodifiableList(row);
            }
        }

        /**
         * Whether the topics have this event's shape.
         *
         * <p>Only the static prefix and the topic count are checked. Trailing
         * topics beyond the declared ones are ignored, because contracts append
         * them: Stellar Asset Contract events carry the SEP-11 asset string.
         */
        public static boolean matches({{ decoded }} event) {
            List<SCVal> topics = event.getTopics();
            if (topics.size() < {{ total_topics }}) {
                return false;
            }
            {%- for symbol in prefix_symbols %}
            if (!staticTopicMatches(topics.get({{ loop.index0 }}), {{ symbol }})) {
                return false;
            }
            {%- endfor %}
            return true;
        }

        public static boolean matches(ContractEvent event) {
            return matches({{ decoded }}.of(event));
        }

        public static boolean matches(GetEventsResponse.EventInfo event) {
            return matches({{ decoded }}.of(event));
        }

        /**
         * Decodes the event.
         *
         * @throws IllegalArgumentException if it does not have this event's shape
         */
        public static {{ class_name }} parse({{ decoded }} event) {
            if (!matches(event)) {
                throw new IllegalArgumentException(
                    "event does not match {{ class_name }}");
            }
            List<SCVal> topics = event.getTopics();
            {%- if validate_void_data %}
            decodeVoid(event.getData());
            {%- endif %}
            {%- if has_vec_data %}
            // Scv.fromVec returns a Collection; indexing needs a List.
            List<SCVal> values = new ArrayList<>(Scv.fromVec(event.getData()));
            if (values.size() < {{ data_param_count }}) {
                throw new IllegalArgumentException(
                    "event data vector has fewer values than declared");
            }
            {%- endif %}
            {%- if has_map_data %}
            LinkedHashMap<String, SCVal> values = eventDataMap(event.getData());
            {%- for key in required_data_keys %}
            if (!values.containsKey({{ key }})) {
                throw new IllegalArgumentException(
                    "event data map is missing required entry " + {{ key }});
            }
            {%- endfor %}
            {%- endif %}
            return new {{ class_name }}(
                {%- for p in params %}
                {{ p.parse_expr }}{% if not loop.last %},{% endif %}
                {%- endfor %}
            );
        }

        public static {{ class_name }} parse(ContractEvent event) {
            return parse({{ decoded }}.of(event));
        }

        public static {{ class_name }} parse(GetEventsResponse.EventInfo event) {
            return parse({{ decoded }}.of(event));
        }
    }
"""
)


_EVENT_DISPATCHER_TEMPLATE = _template(
    """
    /**
     * Decodes an event emitted by this contract.
     *
     * <p>Candidates are tried most specific first, by declared topic count, then
     * in spec order. Declarations sharing a topic shape are separated by which
     * one can decode the data, so a candidate failing to parse is part of the
     * normal flow rather than an error.
     *
     * @return the decoded event, or empty if no declaration matches the topics
     * @throws {{ unparsed }} if the topics matched at least one
     *     declaration but none of them could decode the event
     */
    public static Optional<{{ union }}> parseEvent({{ decoded }} event) {
        List<String> failures = new ArrayList<>();
        {%- for candidate in candidates %}
        if ({{ candidate }}.matches(event)) {
            try {
                return Optional.<{{ union }}>of({{ candidate }}.parse(event));
            } catch (RuntimeException e) {
                failures.add("{{ candidate }}: " + e);
            }
        }
        {%- endfor %}
        if (!failures.isEmpty()) {
            throw new {{ unparsed }}(
                "event topics matched " + failures.size() + " declared event(s) but none"
                    + " parsed successfully (" + String.join("; ", failures) + "); the"
                    + " on-chain event format may have drifted from the spec these"
                    + " bindings were generated from");
        }
        return Optional.empty();
    }

    public static Optional<{{ union }}> parseEvent(ContractEvent event) {
        return parseEvent({{ decoded }}.of(event));
    }

    public static Optional<{{ union }}> parseEvent(GetEventsResponse.EventInfo event) {
        return parseEvent({{ decoded }}.of(event));
    }
"""
)


def _event_params(
    entry: xdr.SCSpecEventV0,
    param_names: List[str],
    prefix_topic_count: int,
    udt_members: dict,
) -> Tuple[List[dict], List[dict], List[str]]:
    """Work out how each declared parameter is typed, decoded and filtered.

    Returns the per-parameter render context, the subset that lands in the topic
    list (which drives topicFilter), and the map keys a MAP-format event must
    carry to parse.
    """
    event_name = entry.name.sc_symbol.decode()
    data_format = entry.data_format
    params: List[dict] = []
    topic_params: List[dict] = []
    required_data_keys: List[str] = []
    topic_index = prefix_topic_count
    data_index = 0
    for param, java_name in zip(entry.params, param_names):
        chain_name = param.name.decode()
        _reject_unsupported_event_type(
            param.type, event_name, chain_name, udt_members=udt_members
        )
        if (
            param.location
            == xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
        ):
            parse_expr = from_scval(param.type, f"topics.get({topic_index})")
            topic_index += 1
            topic_params.append(
                {
                    "java_name": java_name,
                    "java_type": to_java_type(param.type),
                    # Resolved against the field names below, so a parameter
                    # literally called <other>Set cannot take another's flag.
                    "set_flag": None,
                    "filter_expr": None,
                }
            )
        elif (
            data_format
            == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
        ):
            parse_expr = from_scval(param.type, "event.getData()")
        elif data_format == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC:
            parse_expr = from_scval(param.type, f"values.get({data_index})")
            data_index += 1
        elif data_format == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP:
            # SEP-48 wants every declared parameter in the map, but an emitter
            # may leave out one declared as an option: SEP-41 lets the SAC omit
            # to_muxed_id when there is no muxed ID, and the SAC spec does
            # declare it optional. An absent option decodes to null; an absent
            # required entry is rejected in parse() rather than yielding a
            # half-populated event.
            key = java_string_literal(chain_name)
            value_expr = f"values.get({key})"
            if param.type.type == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
                parse_expr = (
                    f"values.containsKey({key}) "
                    f"? {from_scval(param.type, value_expr)} : null"
                )
            else:
                parse_expr = from_scval(param.type, value_expr)
                required_data_keys.append(key)
        else:
            raise ValueError(f"Unsupported event data format: {data_format}")
        params.append(
            {
                "java_name": java_name,
                "java_type": to_java_type(param.type),
                "parse_expr": parse_expr,
            }
        )
    _allocate_topic_filter_names(topic_params, entry, param_names)
    return params, topic_params, required_data_keys


# Locals the generated build() method declares; a topic parameter that took one
# of these names would be shadowed by it rather than read from the builder.
_TOPIC_FILTER_LOCALS = frozenset({"row"})


def _allocate_topic_filter_names(
    topic_params: List[dict], entry: xdr.SCSpecEventV0, param_names: List[str]
) -> None:
    """Give each topic parameter a set-flag, and rename any that build() shadows.

    The builder holds a value and a boolean per topic. Both live in one scope
    along with build()'s locals, so all three sources have to be allocated
    together: a parameter called ``fooSet`` would otherwise claim the flag of a
    parameter called ``foo``, and one called ``row`` would silently read the
    list build() is assembling.
    """
    used = set(param_names) | _TOPIC_FILTER_LOCALS
    for topic in topic_params:
        while topic["java_name"] in _TOPIC_FILTER_LOCALS:
            topic["java_name"] += "_"
            used.add(topic["java_name"])
        flag = topic["java_name"] + "Set"
        while flag in used:
            flag += "_"
        used.add(flag)
        topic["set_flag"] = flag

    # The filter expression names the field, so it can only be built once the
    # renames above are settled.
    topic_types = [
        param
        for param in entry.params
        if param.location
        == xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
    ]
    for topic, param in zip(topic_params, topic_types):
        topic["filter_expr"] = to_scval(param.type, topic["java_name"])


def render_event_helpers(names: dict):
    return _EVENT_HELPERS_TEMPLATE.render(**names)


def render_event(
    entry: xdr.SCSpecEventV0, class_name: str, names: dict, udt_members: dict
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
    params, topic_params, required_data_keys = _event_params(
        entry, param_names, len(prefix_symbols), udt_members
    )
    return _EVENT_TEMPLATE.render(
        class_name=class_name,
        **names,
        event_name=java_string_literal(entry.name.sc_symbol.decode()),
        prefix_symbols=[java_string_literal(symbol) for symbol in prefix_symbols],
        total_topics=declared_topic_count(entry),
        params=params,
        topic_params=topic_params,
        has_vec_data=data_format
        == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_VEC,
        has_map_data=data_format
        == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP,
        validate_void_data=(
            data_format
            == xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
            and not data_params
        ),
        required_data_keys=required_data_keys,
        data_param_count=len(data_params),
    )


def render_event_dispatcher(
    entries: List[xdr.SCSpecEventV0], class_names: List[str], names: dict
):
    # Most specific first, so a looser declaration cannot swallow events of a
    # tighter one through the trailing-topic tolerance in matches().
    #
    # Static prefix topics come first in the key, not just the total: matches()
    # only ever checks the prefix, so a declaration with two static topics is
    # strictly more selective than one with a single static topic followed by a
    # parameter, even though both declare two. Ties keep spec order, which is
    # what separates declarations sharing a topic shape - the SAC transfer
    # family all declare one prefix and three topics, and are told apart by
    # which one can decode the data.
    candidates = [
        name
        for _, name in sorted(
            zip(entries, class_names),
            key=lambda pair: (
                -len(pair[0].prefix_topics),
                -declared_topic_count(pair[0]),
            ),
        )
    ]
    return _EVENT_DISPATCHER_TEMPLATE.render(candidates=candidates, **names)


def _convert(owner, attr: str = "name") -> None:
    """Rewrite a spec identifier into its Java spelling.

    The original bytes are kept on a parallel ``<attr>_r`` attribute, which the
    templates read wherever the name goes on the wire. Identifiers the wire
    never sees (function parameters, enum cases) do not need it, but setting it
    uniformly costs nothing and keeps the rename in one place.
    """
    original = getattr(owner, attr)
    setattr(owner, f"{attr}_r", original)
    setattr(owner, attr, convert_name(original))


def append_underscore(specs: List[xdr.SCSpecEntry]):
    """Convert every spec identifier to the Java name the bindings will use."""
    for spec in specs:
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            _convert(spec.udt_struct_v0)
            for field in spec.udt_struct_v0.fields:
                _convert(field)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            _convert(spec.udt_union_v0)
            for union_case in spec.udt_union_v0.cases:
                if (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0
                ):
                    _convert(union_case.tuple_case)
                elif (
                    union_case.kind
                    == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0
                ):
                    _convert(union_case.void_case)
                else:
                    raise ValueError(f"Unsupported union case kind: {union_case.kind}")
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            _convert(spec.function_v0.name, "sc_symbol")
            for param in spec.function_v0.inputs:
                _convert(param)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
            _convert(spec.udt_enum_v0)
            for enum_case in spec.udt_enum_v0.cases:
                _convert(enum_case)
        elif spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
            _convert(spec.udt_error_enum_v0)
            for error_enum_case in spec.udt_error_enum_v0.cases:
                _convert(error_enum_case)


def generate_binding(specs: List[xdr.SCSpecEntry], package: str) -> str:
    append_underscore(specs)

    generated = []
    generated.append(
        f"// This file was generated by stellar_contract_bindings v{stellar_contract_bindings_version} and stellar_sdk v{stellar_sdk_version}."
    )
    generated.append(f"package {package};")
    generated.append(render_imports(package))
    generated.append("public class Client extends ContractClient {")
    generated.append(render_tuple_classes(specs))

    function_specs: List[xdr.SCSpecFunctionV0] = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and not spec.function_v0.name.sc_symbol.decode().startswith("__")
    ]
    generated.append(render_functions(function_specs))

    event_specs: List[xdr.SCSpecEventV0] = [
        spec.event_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0
    ]
    if event_specs:
        helper_names, event_class_names, event_union_name = resolve_event_names(
            specs, event_specs
        )
        names = dict(zip(("union", "decoded", "unparsed"), helper_names))
        udt_members = _udt_member_types(specs)
        generated.append(render_event_helpers(names))
        for event_spec, event_cls_name in zip(event_specs, event_class_names):
            generated.append(
                render_event(event_spec, event_cls_name, names, udt_members)
            )
        generated.append(render_event_dispatcher(event_specs, event_class_names, names))

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
    from stellar_contract_bindings.utils import get_specs_by_wasm_file

    wasm_file = "/Users/overcat/repo/lightsail/stellar-contract-bindings/tests/contracts/target/wasm32-unknown-unknown/release/python.wasm"
    specs = get_specs_by_wasm_file(wasm_file)
    generated = generate_binding(specs, package="org.stellar.sdk")
    print(generated)
