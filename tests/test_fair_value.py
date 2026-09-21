import json

import pandas as pd
import yaml

from houseedge.config import calibration_basis_hash, load_yaml, reference_policy_hash
from houseedge.data.fair_value import (
    compose_priority_fallback,
    rebuild_multi_venue_references,
    select_calibration_policy,
)


def _targets(values):
    timestamps=pd.to_datetime(values,utc=True)
    return pd.DataFrame({"target_timestamp":timestamps,"swap_count":[1]*len(timestamps)})


def _matches(targets,ages,source):
    target=pd.to_datetime(targets,utc=True)
    age=pd.to_timedelta(ages,unit="s")
    return pd.DataFrame(
        {
            "target_timestamp":target,
            "timestamp":target-age,
            "mid":[3000.0+i for i in range(len(target))],
            "source":source,
        }
    )


def test_priority_fallback_prefers_binance_and_never_looks_forward():
    targets=_targets(["2025-07-01T00:00:01Z","2025-07-01T00:00:02Z"])
    primary=_matches(targets["target_timestamp"],[0.25,-0.1],"binance_spot_trade")
    fallback=_matches(targets["target_timestamp"],[0.1,0.5],"bybit_spot_trade")

    selected,metrics=compose_priority_fallback(
        targets,primary,fallback,tolerance_seconds=1.0
    )

    assert selected["source"].tolist()==["binance_spot_trade","bybit_spot_trade"]
    assert (selected["timestamp"]<=selected["target_timestamp"]).all()
    assert metrics["coverage"]==1.0
    assert metrics["primary_swaps"]==1
    assert metrics["fallback_swaps"]==1


def test_freshness_is_selected_only_from_calibration_then_frozen_for_candidate():
    calibration=_targets(["2025-07-01T00:00:01Z","2025-07-01T00:00:02Z"])
    primary=_matches(calibration["target_timestamp"].iloc[:1],[0.5],"binance_spot_trade")
    fallback=_matches(calibration["target_timestamp"].iloc[1:],[1.5],"bybit_spot_trade")
    selected,grid=select_calibration_policy(
        calibration,primary,fallback,
        freshness_grid_seconds=[1.0,2.0,3.0],required_coverage=0.995,
    )
    assert selected==2.0
    assert [row["passes"] for row in grid]==[False,True,True]

    candidate=_targets(["2026-01-01T00:00:01Z"])
    candidate_primary=_matches(candidate["target_timestamp"],[2.5],"binance_spot_trade")
    _,metrics=compose_priority_fallback(
        candidate,candidate_primary,pd.DataFrame(),tolerance_seconds=selected
    )
    assert metrics["coverage"]==0.0
    assert selected==2.0


def test_rebuild_reuses_events_and_reports_out_of_sample_gate(tmp_path):
    config=load_yaml("configs/experiment_001.yaml")
    config["sample"]["reference_policy"]["freshness_grid_seconds"]=[1.0,2.0,3.0]
    config_path=tmp_path/"experiment.yaml"
    config_path.write_text(yaml.safe_dump(config,sort_keys=False),encoding="utf-8")
    root=tmp_path/"data"
    for window,date in (("calibration","2025-07-01"),("candidate","2026-01-01")):
        event_dir=root/"raw"/f"{window}_events.parquet"
        event_dir.mkdir(parents=True)
        frame=pd.DataFrame(
            {
                "event":["Swap","Swap"],
                "timestamp":pd.to_datetime(
                    [f"{date}T00:00:01Z",f"{date}T00:00:02Z"],utc=True
                ),
            }
        )
        frame.to_parquet(event_dir/"part-1.parquet",index=False)

    def primary_loader(_symbol,targets,_cache,*,max_age_seconds,force):
        del max_age_seconds,force
        target=pd.Series(targets).reset_index(drop=True)
        return _matches(target.iloc[:1],[0.5],"binance_spot_trade")

    def fallback_loader(_symbol,targets,_cache,*,max_age_seconds,force):
        del max_age_seconds,force
        target=pd.Series(targets).reset_index(drop=True)
        return _matches(target.iloc[1:],[1.5],"bybit_spot_trade")

    def regime_loader(_symbol,start,_end,_cache,*,force):
        del force
        return pd.DataFrame(
            {
                "timestamp":[pd.Timestamp(start)],
                "mid":[2999.0],
                "source":["binance_spot_5m"],
                "alignment_eligible":[False],
                "regime_eligible":[True],
            }
        )

    report_path=tmp_path/"reference.json"
    result=rebuild_multi_venue_references(
        config_path=config_path,output_root=root,report_path=report_path,
        binance_loader=primary_loader,bybit_loader=fallback_loader,
        regime_loader=regime_loader,
    )

    selected=load_yaml(config_path)
    persisted=json.loads(report_path.read_text(encoding="utf-8"))
    assert result["status"]=="PASS"
    assert result["selected_max_age_seconds"]==2.0
    assert result["candidate_used_for_policy_selection"] is False
    assert result["candidate_primary_lp_pnl_opened"] is False
    assert result["base_hypersync_download_invoked"] is False
    assert persisted["allowed_missing_fraction"]==0.005
    assert selected["sample"]["primary_alignment"]["max_age_seconds"]==2.0
    assert selected["sample"]["reference_policy"]["selection_status"]=="SELECTED_ON_CALIBRATION"
    assert calibration_basis_hash(selected)==result["calibration_basis_sha256_after_selection"]
    assert reference_policy_hash(selected)==result["reference_policy_sha256"]
    assert (root/"calibration"/"eth_reference.parquet").exists()
    assert (root/"candidate"/"eth_reference.parquet").exists()
