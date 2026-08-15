import com.example.Client;
import org.stellar.sdk.Address;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.SCVal;
import java.math.BigInteger;
import java.util.*;

public class EventSmoke {
    static int failures = 0;

    static void check(String label, boolean ok) {
        System.out.println((ok ? "PASS " : "FAIL ") + label);
        if (!ok) failures++;
    }

    static final String A = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ";
    static final String B = "GDNSSYSCSSJ76FER5WEEXME5G4MTCUBKDRQSKOYP36KUKVDB2VCMERS6";

    static Client.DecodedEvent transfer(SCVal muxedId) {
        List<SCVal> topics = Arrays.asList(
            Scv.toSymbol("transfer"), Scv.toAddress(new Address(A)), Scv.toAddress(new Address(B)));
        LinkedHashMap<SCVal, SCVal> data = new LinkedHashMap<>();
        data.put(Scv.toSymbol("to_muxed_id"), muxedId);
        data.put(Scv.toSymbol("amount"), Scv.toInt128(BigInteger.valueOf(500)));
        return new Client.DecodedEvent(topics, Scv.toMap(data));
    }

    public static void main(String[] args) {
        // The four transfer declarations share topics; only the data type separates them.
        check("u64 muxed id -> TransferEvent",
            Client.parseEvent(transfer(Scv.toUint64(BigInteger.valueOf(42)))).get()
                instanceof Client.TransferEvent);
        check("string muxed id -> TransferWithMuxedStringEvent",
            Client.parseEvent(transfer(Scv.toString("tag-9"))).get()
                instanceof Client.TransferWithMuxedStringEvent);
        check("void muxed id -> TransferEvent",
            Client.parseEvent(transfer(Scv.toVoid())).get() instanceof Client.TransferEvent);

        // The legacy SINGLE_VALUE form shares the same topics.
        Client.DecodedEvent legacy = new Client.DecodedEvent(
            Arrays.asList(Scv.toSymbol("transfer"), Scv.toAddress(new Address(A)),
                          Scv.toAddress(new Address(B))),
            Scv.toInt128(BigInteger.valueOf(7)));
        Client.Event parsedLegacy = Client.parseEvent(legacy).get();
        check("i128 data -> TransferWithAmountOnlyEvent",
            parsedLegacy instanceof Client.TransferWithAmountOnlyEvent);
        check("legacy amount decoded",
            ((Client.TransferWithAmountOnlyEvent) parsedLegacy).getAmount()
                .equals(BigInteger.valueOf(7)));

        // Field values survive the round trip.
        Client.TransferEvent t = (Client.TransferEvent)
            Client.parseEvent(transfer(Scv.toUint64(BigInteger.valueOf(42)))).get();
        check("from decoded", t.getFrom().equals(new Address(A)));
        check("amount decoded", t.getAmount().equals(BigInteger.valueOf(500)));
        check("optional muxed id decoded", t.getToMuxedId().equals(BigInteger.valueOf(42)));

        // An absent optional map entry is null, not a parse failure.
        LinkedHashMap<SCVal, SCVal> onlyAmount = new LinkedHashMap<>();
        onlyAmount.put(Scv.toSymbol("amount"), Scv.toInt128(BigInteger.ONE));
        Client.Event noMux = Client.parseEvent(new Client.DecodedEvent(
            Arrays.asList(Scv.toSymbol("transfer"), Scv.toAddress(new Address(A)),
                          Scv.toAddress(new Address(B))),
            Scv.toMap(onlyAmount))).get();
        check("absent optional entry -> null",
            ((Client.TransferEvent) noMux).getToMuxedId() == null);

        // An undeclared topic yields empty rather than throwing.
        check("unknown event -> empty",
            !Client.parseEvent(new Client.DecodedEvent(
                Arrays.asList(Scv.toSymbol("not_a_real_event")), Scv.toVoid())).isPresent());

        // Topics matched but data is nonsense: that is reported, not swallowed.
        boolean threw = false;
        try {
            Client.parseEvent(new Client.DecodedEvent(
                Arrays.asList(Scv.toSymbol("clawback"), Scv.toAddress(new Address(A))),
                Scv.toSymbol("not an i128")));
        } catch (Client.UnparsedEventException e) {
            threw = true;
        }
        check("matched-but-undecodable throws", threw);

        // Extra trailing topics are tolerated (SAC appends the SEP-11 asset).
        check("extra trailing topic tolerated",
            Client.parseEvent(new Client.DecodedEvent(
                Arrays.asList(Scv.toSymbol("transfer"), Scv.toAddress(new Address(A)),
                              Scv.toAddress(new Address(B)), Scv.toString("USDC:GA...")),
                Scv.toInt128(BigInteger.TEN))).isPresent());

        // topicFilter: unset topics become wildcards, the row ends with "**".
        List<String> row = Client.TransferEvent.topicFilter().to(new Address(B)).build();
        check("filter row length", row.size() == 4);
        check("filter wildcards unset topic", row.get(1).equals("*"));
        check("filter encodes set topic", !row.get(2).equals("*"));
        check("filter ends with **", row.get(3).equals("**"));

        // Lombok value semantics over the byte[]-typed fields.
        check("equal events are equal",
            Client.parseEvent(transfer(Scv.toString("t"))).get()
                .equals(Client.parseEvent(transfer(Scv.toString("t"))).get()));

        if (failures > 0) throw new AssertionError(failures + " checks failed");
        System.out.println("all checks passed");
    }
}
