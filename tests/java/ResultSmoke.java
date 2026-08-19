import com.example.Client;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.SCError;
import org.stellar.sdk.xdr.SCErrorType;
import org.stellar.sdk.xdr.SCVal;
import org.stellar.sdk.xdr.SCValType;
import org.stellar.sdk.xdr.Uint32;
import org.stellar.sdk.xdr.XdrUnsignedInteger;

import java.util.Arrays;

/**
 * Result, SCError and error-enum decoding, which the SAC spec does not use.
 *
 * <p>The spec these bindings come from is built in test_java_compile.py: an
 * error enum {@code Code { Bad = 7 }}, a struct holding a
 * {@code Result<u32, Code>}, one event carrying that Result and one carrying a
 * bare Error, and a function returning {@code Result<u32, Code>}.
 */
public class ResultSmoke {
    static int failures = 0;

    static void check(String label, boolean ok) {
        System.out.println((ok ? "PASS " : "FAIL ") + label);
        if (!ok) failures++;
    }

    static Client.DecodedEvent event(String topic, SCVal data) {
        return new Client.DecodedEvent(Arrays.asList(Scv.toSymbol(topic)), data);
    }

    public static void main(String[] args) {
        // An error enum is an SCV_ERROR carrying an SCE_CONTRACT code, not a u32.
        SCVal encoded = Client.Code.Bad.toSCVal();
        check("error enum encodes as SCV_ERROR",
            encoded.getDiscriminant() == SCValType.SCV_ERROR);
        check("error enum encodes as SCE_CONTRACT",
            encoded.getError().getDiscriminant() == SCErrorType.SCE_CONTRACT);
        check("error enum encodes its declared value",
            encoded.getError().getContractCode().getUint32().getNumber() == 7L);
        check("error enum round-trips", Client.Code.fromSCVal(encoded) == Client.Code.Bad);

        // A u32 is no longer accepted where an error enum is declared.
        boolean rejectedU32 = false;
        try {
            Client.Code.fromSCVal(Scv.toUint32(7));
        } catch (IllegalArgumentException e) {
            rejectedU32 = true;
        }
        check("error enum rejects a bare u32", rejectedU32);

        // A Result-typed event parameter keeps whichever arm arrived.
        Client.OutcomeEvent ok = (Client.OutcomeEvent)
            Client.parseEvent(event("outcome", Scv.toUint32(5))).get();
        check("Ok arm decoded", ok.getR().isOk() && ok.getR().getValue() == 5L);
        check("Ok arm carries no error", ok.getR().getError() == null);

        Client.OutcomeEvent err = (Client.OutcomeEvent)
            Client.parseEvent(event("outcome", Client.Code.Bad.toSCVal())).get();
        check("Err arm decoded",
            !err.getR().isOk() && err.getR().getError() == Client.Code.Bad);
        check("Err arm carries no value", err.getR().getValue() == null);

        // A bare Error parameter comes back as the XDR type.
        SCVal raw = Scv.toError(SCError.builder()
            .discriminant(SCErrorType.SCE_CONTRACT)
            .contractCode(new Uint32(new XdrUnsignedInteger(3L)))
            .build());
        Client.RawEvent rawEvent = (Client.RawEvent) Client.parseEvent(event("raw", raw)).get();
        check("SCError decoded",
            rawEvent.getWhy().getContractCode().getUint32().getNumber() == 3L);

        // Both arms survive a struct round trip.
        Client.Wrapper okWrapper = new Client.Wrapper(Client.Result.<Long, Client.Code>ok(9L));
        check("struct Ok round-trips",
            Client.Wrapper.fromSCVal(okWrapper.toSCVal()).equals(okWrapper));

        Client.Wrapper errWrapper =
            new Client.Wrapper(Client.Result.<Long, Client.Code>err(Client.Code.Bad));
        check("struct Err round-trips",
            Client.Wrapper.fromSCVal(errWrapper.toSCVal()).equals(errWrapper));
        check("struct Err is not read as Ok",
            !Client.Wrapper.fromSCVal(errWrapper.toSCVal()).getR().isOk());

        if (failures > 0) throw new AssertionError(failures + " checks failed");
        System.out.println("all checks passed");
    }
}
