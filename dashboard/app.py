from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import streamlit as st

st.set_page_config(page_title="HouseEdge LP",layout="wide")
st.title("HouseEdge · LP Research")
st.caption("Read-only research dashboard. No execution code is present. Experiment 001 cannot earn GO until v0.15 calibration, primary replay validity, and micro-live reconciliation all pass.")

runs=sorted(Path("runs").glob("*/summary.json"),key=lambda p:p.stat().st_mtime,reverse=True)
if not runs:
    st.info("No experiment runs yet. Try: `houseedge demo`.")
    st.stop()
selected=st.selectbox("Run",runs,format_func=lambda p:p.parent.name)
summary=json.loads(selected.read_text())
p=summary["primary"]; ex=summary.get("excess",{})

c1,c2,c3,c4=st.columns(4)
c1.metric("Decision",summary["decision"])
c2.metric("Net hedged return",f"{p['net_hedged_return']:.2%}")
c3.metric("Annual excess",f"{ex.get('annualized_point_estimate',0):.2%}")
c4.metric("95% excess CI lower",f"{ex.get('annualized_lower',0):.2%}")

if summary.get("outcome_look_number",0):
    st.warning(f"Primary outcome look #{summary['outcome_look_number']}. Any post-unblind rerun is another EdgeLab look/trial.")

st.subheader("Decision gates")
if "gates" in summary:
    st.dataframe(pd.DataFrame([summary["gates"]]),use_container_width=True,hide_index=True)
if "validity" in summary:
    v=summary["validity"]
    st.write(f"Validity: **{v['status']}**")
    if v.get("failures"):
        st.error(", ".join(v["failures"]))

st.subheader("Hedged replay")
replay_path=selected.parent/"hedged_replay.parquet"
if replay_path.exists():
    path=pd.read_parquet(replay_path)
    path["timestamp"]=pd.to_datetime(path["timestamp"],utc=True)
    st.line_chart(path.set_index("timestamp")[["cum_net_pnl_usd","cum_fee_usd"]])
    q1,q2,q3=st.columns(3)
    q1.metric("Fees",f"${p['fee_pnl_usd']:,.2f}")
    q2.metric("Hedge costs",f"${p['hedge_trading_cost_usd']:,.2f}")
    q3.metric("Hedge trades",f"{p['hedge_trades']:,}")

st.subheader("Passive counterfactual capacity")
cap_path=selected.parent/"capacity.csv"
if cap_path.exists():
    cap=pd.read_csv(cap_path)
    chart_col="annualized_excess_return" if "annualized_excess_return" in cap else "annualized_net_return"
    st.line_chart(cap.set_index("capital_usd")[[chart_col]])
    st.dataframe(cap,use_container_width=True,hide_index=True)

st.subheader("Flow-quality diagnostics")
mark_path=selected.parent/"markouts.parquet"
if mark_path.exists():
    m=pd.read_parquet(mark_path)
    cols=[c for c in m if c.startswith("info_markout_")]
    stats=[]
    for c in cols:
        stats.append({"horizon":c,"mean_bps":m[c].mean(),"median_bps":m[c].median(),"n":m[c].notna().sum()})
    st.dataframe(pd.DataFrame(stats),use_container_width=True,hide_index=True)
    st.caption("Markouts diagnose flow quality. They are not LVR and are not the GO/KILL statistic.")

with st.expander("Measurement controls"):
    a=selected.parent/"alignment_sensitivity.csv"; n=selected.parent/"markout_nulls.csv"
    if a.exists(): st.dataframe(pd.read_csv(a),use_container_width=True,hide_index=True)
    if n.exists(): st.dataframe(pd.read_csv(n),use_container_width=True,hide_index=True)

for w in summary.get("warnings",[]):
    st.warning(w)
