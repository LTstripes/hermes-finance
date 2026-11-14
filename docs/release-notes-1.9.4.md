# Finance 1.9.4

The month interface could fail while displaying saved native bond statement
proofs: it expected legacy signed-cash fields that this proof variant does not
contain. The table now displays the native statement proof directly and handles
account commissions and broker bonuses explicitly. Missing values remain unknown.

This is a narrow display compatibility correction with a targeted render regression
and production frontend build. Financial writers, stored amounts, receipt formats
and schema are unchanged. The Owner authorized emergency delivery without waiting
for full suites; broader CI success is not claimed.
