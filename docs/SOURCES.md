# Authoritative implementation references

Checked 2026-09-03.

- Uniswap v3 Base deployments and factory address: https://developers.uniswap.org/docs/protocols/v3/deployments/v3-base-deployments
- Uniswap v3 fee / protocol-fee concepts: https://developers.uniswap.org/docs/get-started/concepts/fees
- Uniswap protocol-fee deployments: https://developers.uniswap.org/docs/protocols/protocol-fee/deployments
- Uniswap v3 pool data / `slot0` / `liquidity`: https://developers.uniswap.org/docs/sdks/v3/guides/pool-data
- Uniswap v3 subgraph event field definitions: https://developers.uniswap.org/docs/ecosystem/subgraphs/concepts/v3/entities
- Base RPC overview and chain id 8453: https://docs.base.org/base-chain/api-reference/rpc-overview
- Circle native USDC on Base address: https://developers.circle.com/stablecoins/usdc-contract-addresses
- Coinbase Exchange public WebSocket market-data feed: https://docs.cdp.coinbase.com/exchange/websocket-feed/overview

The public Base RPC is rate-limited and is not suitable for a month-scale production ingestion job. Use it for plumbing tests; use an archive/log-capable provider for the real experiment.
