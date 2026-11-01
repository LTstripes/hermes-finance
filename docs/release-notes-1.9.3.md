# Hermes Finance 1.9.3

Opening a month or its payments could repeat the same source-proof checks many
times, occupy database connections and make unrelated requests time out. This
correction reuses identical derived checks within one coherent read snapshot.
The cache ends with that snapshot, including failures; writers and subsequent
reads always validate current evidence again.

No financial data, accepted evidence, receipt format or schema is rewritten.
Close, provider refresh and financial confirmation remain explicit actions.
Existing source-only investment proofs retain their implementation-currentness
guard and may require fresh review; this release does not silently reissue them.

This is an Owner-authorized emergency correction with targeted snapshot,
currentness and read-performance validation. Full suites are not claimed as
completed release evidence. Use the normal backup-first Stable update and
separate Start on the exact published identity.
