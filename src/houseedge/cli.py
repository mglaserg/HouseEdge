from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

import typer
from rich import print

from houseedge.config import load_yaml, PoolSpec
from houseedge.data.storage import read_frame, write_frame
from houseedge.data.reference import collect_coinbase_ticker
from houseedge.research.gate0 import gate0
from houseedge.experiment import run_experiment
from houseedge.demo import synthetic_tape
from houseedge.prereg import freeze_record, assert_frozen

app=typer.Typer(help="HouseEdge LP research CLI — no live execution or wallet signing.")
DEFAULT_CONFIG="configs/experiment_001.yaml"

@app.command()
def freeze(config: str=DEFAULT_CONFIG, registry: str="data/prereg_registry.jsonl"):
    """Freeze the Experiment 001 primary spec hash locally before real-data results."""
    rec=freeze_record(config,registry)
    print(rec)

@app.command("gate0")
def gate0_cmd(annualized_vol: float, daily_volume_usd: float, active_capital_usd: float, lp_fee_bps: float=3.75):
    r=gate0(annualized_vol=annualized_vol,daily_volume_usd=daily_volume_usd,active_capital_usd=active_capital_usd,lp_fee_rate=lp_fee_bps/10000)
    print(r.as_dict())

@app.command("discover-pool")
def discover_pool_cmd(config: str=DEFAULT_CONFIG, rpc_url: str|None=None):
    from houseedge.data.uniswap_base import connect, discover_pool
    cfg=load_yaml(config); spec=PoolSpec.from_config(cfg); w3=connect(rpc_url)
    addr=discover_pool(w3,cfg["chain"]["uniswap_v3_factory"],spec)
    print({"pool_address":addr,"chain_id":w3.eth.chain_id})

@app.command("fetch-events")
def fetch_events_cmd(from_block: int, to_block: int, output: str="data/raw/weth_usdc_events.parquet", config: str=DEFAULT_CONFIG, rpc_url: str|None=None, chunk_blocks: int=20000):
    from houseedge.data.uniswap_base import connect, discover_pool, fetch_events
    cfg=load_yaml(config); spec=PoolSpec.from_config(cfg); w3=connect(rpc_url)
    pool=spec.pool_address or discover_pool(w3,cfg["chain"]["uniswap_v3_factory"],spec)
    print(f"Fetching [bold]{pool}[/bold] blocks {from_block:,}..{to_block:,}")
    df=fetch_events(w3,pool,spec,from_block,to_block,chunk_blocks=chunk_blocks)
    write_frame(df,output); print(f"wrote {len(df):,} events -> {output}")

@app.command("collect-reference")
def collect_reference(seconds: int=3600, output: str="data/reference/coinbase_eth_usd.parquet", product_id: str="ETH-USD"):
    p=asyncio.run(collect_coinbase_ticker(product_id,seconds,output)); print(f"wrote {p}")

@app.command("run")
def run_cmd(swaps: str, reference: str, config: str=DEFAULT_CONFIG, output: str|None=None, registry: str="data/prereg_registry.jsonl", allow_unfrozen: bool=False):
    cfg=load_yaml(config)
    if not allow_unfrozen:
        assert_frozen(config,registry)
    stamp=datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out=output or f"runs/{cfg['experiment_id']}_{stamp}"
    result=run_experiment(read_frame(swaps),read_frame(reference),cfg,out)
    print(json.dumps(result,indent=2,default=str))
    print(f"\n[bold]Artifacts:[/bold] {out}")

@app.command()
def demo(config: str=DEFAULT_CONFIG, output: str="runs/demo"):
    swaps,ref=synthetic_tape(); cfg=load_yaml(config)
    result=run_experiment(swaps,ref,cfg,output)
    print(json.dumps(result,indent=2,default=str))
    print("[yellow]Synthetic plumbing validation only — not evidence of an LP edge.[/yellow]")

if __name__ == "__main__":
    app()
