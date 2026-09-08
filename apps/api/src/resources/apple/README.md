# Apple public root certificates

Public DER root certificates downloaded from [Apple PKI](https://www.apple.com/certificateauthority/) on 2026-09-08. They contain no private keys. Apple's official App Store Server Library uses these pinned roots to verify signed transactions and notifications; online revocation checks remain enabled.

| File | SHA-256 | Valid until (UTC) |
| --- | --- | --- |
| AppleRootCA-G2.cer | c2b9b042dd57830e7d117dac55ac8ae19407d38e41d88f3215bc3a890444a050 | 2039-04-30 18:10:09 |
| AppleRootCA-G3.cer | 63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179 | 2039-04-30 18:19:06 |

Refresh from the official Apple PKI source when Apple rotates its roots. `APPLE_ROOT_CA_PATHS` optionally overrides this bundle with a comma-separated list of DER certificate paths; an empty setting uses these packaged files.
