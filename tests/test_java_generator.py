"""Tests for the Java binding generator."""

import re

from stellar_sdk import xdr

from stellar_contract_bindings.java import generate_binding


def _type(t: xdr.SCSpecType) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(t)


def _void_case(name: bytes) -> xdr.SCSpecUDTUnionCaseV0:
    return xdr.SCSpecUDTUnionCaseV0(
        xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_VOID_V0,
        void_case=xdr.SCSpecUDTUnionCaseVoidV0(doc=b"", name=name),
    )


def _tuple_case(name: bytes, *types: xdr.SCSpecTypeDef) -> xdr.SCSpecUDTUnionCaseV0:
    return xdr.SCSpecUDTUnionCaseV0(
        xdr.SCSpecUDTUnionCaseV0Kind.SC_SPEC_UDT_UNION_CASE_TUPLE_V0,
        tuple_case=xdr.SCSpecUDTUnionCaseTupleV0(doc=b"", name=name, type=list(types)),
    )


def _u32() -> xdr.SCSpecTypeDef:
    return _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)


def _union(name: bytes, cases: list) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
        udt_union_v0=xdr.SCSpecUDTUnionV0(doc=b"", lib=b"", name=name, cases=cases),
    )


def _function(name: bytes, inputs: list, outputs: list) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_FUNCTION_V0,
        function_v0=xdr.SCSpecFunctionV0(
            doc=b"",
            name=xdr.SCSymbol(name),
            inputs=[
                xdr.SCSpecFunctionInputV0(doc=b"", name=n, type=t) for n, t in inputs
            ],
            outputs=outputs,
        ),
    )


class TestUnionKindWireNames:
    """``Kind`` carries the on-chain case name, not the Java identifier.

    ``append_underscore`` camelCases every case name so the generated Java
    compiles; ``toSCVal`` writes ``kind.value`` and ``fromSCVal`` looks the
    symbol back up with ``Kind.fromValue``, so that value has to stay the
    name the contract actually uses.
    """

    def setup_method(self):
        union = xdr.SCSpecEntry(
            xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_UNION_V0,
            udt_union_v0=xdr.SCSpecUDTUnionV0(
                doc=b"",
                lib=b"",
                name=b"Choice",
                cases=[
                    _void_case(b"no_data"),
                    _tuple_case(b"set_admin", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    _tuple_case(b"plain", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                ],
            ),
        )
        self.generated = generate_binding([union], package="org.example")

    def test_tuple_case_keeps_the_on_chain_name(self):
        assert 'setAdmin("set_admin")' in self.generated
        assert 'setAdmin("setAdmin")' not in self.generated

    def test_void_case_keeps_the_on_chain_name(self):
        assert 'noData("no_data")' in self.generated

    def test_unrenamed_case_is_unaffected(self):
        assert 'plain("plain")' in self.generated


def _struct(
    name: bytes, fields: list[tuple[bytes, xdr.SCSpecTypeDef]]
) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_UDT_STRUCT_V0,
        udt_struct_v0=xdr.SCSpecUDTStructV0(
            doc=b"",
            lib=b"",
            name=name,
            fields=[
                xdr.SCSpecUDTStructFieldV0(doc=b"", name=n, type=t) for n, t in fields
            ],
        ),
    )


def _result(ok: xdr.SCSpecTypeDef, error: xdr.SCSpecTypeDef) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_RESULT,
        result=xdr.SCSpecTypeResult(ok_type=ok, error_type=error),
    )


class TestResultValuesEncode:
    """A Result-typed value encodes as its Ok arm rather than emitting garbage.

    to_java_type() and from_scval() already reduce Result<T, E> to T, so the
    Java value in hand is a T. to_scval() used to `return` a NotImplementedError
    instead of raising it, which interpolated the exception's message into the
    generated source as a bare expression.
    """

    def setup_method(self):
        u32 = _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)
        error = _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        self.generated = generate_binding(
            [_struct(b"HasResult", [(b"r", _result(u32, error))])],
            package="org.example",
        )

    def test_encodes_the_ok_arm(self):
        assert 'fields.put("r", Scv.toUint32(this.r));' in self.generated

    def test_decodes_the_ok_arm(self):
        assert 'Scv.fromUint32(map.get(Scv.toSymbol("r")))' in self.generated

    def test_no_exception_text_leaks_into_the_source(self):
        assert "not supported" not in self.generated
        assert "NotImplementedError" not in self.generated


class TestVoidValuesDecode:
    """A void field decodes to null, after checking the SCVal really is void.

    `Scv.fromVoid` is declared `void fromVoid(SCVal)`: it takes an argument and
    returns nothing, so `Scv.fromVoid()` neither compiles nor can stand where a
    value is expected. The generated `decodeVoid` wraps it, keeping the check
    while yielding the null that `to_java_type`'s `Void` mapping needs.
    """

    def setup_method(self):
        self.generated = generate_binding(
            [
                _struct(
                    b"HasVoid",
                    [
                        (b"v", _type(xdr.SCSpecType.SC_SPEC_TYPE_VOID)),
                        (b"n", _type(xdr.SCSpecType.SC_SPEC_TYPE_U32)),
                    ],
                )
            ],
            package="org.example",
        )

    def test_encoding_still_uses_to_void(self):
        assert 'fields.put("v", Scv.toVoid());' in self.generated

    def test_decoding_never_emits_a_bare_from_void_call(self):
        """`Scv.fromVoid()` with no argument does not compile."""
        assert "Scv.fromVoid()" not in self.generated

    def test_decoding_validates_rather_than_assuming_void(self):
        """A bare `null` would accept any SCVal as a declared void."""
        constructor = self.generated[
            self.generated.index("public static HasVoid fromSCVal") :
        ]
        assert "decodeVoid(" in constructor
        assert "null," not in constructor

    def test_the_void_helper_is_emitted_once(self):
        assert self.generated.count("private static Void decodeVoid(SCVal scVal)") == 1


class TestSpecDerivedLiteralsAreEscaped:
    """Wire names reach the generated source as Java string literals.

    They come from the contract spec, so a name containing a quote would close
    the literal and let the rest of the name be compiled as code.
    """

    def test_struct_field_wire_name_cannot_close_the_literal(self):
        generated = generate_binding(
            [_struct(b"Hostile", [(b'a", Scv.toSymbol("x', _u32())])],
            package="org.example",
        )
        assert 'fields.put("a\\", Scv.toSymbol(\\"x"' in generated
        assert 'fields.put("a", Scv.toSymbol("x"' not in generated

    def test_function_wire_name_cannot_close_the_literal(self):
        generated = generate_binding(
            [_function(b'go", null); //', [], [])], package="org.example"
        )
        assert 'invoke("go\\", null); //"' in generated

    def test_union_case_wire_name_cannot_close_the_literal(self):
        generated = generate_binding(
            [_union(b"Hostile", [_void_case(b'a", "b')])], package="org.example"
        )
        assert '("a\\", \\"b")' in generated

    def test_non_ascii_wire_names_are_escaped(self):
        """Escaping non-ASCII keeps a literal's meaning independent of encoding.

        Generated files land in a build whose javac -encoding this generator
        does not control, and the platform default is not UTF-8 everywhere.

        Only the literal is covered here. The same name is also emitted as a
        Java identifier, which this generator does not yet sanitise; that is a
        compile failure rather than an injection, and is left for the identifier
        work.
        """
        generated = generate_binding(
            [_struct(b"Unicode", [("中文".encode(), _u32())])],
            package="org.example",
        )
        assert '"\\u4e2d\\u6587"' in generated
        literals = [line for line in generated.split("\n") if "fields.put" in line]
        assert literals and all("\u4e2d" not in line.split(",")[0] for line in literals)


def _tuple(count: int) -> xdr.SCSpecTypeDef:
    return xdr.SCSpecTypeDef(
        xdr.SCSpecType.SC_SPEC_TYPE_TUPLE,
        tuple=xdr.SCSpecTypeTuple([_u32()] * count),
    )


class TestGeneratedTupleClasses:
    """Java has no tuple type, so the generator emits its own instead of
    making every consumer depend on javatuples."""

    def test_no_javatuples_anywhere(self):
        generated = generate_binding(
            [_struct(b"Holder", [(b"pair", _tuple(2))])], package="org.example"
        )
        assert "javatuples" not in generated

    def test_only_the_arities_in_use_are_emitted(self):
        generated = generate_binding(
            [_struct(b"Holder", [(b"a", _tuple(2)), (b"b", _tuple(5))])],
            package="org.example",
        )
        assert "public static class Tuple2<T0, T1> {" in generated
        assert "public static class Tuple5<" in generated
        for unused in (1, 3, 4, 6, 12):
            assert f"class Tuple{unused}<" not in generated

    def test_a_contract_with_no_tuples_gets_no_tuple_classes(self):
        generated = generate_binding(
            [_struct(b"Plain", [(b"v", _u32())])], package="org.example"
        )
        assert "class Tuple" not in generated

    def test_the_spec_maximum_of_twelve_is_supported(self):
        """SCSpecTypeTuple declares valueTypes<12>; javatuples stopped at ten."""
        generated = generate_binding(
            [_struct(b"Wide", [(b"v", _tuple(12))])], package="org.example"
        )
        assert "public static class Tuple12<" in generated
        assert "Tuple12<Long, Long, Long, Long, Long, Long," in generated

    def test_a_union_case_of_one_value_needs_no_tuple(self):
        generated = generate_binding(
            [_union(b"Choice", [_tuple_case(b"one", _u32())])], package="org.example"
        )
        assert "class Tuple" not in generated

    def test_a_udt_colliding_with_a_tuple_class_is_reported(self):
        """Both are nested in Client, so one would be emitted twice."""
        try:
            generate_binding(
                [
                    _struct(b"Tuple2", [(b"v", _u32())]),
                    _struct(b"Holder", [(b"pair", _tuple(2))]),
                ],
                package="org.example",
            )
        except NotImplementedError as exc:
            assert "Tuple2" in str(exc)
        else:
            raise AssertionError("expected the collision to be reported")


class TestUnreachableMultiOutput:
    """SCSpecFunctionV0 declares outputs<1>, so more than one is impossible."""

    def test_no_function_object_can_leak_into_the_source(self):
        generated = generate_binding(
            [_function(b"f", [(b"a", _u32())], [_u32()])], package="org.example"
        )
        assert "<function" not in generated


def _event(
    name: bytes,
    prefix_topics: list[bytes],
    params: list,
    data_format: xdr.SCSpecEventDataFormat,
    doc: bytes = b"",
) -> xdr.SCSpecEntry:
    return xdr.SCSpecEntry(
        xdr.SCSpecEntryKind.SC_SPEC_ENTRY_EVENT_V0,
        event_v0=xdr.SCSpecEventV0(
            doc=doc,
            lib=b"",
            name=xdr.SCSymbol(name),
            prefix_topics=[xdr.SCSymbol(t) for t in prefix_topics],
            params=[
                xdr.SCSpecEventParamV0(doc=b"", name=n, type=t, location=loc)
                for n, t, loc in params
            ],
            data_format=data_format,
        ),
    )


_TOPIC = xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_TOPIC_LIST
_DATA = xdr.SCSpecEventParamLocationV0.SC_SPEC_EVENT_PARAM_LOCATION_DATA
_MAP_FORMAT = xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_MAP
_SINGLE = xdr.SCSpecEventDataFormat.SC_SPEC_EVENT_DATA_FORMAT_SINGLE_VALUE


class TestEventNamesAvoidCollisions:
    """Events become nested classes of Client, alongside every UDT."""

    def test_event_class_name_is_pascal_case_with_an_event_suffix(self):
        generated = generate_binding(
            [_event(b"set_admin", [b"set_admin"], [], _SINGLE)], package="org.example"
        )
        assert "public static class SetAdminEvent implements Event" in generated

    def test_an_event_named_like_a_udt_is_renamed(self):
        generated = generate_binding(
            [
                _struct(b"TransferEvent", [(b"v", _u32())]),
                _event(b"transfer", [b"transfer"], [], _SINGLE),
            ],
            package="org.example",
        )
        assert "public static class TransferEvent {" in generated
        assert "public static class TransferEvent_ implements Event" in generated

    def test_a_udt_named_event_does_not_displace_the_marker_interface(self):
        generated = generate_binding(
            [
                _struct(b"Event", [(b"v", _u32())]),
                _event(b"ping", [b"ping"], [], _SINGLE),
            ],
            package="org.example",
        )
        assert "public interface Event_ {}" in generated
        assert "class PingEvent implements Event_" in generated


class TestEventTypesThatCannotBeDecoded:
    """Reject at generation time rather than emitting a wrong decoder."""

    def test_a_result_parameter_is_rejected(self):
        """to_java_type reduces Result<T, E> to T, but an event may carry Err."""
        error = _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        spec = _event(
            b"oops", [b"oops"], [(b"outcome", _result(_u32(), error), _DATA)], _SINGLE
        )
        try:
            generate_binding([spec], package="org.example")
        except NotImplementedError as exc:
            assert "oops.outcome" in str(exc)
        else:
            raise AssertionError("expected a Result parameter to be rejected")

    def test_a_result_nested_in_a_container_is_rejected(self):
        error = _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        nested = xdr.SCSpecTypeDef(
            xdr.SCSpecType.SC_SPEC_TYPE_VEC,
            vec=xdr.SCSpecTypeVec(_result(_u32(), error)),
        )
        spec = _event(b"oops", [b"oops"], [(b"outcomes", nested, _DATA)], _SINGLE)
        try:
            generate_binding([spec], package="org.example")
        except NotImplementedError as exc:
            assert "oops.outcomes[]" in str(exc)
        else:
            raise AssertionError("expected a nested Result to be rejected")


class TestEventDispatchOrder:
    """Most specific first, so a short declaration cannot swallow a long one."""

    def test_candidates_are_ordered_by_declared_topic_count(self):
        generated = generate_binding(
            [
                _event(b"short", [b"act"], [], _SINGLE),
                _event(b"long", [b"act"], [(b"who", _u32(), _TOPIC)], _SINGLE),
            ],
            package="org.example",
        )
        dispatcher = generated[
            generated.index("public static Optional<Event> parseEvent") :
        ]
        assert dispatcher.index("LongEvent.matches") < dispatcher.index(
            "ShortEvent.matches"
        )

    def test_a_failed_candidate_does_not_stop_the_others(self):
        """Independent ifs, not else-if: matching topics may still fail to parse."""
        generated = generate_binding(
            [
                _event(b"a", [b"act"], [(b"v", _u32(), _DATA)], _SINGLE),
                _event(b"b", [b"act"], [(b"v", _u32(), _DATA)], _SINGLE),
            ],
            package="org.example",
        )
        dispatcher = generated[
            generated.index("public static Optional<Event> parseEvent") :
        ]
        assert "} else if (" not in dispatcher
        assert dispatcher.count("catch (RuntimeException e)") == 2


class TestEventTopicFilter:
    """An unset topic is a wildcard; that is not the same as an explicit null."""

    def setup_method(self):
        self.generated = generate_binding(
            [
                _event(
                    b"transfer",
                    [b"transfer"],
                    [
                        (b"from", _type(xdr.SCSpecType.SC_SPEC_TYPE_ADDRESS), _TOPIC),
                        (b"amount", _u32(), _DATA),
                    ],
                    _MAP_FORMAT,
                )
            ],
            package="org.example",
        )

    def test_set_state_is_tracked_separately_from_the_value(self):
        assert "private boolean fromSet;" in self.generated
        assert (
            'row.add(fromSet ? encodeTopic(Scv.toAddress(from)) : "*");'
            in self.generated
        )

    def test_the_row_ends_with_the_trailing_wildcard(self):
        assert 'row.add("**");' in self.generated

    def test_required_map_entries_are_checked(self):
        assert 'values.containsKey("amount")' in self.generated


class TestEventNameAllocationIsComplete:
    """Every generated nested class competes for one namespace inside Client."""

    def test_a_udt_named_like_a_helper_pushes_the_helper_aside(self):
        generated = generate_binding(
            [
                _struct(b"DecodedEvent", [(b"v", _u32())]),
                _event(b"ping", [b"ping"], [], _SINGLE),
            ],
            package="org.example",
        )
        assert "public static class DecodedEvent_ {" in generated
        assert "DecodedEvent_.of(event)" in generated
        # The contract's own type keeps its name.
        assert "public static class DecodedEvent {" in generated

    def test_a_topic_parameter_cannot_claim_another_ones_flag(self):
        """`foo` needs a `fooSet` flag, which a parameter named `foo_set` takes."""
        generated = generate_binding(
            [
                _event(
                    b"e",
                    [b"e"],
                    [(b"foo", _u32(), _TOPIC), (b"foo_set", _u32(), _TOPIC)],
                    _SINGLE,
                )
            ],
            package="org.example",
        )
        declared = re.findall(r"private (?:Long|boolean) (\w+);", generated)
        assert len(declared) == len(set(declared)), declared

    def test_a_topic_parameter_cannot_shadow_a_builder_local(self):
        """build() assembles a local `row`; a parameter of that name read it."""
        generated = generate_binding(
            [_event(b"e", [b"e"], [(b"row", _u32(), _TOPIC)], _SINGLE)],
            package="org.example",
        )
        assert "encodeTopic(Scv.toUint32(row))" not in generated


class TestEventDispatchPrefersStaticTopics:
    """Topic count alone does not measure how selective a declaration is."""

    def test_more_static_prefix_topics_wins_at_equal_total(self):
        """matches() only checks the prefix, so more prefix is strictly tighter."""
        generated = generate_binding(
            [
                _event(
                    b"generic",
                    [b"x"],
                    [(b"anything", _type(xdr.SCSpecType.SC_SPEC_TYPE_VAL), _TOPIC)],
                    _SINGLE,
                ),
                _event(b"specific", [b"x", b"y"], [], _SINGLE),
            ],
            package="org.example",
        )
        dispatcher = generated[
            generated.index("public static Optional<Event> parseEvent") :
        ]
        assert dispatcher.index("SpecificEvent.matches") < dispatcher.index(
            "GenericEvent.matches"
        )


class TestUdtReferencesMatchDeclarations:
    """append_underscore renames the declaration; references must follow."""

    def test_a_renamed_udt_is_referenced_by_its_java_name(self):
        udt = xdr.SCSpecTypeDef(
            xdr.SCSpecType.SC_SPEC_TYPE_UDT, udt=xdr.SCSpecTypeUDT(name=b"snake_type")
        )
        generated = generate_binding(
            [
                _struct(b"snake_type", [(b"v", _u32())]),
                _struct(b"Holder", [(b"thing", udt)]),
            ],
            package="org.example",
        )
        assert "public static class snakeType {" in generated
        assert "snakeType thing;" in generated
        assert "snake_type thing;" not in generated


class TestResultRejectionSeesThroughUdts:
    """A UDT hides its members behind a name; the decoder has the same gap."""

    def test_a_result_inside_a_referenced_struct_is_rejected(self):
        error = _type(xdr.SCSpecType.SC_SPEC_TYPE_ERROR)
        box = xdr.SCSpecTypeDef(
            xdr.SCSpecType.SC_SPEC_TYPE_UDT, udt=xdr.SCSpecTypeUDT(name=b"Box")
        )
        specs = [
            _struct(b"Box", [(b"inner", _result(_u32(), error))]),
            _event(b"boxed", [b"boxed"], [(b"payload", box, _DATA)], _SINGLE),
        ]
        try:
            generate_binding(specs, package="org.example")
        except NotImplementedError as exc:
            assert "boxed.payload.inner" in str(exc)
        else:
            raise AssertionError("expected a Result behind a UDT to be rejected")

    def test_a_recursive_udt_does_not_loop(self):
        node = xdr.SCSpecTypeDef(
            xdr.SCSpecType.SC_SPEC_TYPE_UDT, udt=xdr.SCSpecTypeUDT(name=b"Node")
        )
        specs = [
            _struct(
                b"Node",
                [
                    (b"value", _u32()),
                    (
                        b"next",
                        xdr.SCSpecTypeDef(
                            xdr.SCSpecType.SC_SPEC_TYPE_OPTION,
                            option=xdr.SCSpecTypeOption(node),
                        ),
                    ),
                ],
            ),
            _event(b"linked", [b"linked"], [(b"head", node, _DATA)], _SINGLE),
        ]
        generate_binding(specs, package="org.example")  # must terminate
