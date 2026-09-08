# Authoritative implementation references

Checked 2026-09-08.

- Uniswap v3 Base deployments and factory address: https://developers.uniswap.org/docs/protocols/v3/deployments/v3-base-deployments
- Uniswap v3 fee / protocol-fee concepts: https://developers.uniswap.org/docs/get-started/concepts/fees
- Uniswap protocol-fee deployments: https://developers.uniswap.org/docs/protocols/protocol-fee/deployments
- Uniswap v3 pool data / `slot0` / `liquidity`: https://developers.uniswap.org/docs/sdks/v3/guides/pool-data
- Base RPC overview and chain id 8453: https://docs.base.org/base-chain/api-reference/rpc-overview
- Circle native USDC on Base address: https://developers.circle.com/stablecoins/usdc-contract-addresses
- Binance public historical market-data archive: https://github.com/binance/binance-public-data
- Binance public market-data-only endpoints: https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md
- Hyperliquid `fundingHistory` info endpoint and pagination: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- Aave official Base v3 address book (`POOL`, data provider, assets): https://github.com/aave-dao/aave-address-book/blob/main/src/AaveV3Base.sol
- Aave v3 protocol subgraph/rate conventions and historical queries: https://github.com/aave/aave-v3-core/tree/master
- Coinbase Exchange public WebSocket market-data feed (prospective diagnostics only): https://docs.cdp.coinbase.com/exchange/websocket-feed/overview

The public Base RPC is rate-limited and is not suitable for the multi-month Experiment 001 acquisition. Use an archive/log-capable Base provider for `fetch-calibration-data`.
