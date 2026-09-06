from __future__ import annotations
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

import typer
from rich import print

from houseedge.config import load_yaml, PoolSpec
from houseedge.data.storage import read_frame, write_frame
from houseedge.data.reference import collect_coinbase_ticker
from houseedge.research.gate0 import gate0
from houseedge.experiment import run_experiment, preflight_primary_inputs
from houseedge.demo import synthetic_tape
from houseedge.prereg import freeze_record, assert_frozen, seal_prediction, register_outcome_look
from houseedge.calibration import run_design_calibration

app=typer.Typer(help="HouseEdge LP research CLI — no live execution or wallet signing.")
DEFAULT_CONFIG="configs/experiment_001.yaml"

@app.command()
def freeze(
    config: str=DEFAULT_CONFIG,
    calibration_report: str=typer.Option(...,"--calibration-report"),
    prediction: str|None=None,
    registry: str="data/prereg_registry.jsonl",
    prediction_registry: str="data/prediction_registry.jsonl",
):
    """Freeze Experiment 001 only after passing v0.15 calibration."""
    rec=freeze_record(config,registry,calibration_report_path=calibration_report,prediction_path=prediction,prediction_registry_path=prediction_registry)
    print(rec)

@app.command("seal-prediction")
def seal_prediction_cmd(prediction: str="prereg/experiment_001_prediction.json", registry: str="data/prediction_registry.jsonl"):
    """SHA-256 seal the prior prediction before primary replay."""
    print(seal_prediction(prediction,registry))

@app.command("calibrate-design")
def calibrate_design_cmd(
    calibration_increments: str,
    calibration_reference: str,
    candidate_reference: str,
    candidate_events: str,
    benchmark_rates: str,
    config: str=DEFAULT_CONFIG,
    output: str="runs/v015_calibration",
):
    """Run outcome-blind v0.15 power/regime/napkin/capacity/JIT gates."""
    cfg=load_yaml(config)
    result=run_design_calibration(
        calibration_excess_increments=read_frame(calibration_increments),
        calibration_reference=read_frame(calibration_reference),
        candidate_reference=read_frame(candidate_reference),
        candidate_events=read_frame(candidate_events),
        benchmark_rates=read_frame(benchmark_rates),
        cfg=cfg,output_dir=output,
    )
    print(json.dumps(result,indent=2,default=str))

@app.command("gate0")
def gate0_cmd(annualized_vol: float, daily_volume_usd: float, active_capital_usd: float, lp_fee_bps: float=3.75):
    """Legacy scalar napkin only. Prefer `calibrate-design` for v0.15."""
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
    from houseedge.data.uniswap_base import connect, discover_pool, fetch_events, read_fee_protocol_at_block
    from houseedge.research.protocol_fee import attach_protocol_fee_state
    cfg=load_yaml(config); spec=PoolSpec.from_config(cfg); w3=connect(rpc_url)
    pool=spec.pool_address or discover_pool(w3,cfg["chain"]["uniswap_v3_factory"],spec)
    print(f"Fetching [bold]{pool}[/bold] blocks {from_block:,}..{to_block:,}")
    df=fetch_events(w3,pool,spec,from_block,to_block,chunk_blocks=chunk_blocks)
    initial=read_fee_protocol_at_block(w3,pool,from_block-1)
    df=attach_protocol_fee_state(df,initial)
    write_frame(df,output)
    print({"events":len(df),"output":output,"initial_fee_protocol_packed":initial,"protocol_fee_events":int((df.get('event')=='SetFeeProtocol').sum()) if not df.empty else 0})

@app.command("collect-reference")
def collect_reference(seconds: int=3600, output: str="data/reference/coinbase_eth_usd.parquet", product_id: str="ETH-USD"):
    p=asyncio.run(collect_coinbase_ticker(product_id,seconds,output)); print(f"wrote {p}")

@app.command("run")
def run_cmd(
    swaps: str,
    reference: str,
    funding: str,
    benchmark_rates: str,
    replay_validation: str=typer.Option(...,"--replay-validation",help="JSON from v0.2 state reconciliation with replay_state_valid=true"),
    micro_live_report: str=typer.Option(...,"--micro-live-report",help="JSON with fee_error_bps_nav from the preregistered telemetry pilot"),
    config: str=DEFAULT_CONFIG,
    output: str|None=None,
    registry: str="data/prereg_registry.jsonl",
    looks_registry: str="data/outcome_looks.jsonl",
):
    """Open the frozen primary outcome only after outcome-blind preflight validity passes."""
    cfg=load_yaml(config)
    assert_frozen(config,registry)
    swaps_df=read_frame(swaps); ref_df=read_frame(reference); funding_df=read_frame(funding); benchmark_df=read_frame(benchmark_rates)
    rv=json.loads(Path(replay_validation).read_text(encoding="utf-8"))
    ml=json.loads(Path(micro_live_report).read_text(encoding="utf-8"))
    replay_ok=bool(rv.get("replay_state_valid",False))
    fee_error=ml.get("fee_error_bps_nav")
    if fee_error is None:
        print({"decision":"VOID_PRE_OUTCOME","validity":{"status":"VOID","failures":["MICRO_LIVE_REPORT_MISSING_FEE_ERROR"]},"outcome_look_spent":False})
        raise typer.Exit(code=2)
    preflight=preflight_primary_inputs(swaps_df,ref_df,funding_df,cfg,replay_state_valid=replay_ok,micro_live_fee_error_bps_nav=fee_error)
    if preflight.status != "VALID":
        print({"decision":"VOID_PRE_OUTCOME","validity":preflight.as_dict(),"outcome_look_spent":False})
        raise typer.Exit(code=2)
    look=register_outcome_look(cfg["experiment_id"],looks_registry,reason="primary_run")
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out=output or f"runs/{cfg['experiment_id']}_look{look['look_number']}_{stamp}"
    result=run_experiment(
        swaps_df,ref_df,cfg,out,
        funding_events=funding_df,benchmark_rates=benchmark_df,
        outcome_look_number=int(look["look_number"]),replay_state_valid=replay_ok,micro_live_fee_error_bps_nav=float(fee_error),
    )
    print(json.dumps(result,indent=2,default=str))
    print(f"\n[bold]Artifacts:[/bold] {out}")

@app.command()
def demo(output: str="runs/demo"):
    """Synthetic plumbing validation; never touches the primary preregistration."""
    swaps,ref=synthetic_tape()
    cfg=load_yaml("configs/demo.yaml")
    result=run_experiment(swaps,ref,cfg,output,funding_events=None,benchmark_rates=None,outcome_look_number=0,synthetic=True)
    print(json.dumps(result,indent=2,default=str))
    print("[yellow]Synthetic plumbing validation only — not evidence of an LP edge.[/yellow]")

if __name__ == "__main__":
    app()
