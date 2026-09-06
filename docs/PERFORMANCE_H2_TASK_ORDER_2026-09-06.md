# Investment Performance H2 execution order

Parent: #315

The implementation order after PERF-H1 v3 is intentionally risk-first rather
than based on issue creation time:

1. stable whole-portfolio membership gate;
2. affirmative cash-boundary history coverage;
3. async internal-transfer transit/reconciliation;
4. in-kind boundary coverage;
5. tax/direct-payout hardening.

This file exists only to keep worker routing unambiguous while issue numbering
is reconciled. No financial implementation is authorized by this document.
