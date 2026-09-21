# HouseEdge LP — Experiment 001 (v0.15 calibration draft)

**Status:** NOT YET FROZEN. The v0.1 primary specification is superseded. Do not inspect or use primary LP P&L until the v0.15 outcome-blind calibration gates pass and this specification is frozen.

## Counterparty / mechanism / falsifier

- **Counterparty:** liquidity-demanding traders whose orders reach the Base Uniswap v3 WETH/USDC 5 bp pool.
- **Mechanism:** passive LP capital earns swap fees for immediacy while paying adverse-selection/rebalancing, boundary, protocol, gas, hedge, funding, and operational costs.
- **Falsifier:** net discrete-delta-hedged LP **excess return over the precommitted on-chain cash alternative** fails the statistical, economic, or capacity hurdle. Measurement failures are VOID, not evidence against the hypothesis.

## v0.15 gates before freeze

1. **Prospective power:** use a separate calibration return process with stationary dependence. Require >=80% statistical power to detect a true +5% annual excess edge. Because the final decision also requires a point estimate >=5%, full-GO power is separately evaluated at a larger material alternative (default +8%); power at a true +5% edge cannot exceed roughly 50% under an unbiased point-estimate hurdle set at +5%.
2. **Regime coverage:** use ETH prices only. Define 20th/80th realized-variance thresholds on the calibration period and choose the still-blind primary window only if it contains at least five days in each tail regime.
3. **Gate 0:** compute fee capture and predictable LVR on the same hypothetical concentrated-liquidity position. Use mean realized variance `E[sigma^2]`, never `(E[sigma])^2`.
4. **Protocol fees:** read packed `slot0.feeProtocol` at the block preceding the sample and replay every `SetFeeProtocol` event. No static LP fee-share assumption.
5. **JIT diagnostic:** detect short-lived Mint/Burn liquidity (<=3 blocks by default) and quantify its overlap with active liquidity. This is a diagnostic, not an assertion that pool events uniquely identify economic NFT positions.
6. **Reference convention:** primary reference is a deterministic priority fallback: the last non-stale Binance spot ETH/USDT trade at or before the Base block timestamp, otherwise the last non-stale Bybit spot ETH/USDT trade. No look-ahead is permitted. The maximum age is the smallest member of the predeclared `[1, 2, 3, 5, 10]` second grid that meets 99.5% swap-weighted coverage on the calibration window only. Venue order and freshness are then frozen; the candidate window is used solely for the out-of-sample 99.5% coverage validity check and cannot select or change the rule.
7. **Seal prediction:** expected point estimate, CI width, capacity, and GO/KILL prediction are hashed before primary replay.

## Frozen decision rule once v0.15 passes

- **Numeraire:** USD.
- **Primary hedge:** ETH perpetual on a venue selected and frozen before primary replay.
- **Hedge trigger:** residual ETH delta notional >5% of current LP NAV.
- **Hedge action:** rebalance residual delta to zero.
- **Funding:** actual historical funding payments applied to actual hedge notional.
- **Benchmark:** time-matched Aave v3 Base USDC supply return, explicitly treated as an on-chain cash alternative rather than a risk-free rate.
- **Statistical GO:** lower 95% stationary-bootstrap CI of annualized excess return >0.
- **Economic GO:** point estimate annualized excess return >=5%.
- **Capacity GO:** passive-counterfactual capacity supports >=$10,000 expected annual excess profit at the economic hurdle.
- **GO requires all three.** Otherwise KILL, unless a validity criterion makes the experiment VOID.
- **Range optimization cannot rescue a KILL.**

## VOID criteria

The experiment is VOID rather than KILL if any preregistered measurement requirement fails, including incomplete protocol-fee history, unresolved funding coverage, replay-state reconciliation failure, reference missingness >0.5%, or a micro-live fee-reconciliation error >1 bp of pilot NAV.

## Micro-live pilot

Run a permissionless micro-live LP telemetry position in parallel only after v0.15 selects a viable minimum size. It is excluded from the primary statistical sample. Its job is operational reconciliation: replayed accrued fees must match on-chain accrued fees within 1 bp of pilot NAV; failure blocks GO.

## Re-runs / looks

Any rerun after the primary outcome has been unblinded is a new EdgeLab look/trial, including a bug-fix rerun. Bugs found by preregistered reconciliation tests before primary outcome exposure are logged QA corrections and do not spend the outcome.

## Markouts

30s / 60s / 5m markouts are **flow-quality diagnostics only**. They are not LVR and are never subtracted from fees to create the primary statistic.
