
from enum import IntEnum, Enum
from typing import Dict, List, Tuple, Optional

from stellar_sdk import scval, xdr, Address
from stellar_sdk.contract import AssembledTransaction, ContractClient


class Test:
    '''This is from the rust doc above the struct Test'''
    a: int
    b: bool
    c: str

    def __init__(self, a: int, b: bool, c: str):
        self.a = a
        self.b = b
        self.c = c

    def to_scval(self) -> xdr.SCVal:
        return scval.to_struct({
            'a': scval.to_uint32(self.a),
            'b': scval.to_bool(self.b),
            'c': scval.to_symbol(self.c)
        })

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_struct(val)
        return cls(
            scval.from_uint32(elements["a"]),
            scval.from_bool(elements["b"]),
            scval.from_symbol(elements["c"])
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Test):
            return NotImplemented
        return self.a == other.a and self.b == other.b and self.c == other.c

    def __hash__(self) -> int:
        return hash((self.a, self.b, self.c))

class SimpleEnumKind(Enum):
    First = 'First'
    Second = 'Second'
    Third = 'Third'

class SimpleEnum:
    def __init__(self,
        kind: SimpleEnumKind,
    ):
        self.kind = kind

    def to_scval(self) -> xdr.SCVal:
        if self.kind == SimpleEnumKind.First:
            return scval.to_enum(self.kind.name, None)
        if self.kind == SimpleEnumKind.Second:
            return scval.to_enum(self.kind.name, None)
        if self.kind == SimpleEnumKind.Third:
            return scval.to_enum(self.kind.name, None)
    
    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_enum(val)
        kind = SimpleEnumKind(elements[0])
        if kind == SimpleEnumKind.First:
            return cls(kind)
        if kind == SimpleEnumKind.Second:
            return cls(kind)
        if kind == SimpleEnumKind.Third:
            return cls(kind)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SimpleEnum):
            return NotImplemented
        if self.kind != other.kind:
            return False
        return True

    def __hash__(self) -> int:
        return hash(self.kind)

class RoyalCard(IntEnum):
    Jack = 11
    Queen = 12
    King = 13
    def to_scval(self) -> xdr.SCVal:
        return scval.to_uint32(self.value)

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        return cls(scval.from_uint32(val))

class TupleStruct:

    def __init__(self, value: Tuple[Test, SimpleEnum]):
        self.value = value

    def to_scval(self) -> xdr.SCVal:
        return scval.to_tuple_struct([self.value[0].to_scval(), self.value[1].to_scval()]) 
    
    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_tuple_struct(val)
        values = (Test.from_scval(elements[0]), SimpleEnum.from_scval(elements[1]), )
        return cls(values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TupleStruct):
            return NotImplemented
        return self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)

class ComplexEnumKind(Enum):
    Struct = 'Struct'
    Tuple = 'Tuple'
    Enum = 'Enum'
    Asset = 'Asset'
    Void = 'Void'

class ComplexEnum:
    def __init__(self,
        kind: ComplexEnumKind,
        struct: Optional[Test] = None,
        tuple: Optional[TupleStruct] = None,
        enum: Optional[SimpleEnum] = None,
        asset: Optional[Tuple[Address, int]] = None,
    ):
        self.kind = kind 
        self.struct = struct 
        self.tuple = tuple 
        self.enum = enum 
        self.asset = asset

    def to_scval(self) -> xdr.SCVal:
        if self.kind == ComplexEnumKind.Struct:
            return scval.to_enum(self.kind.name, self.struct.to_scval())
        if self.kind == ComplexEnumKind.Tuple:
            return scval.to_enum(self.kind.name, self.tuple.to_scval())
        if self.kind == ComplexEnumKind.Enum:
            return scval.to_enum(self.kind.name, self.enum.to_scval())
        if self.kind == ComplexEnumKind.Asset:
            return scval.to_enum(self.kind.name, [
                scval.to_address(self.asset[0]),
                scval.to_int128(self.asset[1])
            ])
        if self.kind == ComplexEnumKind.Void:
            return scval.to_enum(self.kind.name, None)
    
    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        elements = scval.from_enum(val)
        kind = ComplexEnumKind(elements[0])
        if kind == ComplexEnumKind.Struct:
            return cls(kind, struct=Test.from_scval(elements[1]))
        if kind == ComplexEnumKind.Tuple:
            return cls(kind, tuple=TupleStruct.from_scval(elements[1]))
        if kind == ComplexEnumKind.Enum:
            return cls(kind, enum=SimpleEnum.from_scval(elements[1]))
        if kind == ComplexEnumKind.Asset:
            return cls(kind, asset=(
                scval.from_address(elements[1][0]),
                scval.from_int128(elements[1][1])
            ))
        if kind == ComplexEnumKind.Void:
            return cls(kind)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ComplexEnum):
            return NotImplemented
        if self.kind != other.kind:
            return False
        if self.kind == ComplexEnumKind.Struct:
            return self.struct == other.struct
        if self.kind == ComplexEnumKind.Tuple:
            return self.tuple == other.tuple
        if self.kind == ComplexEnumKind.Enum:
            return self.enum == other.enum
        if self.kind == ComplexEnumKind.Asset:
            return self.asset == other.asset
        return True

    def __hash__(self) -> int:
        if self.kind == ComplexEnumKind.Struct:
            return hash((self.kind, self.struct))
        if self.kind == ComplexEnumKind.Tuple:
            return hash((self.kind, self.tuple))
        if self.kind == ComplexEnumKind.Enum:
            return hash((self.kind, self.enum))
        if self.kind == ComplexEnumKind.Asset:
            return hash((self.kind, self.asset))
        return hash(self.kind)

class Error(IntEnum):
    NumberMustBeOdd = 1
    def to_scval(self) -> xdr.SCVal:
        return scval.to_uint32(self.value)

    @classmethod
    def from_scval(cls, val: xdr.SCVal):
        return cls(scval.from_uint32(val))
    

class Client(ContractClient):
    def hello(self, hello: str) -> AssembledTransaction[str]:
        return self.invoke('hello', [scval.to_symbol(hello)], parse_result_xdr_fn=lambda v: scval.from_symbol(v))
    def void(self, ) -> AssembledTransaction[None]:
        return self.invoke('void', [], parse_result_xdr_fn=lambda _: None)
    def u32_fail_on_even(self, u32_: int) -> AssembledTransaction[int]:
        return self.invoke('u32_fail_on_even', [scval.to_uint32(u32_)], parse_result_xdr_fn=lambda v: scval.from_uint32(v))
    def u32(self, u32: int) -> AssembledTransaction[int]:
        return self.invoke('u32', [scval.to_uint32(u32)], parse_result_xdr_fn=lambda v: scval.from_uint32(v))
    def i32(self, i32: int) -> AssembledTransaction[int]:
        return self.invoke('i32', [scval.to_int32(i32)], parse_result_xdr_fn=lambda v: scval.from_int32(v))
    def u64(self, u64: int) -> AssembledTransaction[int]:
        return self.invoke('u64', [scval.to_uint64(u64)], parse_result_xdr_fn=lambda v: scval.from_uint64(v))
    def i64(self, i64: int) -> AssembledTransaction[int]:
        return self.invoke('i64', [scval.to_int64(i64)], parse_result_xdr_fn=lambda v: scval.from_int64(v))
    def strukt_hel(self, strukt: Test) -> AssembledTransaction[List[str]]:
        """Example contract method which takes a struct"""
        return self.invoke('strukt_hel', [strukt.to_scval()], parse_result_xdr_fn=lambda v: [scval.from_symbol(e) for e in scval.from_vec(v)])
    def strukt(self, strukt: Test) -> AssembledTransaction[Test]:
        return self.invoke('strukt', [strukt.to_scval()], parse_result_xdr_fn=lambda v: Test.from_scval(v))
    def simple(self, simple: SimpleEnum) -> AssembledTransaction[SimpleEnum]:
        return self.invoke('simple', [simple.to_scval()], parse_result_xdr_fn=lambda v: SimpleEnum.from_scval(v))
    def complex(self, complex: ComplexEnum) -> AssembledTransaction[ComplexEnum]:
        return self.invoke('complex', [complex.to_scval()], parse_result_xdr_fn=lambda v: ComplexEnum.from_scval(v))
    def address(self, address: Address) -> AssembledTransaction[Address]:
        return self.invoke('address', [scval.to_address(address)], parse_result_xdr_fn=lambda v: scval.from_address(v))
    def bytes(self, bytes: bytes) -> AssembledTransaction[bytes]:
        return self.invoke('bytes', [scval.to_bytes(bytes)], parse_result_xdr_fn=lambda v: scval.from_bytes(v))
    def bytes_n(self, bytes_n: bytes) -> AssembledTransaction[bytes]:
        return self.invoke('bytes_n', [scval.to_bytes(bytes_n)], parse_result_xdr_fn=lambda v: scval.from_bytes(v))
    def card(self, card: RoyalCard) -> AssembledTransaction[RoyalCard]:
        return self.invoke('card', [card.to_scval()], parse_result_xdr_fn=lambda v: RoyalCard.from_scval(v))
    def boolean(self, boolean: bool) -> AssembledTransaction[bool]:
        return self.invoke('boolean', [scval.to_bool(boolean)], parse_result_xdr_fn=lambda v: scval.from_bool(v))
    def not_(self, boolean: bool) -> AssembledTransaction[bool]:
        """Negates a boolean value"""
        return self.invoke('not_', [scval.to_bool(boolean)], parse_result_xdr_fn=lambda v: scval.from_bool(v))
    def i128(self, i128: int) -> AssembledTransaction[int]:
        return self.invoke('i128', [scval.to_int128(i128)], parse_result_xdr_fn=lambda v: scval.from_int128(v))
    def u128(self, u128: int) -> AssembledTransaction[int]:
        return self.invoke('u128', [scval.to_uint128(u128)], parse_result_xdr_fn=lambda v: scval.from_uint128(v))
    def multi_args(self, a: int, b: bool) -> AssembledTransaction[int]:
        return self.invoke('multi_args', [scval.to_uint32(a), scval.to_bool(b)], parse_result_xdr_fn=lambda v: scval.from_uint32(v))
    def map(self, map: Dict[int, bool]) -> AssembledTransaction[Dict[int, bool]]:
        return self.invoke('map', [scval.to_map({scval.to_uint32(k): scval.to_bool(v) for k, v in map.items()})], parse_result_xdr_fn=lambda v: {scval.from_uint32(k): scval.from_bool(v) for k, v in scval.from_map(v).items()})
    def vec(self, vec: List[int]) -> AssembledTransaction[List[int]]:
        return self.invoke('vec', [scval.to_vec([scval.to_uint32(e) for e in vec])], parse_result_xdr_fn=lambda v: [scval.from_uint32(e) for e in scval.from_vec(v)])
    def tuple(self, tuple: Tuple[str, int]) -> AssembledTransaction[Tuple[str, int]]:
        return self.invoke('tuple', [scval.to_tuple_struct([scval.to_symbol(tuple[0]), scval.to_uint32(tuple[1])])], parse_result_xdr_fn=lambda v: (scval.from_symbol(scval.from_tuple_struct(v)[0]), scval.from_uint32(scval.from_tuple_struct(v)[1])))
    def option(self, option: Optional[int]) -> AssembledTransaction[Optional[int]]:
        """Example of an optional argument"""
        return self.invoke('option', [scval.to_uint32(option) if option is not None else scval.to_void()], parse_result_xdr_fn=lambda v: scval.from_uint32(v) if v.type != xdr.SCValType.SCV_VOID else scval.from_void(v))
    def u256(self, u256: int) -> AssembledTransaction[int]:
        return self.invoke('u256', [scval.to_uint256(u256)], parse_result_xdr_fn=lambda v: scval.from_uint256(v))
    def i256(self, i256: int) -> AssembledTransaction[int]:
        return self.invoke('i256', [scval.to_int256(i256)], parse_result_xdr_fn=lambda v: scval.from_int256(v))
    def string(self, string: bytes) -> AssembledTransaction[bytes]:
        return self.invoke('string', [scval.to_string(string)], parse_result_xdr_fn=lambda v: scval.from_string(v))
    def tuple_strukt(self, tuple_strukt: TupleStruct) -> AssembledTransaction[TupleStruct]:
        return self.invoke('tuple_strukt', [tuple_strukt.to_scval()], parse_result_xdr_fn=lambda v: TupleStruct.from_scval(v))
    def tuple_strukt_nested(self, tuple_strukt: Tuple[Test, SimpleEnum]) -> AssembledTransaction[Tuple[Test, SimpleEnum]]:
        return self.invoke('tuple_strukt_nested', [scval.to_tuple_struct([tuple_strukt[0].to_scval(), tuple_strukt[1].to_scval()])], parse_result_xdr_fn=lambda v: (Test.from_scval(scval.from_tuple_struct(v)[0]), SimpleEnum.from_scval(scval.from_tuple_struct(v)[1])))
    def timepoint(self, timepoint: int) -> AssembledTransaction[int]:
        return self.invoke('timepoint', [scval.to_timepoint(timepoint)], parse_result_xdr_fn=lambda v: scval.from_timepoint(v))
    def duration(self, duration: int) -> AssembledTransaction[int]:
        return self.invoke('duration', [scval.to_duration(duration)], parse_result_xdr_fn=lambda v: scval.from_duration(v))