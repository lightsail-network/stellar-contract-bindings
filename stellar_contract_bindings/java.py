"""Java binding generator.

The bindings for a contract are emitted as one file holding a single public
class, ``Client`` by default, which extends the SDK's ``ContractClient``. Every
contract function becomes a pair of methods on it, and everything else the
spec declares is nested inside it: one class per struct, union and event, one
enum per enum and error enum, plus the scaffolding they share (``MethodOptions``,
``Result``, the tuple classes and the event dispatcher).

Generation runs in three stages, kept apart on purpose:

1. :func:`build_model` reads the spec entries and decides every Java name
   the output will use. Spec names are only length-limited, so they can be
   keywords, collide with each other once converted to Java conventions, or
   shadow the SDK and JDK types the generated code needs. All of that is
   settled here, before a line of Java exists, and the spec objects are never
   modified.
2. :class:`_Codec` maps spec types to Java types and to the expressions that
   encode a value into an ``SCVal`` and decode one back.
3. The ``_render_*`` functions write the Java through :class:`_Java`, an
   indentation-aware line emitter.

The generated code introduces identifiers of its own, such as the lambda
parameters inside the codec expressions and the locals of the decoders. They
are ordinary names, kept apart from the spec-derived ones by construction:
instance methods reach their fields through ``this``, the static decoders
have no spec-derived parameters, and the one scope where both meet, a
contract function's parameter list, reserves the names its body will use.

The generated source is pure ASCII: text from the spec is escaped in string
literals and Javadoc, so its meaning does not depend on the encoding javac
happens to read the file with.
"""

from __future__ import annotations

import os
import re
import textwrap
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import (
    Callable,
    Container,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

import click
from stellar_sdk import StrKey
from stellar_sdk import __version__ as stellar_sdk_version
from stellar_sdk import xdr

from stellar_contract_bindings import __version__ as stellar_contract_bindings_version
from stellar_contract_bindings.utils import get_specs_by_contract_id

# The generated source compiles against this SDK release or newer: it needs the
# key-sorting Scv.toMap(Map) and the ContractClient.invoke overload with the
# simulate/restore flags.
MINIMUM_SDK_VERSION = "4.0.0"

DEFAULT_CLASS_NAME = "Client"
DEFAULT_PACKAGE = "org.stellar"


# ---------------------------------------------------------------------------
# Lexical helpers
# ---------------------------------------------------------------------------

# https://docs.oracle.com/javase/specs/jls/se21/html/jls-3.html#jls-3.9
# The literals and the lone underscore are not keywords by the letter of the
# spec, but they are just as unusable as identifiers. The last line holds the
# restricted identifiers: none may name a type, and javac already warns about
# `yield` as a variable, so they are avoided everywhere.
_JAVA_KEYWORDS = frozenset("""
    abstract assert boolean break byte case catch char class const continue
    default do double else enum extends final finally float for goto if
    implements import instanceof int interface long native new package private
    protected public return short static strictfp super switch synchronized
    this throw throws transient try void volatile while
    true false null _
    var yield record sealed permits
    """.split())

_PLACEHOLDER_NAME = "unnamed"


def is_java_keyword(word: str) -> bool:
    return word in _JAVA_KEYWORDS


def java_identifier(name: str) -> str:
    """Return a valid, pure-ASCII Java identifier for a spec name.

    Every character Java does not accept, and every non-ASCII one, becomes an
    underscore, so two different names stay different as often as possible; a
    leading digit gets an underscore in front. Keywords take a trailing
    underscore. A ``$`` is treated like any other unusable character.
    """
    candidate = "".join(
        char if (char.isascii() and (char.isalnum() or char == "_")) else "_"
        for char in name
    )
    if not candidate.strip("_"):
        candidate = _PLACEHOLDER_NAME
    if candidate[0].isdigit():
        candidate = "_" + candidate
    if is_java_keyword(candidate):
        candidate += "_"
    return candidate


def _words(name: str) -> List[str]:
    """Split a spec name into the words a Java name is assembled from.

    Rust names are snake_case, so underscores separate words. A word written
    entirely in capitals is lowered first so that ``HTTP_URL`` reads
    ``httpUrl`` rather than ``hTTPURL``. The keyword suffix java_identifier
    may have added is dropped: it is put back once the words are joined.
    """
    words = [word for word in re.split(r"_+", java_identifier(name)) if word]
    words = [
        word.lower() if len(word) > 1 and word.isupper() else word for word in words
    ]
    return words or [_PLACEHOLDER_NAME]


def to_camel_case(name: str) -> str:
    """Convert a spec name to a lowerCamelCase Java member name."""
    head, *tail = _words(name)
    return java_identifier(
        head[:1].lower() + head[1:] + "".join(w[:1].upper() + w[1:] for w in tail)
    )


def to_pascal_case(name: str) -> str:
    """Convert a spec name to an UpperCamelCase Java type name."""
    return java_identifier("".join(w[:1].upper() + w[1:] for w in _words(name)))


# Characters with a named escape in a Java string literal.
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

    Unicode escapes are processed in a translation phase *before* lexing (JLS
    3.3), so a ``\\uXXXX`` that decodes to a quote would close the literal even
    though it sits inside one. Unicode escapes are therefore only used for
    characters at or above U+0080, which can never be syntactically
    significant; control characters take an octal escape instead. Always three
    octal digits, so a following digit cannot extend the escape.
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


def javadoc_lines(text: str) -> List[str]:
    """Escape spec text for the inside of a Javadoc comment, one line each.

    Javadoc is HTML, so ``&``, ``<`` and ``>`` are escaped, and ``@`` is
    escaped so that a line of the doc cannot become a block tag or start an
    inline one. A backslash is escaped because javac translates ``\\uXXXX``
    everywhere, comments included, so ``\\u002a\\u002f`` would end the comment
    early; the ``*/`` sequence itself is broken up for the same reason. Every
    other non-ASCII or control character is written as a numeric entity, which
    Javadoc renders back to the character.
    """
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        escaped = []
        for char in line:
            if char == "&":
                escaped.append("&amp;")
            elif char == "<":
                escaped.append("&lt;")
            elif char == ">":
                escaped.append("&gt;")
            elif char == "@":
                escaped.append("&#64;")
            elif char == "\\":
                escaped.append("&#92;")
            elif char == "/" and escaped and escaped[-1] == "*":
                escaped.append("&#47;")
            elif " " <= char <= "~":
                escaped.append(char)
            elif char == "\t":
                escaped.append("    ")
            elif char < " " or char == "\x7f":
                continue
            else:
                escaped.append(f"&#{ord(char)};")
        out.append("".join(escaped).rstrip())
    return out


# ---------------------------------------------------------------------------
# Line emitter
# ---------------------------------------------------------------------------


class _Java:
    """An indentation-aware line emitter for Java source."""

    INDENT = "    "

    def __init__(self) -> None:
        self._lines: List[str] = []
        self._depth = 0

    def line(self, text: str = "") -> None:
        self._lines.append(f"{self.INDENT * self._depth}{text}" if text else "")

    def lines(self, text: str) -> None:
        for line in text.split("\n"):
            self.line(line)

    def blank(self) -> None:
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    @contextmanager
    def indented(self) -> Iterator[None]:
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1

    @contextmanager
    def block(self, header: str, footer: str = "}") -> Iterator[None]:
        self.line(f"{header} {{")
        with self.indented():
            yield
        self.line(footer)

    def javadoc(
        self,
        text: str,
        tags: Sequence[Tuple[str, str]] = (),
        spec: bool = True,
        trailer: str = "",
    ) -> None:
        """Write a Javadoc block.

        ``spec`` says whether ``text`` comes from the contract spec, in which
        case it is escaped and its own line breaks are kept, or from the
        generator, in which case it is trusted and re-wrapped. ``trailer`` is
        a trusted paragraph of the generator's own that follows the text. A
        tag's text is always treated as spec text; the generator's own tag
        texts carry nothing that escaping would change.
        """
        if spec:
            body = javadoc_lines(text) if text.strip() else []
        else:
            body = self._wrap(text)
        if trailer:
            if body:
                body.append("")
            body.extend(self._wrap(trailer))
        rendered: List[str] = list(body)
        if tags:
            if rendered:
                rendered.append("")
            for tag, tag_text in tags:
                first, *rest = javadoc_lines(tag_text) or [""]
                rendered.append(f"{tag} {first}".rstrip())
                rendered.extend(f"    {line}" for line in rest)
        if not rendered:
            return
        if len(rendered) == 1 and not tags:
            single = f"/** {rendered[0]} */"
            if len(single) + len(self.INDENT) * self._depth <= _LINE_WIDTH:
                self.line(single)
                return
        self.line("/**")
        for line in rendered:
            self.line(f" * {line}".rstrip())
        self.line(" */")

    def call(self, prefix: str, arguments: Sequence[str], suffix: str = ";") -> None:
        """Write ``prefix(arguments)suffix``, one argument per line if long."""
        single = f"{prefix}({', '.join(arguments)}){suffix}"
        if len(single) + len(self.INDENT) * self._depth <= _LINE_WIDTH:
            self.line(single)
            return
        self.line(f"{prefix}(")
        with self.indented():
            for i, argument in enumerate(arguments):
                end = f"){suffix}" if i == len(arguments) - 1 else ","
                self.line(f"{argument}{end}")

    def _wrap(self, text: str) -> List[str]:
        """Wrap the generator's own doc text to the line width, per paragraph."""
        width = max(40, 96 - len(self.INDENT) * self._depth - 3)
        lines: List[str] = []
        for i, paragraph in enumerate(text.split("\n\n")):
            if i:
                lines.append("")
            lines.extend(
                textwrap.wrap(
                    " ".join(paragraph.split()), width, break_on_hyphens=False
                )
                or [""]
            )
        return lines

    def text(self) -> str:
        return "\n".join(self._lines)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


class _Scope:
    """Allocates unique names within one Java scope.

    ``key`` maps a name to the form that has to be unique: field names, for
    example, are keyed by the getter Lombok derives from them, so ``foo`` and
    ``Foo`` cannot both be claimed. Collisions take the smallest numeric suffix
    that is free, which is what the TypeScript generator does too.
    """

    def __init__(
        self, reserved: Sequence[str] = (), key: Callable[[str], str] = lambda n: n
    ) -> None:
        self._key = key
        self._used: Set[str] = {key(name) for name in reserved}

    def reserve(self, name: str) -> None:
        self._used.add(self._key(name))

    def taken(self, name: str) -> bool:
        return self._key(name) in self._used

    def claim(self, preferred: str, avoid: Container[str] = frozenset()) -> str:
        """Claim ``preferred`` or its first free numbered variant.

        ``avoid`` holds names that are not claimed in this scope but must not
        be taken either, such as the case names nested inside the unions.
        """
        candidate, suffix = preferred, 2
        while self.taken(candidate) or candidate in avoid:
            candidate = f"{preferred}{suffix}"
            suffix += 1
        self.reserve(candidate)
        return candidate


def lombok_getter(name: str, primitive_boolean: bool) -> str:
    """The getter Lombok derives from a field.

    A ``boolean`` field gets ``isX()``, or keeps its own name when it already
    starts with ``is`` and a capital; everything else gets ``getX()``. Two
    fields that derive the same getter cannot coexist: Lombok generates it for
    the first and silently skips it for the second.
    """
    if primitive_boolean:
        if re.match(r"is[A-Z]", name):
            return name
        return "is" + name[:1].upper() + name[1:]
    return "get" + name[:1].upper() + name[1:]


class _FieldScope:
    """Allocates the fields of one Lombok value class.

    A field name has to be unique, and so does the getter derived from it,
    which depends on the field's type; both are checked. A field that also
    gets a builder setter of its own name cannot be a ``long`` called
    ``wait``: the setter would override the final ``Object.wait(long)``.
    """

    def __init__(self, reserved: Sequence[str] = ()) -> None:
        self._names = _Scope(reserved=reserved)
        self._getters = _Scope(reserved=[lombok_getter(n, False) for n in reserved])

    def claim(self, preferred: str, primitive: Optional[str], setter: bool) -> str:
        boolean = primitive == "boolean"
        candidate, suffix = preferred, 2
        while (
            self._names.taken(candidate)
            or self._getters.taken(lombok_getter(candidate, boolean))
            or (setter and candidate == "wait" and primitive == "long")
        ):
            candidate = f"{preferred}{suffix}"
            suffix += 1
        self._names.reserve(candidate)
        self._getters.reserve(lombok_getter(candidate, boolean))
        return candidate


# Every type the generated code references by simple name, and where it lives.
# All UDTs are nested in the client class, so one named after any of these
# would shadow it for the whole file; when that happens the generated code
# spells the shadowed type in full instead of renaming the contract's type.
_EXTERNAL_TYPES = {
    "Boolean": "java.lang.Boolean",
    "Integer": "java.lang.Integer",
    "Long": "java.lang.Long",
    "String": "java.lang.String",
    "Void": "java.lang.Void",
    "Object": "java.lang.Object",
    "Override": "java.lang.Override",
    "RuntimeException": "java.lang.RuntimeException",
    "IllegalArgumentException": "java.lang.IllegalArgumentException",
    "IllegalStateException": "java.lang.IllegalStateException",
    "ArrayList": "java.util.ArrayList",
    "Arrays": "java.util.Arrays",
    "Collections": "java.util.Collections",
    "LinkedHashMap": "java.util.LinkedHashMap",
    "List": "java.util.List",
    "Map": "java.util.Map",
    "Optional": "java.util.Optional",
    "Function": "java.util.function.Function",
    "BigInteger": "java.math.BigInteger",
    "StandardCharsets": "java.nio.charset.StandardCharsets",
    "Matcher": "java.util.regex.Matcher",
    "Pattern": "java.util.regex.Pattern",
    "SimulationFailedException": "org.stellar.sdk.contract.exception.SimulationFailedException",
    "IOException": "java.io.IOException",
    "Address": "org.stellar.sdk.Address",
    "KeyPair": "org.stellar.sdk.KeyPair",
    "Network": "org.stellar.sdk.Network",
    "AssembledTransaction": "org.stellar.sdk.contract.AssembledTransaction",
    "ContractClient": "org.stellar.sdk.contract.ContractClient",
    "GetEventsResponse": "org.stellar.sdk.responses.sorobanrpc.GetEventsResponse",
    "Scv": "org.stellar.sdk.scval.Scv",
    "ContractEvent": "org.stellar.sdk.xdr.ContractEvent",
    "SCError": "org.stellar.sdk.xdr.SCError",
    "SCErrorType": "org.stellar.sdk.xdr.SCErrorType",
    "SCVal": "org.stellar.sdk.xdr.SCVal",
    "SCValType": "org.stellar.sdk.xdr.SCValType",
    "Uint32": "org.stellar.sdk.xdr.Uint32",
    "XdrUnsignedInteger": "org.stellar.sdk.xdr.XdrUnsignedInteger",
    "AllArgsConstructor": "lombok.AllArgsConstructor",
    "Builder": "lombok.Builder",
    "EqualsAndHashCode": "lombok.EqualsAndHashCode",
    "Getter": "lombok.Getter",
    "ToString": "lombok.ToString",
    "Value": "lombok.Value",
}

# The roots of every package the generated code names in full, or that the
# code Lombok generates names in full (java.lang.Object, for one). A type or a
# variable called after one would hide the package from every qualified name
# in its scope, so no spec-derived name may be one of these.
_PACKAGE_ROOTS = ("java", "org", "lombok")

# Methods the client class inherits. A contract function of the same name would
# override one, or overload it confusingly, so functions never take these. The
# generated helpers live in a nested class of their own, out of the way.
_INHERITED_METHODS = frozenset("""
    invoke close equals hashCode toString getClass notify notifyAll wait
    finalize clone getDefaultOptions
    """.split())


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class StructField:
    wire: str
    name: str
    type: xdr.SCSpecTypeDef
    doc: str


@dataclass
class StructModel:
    spec_name: str
    name: str
    doc: str
    fields: List[StructField]
    is_tuple: bool
    # The Lombok builder nested in the struct, named around the client's
    # types so that it cannot hide one the struct's fields refer to.
    builder_name: str = "Builder"


@dataclass
class EnumCase:
    wire: str
    name: str
    value: int
    doc: str


@dataclass
class EnumModel:
    spec_name: str
    name: str
    doc: str
    cases: List[EnumCase]
    is_error: bool
    # The private field holding a case's value; it moves aside for a case
    # named after it, since constants and fields share the enum's scope.
    value_field: str = "value"


@dataclass
class UnionCase:
    wire: str
    name: str
    constant: str
    # The name of this case's function in the union's match(...) method.
    match_param: str
    types: List[xdr.SCSpecTypeDef]
    doc: str


@dataclass
class UnionModel:
    spec_name: str
    name: str
    kind_name: str
    doc: str
    cases: List[UnionCase]
    # The private field of the Kind enum holding a case's symbol.
    symbol_field: str = "symbol"
    # The type parameter of match(...); it would hide a case of the same name.
    match_type_param: str = "R"


@dataclass
class Param:
    wire: str
    name: str
    type: xdr.SCSpecTypeDef
    doc: str


@dataclass
class FunctionModel:
    wire: str
    name: str
    doc: str
    params: List[Param]
    output: Optional[xdr.SCSpecTypeDef]


@dataclass
class EventParam:
    wire: str
    name: str
    type: xdr.SCSpecTypeDef
    doc: str
    in_topics: bool


@dataclass
class EventModel:
    wire: str
    name: str
    builder_name: str
    doc: str
    prefix_topics: List[str]
    params: List[EventParam]
    data_format: xdr.SCSpecEventDataFormat

    @property
    def topic_params(self) -> List[EventParam]:
        return [p for p in self.params if p.in_topics]

    @property
    def data_params(self) -> List[EventParam]:
        return [p for p in self.params if not p.in_topics]

    @property
    def declared_topic_count(self) -> int:
        return len(self.prefix_topics) + len(self.topic_params)


@dataclass
class Model:
    package: str
    class_name: str
    # The declarations by kind, each list in spec order.
    structs: List[StructModel] = field(default_factory=list)
    enums: List[EnumModel] = field(default_factory=list)
    unions: List[UnionModel] = field(default_factory=list)
    functions: List[FunctionModel] = field(default_factory=list)
    events: List[EventModel] = field(default_factory=list)
    # Every UDT declaration in spec order, so the output keeps it.
    declarations: List[Union[StructModel, UnionModel, EnumModel]] = field(
        default_factory=list
    )
    # Java class name of every UDT, keyed by spec name.
    udt_names: Dict[str, str] = field(default_factory=dict)
    error_enum_names: Set[str] = field(default_factory=set)
    # Generated helper names, resolved against the contract's own types.
    method_options: str = "MethodOptions"
    options_builder: str = "Builder"
    codec_class: str = "Codec"
    result: str = "Result"
    uses_result: bool = False
    tuples: Dict[int, str] = field(default_factory=dict)
    event_interface: str = "Event"
    decoded_event: str = "DecodedEvent"
    unparsed_event: str = "UnparsedEventException"
    parse_event: str = "parseEvent"
    # External types a contract type shadows, which are spelled in full.
    shadowed: Set[str] = field(default_factory=set)
    diagnostics: List[str] = field(default_factory=list)


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _udt_entry(spec: xdr.SCSpecEntry):
    """The UDT payload of a spec entry, or None for functions and events."""
    kind = spec.kind
    if kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
        return spec.udt_struct_v0
    if kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
        return spec.udt_union_v0
    if kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ENUM_V0:
        return spec.udt_enum_v0
    if kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0:
        return spec.udt_error_enum_v0
    return None


def is_tuple_struct(entry: xdr.SCSpecUDTStructV0) -> bool:
    """A tuple struct declares its fields by position: ``0``, ``1``, ..."""
    return bool(entry.fields) and all(
        f.name.decode() == str(i) for i, f in enumerate(entry.fields)
    )


def _primitive(td: xdr.SCSpecTypeDef) -> Optional[str]:
    """The Java primitive a plain value of this type is declared as, if any."""
    scalar = _JAVA_SCALARS.get(td.type)
    return _PRIMITIVES.get(scalar) if scalar else None


def _bare_udt_name(spec_name: str) -> str:
    """The last segment of a possibly module-qualified spec name."""
    segments = [segment for segment in spec_name.split("::") if segment]
    return java_identifier(segments[-1] if segments else spec_name)


def _flat_udt_name(spec_name: str) -> str:
    segments = [segment for segment in spec_name.split("::") if segment]
    return java_identifier("_".join(segments) if segments else spec_name)


def _walk_types(
    td: xdr.SCSpecTypeDef, visit: Callable[[xdr.SCSpecTypeDef], None]
) -> None:
    """Call ``visit`` on this type and every type nested inside it."""
    visit(td)
    t = td.type
    if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
        _walk_types(td.option.value_type, visit)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        _walk_types(td.result.ok_type, visit)
        _walk_types(td.result.error_type, visit)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
        _walk_types(td.vec.element_type, visit)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
        _walk_types(td.map.key_type, visit)
        _walk_types(td.map.value_type, visit)
    elif t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
        for value_type in td.tuple.value_types:
            _walk_types(value_type, visit)


def unwrap_result_output(td: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    """Reduce a function output declared ``Result<T, E>`` to its Ok arm.

    Returning ``Err`` traps the invocation and the SDK raises, so the value a
    generated ``AssembledTransaction<T>`` decodes is always a T. Everywhere
    else a Result is a value that may carry either arm, and is generated as
    the ``Result`` class.
    """
    if td.type == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
        return td.result.ok_type
    return td


def _spec_types(specs: Sequence[xdr.SCSpecEntry]) -> Iterator[xdr.SCSpecTypeDef]:
    """Every type a spec declares, read straight from the entries.

    The same types :func:`_every_type` yields once the model is built; this
    one is for decisions that have to be made before it is.
    """
    for spec in specs:
        kind = spec.kind
        if kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            for f in spec.udt_struct_v0.fields:
                yield f.type
        elif kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            for case in spec.udt_union_v0.cases:
                if case.tuple_case is not None:
                    yield from case.tuple_case.type
        elif kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0:
            for p in spec.function_v0.inputs:
                yield p.type
            for output in spec.function_v0.outputs:
                yield unwrap_result_output(output)
        elif kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0:
            for p in spec.event_v0.params:
                yield p.type


def _every_type(model: Model) -> Iterator[xdr.SCSpecTypeDef]:
    """Every type the generated code has to encode or decode."""
    for struct in model.structs:
        for f in struct.fields:
            yield f.type
    for union in model.unions:
        for case in union.cases:
            yield from case.types
    for function in model.functions:
        for param in function.params:
            yield param.type
        if function.output is not None:
            yield function.output
    for event in model.events:
        for event_param in event.params:
            yield event_param.type


def build_model(
    specs: Sequence[xdr.SCSpecEntry],
    package: str = DEFAULT_PACKAGE,
    class_name: str = DEFAULT_CLASS_NAME,
) -> Model:
    """Resolve every Java name the bindings will use.

    Contract types keep their declared names wherever Java allows it, and
    win every collision with a generated name: a helper, an event class or an
    SDK type that a contract type displaces is renamed or spelled in full
    instead. Only a collision between two contract types, or with a Java
    keyword, changes a contract type's name, and every rename is reported in
    ``diagnostics``.
    """
    model = Model(package=package, class_name=class_name)
    diagnostics = model.diagnostics

    # 1. Type names nested directly in the client class. A nested class cannot
    #    share the name of its enclosing class, nor of a package root.
    types = _Scope(reserved=[class_name, *_PACKAGE_ROOTS])

    udt_specs = [(spec, _udt_entry(spec)) for spec in specs]
    udt_specs = [(spec, udt) for spec, udt in udt_specs if udt is not None]
    spec_names = [_decode(udt.name) for _, udt in udt_specs]
    bare_claimants: Dict[str, int] = {}
    for spec_name in dict.fromkeys(spec_names):
        bare = _bare_udt_name(spec_name)
        bare_claimants[bare] = bare_claimants.get(bare, 0) + 1

    for spec_name in dict.fromkeys(spec_names):
        # The bare name is what the contract's own code calls the type. The
        # module path is only spelled out when several modules claim one name.
        bare = _bare_udt_name(spec_name)
        preferred = bare if bare_claimants[bare] == 1 else _flat_udt_name(spec_name)
        name = types.claim(preferred)
        model.udt_names[spec_name] = name
        if name != spec_name:
            diagnostics.append(f"type {spec_name!r} is generated as {name}")

    # 2. Events: <Name>Event, after the UDTs so a UDT of that name wins.
    event_specs = [
        spec.event_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0
        and spec.event_v0 is not None
    ]
    event_names = []
    for event_spec in event_specs:
        wire = _decode(event_spec.name.sc_symbol)
        preferred = to_pascal_case(wire)
        if not preferred.endswith("Event"):
            preferred += "Event"
        name = types.claim(preferred)
        if name != preferred:
            diagnostics.append(f"event {wire!r} is generated as {name}")
        event_names.append(name)

    # 3. Scaffolding, which is renamed rather than displacing a contract type.
    #    A union case is a class nested in its union, so a case named like a
    #    helper would hide the helper from a sibling case that holds one; the
    #    helpers steer clear of every case name, and the case keeps its own.
    case_names = {
        java_identifier(_case_name(case))
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0
        for case in spec.udt_union_v0.cases
    }
    model.method_options = types.claim("MethodOptions", case_names)
    # Nested in MethodOptions, so it must not share a name with it or with
    # any enclosing or referenced type.
    builder = "Builder"
    while types.taken(builder) or builder == model.method_options:
        builder = f"Builder{_next_suffix(builder, 'Builder')}"
    model.options_builder = builder
    model.codec_class = types.claim("Codec", case_names)
    if event_specs:
        model.event_interface = types.claim("Event", case_names)
        model.decoded_event = types.claim("DecodedEvent", case_names)
        model.unparsed_event = types.claim("UnparsedEventException", case_names)
    arities: Set[int] = set()
    uses_result = False

    def visit(td: xdr.SCSpecTypeDef) -> None:
        nonlocal uses_result
        if td.type == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE and td.tuple.value_types:
            arities.add(len(td.tuple.value_types))
        elif td.type == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            uses_result = True

    for td in _spec_types(specs):
        _walk_types(td, visit)
    for arity in sorted(arities):
        model.tuples[arity] = types.claim(f"Tuple{arity}", case_names)
    model.uses_result = uses_result
    if uses_result:
        model.result = types.claim("Result", case_names)

    # 4. The declarations themselves. SEP-48 does not require names to be
    #    unique, but a reference to a type can only mean one declaration, so
    #    a repeated one is dropped rather than emitted as a duplicate class.
    declared: Set[str] = set()
    for spec, udt in udt_specs:
        spec_name = _decode(udt.name)
        if spec_name in declared:
            diagnostics.append(
                f"type {spec_name!r} is declared more than once; only the first declaration is generated"
            )
            continue
        declared.add(spec_name)
        name = model.udt_names[spec_name]
        kind = spec.kind
        if kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0:
            struct = _build_struct(udt, name, types, diagnostics)
            model.structs.append(struct)
            model.declarations.append(struct)
        elif kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0:
            union = _build_union(udt, name, types, diagnostics)
            model.unions.append(union)
            model.declarations.append(union)
        else:
            is_error = kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_ERROR_ENUM_V0
            enum = _build_enum(udt, name, is_error, model.codec_class, diagnostics)
            model.enums.append(enum)
            model.declarations.append(enum)
            if is_error:
                model.error_enum_names.add(name)

    # A constructor is invoked by deploying, which these bindings do not do.
    function_specs = [
        spec.function_v0
        for spec in specs
        if spec.kind == xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0
        and spec.function_v0 is not None
        and not _decode(spec.function_v0.name.sc_symbol).startswith("__")
    ]
    methods = _Scope(reserved=sorted(_INHERITED_METHODS))
    for function_spec in function_specs:
        model.functions.append(_build_function(function_spec, methods, diagnostics))
    if event_specs:
        model.parse_event = methods.claim("parseEvent")

    for event_spec, name in zip(event_specs, event_names):
        model.events.append(_build_event(event_spec, name, types, diagnostics))

    # 5. Every type name in the file, the client class included, shadows an SDK
    #    or JDK type of the same name inside the class it is declared in.
    nested = {class_name} | set(model.udt_names.values()) | set(event_names)
    for union in model.unions:
        nested.add(union.kind_name)
        nested.update(case.name for case in union.cases)
    for event in model.events:
        nested.add(event.builder_name)
    model.shadowed = {name for name in _EXTERNAL_TYPES if name in nested}

    _check_result_error_arms(model)
    return model


def _claim_member(
    scope: _Scope, preferred: str, owner: str, wire: str, diagnostics: List[str]
) -> str:
    """Claim a member name, reporting it when the preferred one was taken."""
    name = scope.claim(preferred)
    if name != preferred:
        diagnostics.append(f"{owner}{wire!r} is generated as {name}")
    return name


def _build_struct(
    udt: xdr.SCSpecUDTStructV0, name: str, types: _Scope, diagnostics: List[str]
) -> StructModel:
    tuple_struct = is_tuple_struct(udt)
    fields = _FieldScope(reserved=_PACKAGE_ROOTS)
    result = []
    for i, f in enumerate(udt.fields):
        wire = _decode(f.name)
        preferred = f"value{i}" if tuple_struct else to_camel_case(wire)
        java_name = fields.claim(preferred, _primitive(f.type), setter=not tuple_struct)
        if java_name != preferred:
            diagnostics.append(f"field {name}.{wire!r} is generated as {java_name}")
        result.append(StructField(wire, java_name, f.type, _decode(f.doc)))
    builder = "Builder"
    while types.taken(builder) or builder == name:
        builder = f"Builder{_next_suffix(builder, 'Builder')}"
    return StructModel(
        _decode(udt.name), name, _decode(udt.doc), result, tuple_struct, builder
    )


# Names an enum body uses to qualify a static call. An enum constant is a
# field, and a field in scope wins over a type of the same name, so no
# constant may take one of these; the package roots cover a qualifier
# spelled in full.
_ENUM_QUALIFIERS = ("Scv", "Optional", *_PACKAGE_ROOTS)


def _build_enum(
    udt, name: str, is_error: bool, codec_class: str, diagnostics: List[str]
) -> EnumModel:
    constants = _Scope(reserved=[codec_class, *_ENUM_QUALIFIERS])
    cases = []
    for case in udt.cases:
        wire = _decode(case.name)
        constant = _claim_member(
            constants, java_identifier(wire), f"case {name}.", wire, diagnostics
        )
        cases.append(EnumCase(wire, constant, case.value.uint32, _decode(case.doc)))
    return EnumModel(
        _decode(udt.name),
        name,
        _decode(udt.doc),
        cases,
        is_error,
        value_field=constants.claim("value"),
    )


def _case_name(case: xdr.SCSpecUDTUnionCaseV0) -> str:
    if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0:
        return _decode(case.void_case.name)
    if case.kind == xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0:
        return _decode(case.tuple_case.name)
    raise ValueError(f"Unsupported union case kind: {case.kind}")


def _build_union(
    udt: xdr.SCSpecUDTUnionV0, name: str, types: _Scope, diagnostics: List[str]
) -> UnionModel:
    # Each case is a class nested in the union: it cannot take the union's own
    # name, and must not shadow a type declared in the client class, which the
    # union's code may refer to.
    case_classes = _Scope(reserved=[name])
    constants = _Scope(reserved=_PACKAGE_ROOTS)
    match_params = _Scope(reserved=_PACKAGE_ROOTS)
    cases = []
    for case in udt.cases:
        wire = _case_name(case)
        if case.tuple_case is not None:
            doc, case_types = _decode(case.tuple_case.doc), list(case.tuple_case.type)
        else:
            doc, case_types = _decode(case.void_case.doc), []
        preferred = java_identifier(wire)
        class_name = preferred
        while case_classes.taken(class_name) or types.taken(class_name):
            class_name = f"{preferred}{_next_suffix(class_name, preferred)}"
        case_classes.reserve(class_name)
        if class_name != preferred:
            diagnostics.append(f"case {name}.{wire!r} is generated as {class_name}")
        cases.append(
            UnionCase(
                wire,
                class_name,
                constants.claim(preferred),
                match_params.claim(to_camel_case(wire)),
                case_types,
                doc,
            )
        )
    kind_name = "Kind"
    while case_classes.taken(kind_name) or types.taken(kind_name):
        kind_name = f"Kind{_next_suffix(kind_name, 'Kind')}"
    return UnionModel(
        _decode(udt.name),
        name,
        kind_name,
        _decode(udt.doc),
        cases,
        symbol_field=constants.claim("symbol"),
        match_type_param=_Scope(reserved=[case.name for case in cases]).claim("R"),
    )


def _next_suffix(current: str, preferred: str) -> int:
    suffix = current[len(preferred) :]
    return int(suffix) + 1 if suffix.isdigit() else 2


def _build_function(
    spec: xdr.SCSpecFunctionV0, methods: _Scope, diagnostics: List[str]
) -> FunctionModel:
    wire = _decode(spec.name.sc_symbol)
    preferred = to_camel_case(wire)
    name = methods.claim(preferred)
    if name != preferred:
        diagnostics.append(f"function {wire!r} is generated as {name}")
    # The options parameter shares the parameter list, and so do the lambda
    # parameters of the codec expressions in the body: Java forbids a lambda
    # parameter shadowing a method parameter.
    reserved = {"options", _RESULT_LAMBDA, *_PACKAGE_ROOTS}
    for p in spec.inputs:
        reserved |= lambda_names(p.type)
    for declared_output in spec.outputs:
        reserved |= lambda_names(unwrap_result_output(declared_output))
    params = _Scope(reserved=sorted(reserved))
    inputs = []
    for p in spec.inputs:
        param_wire = _decode(p.name)
        java_name = _claim_member(
            params,
            to_camel_case(param_wire),
            f"parameter {name}.",
            param_wire,
            diagnostics,
        )
        inputs.append(Param(param_wire, java_name, p.type, _decode(p.doc)))
    if len(spec.outputs) > 1:
        # Unreachable: SCSpecFunctionV0 declares outputs<1>.
        raise NotImplementedError("a function with several outputs is not supported")
    output: Optional[xdr.SCSpecTypeDef] = None
    if spec.outputs:
        output = unwrap_result_output(spec.outputs[0])
    return FunctionModel(wire, name, _decode(spec.doc), inputs, output)


def _build_event(
    spec: xdr.SCSpecEventV0, name: str, types: _Scope, diagnostics: List[str]
) -> EventModel:
    topic = xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
    # Every event answers getEventName(), so no parameter may take the field
    # Lombok would derive that getter from. A topic parameter is encoded inside
    # its builder setter, whose parameter takes the same name, so the codec
    # lambdas must not shadow it either.
    reserved: Set[str] = {"eventName", *_PACKAGE_ROOTS}
    for p in spec.params:
        if p.location == topic:
            reserved |= lambda_names(p.type)
    fields = _FieldScope(reserved=sorted(reserved))
    params = []
    for p in spec.params:
        wire = _decode(p.name)
        preferred = to_camel_case(wire)
        java_name = fields.claim(
            preferred, _primitive(p.type), setter=p.location == topic
        )
        if java_name != preferred:
            diagnostics.append(f"parameter {name}.{wire!r} is generated as {java_name}")
        params.append(
            EventParam(wire, java_name, p.type, _decode(p.doc), p.location == topic)
        )
    builder = "TopicFilterBuilder"
    while types.taken(builder) or builder == name:
        builder = f"TopicFilterBuilder{_next_suffix(builder, 'TopicFilterBuilder')}"
    event = EventModel(
        _decode(spec.name.sc_symbol),
        name,
        builder,
        _decode(spec.doc),
        [_decode(t.sc_symbol) for t in spec.prefix_topics],
        params,
        spec.data_format,
    )
    single = xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE
    if event.data_format == single and len(event.data_params) > 1:
        raise ValueError(
            "SINGLE_VALUE events may declare at most one data parameter; "
            f"{event.wire!r} declares {len(event.data_params)}"
        )
    return event


def _check_result_error_arms(model: Model) -> None:
    """Refuse a Result whose Err arm cannot be told apart from its Ok arm.

    SEP-48 has the error arm carry an Error or an error-enum UDT, and both
    reach the wire as SCV_ERROR; that is what the generated decoder tests to
    pick an arm. An arm of any other type encodes as an ordinary value and
    decodes straight back as the Ok arm, so a round trip would silently turn
    an Err into an Ok.
    """

    def visit(td: xdr.SCSpecTypeDef) -> None:
        if td.type != xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            return
        arm = td.result.error_type
        if arm.type == xdr.SCSpecType.SC_SPEC_TYPE_ERROR:
            return
        if arm.type == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
            spec_name = _decode(arm.udt.name)
            if model.udt_names.get(spec_name) in model.error_enum_names:
                return
            declared = f"the type {spec_name}"
        else:
            declared = arm.type.name
        raise NotImplementedError(
            f"the error arm of a Result is declared {declared}, which does not "
            f"reach the wire as SCV_ERROR; SEP-48 has it carry an Error or an "
            f"error enum, and the generated decoder has nothing else to tell "
            f"the two arms apart by"
        )

    for td in _every_type(model):
        _walk_types(td, visit)


# ---------------------------------------------------------------------------
# Types and codecs
# ---------------------------------------------------------------------------

# Scalar types whose Scv helpers are named symmetrically: to<Codec>/from<Codec>.
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
    xdr.SCSpecType.SC_SPEC_TYPE_ERROR: "Error",
}

# Scalar types and the (external) Java type each maps to, in boxed form. A
# value that can never be null, such as a plain field or parameter, takes the
# primitive from _PRIMITIVES instead; only an Option, and the arguments of a
# generic type, stay boxed.
_JAVA_SCALARS = {
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
    # A Soroban string is a byte sequence with no encoding of its own: the
    # protocol does not require UTF-8, so neither does the mapping.
    xdr.SCSpecType.SC_SPEC_TYPE_STRING: "byte[]",
    xdr.SCSpecType.SC_SPEC_TYPE_SYMBOL: "String",
    xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS: "Address",
    xdr.SCSpecType.SC_SPEC_TYPE_MUXED_ADDRESS: "Address",
    xdr.SCSpecType.SC_SPEC_TYPE_ERROR: "SCError",
}

_PRIMITIVES = {"Boolean": "boolean", "Integer": "int", "Long": "long"}

# Private static helpers the codec expressions call, emitted only when used.
_HELPERS = {
    "decodeVoid": """\
private static Void decodeVoid(SCVal scVal) {
    Scv.fromVoid(scVal);
    return null;
}""",
    "bytesN": """\
private static byte[] bytesN(byte[] bytes, int length) {
    if (bytes.length != length) {
        throw new IllegalArgumentException(
            "expected " + length + " bytes, got " + bytes.length);
    }
    return bytes;
}""",
    "encodeOption": """\
private static <T> SCVal encodeOption(T value, Function<T, SCVal> encode) {
    return value == null ? Scv.toVoid() : encode.apply(value);
}""",
    "decodeOption": """\
private static <T> T decodeOption(SCVal scVal, Function<SCVal, T> decode) {
    return scVal.getDiscriminant() == SCValType.SCV_VOID ? null : decode.apply(scVal);
}""",
    "encodeVec": """\
private static <T> SCVal encodeVec(List<T> values, Function<T, SCVal> encode) {
    List<SCVal> encoded = new ArrayList<>(values.size());
    for (T value : values) {
        encoded.add(encode.apply(value));
    }
    return Scv.toVec(encoded);
}""",
    "decodeVec": """\
private static <T> List<T> decodeVec(SCVal scVal, Function<SCVal, T> decode) {
    List<T> decoded = new ArrayList<>();
    for (SCVal element : Scv.fromVec(scVal)) {
        decoded.add(decode.apply(element));
    }
    return decoded;
}""",
    "encodeMap": """\
private static <K, V> SCVal encodeMap(
        Map<K, V> map, Function<K, SCVal> encodeKey, Function<V, SCVal> encodeValue) {
    Map<SCVal, SCVal> encoded = new LinkedHashMap<>();
    for (Map.Entry<K, V> entry : map.entrySet()) {
        encoded.put(encodeKey.apply(entry.getKey()), encodeValue.apply(entry.getValue()));
    }
    return Scv.toMap(encoded);
}""",
    "decodeMap": """\
private static <K, V> Map<K, V> decodeMap(
        SCVal scVal, Function<SCVal, K> decodeKey, Function<SCVal, V> decodeValue) {
    Map<K, V> decoded = new LinkedHashMap<>();
    for (Map.Entry<SCVal, SCVal> entry : Scv.fromMap(scVal).entrySet()) {
        decoded.put(decodeKey.apply(entry.getKey()), decodeValue.apply(entry.getValue()));
    }
    return decoded;
}""",
    "decodeTuple": """\
private static <T> T decodeTuple(SCVal scVal, int size, Function<List<SCVal>, T> build) {
    List<SCVal> elements = new ArrayList<>(Scv.fromVec(scVal));
    if (elements.size() != size) {
        throw new IllegalArgumentException(
            "expected a tuple of " + size + " values, got " + elements.size());
    }
    return build.apply(elements);
}""",
    "encodeResult": """\
private static <T, E> SCVal encodeResult(
        {result}<T, E> result, Function<T, SCVal> encodeValue, Function<E, SCVal> encodeError) {
    return result.isOk() ? encodeValue.apply(result.getValue()) : encodeError.apply(result.getError());
}""",
    "decodeResult": """\
private static <T, E> {result}<T, E> decodeResult(
        SCVal scVal, Function<SCVal, T> decodeValue, Function<SCVal, E> decodeError) {
    if (scVal.getDiscriminant() == SCValType.SCV_ERROR) {
        return {result}.err(decodeError.apply(scVal));
    }
    return {result}.ok(decodeValue.apply(scVal));
}""",
    "structField": """\
private static SCVal structField(Map<SCVal, SCVal> fields, String name) {
    SCVal value = fields.get(Scv.toSymbol(name));
    if (value == null) {
        throw new IllegalArgumentException("struct is missing the field " + name);
    }
    return value;
}""",
    "contractError": """\
private static SCVal contractError(long code) {
    return Scv.toError(SCError.builder()
        .discriminant(SCErrorType.SCE_CONTRACT)
        .contractCode(new Uint32(new XdrUnsignedInteger(code)))
        .build());
}""",
    "contractErrorCode": """\
private static long contractErrorCode(SCVal scVal) {
    SCError error = Scv.fromError(scVal);
    if (error.getDiscriminant() != SCErrorType.SCE_CONTRACT || error.getContractCode() == null) {
        throw new IllegalArgumentException(
            "expected an SCE_CONTRACT error, got " + error.getDiscriminant());
    }
    return error.getContractCode().getUint32().getNumber();
}""",
    # The host reports a contract error as "Error(Contract, #<code>)" inside the
    # text a failed simulation carries; the same text the TypeScript bindings
    # read the code from.
    "simulationErrorCode": """\
private static final Pattern CONTRACT_ERROR = Pattern.compile("Error\\\\(Contract, #(\\\\d+)\\\\)");

private static Long simulationErrorCode(String message) {
    if (message == null) {
        return null;
    }
    Matcher matcher = CONTRACT_ERROR.matcher(message);
    return matcher.find() ? Long.valueOf(matcher.group(1)) : null;
}""",
    # SEP-48: a static topic may be published as either a symbol or a string,
    # and parsers are expected to accept both.
    "staticTopicMatches": """\
private static boolean staticTopicMatches(SCVal topic, String expected) {
    if (topic.getDiscriminant() == SCValType.SCV_SYMBOL) {
        return expected.equals(Scv.fromSymbol(topic));
    }
    if (topic.getDiscriminant() == SCValType.SCV_STRING) {
        return Arrays.equals(Scv.fromString(topic), expected.getBytes(StandardCharsets.UTF_8));
    }
    return false;
}""",
    # SCVal.toXdrBase64 declares IOException, but it is writing to memory: a
    # failure is a bug here, not something a caller can act on.
    "encodeTopic": """\
private static String encodeTopic(SCVal topic) {
    try {
        return topic.toXdrBase64();
    } catch (IOException e) {
        throw new IllegalStateException("could not encode topic filter", e);
    }
}""",
    # A topic the filter leaves unset is a wildcard.
    "topicOrWildcard": """\
private static String topicOrWildcard(Map<String, SCVal> topics, String name) {
    SCVal topic = topics.get(name);
    return topic == null ? "*" : encodeTopic(topic);
}""",
    "eventDataMap": """\
private static Map<String, SCVal> eventDataMap(SCVal data) {
    Map<String, SCVal> entries = new LinkedHashMap<>();
    for (Map.Entry<SCVal, SCVal> entry : Scv.fromMap(data).entrySet()) {
        entries.put(Scv.fromSymbol(entry.getKey()), entry.getValue());
    }
    return entries;
}""",
}


# The lambda parameters the codec expressions introduce, by the type that
# needs them. A nested type appends its depth, so element -> element1 -> ...
_LAMBDA_NAMES = {
    xdr.SCSpecType.SC_SPEC_TYPE_OPTION: ("some",),
    xdr.SCSpecType.SC_SPEC_TYPE_RESULT: ("ok", "err"),
    xdr.SCSpecType.SC_SPEC_TYPE_VEC: ("element",),
    xdr.SCSpecType.SC_SPEC_TYPE_MAP: ("mapKey", "mapValue"),
    xdr.SCSpecType.SC_SPEC_TYPE_TUPLE: ("tupleValues",),
}

# The parameter of the lambda that decodes a contract function's result.
_RESULT_LAMBDA = "scVal"


def _lambda(name: str, depth: int) -> str:
    return name if depth == 0 else f"{name}{depth}"


def lambda_names(td: xdr.SCSpecTypeDef, depth: int = 0) -> Set[str]:
    """Every lambda parameter encoding or decoding this type may introduce.

    A contract function's parameters share a scope with these, and Java does
    not let a lambda parameter shadow one, so the parameter names are
    allocated around them.
    """
    names: Set[str] = set()

    def visit(inner: xdr.SCSpecTypeDef, inner_depth: int) -> None:
        for name in _LAMBDA_NAMES.get(inner.type, ()):
            names.add(_lambda(name, inner_depth))
        t = inner.type
        if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
            visit(inner.option.value_type, inner_depth + 1)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            visit(inner.result.ok_type, inner_depth + 1)
            visit(inner.result.error_type, inner_depth + 1)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
            visit(inner.vec.element_type, inner_depth + 1)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
            visit(inner.map.key_type, inner_depth + 1)
            visit(inner.map.value_type, inner_depth + 1)
        elif t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
            for value_type in inner.tuple.value_types:
                visit(value_type, inner_depth + 1)

    visit(td, depth)
    return names


# Helpers whose bodies call other helpers, which are then emitted with them.
_HELPER_DEPENDENCIES = {"topicOrWildcard": ("encodeTopic",)}


class _Codec:
    """Maps spec types to Java types and to encode/decode expressions.

    Every reference to an SDK or JDK type goes through :meth:`ext`, which
    spells a type in full when a contract type shadows its simple name, and
    records the imports the file needs. Helper methods are recorded the same
    way, so only the ones in use are emitted.
    """

    def __init__(self, model: Model) -> None:
        self.model = model
        self.used_externals: Set[str] = set()
        self.used_helpers: Set[str] = set()

    def ext(self, name: str) -> str:
        self.used_externals.add(name)
        if name in self.model.shadowed:
            return _EXTERNAL_TYPES[name]
        return name

    def helper(self, name: str) -> str:
        """The qualified name of a helper, recording that it is needed."""
        self.used_helpers.add(name)
        self.used_helpers.update(_HELPER_DEPENDENCIES.get(name, ()))
        return f"{self.model.codec_class}.{name}"

    def udt(self, td: xdr.SCSpecTypeDef) -> str:
        spec_name = _decode(td.udt.name)
        # A spec may reference a UDT it does not declare; the bare name at
        # least renders as a valid identifier.
        return self.model.udt_names.get(spec_name) or _bare_udt_name(spec_name)

    def udt_static(self, td: xdr.SCSpecTypeDef) -> str:
        """The UDT's name as the qualifier of a static call.

        A variable in scope wins over a type of the same simple name. Every
        variable the generated code declares starts with a lowercase letter or
        an underscore, so a type named that way is reached through the client
        class, whose name starts with a capital (validate_class_name sees to
        it) and so is one no variable can take.
        """
        name = self.udt(td)
        if name[0].isupper():
            return name
        return f"{self.model.class_name}.{name}"

    # -- types ------------------------------------------------------------

    def java_type(self, td: xdr.SCSpecTypeDef, boxed: bool = False) -> str:
        """The Java type of a value of this spec type.

        ``boxed`` asks for the reference type of a scalar, which a generic
        type argument or a nullable value needs; a plain field or parameter
        takes the primitive.
        """
        t = td.type
        if t in _JAVA_SCALARS:
            scalar = _JAVA_SCALARS[t]
            if not boxed and scalar in _PRIMITIVES:
                return _PRIMITIVES[scalar]
            return scalar if scalar == "byte[]" else self.ext(scalar)
        if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
            # A plain nullable reference; Option<Option<T>> collapses.
            return self.java_type(td.option.value_type, boxed=True)
        if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            ok = self.java_type(td.result.ok_type, boxed=True)
            err = self.java_type(td.result.error_type, boxed=True)
            return f"{self.model.result}<{ok}, {err}>"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
            element = self.java_type(td.vec.element_type, boxed=True)
            return f"{self.ext('List')}<{element}>"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
            key = self.java_type(td.map.key_type, boxed=True)
            value = self.java_type(td.map.value_type, boxed=True)
            return f"{self.ext('Map')}<{key}, {value}>"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
            if not td.tuple.value_types:
                return self.ext("Void")
            args = ", ".join(
                self.java_type(v, boxed=True) for v in td.tuple.value_types
            )
            return f"{self.model.tuples[len(td.tuple.value_types)]}<{args}>"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
            return self.udt(td)
        raise ValueError(f"Unsupported spec type: {t}")

    # -- encoding ---------------------------------------------------------

    def encode(self, td: xdr.SCSpecTypeDef, expr: str, depth: int = 0) -> str:
        """A Java expression encoding ``expr`` (a value of this type) to an SCVal."""
        t = td.type
        scv = self.ext("Scv")
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
            return expr
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
            return f"{scv}.toVoid()"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
            return (
                f"{scv}.toBytes({self.helper('bytesN')}({expr}, {td.bytes_n.n.uint32}))"
            )
        if t in _SCV_CODECS:
            return f"{scv}.to{_SCV_CODECS[t]}({expr})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
            var = _lambda("some", depth)
            inner = self.encode(td.option.value_type, var, depth + 1)
            return f"{self.helper('encodeOption')}({expr}, {var} -> {inner})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            ok_var, err_var = _lambda("ok", depth), _lambda("err", depth)
            ok = self.encode(td.result.ok_type, ok_var, depth + 1)
            err = self.encode(td.result.error_type, err_var, depth + 1)
            return f"{self.helper('encodeResult')}({expr}, {ok_var} -> {ok}, {err_var} -> {err})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
            var = _lambda("element", depth)
            inner = self.encode(td.vec.element_type, var, depth + 1)
            return f"{self.helper('encodeVec')}({expr}, {var} -> {inner})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
            key_var, value_var = _lambda("mapKey", depth), _lambda("mapValue", depth)
            key = self.encode(td.map.key_type, key_var, depth + 1)
            value = self.encode(td.map.value_type, value_var, depth + 1)
            return f"{self.helper('encodeMap')}({expr}, {key_var} -> {key}, {value_var} -> {value})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
            if not td.tuple.value_types:
                return f"{scv}.toVoid()"
            # No lambda of its own, but counted as a level by lambda_names(),
            # so the elements' lambdas take the names reserved for that level.
            values = ", ".join(
                self.encode(v, f"{expr}.getValue{i}()", depth + 1)
                for i, v in enumerate(td.tuple.value_types)
            )
            return f"{scv}.toVec({self.ext('Arrays')}.asList({values}))"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
            return f"{expr}.toSCVal()"
        raise ValueError(f"Unsupported spec type: {t}")

    # -- decoding ---------------------------------------------------------

    def decode(self, td: xdr.SCSpecTypeDef, expr: str, depth: int = 0) -> str:
        """A Java expression decoding ``expr`` (an SCVal) to a value of this type."""
        t = td.type
        scv = self.ext("Scv")
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VAL:
            return expr
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VOID:
            return f"{self.helper('decodeVoid')}({expr})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_BYTES_N:
            return f"{self.helper('bytesN')}({scv}.fromBytes({expr}), {td.bytes_n.n.uint32})"
        if t in _SCV_CODECS:
            return f"{scv}.from{_SCV_CODECS[t]}({expr})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
            var = _lambda("some", depth)
            inner = self.decode(td.option.value_type, var, depth + 1)
            return f"{self.helper('decodeOption')}({expr}, {var} -> {inner})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_RESULT:
            ok_var, err_var = _lambda("ok", depth), _lambda("err", depth)
            ok = self.decode(td.result.ok_type, ok_var, depth + 1)
            err = self.decode(td.result.error_type, err_var, depth + 1)
            return f"{self.helper('decodeResult')}({expr}, {ok_var} -> {ok}, {err_var} -> {err})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_VEC:
            var = _lambda("element", depth)
            inner = self.decode(td.vec.element_type, var, depth + 1)
            return f"{self.helper('decodeVec')}({expr}, {var} -> {inner})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_MAP:
            key_var, value_var = _lambda("mapKey", depth), _lambda("mapValue", depth)
            key = self.decode(td.map.key_type, key_var, depth + 1)
            value = self.decode(td.map.value_type, value_var, depth + 1)
            return f"{self.helper('decodeMap')}({expr}, {key_var} -> {key}, {value_var} -> {value})"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_TUPLE:
            if not td.tuple.value_types:
                return f"{self.helper('decodeVoid')}({expr})"
            var = _lambda("tupleValues", depth)
            values = ", ".join(
                self.decode(v, f"{var}.get({i})", depth + 1)
                for i, v in enumerate(td.tuple.value_types)
            )
            size = len(td.tuple.value_types)
            cls = self.model.tuples[size]
            return f"{self.helper('decodeTuple')}({expr}, {size}, {var} -> new {cls}<>({values}))"
        if t == xdr.SCSpecType.SC_SPEC_TYPE_UDT:
            return f"{self.udt_static(td)}.fromSCVal({expr})"
        raise ValueError(f"Unsupported spec type: {t}")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

NULL_ACCOUNT = "GAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWHF"


def _render_client_preamble(out: _Java, model: Model, codec: _Codec) -> None:
    string, keypair, network = (
        codec.ext("String"),
        codec.ext("KeyPair"),
        codec.ext("Network"),
    )
    out.javadoc(
        "The all-zero account, used as the transaction source when none is "
        "given. It exists on the public networks, and a read-only call "
        "simulated from it needs no signer.",
        spec=False,
    )
    out.line(
        f"public static final {string} NULL_ACCOUNT = {java_string_literal(NULL_ACCOUNT)};"
    )
    out.blank()
    options = model.method_options
    out.line("/** The options a call uses when it is given none. */")
    out.line(f"private final {options} defaultOptions;")
    out.blank()
    out.javadoc(
        f"Creates a new {model.class_name} for the given contract. A call that "
        "is given no options is a read-only simulation from "
        "{@link #NULL_ACCOUNT}.",
        [
            ("@param contractId", "the contract ID (C...) to interact with"),
            ("@param rpcUrl", "the URL of the Soroban RPC server"),
            ("@param network", "the network the contract is deployed on"),
        ],
        spec=False,
    )
    with out.block(
        f"public {model.class_name}({string} contractId, {string} rpcUrl, {network} network)"
    ):
        out.line(f"this(contractId, rpcUrl, network, {options}.defaults());")
    out.blank()
    out.javadoc(
        f"Creates a new {model.class_name} for the given contract, with the "
        "options every call uses unless it is given its own. Passing "
        f"{{@code {options}.signedBy(keyPair)}} makes every call a transaction "
        "from that account, ready to be signed and submitted.",
        [
            ("@param contractId", "the contract ID (C...) to interact with"),
            ("@param rpcUrl", "the URL of the Soroban RPC server"),
            ("@param network", "the network the contract is deployed on"),
            ("@param defaultOptions", "the options a call uses when it is given none"),
        ],
        spec=False,
    )
    _method_header(
        out,
        f"public {model.class_name}",
        [
            ("contractId", string),
            ("rpcUrl", string),
            ("network", network),
            ("defaultOptions", options),
        ],
    )
    with out.indented():
        out.line("super(contractId, rpcUrl, network);")
        with out.block("if (defaultOptions == null)"):
            out.line(
                f'throw new {codec.ext("IllegalArgumentException")}("defaultOptions must not be null");'
            )
        out.line("this.defaultOptions = defaultOptions;")
    out.line("}")
    out.blank()
    out.line("/** The options a call uses when it is given none. */")
    with out.block(f"public {options} getDefaultOptions()"):
        out.line("return this.defaultOptions;")
    out.blank()
    out.javadoc(
        "Options for invoking a contract function. Every field has a default, "
        "so {@code builder().build()} is a read-only simulation.\n\n"
        "The source account defaults to the signer's account when a signer is "
        f"given, and to {{@link {model.class_name}#NULL_ACCOUNT}} otherwise. A call that changes "
        "ledger state needs a signer; a read-only simulation needs neither a "
        "signer nor a source of its own.",
        spec=False,
    )
    out.line(f"@{codec.ext('Value')}")
    out.line(
        f"@{codec.ext('Builder')}(builderClassName = "
        f"{java_string_literal(model.options_builder)}, toBuilder = true)"
    )
    with out.block(f"public static class {options}"):
        out.line("/** The source account of the transaction, or null to derive it. */")
        out.line(f"{string} source;")
        out.blank()
        out.line(
            "/** The key pair that signs the transaction, or null for a read-only call. */"
        )
        out.line(f"{keypair} signer;")
        out.blank()
        out.line("/** The base fee, in stroops. */")
        out.line(f"@{codec.ext('Builder')}.Default")
        out.line("int baseFee = 100;")
        out.blank()
        out.line("/** The transaction timeout, in seconds. */")
        out.line(f"@{codec.ext('Builder')}.Default")
        out.line("int transactionTimeout = 300;")
        out.blank()
        out.line("/** How long to wait for a submitted transaction, in seconds. */")
        out.line(f"@{codec.ext('Builder')}.Default")
        out.line("int submitTimeout = 30;")
        out.blank()
        out.line(
            "/** Whether to simulate the transaction as soon as it is assembled. */"
        )
        out.line(f"@{codec.ext('Builder')}.Default")
        out.line("boolean simulate = true;")
        out.blank()
        out.line(
            "/** Whether to restore archived ledger entries the simulation reports. */"
        )
        out.line(f"@{codec.ext('Builder')}.Default")
        out.line("boolean restore = true;")
        out.blank()
        out.line(
            f"/** The defaults: a read-only simulation from {{@link {model.class_name}#NULL_ACCOUNT}}. */"
        )
        with out.block(f"public static {options} defaults()"):
            out.line("return builder().build();")
        out.blank()
        out.line("/** Options signing with {@code signer}, from its own account. */")
        with out.block(f"public static {options} signedBy({keypair} signer)"):
            out.line("return builder().signer(signer).build();")
        out.blank()
        out.line(
            "/** The source account, derived from the signer when none was set. */"
        )
        with out.block(f"public {string} sourceAccount()"):
            with out.block("if (source != null)"):
                out.line("return source;")
            out.line("return signer != null ? signer.getAccountId() : NULL_ACCOUNT;")
    out.blank()

    scval, function, assembled = (
        codec.ext("SCVal"),
        codec.ext("Function"),
        codec.ext("AssembledTransaction"),
    )
    _method_header(
        out,
        f"private <T> {assembled}<T> invoke",
        [
            ("functionName", string),
            ("parameters", f"{codec.ext('List')}<{scval}>"),
            ("options", options),
            ("parseResult", f"{function}<{scval}, T>"),
        ],
    )
    with out.indented():
        out.lines(
            "return invoke(\n"
            "    functionName,\n"
            "    parameters,\n"
            "    options.sourceAccount(),\n"
            "    options.getSigner(),\n"
            "    parseResult,\n"
            "    options.getBaseFee(),\n"
            "    options.getTransactionTimeout(),\n"
            "    options.getSubmitTimeout(),\n"
            "    options.isSimulate(),\n"
            "    options.isRestore());"
        )
    out.line("}")


def _render_function(
    out: _Java, model: Model, codec: _Codec, fn: FunctionModel
) -> None:
    assembled = codec.ext("AssembledTransaction")
    output = (
        codec.java_type(fn.output, boxed=True)
        if fn.output is not None
        else codec.ext("Void")
    )
    params = [(p.name, codec.java_type(p.type)) for p in fn.params]
    arguments = ", ".join(n for n, _ in params)
    doc = fn.doc
    tags = [(f"@param {p.name}", p.doc) for p in fn.params if p.doc]
    returns = ("@return", "the assembled transaction, which decodes the result")

    if not doc:
        # Escaped like spec text, so the wire name is safe to interpolate.
        doc = f"Invokes the contract function {fn.wire}."
    out.javadoc(doc, tags + [returns])
    _method_header(out, f"public {assembled}<{output}> {fn.name}", params)
    with out.indented():
        args = f"{arguments}, " if arguments else ""
        out.line(f"return {fn.name}({args}this.defaultOptions);")
    out.line("}")
    out.blank()
    out.javadoc(
        doc,
        tags
        + [
            (
                "@param options",
                "how to assemble the transaction, in place of the client's defaults",
            ),
            returns,
        ],
    )
    _method_header(
        out,
        f"public {assembled}<{output}> {fn.name}",
        params + [("options", model.method_options)],
    )
    with out.indented():
        encoded = ", ".join(codec.encode(p.type, p.name) for p in fn.params)
        if fn.output is None:
            parse = f"{_RESULT_LAMBDA} -> null"
        else:
            parse = f"{_RESULT_LAMBDA} -> {codec.decode(fn.output, _RESULT_LAMBDA)}"
        out.line("return invoke(")
        with out.indented():
            out.line(f"{java_string_literal(fn.wire)},")
            out.line(f"{codec.ext('Arrays')}.asList({encoded}),")
            out.line("options,")
            out.line(f"{parse});")
    out.line("}")


_LINE_WIDTH = 100


def _method_header(
    out: _Java,
    prefix: str,
    params: Sequence[Tuple[str, str]],
    terminator: str = " {",
) -> None:
    """Open a method, one parameter per line when the header would be long.

    ``terminator`` follows the closing parenthesis: a brace for a method with
    a body, a semicolon for an abstract one.
    """
    signature = ", ".join(f"{t} {n}" for n, t in params)
    header = f"{prefix}({signature}){terminator}"
    if len(header) + len(out.INDENT) * out._depth <= _LINE_WIDTH or not params:
        out.line(header)
        return
    out.line(f"{prefix}(")
    with out.indented():
        with out.indented():
            for i, (name, java_type) in enumerate(params):
                separator = f"){terminator}" if i == len(params) - 1 else ","
                out.line(f"{java_type} {name}{separator}")


def _render_helpers(out: _Java, model: Model, codec: _Codec) -> None:
    """Emit the helpers in use, as static methods of one nested class.

    Keeping them in a class of their own leaves the client's method namespace
    to the contract's functions, so no function name has to be avoided.
    """
    if not codec.used_helpers:
        return
    out.blank()
    out.javadoc(
        "The encoders and decoders the generated code shares. Every helper is "
        "static and stateless.",
        spec=False,
    )
    with out.block(f"private static final class {model.codec_class}"):
        with out.block(f"private {model.codec_class}()"):
            pass
        for name in sorted(codec.used_helpers):
            body = _HELPERS[name].replace("{result}", model.result)
            # A helper may be the first use of an external type, and spells
            # in full those a contract type shadows, like everything else.
            for ext in sorted(set(re.findall(r"\b([A-Z]\w+)\b", body))):
                if ext in _EXTERNAL_TYPES:
                    body = re.sub(rf"\b{ext}\b", codec.ext(ext), body)
            out.blank()
            out.lines(body)


def _render_tuple(out: _Java, model: Model, codec: _Codec, arity: int) -> None:
    params = ", ".join(f"T{i}" for i in range(arity))
    name = model.tuples[arity]
    out.javadoc(f"A tuple of {arity} values, encoded as a vector.", spec=False)
    out.line(f"@{codec.ext('Value')}")
    with out.block(f"public static class {name}<{params}>"):
        for i in range(arity):
            out.line(f"T{i} value{i};")
        out.blank()
        arguments = ", ".join(f"T{i} value{i}" for i in range(arity))
        with out.block(f"public static <{params}> {name}<{params}> of({arguments})"):
            out.line(
                f"return new {name}<>({', '.join(f'value{i}' for i in range(arity))});"
            )


def _render_result(out: _Java, model: Model, codec: _Codec) -> None:
    result = model.result
    illegal = codec.ext("IllegalStateException")
    out.javadoc(
        "A spec {@code Result<T, E>}, holding either the Ok value or the Err "
        "value.\n\n"
        "An Err arrives on the wire as an SCV_ERROR, which is how the two arms "
        "are told apart when decoding. A contract function that returns a "
        "Result is not generated through this class: returning Err traps the "
        "invocation and the SDK raises, so its AssembledTransaction only ever "
        "carries the Ok value.",
        spec=False,
    )
    # The getters throw for the arm that is not held, so Lombok must read
    # the fields rather than call them.
    out.line(f"@{codec.ext('EqualsAndHashCode')}(doNotUseGetters = true)")
    out.line(f"@{codec.ext('ToString')}(doNotUseGetters = true)")
    with out.block(f"public static final class {result}<T, E>"):
        out.line("private final boolean ok;")
        out.line("private final T value;")
        out.line("private final E error;")
        out.blank()
        with out.block(f"private {result}(boolean ok, T value, E error)"):
            out.line("this.ok = ok;")
            out.line("this.value = value;")
            out.line("this.error = error;")
        out.blank()
        with out.block(f"public static <T, E> {result}<T, E> ok(T value)"):
            out.line(f"return new {result}<>(true, value, null);")
        out.blank()
        with out.block(f"public static <T, E> {result}<T, E> err(E error)"):
            out.line(f"return new {result}<>(false, null, error);")
        out.blank()
        with out.block("public boolean isOk()"):
            out.line("return ok;")
        out.blank()
        with out.block("public boolean isErr()"):
            out.line("return !ok;")
        out.blank()
        out.javadoc(
            "The Ok value.", [("@throws", f"{illegal} if this is an Err")], spec=False
        )
        with out.block("public T getValue()"):
            with out.block("if (!ok)"):
                out.line(f'throw new {illegal}("not an Ok result: " + error);')
            out.line("return value;")
        out.blank()
        out.javadoc(
            "The Err value.", [("@throws", f"{illegal} if this is an Ok")], spec=False
        )
        with out.block("public E getError()"):
            with out.block("if (ok)"):
                out.line(f'throw new {illegal}("not an Err result: " + value);')
            out.line("return error;")


def _render_enum(out: _Java, model: Model, codec: _Codec, enum: EnumModel) -> None:
    scval, scv = codec.ext("SCVal"), codec.ext("Scv")
    if enum.is_error:
        out.javadoc(
            enum.doc,
            trailer="A contract error, encoded as an SCV_ERROR carrying the case's "
            "code as an SCE_CONTRACT error. {@code fromSimulationError} reads "
            "one back out of a failed call.",
        )
    else:
        out.javadoc(enum.doc)
    with out.block(f"public enum {enum.name}"):
        for i, case in enumerate(enum.cases):
            if case.doc:
                out.javadoc(case.doc)
            separator = ";" if i == len(enum.cases) - 1 else ","
            out.line(f"{case.name}({case.value}L){separator}")
        if not enum.cases:
            out.line(";")
        out.blank()
        value = enum.value_field
        out.line(f"private final long {value};")
        out.blank()
        with out.block(f"{enum.name}(long {value})"):
            out.line(f"this.{value} = {value};")
        out.blank()
        out.line("/** The case's numeric value on the wire. */")
        with out.block("public long getValue()"):
            out.line(f"return this.{value};")
        out.blank()
        with out.block(f"public static {enum.name} fromValue(long value)"):
            with out.block(f"for ({enum.name} candidate : values())"):
                with out.block(f"if (candidate.{value} == value)"):
                    out.line("return candidate;")
            out.line(
                f'throw new {codec.ext("IllegalArgumentException")}('
                f'"unknown {enum.name} value: " + value);'
            )
        out.blank()
        with out.block(f"public {scval} toSCVal()"):
            if enum.is_error:
                out.line(f"return {codec.helper('contractError')}(this.{value});")
            else:
                out.line(f"return {scv}.toUint32(this.{value});")
        out.blank()
        with out.block(f"public static {enum.name} fromSCVal({scval} scVal)"):
            if enum.is_error:
                out.line(
                    f"return fromValue({codec.helper('contractErrorCode')}(scVal));"
                )
            else:
                out.line(f"return fromValue({scv}.fromUint32(scVal));")
        if enum.is_error:
            optional, string = codec.ext("Optional"), codec.ext("String")
            out.blank()
            out.javadoc(
                "The case a failed simulation reports, if the failure is one of "
                "these contract errors. A contract function that returns an "
                "Err, or panics with one, fails its simulation, and the SDK "
                "raises; this reads the error code back out of that failure.",
                [
                    (
                        "@return",
                        "the case, or empty if the failure is not one of these errors",
                    )
                ],
                spec=False,
            )
            with out.block(
                f"public static {optional}<{enum.name}> fromSimulationError("
                f"{codec.ext('SimulationFailedException')} failure)"
            ):
                out.line("return fromSimulationError(failure.getMessage());")
            out.blank()
            out.javadoc(
                "The case named in the text of a failed simulation, if any.",
                spec=False,
            )
            with out.block(
                f"public static {optional}<{enum.name}> fromSimulationError({string} message)"
            ):
                out.line(
                    f"{codec.ext('Long')} code = {codec.helper('simulationErrorCode')}(message);"
                )
                with out.block("if (code == null)"):
                    out.line(f"return {optional}.empty();")
                with out.block(f"for ({enum.name} candidate : values())"):
                    with out.block(f"if (candidate.{value} == code)"):
                        out.line(f"return {optional}.of(candidate);")
                out.line(f"return {optional}.empty();")


def _render_struct(
    out: _Java, model: Model, codec: _Codec, struct: StructModel
) -> None:
    scval, scv = codec.ext("SCVal"), codec.ext("Scv")
    if struct.is_tuple:
        out.javadoc(struct.doc, trailer="A tuple struct, encoded as a vector.")
    else:
        out.javadoc(
            struct.doc,
            trailer=f"Build one with {{@code {struct.name}.builder()}} or the constructor.",
        )
    out.line(f"@{codec.ext('Value')}")
    if not struct.is_tuple:
        # Lombok would make the all-args constructor package-private next to
        # a builder; declaring it keeps it public.
        out.line(
            f"@{codec.ext('Builder')}(builderClassName = {java_string_literal(struct.builder_name)})"
        )
        out.line(f"@{codec.ext('AllArgsConstructor')}")
    with out.block(f"public static class {struct.name}"):
        for f in struct.fields:
            if f.doc:
                out.javadoc(f.doc)
            out.line(f"{codec.java_type(f.type)} {f.name};")
        out.blank()
        # Fields are read through this, so the locals and the lambda
        # parameters below are free to take any name a field has.
        with out.block(f"public {scval} toSCVal()"):
            if struct.is_tuple:
                out.line(f"return {scv}.toVec({codec.ext('Arrays')}.asList(")
                with out.indented():
                    for i, f in enumerate(struct.fields):
                        separator = "));" if i == len(struct.fields) - 1 else ","
                        out.line(f"{codec.encode(f.type, f'this.{f.name}')}{separator}")
            else:
                map_type = f"{codec.ext('Map')}<{scval}, {scval}>"
                out.line(f"{map_type} fields = new {codec.ext('LinkedHashMap')}<>();")
                for f in struct.fields:
                    key = f"{scv}.toSymbol({java_string_literal(f.wire)})"
                    out.line(
                        f"fields.put({key}, {codec.encode(f.type, f'this.{f.name}')});"
                    )
                out.line(f"return {scv}.toMap(fields);")
        out.blank()
        with out.block(f"public static {struct.name} fromSCVal({scval} scVal)"):
            if struct.is_tuple:
                size = len(struct.fields)
                values = _lambda("tupleValues", 0)
                out.line(
                    f"return {codec.helper('decodeTuple')}(scVal, {size}, {values} -> new {struct.name}("
                )
                with out.indented():
                    for i, f in enumerate(struct.fields):
                        separator = "));" if i == len(struct.fields) - 1 else ","
                        # Nested from depth 1: depth 0 is the lambda above.
                        out.line(
                            f"{codec.decode(f.type, f'{values}.get({i})', 1)}{separator}"
                        )
            else:
                map_type = f"{codec.ext('Map')}<{scval}, {scval}>"
                out.line(f"{map_type} fields = {scv}.fromMap(scVal);")
                out.call(
                    f"return new {struct.name}",
                    [
                        codec.decode(
                            f.type,
                            f"{codec.helper('structField')}(fields, {java_string_literal(f.wire)})",
                        )
                        for f in struct.fields
                    ],
                )


def _render_union(out: _Java, model: Model, codec: _Codec, union: UnionModel) -> None:
    scval, scv = codec.ext("SCVal"), codec.ext("Scv")
    string, illegal = codec.ext("String"), codec.ext("IllegalArgumentException")
    kind = union.kind_name
    out.javadoc(
        union.doc,
        trailer="A union, with one nested class per case. Handle every case with "
        "{@code match(...)}, or tell them apart with {@code getKind()} or "
        "{@code instanceof}.",
    )
    function, r = codec.ext("Function"), union.match_type_param
    matchers = [
        (case.match_param, f"{function}<{case.name}, {r}>") for case in union.cases
    ]
    with out.block(f"public abstract static class {union.name}"):
        with out.block(f"private {union.name}()"):
            pass
        out.blank()
        out.line(f"public abstract {kind} getKind();")
        out.blank()
        out.line(f"public abstract {scval} toSCVal();")
        out.blank()
        if union.cases:
            out.javadoc(
                "Applies the function for the case this value holds, and returns "
                "its result. Every case takes a function, so handling a new case "
                "is a compile error rather than a forgotten branch.",
                spec=False,
            )
            _method_header(
                out, f"public abstract <{r}> {r} match", matchers, terminator=";"
            )
            out.blank()
        with out.block(f"public static {union.name} fromSCVal({scval} scVal)"):
            list_type = f"{codec.ext('List')}<{scval}>"
            out.line(
                f"{list_type} elements = new {codec.ext('ArrayList')}<>({scv}.fromVec(scVal));"
            )
            with out.block("if (elements.isEmpty())"):
                out.line(f'throw new {illegal}("union value has no case symbol");')
            out.line(f"{string} symbol = {scv}.fromSymbol(elements.get(0));")
            for case in union.cases:
                with out.block(f"if (symbol.equals({java_string_literal(case.wire)}))"):
                    if not case.types:
                        out.line(f"return new {case.name}();")
                    else:
                        with out.block(
                            f"if (elements.size() != {len(case.types) + 1})"
                        ):
                            message = java_string_literal(
                                f"case {case.wire} expects {len(case.types)} value(s), got "
                            )
                            out.line(f"throw new {illegal}(")
                            with out.indented():
                                out.line(f"{message} + (elements.size() - 1));")
                        out.call(
                            f"return new {case.name}",
                            [
                                codec.decode(td, f"elements.get({i + 1})")
                                for i, td in enumerate(case.types)
                            ],
                        )
            out.line(f'throw new {illegal}("unknown {union.name} case: " + symbol);')
        out.blank()

        out.line("/** The cases, each carrying its symbol on the wire. */")
        with out.block(f"public enum {kind}"):
            for i, case in enumerate(union.cases):
                separator = ";" if i == len(union.cases) - 1 else ","
                out.line(
                    f"{case.constant}({java_string_literal(case.wire)}){separator}"
                )
            if not union.cases:
                out.line(";")
            out.blank()
            symbol = union.symbol_field
            out.line(f"private final {string} {symbol};")
            out.blank()
            with out.block(f"{kind}({string} {symbol})"):
                out.line(f"this.{symbol} = {symbol};")
            out.blank()
            with out.block(f"public {string} getSymbol()"):
                out.line(f"return this.{symbol};")

        for case in union.cases:
            out.blank()
            out.javadoc(case.doc)
            if not case.types:
                out.line(f"@{codec.ext('EqualsAndHashCode')}(callSuper = false)")
                out.line(f"@{codec.ext('ToString')}")
                with out.block(
                    f"public static final class {case.name} extends {union.name}"
                ):
                    out.line(f"@{codec.ext('Override')}")
                    with out.block(f"public {kind} getKind()"):
                        out.line(f"return {kind}.{case.constant};")
                    out.blank()
                    out.line(f"@{codec.ext('Override')}")
                    with out.block(f"public {scval} toSCVal()"):
                        symbol = f"{scv}.toSymbol({java_string_literal(case.wire)})"
                        out.line(
                            f"return {scv}.toVec({codec.ext('Collections')}.singletonList({symbol}));"
                        )
                    _render_match_override(out, codec, matchers, case, r)
                continue
            out.line(f"@{codec.ext('Value')}")
            out.line(f"@{codec.ext('EqualsAndHashCode')}(callSuper = false)")
            with out.block(f"public static class {case.name} extends {union.name}"):
                for i, td in enumerate(case.types):
                    out.line(f"{codec.java_type(td)} value{i};")
                out.blank()
                out.line(f"@{codec.ext('Override')}")
                with out.block(f"public {kind} getKind()"):
                    out.line(f"return {kind}.{case.constant};")
                out.blank()
                out.line(f"@{codec.ext('Override')}")
                with out.block(f"public {scval} toSCVal()"):
                    out.line(f"return {scv}.toVec({codec.ext('Arrays')}.asList(")
                    with out.indented():
                        out.line(f"{scv}.toSymbol({java_string_literal(case.wire)}),")
                        for i, td in enumerate(case.types):
                            separator = "));" if i == len(case.types) - 1 else ","
                            out.line(f"{codec.encode(td, f'this.value{i}')}{separator}")
                _render_match_override(out, codec, matchers, case, r)


def _render_match_override(
    out: _Java,
    codec: _Codec,
    matchers: Sequence[Tuple[str, str]],
    case: UnionCase,
    type_param: str,
) -> None:
    out.blank()
    out.line(f"@{codec.ext('Override')}")
    _method_header(out, f"public <{type_param}> {type_param} match", matchers)
    with out.indented():
        out.line(f"return {case.match_param}.apply(this);")
    out.line("}")


def _render_event_scaffolding(out: _Java, model: Model, codec: _Codec) -> None:
    scval, string = codec.ext("SCVal"), codec.ext("String")
    list_type = f"{codec.ext('List')}<{scval}>"
    decoded, illegal = model.decoded_event, codec.ext("IllegalArgumentException")

    out.javadoc("Every event this contract declares.", spec=False)
    with out.block(f"public interface {model.event_interface}"):
        out.line("/** The name the event is declared under in the contract spec. */")
        out.line(f"{codec.ext('String')} getEventName();")
    out.blank()

    out.javadoc(
        "An event's topics and data, decoded once.\n\n"
        "The dispatcher offers the same instance to every candidate event; "
        "decoding per candidate would re-parse the base64 an RPC event arrives "
        "as, once per declaration that does not match.",
        spec=False,
    )
    out.line(f"@{codec.ext('Value')}")
    with out.block(f"public static class {decoded}"):
        out.line(f"{list_type} topics;")
        out.line(f"{scval} data;")
        out.blank()
        out.line("/** Decodes an event carried in transaction meta. */")
        with out.block(
            f"public static {decoded} of({codec.ext('ContractEvent')} event)"
        ):
            with out.block(
                "if (event.getBody() == null || event.getBody().getV0() == null)"
            ):
                out.line(f'throw new {illegal}("contract event has no v0 body");')
            out.line(f"return new {decoded}(")
            with out.indented():
                out.line(
                    f"{codec.ext('Arrays')}.asList(event.getBody().getV0().getTopics()),"
                )
                out.line("event.getBody().getV0().getData());")
        out.blank()
        out.line(
            "/** Decodes an event as returned by getEvents, whose fields are base64 XDR. */"
        )
        with out.block(
            f"public static {decoded} of({codec.ext('GetEventsResponse')}.EventInfo event)"
        ):
            out.line(f"{list_type} topics = event.parseTopic();")
            out.line(f"{scval} data = event.parseValue();")
            with out.block("if (topics == null || data == null)"):
                out.line(f'throw new {illegal}("event is missing topics or value");')
            out.line(f"return new {decoded}(topics, data);")
    out.blank()

    out.javadoc(
        "Thrown when an event's topics match a declared event but no candidate "
        "could decode it, which usually means the on-chain format has drifted "
        "from the spec these bindings were generated from.",
        spec=False,
    )
    with out.block(f"public static class {model.unparsed_event} extends {illegal}"):
        out.line("private static final long serialVersionUID = 1L;")
        out.blank()
        with out.block(f"public {model.unparsed_event}({string} message)"):
            out.line("super(message);")
    out.blank()


def _render_event(out: _Java, model: Model, codec: _Codec, event: EventModel) -> None:
    scval, scv, string = codec.ext("SCVal"), codec.ext("Scv"), codec.ext("String")
    list_type = f"{codec.ext('List')}<{scval}>"
    decoded, illegal = model.decoded_event, codec.ext("IllegalArgumentException")
    fmt = xdr.SCSpecEventDataFormat
    topic_params, data_params = event.topic_params, event.data_params

    doc = event.doc
    tags = [(f"@param {p.name}", p.doc) for p in event.params if p.doc]
    out.javadoc(doc or f"The {event.wire} event.", tags)
    out.line(f"@{codec.ext('Value')}")
    with out.block(
        f"public static class {event.name} implements {model.event_interface}"
    ):
        out.line("/** The name this event is declared under in the contract spec. */")
        out.line(
            f"public static final {string} EVENT_NAME = {java_string_literal(event.wire)};"
        )
        out.blank()
        for p in event.params:
            if p.doc:
                out.javadoc(p.doc)
            out.line(f"{codec.java_type(p.type)} {p.name};")
        if event.params:
            out.blank()
        out.line(f"@{codec.ext('Override')}")
        with out.block(f"public {string} getEventName()"):
            out.line("return EVENT_NAME;")
        out.blank()

        # -- topic filter ------------------------------------------------
        out.javadoc(
            "Starts one topics row for a getEvents filter.\n\n"
            "A topic left unset is filtered as a wildcard. That is distinct from "
            "setting it to null, which matches only an explicit void.",
            spec=False,
        )
        with out.block(f"public static {event.builder_name} topicFilter()"):
            out.line(f"return new {event.builder_name}();")
        out.blank()
        with out.block(f"public static final class {event.builder_name}"):
            # Reached through this, so a setter's parameter cannot hide it.
            out.line(
                "/** The topics set so far, encoded, keyed by their wire names. */"
            )
            out.line(
                f"private final {codec.ext('Map')}<{string}, {scval}> topicValues "
                f"= new {codec.ext('LinkedHashMap')}<>();"
            )
            for p in topic_params:
                out.blank()
                with out.block(
                    f"public {event.builder_name} {p.name}({codec.java_type(p.type)} {p.name})"
                ):
                    out.line(
                        f"this.topicValues.put({java_string_literal(p.wire)}, "
                        f"{codec.encode(p.type, p.name)});"
                    )
                    out.line("return this;")
            out.blank()
            out.javadoc(
                "Builds the row.\n\n"
                'It ends with "**" so that, like {@code matches}, it also selects '
                "events carrying topics beyond the declared ones; without it the "
                "RPC matches on exact topic count and those events are skipped. "
                '"**" needs stellar-rpc v23.0.0 or newer, the release that '
                "introduced SEP-48 event specs, and does not count towards the "
                "filter's four segments.",
                spec=False,
            )
            with out.block(f"public {codec.ext('List')}<{string}> build()"):
                out.line(
                    f"{codec.ext('List')}<{string}> row = new {codec.ext('ArrayList')}<>();"
                )
                for symbol in event.prefix_topics:
                    out.line(
                        f"row.add({codec.helper('encodeTopic')}({scv}.toSymbol({java_string_literal(symbol)})));"
                    )
                for p in topic_params:
                    key = java_string_literal(p.wire)
                    out.line(
                        f"row.add({codec.helper('topicOrWildcard')}(this.topicValues, {key}));"
                    )
                out.line('row.add("**");')
                out.line(f"return {codec.ext('Collections')}.unmodifiableList(row);")
        out.blank()

        # -- matches -----------------------------------------------------
        out.javadoc(
            "Whether the topics have this event's shape.\n\n"
            "Only the static prefix and the topic count are checked. Trailing "
            "topics beyond the declared ones are ignored, because contracts "
            "append them: Stellar Asset Contract events carry the SEP-11 asset "
            "string.",
            spec=False,
        )
        with out.block(f"public static boolean matches({decoded} event)"):
            out.line(f"{list_type} topics = event.getTopics();")
            with out.block(f"if (topics.size() < {event.declared_topic_count})"):
                out.line("return false;")
            for i, symbol in enumerate(event.prefix_topics):
                with out.block(
                    f"if (!{codec.helper('staticTopicMatches')}(topics.get({i}), {java_string_literal(symbol)}))"
                ):
                    out.line("return false;")
            out.line("return true;")
        out.blank()
        with out.block(
            f"public static boolean matches({codec.ext('ContractEvent')} event)"
        ):
            out.line(f"return matches({decoded}.of(event));")
        out.blank()
        with out.block(
            f"public static boolean matches({codec.ext('GetEventsResponse')}.EventInfo event)"
        ):
            out.line(f"return matches({decoded}.of(event));")
        out.blank()

        # -- parse -------------------------------------------------------
        out.javadoc(
            "Decodes the event.",
            [("@throws", f"{illegal} if it does not have this event's shape")],
            spec=False,
        )
        with out.block(f"public static {event.name} parse({decoded} event)"):
            with out.block("if (!matches(event))"):
                out.line(f'throw new {illegal}("event does not match {event.name}");')
            if topic_params:
                out.line(f"{list_type} topics = event.getTopics();")
            values: List[str] = []
            topic_index = len(event.prefix_topics)
            data_index = 0
            if event.data_format == fmt.SC_SPEC_EVENT_DATA_FORMAT_VEC:
                out.line(
                    f"{list_type} data = new {codec.ext('ArrayList')}<>({scv}.fromVec(event.getData()));"
                )
                # Exact, unlike the trailing topics matches() tolerates: positional
                # data carries no names, so an extra value cannot be told from a
                # different declaration's data.
                with out.block(f"if (data.size() != {len(data_params)})"):
                    out.line(f"throw new {illegal}(")
                    with out.indented():
                        out.line(
                            f'"event data vector holds " + data.size() + " values, but "'
                            f' + "{event.name} declares {len(data_params)}");'
                        )
            elif event.data_format == fmt.SC_SPEC_EVENT_DATA_FORMAT_MAP:
                out.line(
                    f"{codec.ext('Map')}<{string}, {scval}> data = {codec.helper('eventDataMap')}(event.getData());"
                )
                for p in data_params:
                    if p.type.type == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
                        continue
                    with out.block(
                        f"if (!data.containsKey({java_string_literal(p.wire)}))"
                    ):
                        message = java_string_literal(
                            f"event data map is missing the entry {p.wire}"
                        )
                        out.line(f"throw new {illegal}({message});")
            elif not data_params:
                # SINGLE_VALUE with nothing declared: the data has to be void.
                out.line(f"{codec.helper('decodeVoid')}(event.getData());")

            for p in event.params:
                if p.in_topics:
                    values.append(codec.decode(p.type, f"topics.get({topic_index})"))
                    topic_index += 1
                elif event.data_format == fmt.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE:
                    values.append(codec.decode(p.type, "event.getData()"))
                elif event.data_format == fmt.SC_SPEC_EVENT_DATA_FORMAT_VEC:
                    values.append(codec.decode(p.type, f"data.get({data_index})"))
                    data_index += 1
                elif event.data_format == fmt.SC_SPEC_EVENT_DATA_FORMAT_MAP:
                    # SEP-48 wants every declared parameter in the map, but an
                    # emitter may leave out one declared as an option: SEP-41 lets
                    # the SAC omit to_muxed_id when there is no muxed ID. An
                    # absent option decodes to null.
                    key = java_string_literal(p.wire)
                    if p.type.type == xdr.SCSpecType.SC_SPEC_TYPE_OPTION:
                        inner = codec.decode(p.type, f"data.get({key})")
                        values.append(f"data.containsKey({key}) ? {inner} : null")
                    else:
                        values.append(codec.decode(p.type, f"data.get({key})"))
                else:
                    raise ValueError(
                        f"Unsupported event data format: {event.data_format}"
                    )
            out.call(f"return new {event.name}", values)
        out.blank()
        with out.block(
            f"public static {event.name} parse({codec.ext('ContractEvent')} event)"
        ):
            out.line(f"return parse({decoded}.of(event));")
        out.blank()
        with out.block(
            f"public static {event.name} parse({codec.ext('GetEventsResponse')}.EventInfo event)"
        ):
            out.line(f"return parse({decoded}.of(event));")


def _render_event_dispatcher(out: _Java, model: Model, codec: _Codec) -> None:
    decoded, iface = model.decoded_event, model.event_interface
    optional, string = codec.ext("Optional"), codec.ext("String")
    # Most specific first, so a looser declaration cannot swallow events of a
    # tighter one through the trailing-topic tolerance in matches(). Static
    # prefix topics come first in the key: matches() only ever checks the
    # prefix, so a declaration with two static topics is strictly more
    # selective than one with a single static topic followed by a parameter.
    # Ties keep spec order, which is what separates declarations sharing a
    # topic shape: the SAC transfer family is told apart by which one can
    # decode the data.
    candidates = sorted(
        model.events,
        key=lambda e: (-len(e.prefix_topics), -e.declared_topic_count),
    )
    out.javadoc(
        "Decodes an event emitted by this contract.\n\n"
        "Candidates are tried most specific first, by declared topic count, "
        "then in spec order. Declarations sharing a topic shape are separated "
        "by which one can decode the data, so a candidate failing to parse is "
        "part of the normal flow rather than an error.",
        [
            (
                "@return",
                "the decoded event, or empty if no declaration matches the topics",
            ),
            (
                "@throws",
                f"{model.unparsed_event} if the topics matched at least one "
                "declaration but none of them could decode the event",
            ),
        ],
        spec=False,
    )
    with out.block(
        f"public static {optional}<{iface}> {model.parse_event}({decoded} event)"
    ):
        out.line(
            f"{codec.ext('List')}<{string}> failures = new {codec.ext('ArrayList')}<>();"
        )
        for event in candidates:
            with out.block(f"if ({event.name}.matches(event))"):
                with out.block(
                    "try", footer=f"}} catch ({codec.ext('RuntimeException')} e) {{"
                ):
                    out.line(
                        f"return {optional}.<{iface}>of({event.name}.parse(event));"
                    )
                with out.indented():
                    out.line(f'failures.add("{event.name}: " + e);')
                out.line("}")
        with out.block("if (!failures.isEmpty())"):
            out.line(f"throw new {model.unparsed_event}(")
            with out.indented():
                out.line(
                    '"event topics matched " + failures.size() + " declared event(s) but none"'
                )
                out.line(
                    f'    + " parsed successfully (" + {string}.join("; ", failures) + "); the"'
                )
                out.line(
                    '    + " on-chain event format may have drifted from the spec these"'
                )
                out.line('    + " bindings were generated from");')
        out.line(f"return {optional}.empty();")
    out.blank()
    with out.block(
        f"public static {optional}<{iface}> {model.parse_event}({codec.ext('ContractEvent')} event)"
    ):
        out.line(f"return {model.parse_event}({decoded}.of(event));")
    out.blank()
    with out.block(
        f"public static {optional}<{iface}> {model.parse_event}({codec.ext('GetEventsResponse')}.EventInfo event)"
    ):
        out.line(f"return {model.parse_event}({decoded}.of(event));")


def render(model: Model) -> str:
    """Render the bindings for a resolved model."""
    codec = _Codec(model)
    body = _Java()
    with body.indented():
        _render_client_preamble(body, model, codec)
        for fn in model.functions:
            body.blank()
            _render_function(body, model, codec, fn)
        for declaration in model.declarations:
            body.blank()
            if isinstance(declaration, StructModel):
                _render_struct(body, model, codec, declaration)
            elif isinstance(declaration, UnionModel):
                _render_union(body, model, codec, declaration)
            else:
                _render_enum(body, model, codec, declaration)
        if model.events:
            body.blank()
            _render_event_scaffolding(body, model, codec)
            for event in model.events:
                body.blank()
                _render_event(body, model, codec, event)
            body.blank()
            _render_event_dispatcher(body, model, codec)
        for arity in sorted(model.tuples):
            body.blank()
            _render_tuple(body, model, codec, arity)
        if model.uses_result:
            body.blank()
            _render_result(body, model, codec)
        # The helpers come last, and are rendered after everything that could
        # have requested one. A helper's body may itself be the first use of an
        # external type, so the imports come after them.
        _render_helpers(body, model, codec)

    # Resolved before the imports are listed, since it may be the first use.
    base_class = codec.ext("ContractClient")

    out = _Java()
    out.line(
        f"// This file was generated by stellar_contract_bindings "
        f"v{stellar_contract_bindings_version} and stellar_sdk v{stellar_sdk_version}."
    )
    out.line(
        f"// It needs network.lightsail:stellar-sdk {MINIMUM_SDK_VERSION} or newer and "
        f"Lombok on the compile classpath."
    )
    out.line(f"package {model.package};")
    out.blank()
    imports = sorted(
        _EXTERNAL_TYPES[name]
        for name in codec.used_externals
        if name not in model.shadowed
        and not _EXTERNAL_TYPES[name].startswith("java.lang.")
    )
    for fqn in imports:
        out.line(f"import {fqn};")
    if imports:
        out.blank()
    out.javadoc(
        "Bindings for a Soroban contract, generated from its SEP-48 spec.\n\n"
        "Each contract function is a method returning an AssembledTransaction: "
        "call {@code result()} on it to read a simulated value, or "
        "{@code signAndSubmit(...)} to submit it. The contract's types are the "
        "nested classes; each one converts to and from an SCVal.",
        spec=False,
    )
    out.line(f"public class {model.class_name} extends {base_class} {{")
    out.lines(body.text())
    out.line("}")
    return out.text() + "\n"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def validate_package(package: str) -> None:
    """Raise ValueError unless ``package`` is a valid Java package name."""
    for segment in package.split("."):
        if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", segment):
            raise ValueError(f"{package!r} is not a valid Java package name")
        if is_java_keyword(segment):
            raise ValueError(
                f"{package!r} is not a valid Java package name: {segment!r} is a keyword"
            )


def validate_class_name(class_name: str) -> None:
    """Raise ValueError unless ``class_name`` can name the client class.

    The name has to start with a capital letter. That is the Java convention,
    and the generated code relies on it: every variable it declares starts
    with a lowercase letter, so the client class can qualify a type without
    a variable of the same name ever hiding it.
    """
    if not re.fullmatch(r"[A-Z][A-Za-z0-9_$]*", class_name):
        raise ValueError(
            f"{class_name!r} is not a valid Java class name: it must start with a "
            "capital letter, followed by letters, digits or underscores"
        )


def generate_binding_with_diagnostics(
    specs: Sequence[xdr.SCSpecEntry],
    package: str = DEFAULT_PACKAGE,
    class_name: str = DEFAULT_CLASS_NAME,
) -> Tuple[str, List[str]]:
    """Generate the bindings, plus printable notes about every renamed name.

    :raises ValueError: if ``package`` or ``class_name`` is not valid Java, or
        the spec declares an event the generator cannot represent.
    :raises NotImplementedError: if the spec uses a Result whose error arm the
        generated decoder could not tell from its Ok arm.
    """
    validate_package(package)
    validate_class_name(class_name)
    model = build_model(specs, package, class_name)
    return render(model), list(model.diagnostics)


def generate_binding(
    specs: Sequence[xdr.SCSpecEntry],
    package: str = DEFAULT_PACKAGE,
    class_name: str = DEFAULT_CLASS_NAME,
) -> str:
    return generate_binding_with_diagnostics(specs, package, class_name)[0]


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
    default=DEFAULT_PACKAGE,
    help="Package name for generated bindings",
)
@click.option(
    "--class-name",
    default=DEFAULT_CLASS_NAME,
    help="Name of the generated client class, which also names the file; "
    "it must start with a capital letter",
)
def command(contract_id: str, rpc_url: str, output: str, package: str, class_name: str):
    """Generate Java bindings for a Soroban contract"""
    if not StrKey.is_valid_contract(contract_id):
        click.echo(f"Invalid contract ID: {contract_id}", err=True)
        raise click.Abort()
    try:
        validate_package(package)
        validate_class_name(class_name)
    except ValueError as e:
        raise click.BadParameter(str(e))

    if output is None:
        output = os.getcwd()
    try:
        specs = get_specs_by_contract_id(contract_id, rpc_url)
    except Exception as e:
        click.echo(f"Get contract specs failed: {e}", err=True)
        raise click.Abort()

    click.echo("Generating Java bindings")
    try:
        generated, diagnostics = generate_binding_with_diagnostics(
            specs, package, class_name
        )
    except (ValueError, NotImplementedError) as e:
        click.echo(f"Cannot generate bindings for this contract: {e}", err=True)
        raise click.Abort()
    for diagnostic in diagnostics:
        click.echo(f"Note: {diagnostic}", err=True)

    if not os.path.exists(output):
        os.makedirs(output)
    output_path = os.path.join(output, f"{class_name}.java")
    with open(output_path, "w", encoding="ascii") as f:
        f.write(generated)
    click.echo(f"Generated Java bindings to {output_path}")
