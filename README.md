# HouseEdge LP v0.1.0

A **research-first, preregistered liquidity-provision lab** for HouseEdge. This bundle deliberately does not contain wallet keys, transaction signing, LP minting, or live execution.

The primary Experiment 001 question is:

> Does a passive Uniswap v3 WETH/USDC LP position on Base retain a reliably positive return after discrete delta hedging, LP protocol-fee share, hedge trading costs/funding, and operating costs?

## Architecture

```text
Base / Uniswap logs ──┐
                      ├─> local Parquet ─> Experiment runner ─> runs/<id>/
CEX reference mids ───┘                         │
                                                └─> read-only Streamlit dashboard
```

The dashboard is **separate from running**. The research runner writes artifacts to disk; Streamlit only reads them.

## Experiment layers

1. **Gate 0** — cheap active-capital fee-vs-vol screen.
2. **Reference alignment lab** — quantify timestamp coverage and sensitivity.
3. **Flow quality** — 30s/60s/5m markouts plus shuffled-direction null. Diagnostic only.
4. **Discrete delta-hedged replay** — primary GO/KILL statistic.
5. **Stationary bootstrap** — lower 95% CI must exceed zero for Research GO.
6. **Capacity sweep** — passive counterfactual only.

Range optimization, ML, and live execution are intentionally postponed until a strong GO.

## Setup (Windows / uv)

```powershell
cd houseedge
uv venv
.venv\Scripts\activate
uv pip install -e ".[dev]"
```

or:

```powershell
uv sync --extra dev
```

## 1. Validate the full plumbing immediately

```powershell
houseedge demo
streamlit run dashboard/app.py
```

The demo generates synthetic swaps and quotes and runs the complete analysis. **Its P&L is not evidence.** It exists to catch code/plumbing bugs before real data touches the experiment.

## 2. Freeze Experiment 001 before real results

Review `configs/experiment_001.yaml` and `prereg/experiment_001.md`. Once you want that exact spec to be the primary test:

```powershell
houseedge freeze
```

This appends a SHA-256 spec hash to `data/prereg_registry.jsonl`. A later edit under the same experiment ID causes the real-data runner to stop. The included `prereg/edgelab_manifest.json` is the handoff manifest for the canonical EdgeLab registry; HouseEdge does not pretend to know or replace your EdgeLab package API.

## 3. Gate 0

Example only:

```powershell
houseedge gate0 --annualized-vol 0.60 --daily-volume-usd 25000000 --active-capital-usd 100000000 --lp-fee-bps 3.75
```

`active_capital_usd`, not total pool TVL, is the intended denominator. Gate 0 uses the frictionless `sigma^2/8` LVR benchmark as a conservative screen, not as calibrated realized LVR.

## 4. Find the configured WETH/USDC 5bp pool

```powershell
houseedge discover-pool
```

The Base public RPC is useful for testing but rate-limited. For month-scale event pulls set an archive-capable provider:

```powershell
$env:BASE_RPC_URL="https://YOUR_BASE_RPC"
```

## 5. Pull exact on-chain event order

```powershell
houseedge fetch-events --from-block 12345678 --to-block 12445678
```

Swap, Mint, and Burn logs are saved in block / transaction / log order. The replay uses the Swap event's active-liquidity value; Mint/Burn are archived so later exact tick-state reconstruction/JIT studies do not require a re-download.

## 6. Reference prices

For prospective data collection:

```powershell
houseedge collect-reference --seconds 3600
```

This records public Coinbase `ETH-USD` ticker bid/ask/mid updates. For a historical experiment, provide a tick-level CSV or Parquet with:

```text
timestamp,mid,source
2026-08-01T00:00:00.123Z,3521.14,composite
...
```

or `timestamp,bid,ask,source`. Do **not** substitute one-minute candles and then interpret a 30-second markout as precise.

The preregistered primary reference is labeled `composite`: build that file externally from the venues you approve, then feed it to HouseEdge. Venue-specific series belong in sensitivity/future variants rather than silently changing the primary reference.

## 7. Run Experiment 001

```powershell
houseedge run --swaps data/raw/weth_usdc_events.parquet --reference data/reference/composite_eth_usd.parquet
```

Outputs include:

- `summary.json`
- `aligned_swaps.parquet`
- `alignment_sensitivity.csv`
- `markouts.parquet`
- `markout_nulls.csv`
- `hedged_replay.parquet`
- `bootstrap.parquet`
- `capacity.csv`

Research GO is mechanically:

```text
lower 95% stationary-bootstrap CI of annualized net hedged LP return > 0
```

Nothing in the markout charts can override that rule.

## Important implementation choices

- **Raw Uniswap liquidity units:** hypothetical LP liquidity is computed in raw-token coordinates, so `L_ours` is comparable to the pool's on-chain active `liquidity`.
- **Protocol fees:** Experiment 001 conservatively assumes LPs retain 75% of the 5bp fee. Confirm the actual selected pool configuration before interpreting a GO.
- **Boundary crossing:** if a swap moves the hypothetical position across an in/out-of-range boundary, V0 assigns zero fee to that swap rather than overclaiming partial-step fees. A later exact swap-step replay can improve this if Experiment 001 survives.
- **Markouts:** information and execution markouts diagnose toxicity. They do not equal LVR.
- **Hedge:** fixed $250 no-trade dollar-delta band; trade back only to the band edge. No tuning inside Experiment 001.
- **Capacity:** the sweep assumes the historical tape is unchanged by our added liquidity. It is labeled passive counterfactual capacity for that reason.

## What V0.1 intentionally does not claim

Exact fee partition on a swap that crosses our range boundary requires step-by-step Uniswap swap reconstruction across initialized ticks. Rather than smuggling an approximation into the primary statistic, V0.1 assigns zero fee to those boundary-crossing swaps. If the edge cannot survive that conservative treatment, there is no reason to spend the engineering time on exact crossing reconstruction.

Similarly, historical block timestamps do not identify sub-block transaction wall-clock time. The alignment diagnostics are therefore part of the measurement validity check, not cosmetic charts.

## Safety

There are no private-key fields, signing methods, wallet connectors, or transaction-broadcast methods in this repository. Live LP execution is a later HouseEdge phase and should remain a separate service from the dashboard.
