# Archived journal entries

Entries here are kept for the record but are NOT counted in the Phase 1 gate, the daily
report, the dashboard or Pattern Finder. Those read only `journal/firm_trades.jsonl`.

## aborted_run_20261115_trades.jsonl

4 paper trades (poorcat, dragoncat, SLIDES, DIGS), total -$7.41, all closed at
2026-11-15T11:59:50Z with exit reason "firm shutdown".

Why archived: they come from the first attempt at the 60-minute live run, which the operator
stopped after about 3 minutes to fix a bug. On that code the firm picked a token's market by
liquidity alone, so a junk side pool could supply the price, and open positions were not
checked during a long scan. The trades were entered on that code and closed by the operator's
stop 4 to 73 seconds after entry, not by any trading rule. They say nothing about the strategy.

Moved here on the founder's instruction, 15 Nov 2026. Nothing was deleted.
The decisions from the same run are in `logs/aborted_run1_decisions.jsonl`.
