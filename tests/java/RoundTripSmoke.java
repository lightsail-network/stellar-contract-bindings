import com.example.Client;
import org.stellar.sdk.Address;
import org.stellar.sdk.KeyPair;
import org.stellar.sdk.Network;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.SCVal;
import org.stellar.sdk.xdr.SCValType;

import java.math.BigInteger;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Exercises the bindings generated from tests/contracts/contracts/python.
 *
 * <p>Compilation proves the generated source is valid; this proves the
 * codecs read and write the values the contract does. Every check builds a
 * value, encodes it, decodes it, and compares; the wire shapes are checked
 * against what the Soroban SDK produces where that matters.
 */
public class RoundTripSmoke {
    static int failures = 0;

    static void check(String label, boolean ok) {
        System.out.println((ok ? "PASS " : "FAIL ") + label);
        if (!ok) failures++;
    }

    static final String A = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ";
    // Well-formed, and never contacted: the client below makes no request.
    static final String CONTRACT_ID = "CAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABSC4";

    public static void main(String[] args) throws Exception {
        // A struct is a map keyed by field name; the SDK sorts the keys.
        Client.SimpleStruct simple = new Client.SimpleStruct(7, true, "sym");
        SCVal encoded = simple.toSCVal();
        check("struct encodes as a map", encoded.getDiscriminant() == SCValType.SCV_MAP);
        check("struct round-trips", Client.SimpleStruct.fromSCVal(encoded).equals(simple));
        check("struct getters are camelCase and primitive",
            simple.getA() == 7 && simple.isB() && simple.getC().equals("sym"));
        check("struct builder", Client.SimpleStruct.builder().a(7).b(true).c("sym").build().equals(simple));

        // A missing field is reported by name rather than as a NullPointerException.
        Map<SCVal, SCVal> partial = new LinkedHashMap<>();
        partial.put(Scv.toSymbol("a"), Scv.toUint32(1L));
        String missing = "";
        try {
            Client.SimpleStruct.fromSCVal(Scv.toMap(partial));
        } catch (IllegalArgumentException e) {
            missing = e.getMessage();
        }
        check("missing struct field is named", missing.contains("b"));

        // A tuple struct is a vec.
        Client.TupleStruct tupleStruct = new Client.TupleStruct(simple, new Client.SimpleEnum.Second());
        check("tuple struct encodes as a vec", tupleStruct.toSCVal().getDiscriminant() == SCValType.SCV_VEC);
        check("tuple struct round-trips", Client.TupleStruct.fromSCVal(tupleStruct.toSCVal()).equals(tupleStruct));

        // Enums carry their declared values.
        check("enum value", Client.RoyalCard.Queen.getValue() == 12L);
        check("enum encodes as u32", Scv.fromUint32(Client.RoyalCard.King.toSCVal()) == 13L);
        check("enum round-trips", Client.RoyalCard.fromSCVal(Client.RoyalCard.Jack.toSCVal()) == Client.RoyalCard.Jack);
        check("enum from value", Client.RoyalCard.fromValue(11L) == Client.RoyalCard.Jack);
        boolean unknownRejected = false;
        try {
            Client.RoyalCard.fromValue(99L);
        } catch (IllegalArgumentException e) {
            unknownRejected = true;
        }
        check("unknown enum value rejected", unknownRejected);

        // A Rust enum without repr(u32) is a union of void cases: a one-element vec.
        Client.SimpleEnum first = new Client.SimpleEnum.First();
        check("void-case union encodes as [symbol]",
            Scv.fromVec(first.toSCVal()).size() == 1 && first.getKind() == Client.SimpleEnum.Kind.First);
        check("void-case union round-trips", Client.SimpleEnum.fromSCVal(first.toSCVal()).equals(first));
        check("void cases are equal by kind", new Client.SimpleEnum.First().equals(first)
            && !new Client.SimpleEnum.Third().equals(first));

        // An error enum is an SCV_ERROR on the wire.
        SCVal error = Client.Error.NumberMustBeOdd.toSCVal();
        check("error enum encodes as SCV_ERROR", error.getDiscriminant() == SCValType.SCV_ERROR);
        check("error enum round-trips", Client.Error.fromSCVal(error) == Client.Error.NumberMustBeOdd);

        // A tuple has a factory, so the type arguments are inferred.
        Client.Tuple2<String, Long> pair = Client.Tuple2.of("a", 1L);
        check("tuple factory", pair.getValue0().equals("a") && pair.getValue1() == 1L);

        // Every union case, through its own class.
        Client.ComplexEnum[] cases = {
            new Client.ComplexEnum.Struct(simple),
            new Client.ComplexEnum.Tuple(tupleStruct),
            new Client.ComplexEnum.Enum(new Client.SimpleEnum.Third()),
            new Client.ComplexEnum.Asset(new Address(A), BigInteger.valueOf(-5)),
            new Client.ComplexEnum.Void(),
        };
        Client.ComplexEnum.Kind[] kinds = {
            Client.ComplexEnum.Kind.Struct,
            Client.ComplexEnum.Kind.Tuple,
            Client.ComplexEnum.Kind.Enum,
            Client.ComplexEnum.Kind.Asset,
            Client.ComplexEnum.Kind.Void,
        };
        for (int i = 0; i < cases.length; i++) {
            Client.ComplexEnum back = Client.ComplexEnum.fromSCVal(cases[i].toSCVal());
            check("union case " + kinds[i] + " round-trips", back.equals(cases[i]));
            check("union case " + kinds[i] + " kind", back.getKind() == kinds[i]);
            check("union case " + kinds[i] + " symbol", kinds[i].getSymbol().equals(kinds[i].name()));
        }
        Client.ComplexEnum asset = Client.ComplexEnum.fromSCVal(cases[3].toSCVal());
        check("union case values are accessible", ((Client.ComplexEnum.Asset) asset).getValue1().equals(BigInteger.valueOf(-5)));
        // match() takes one function per case and returns whatever they return.
        String described = asset.match(
            s -> "struct",
            t -> "tuple",
            e -> "enum",
            a -> "asset of " + a.getValue1(),
            v -> "void");
        check("union match", described.equals("asset of -5"));
        check("union match on a void case", cases[4].match(s -> 1, t -> 2, e -> 3, a -> 4, v -> 5) == 5);
        // The symbol comes first on the wire, so a hand-built vec decodes too.
        Client.ComplexEnum manual = Client.ComplexEnum.fromSCVal(
            Scv.toVec(Arrays.asList(Scv.toSymbol("Enum"), Scv.toVec(Arrays.asList(Scv.toSymbol("Second"))))));
        check("hand-built union decodes", manual.equals(new Client.ComplexEnum.Enum(new Client.SimpleEnum.Second())));
        boolean wrongArity = false;
        try {
            Client.ComplexEnum.fromSCVal(Scv.toVec(Arrays.asList(Scv.toSymbol("Asset"), Scv.toAddress(A))));
        } catch (IllegalArgumentException e) {
            wrongArity = true;
        }
        check("union case with missing values rejected", wrongArity);
        boolean unknownCase = false;
        try {
            Client.ComplexEnum.fromSCVal(Scv.toVec(Arrays.asList(Scv.toSymbol("Nope"))));
        } catch (IllegalArgumentException e) {
            unknownCase = true;
        }
        check("unknown union case rejected", unknownCase);

        // Names that are keywords in Python or Java keep their wire names.
        Client.True t = new Client.True(3);
        check("keyword struct round-trips", Client.True.fromSCVal(t.toSCVal()).equals(t));
        check("keyword field keeps its wire name",
            Scv.fromMap(t.toSCVal()).containsKey(Scv.toSymbol("def")));
        check("keyword error enum", Client.False.elif.getValue() == 1L);
        check("keyword union", new Client.None.nonlocal().getKind() == Client.None.Kind.nonlocal
            && Client.None.Kind.nonlocal.getSymbol().equals("nonlocal"));
        check("keyword enum", Client.import_.elif.getValue() == 12L);

        // MethodOptions derive the source account from the signer.
        KeyPair signer = KeyPair.random();
        check("default source is the null account",
            Client.MethodOptions.defaults().sourceAccount().equals(Client.NULL_ACCOUNT));
        check("signer's account is the default source",
            Client.MethodOptions.signedBy(signer).sourceAccount().equals(signer.getAccountId()));
        check("an explicit source wins",
            Client.MethodOptions.builder().signer(signer).source(A).build().sourceAccount().equals(A));
        check("defaults", Client.MethodOptions.defaults().getBaseFee() == 100
            && Client.MethodOptions.defaults().getTransactionTimeout() == 300
            && Client.MethodOptions.defaults().isSimulate());
        check("toBuilder keeps values",
            Client.MethodOptions.signedBy(signer).toBuilder().baseFee(200).build().getSigner() == signer);

        // The client itself constructs without touching the network, and
        // carries the options a call uses when given none.
        try (Client client = new Client(
                CONTRACT_ID, "https://soroban-testnet.stellar.org", Network.TESTNET)) {
            check("client defaults to a read-only simulation",
                client.getDefaultOptions().getSigner() == null
                    && client.getDefaultOptions().sourceAccount().equals(Client.NULL_ACCOUNT));
        }
        try (Client client = new Client(
                CONTRACT_ID,
                "https://soroban-testnet.stellar.org",
                Network.TESTNET,
                Client.MethodOptions.signedBy(signer))) {
            check("client-level signer", client.getDefaultOptions().getSigner() == signer);
        }

        // A failed simulation names the contract error in its message.
        String message = "Transaction simulation failed: HostError: Error(Contract, #1)\n\nEvent log";
        check("contract error read from a simulation failure",
            Client.Error.fromSimulationError(message).get() == Client.Error.NumberMustBeOdd);
        check("other failures are not contract errors",
            !Client.Error.fromSimulationError("HostError: Error(Storage, MissingValue)").isPresent()
                && !Client.Error.fromSimulationError((String) null).isPresent());
        check("unknown codes are not this enum",
            !Client.Error.fromSimulationError("Error(Contract, #99)").isPresent());

        if (failures > 0) throw new AssertionError(failures + " checks failed");
        System.out.println("all checks passed");
    }
}
