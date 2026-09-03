# HouseEdge LP — Experiment 001

**Status:** primary specification frozen before results.

## Counterparty
Liquidity-demanding traders whose orders reach the Uniswap v3 pool.

## Mechanism
The LP earns its pro-rata share of swap fees while bearing adverse-selection / rebalancing losses. A discrete external delta hedge removes most directional exposure but introduces trading costs, funding, and hedge error.

## Falsifier
Kill the pool hypothesis if the lower 95% stationary-bootstrap confidence bound of annualized **net discrete-hedged LP return** is not above zero after the preregistered costs, or if alignment diagnostics show that the apparent result is not robust enough to measure reliably.

## Primary outcome
Discrete-delta-hedged LP P&L, including LP inventory mark-to-market, fee revenue, hedge P&L, hedge trading cost, funding, and fixed operating cost.

Markouts are **flow-quality diagnostics only**. They are never subtracted from fees to manufacture a synthetic "house edge" statistic.

## Primary hedge policy
A fixed $250 dollar-delta no-trade band. When the target hedge minus the current hedge exceeds the band, rebalance only to the nearest band edge. Alternative bands are not tuned inside Experiment 001.

## Primary inference
Stationary bootstrap over serially dependent swap-event P&L increments, 2,000 replications, expected block length 100 swaps.

Research GO requires the lower 95% confidence bound of annualized net hedged return to exceed zero.

Production is a later and harder gate: >=5% annualized net hedged return and approximately >=1 hedged Sharpe, with regime and out-of-sample validation.

## Null and measurement controls
- Randomized swap-direction information markouts should be approximately zero.
- Reference-price time shifts of -10, -5, -2, 0, +2, +5, +10 seconds quantify timestamp sensitivity.
- Reference quotes older than 3 seconds are stale for the primary analysis.

## Capacity
Sweep hypothetical capital from $1k to $300k using the same historical tape. Results are explicitly labeled **passive counterfactual capacity**; large sizes can change routing, price impact, and arbitrage and therefore are not assumed causal/exact.

## Scope exclusions
No live wallet, no transaction signing, no range optimizer, no ML, and no execution service in Experiment 001.
