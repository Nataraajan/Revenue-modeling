"""
Revenue Architecture Dashboard — Streamlit app
================================================
Wraps capacity_engine.py, revenue_recognition_engine.py, and renewal_engine.py
into an interactive dashboard. Deploy via Streamlit Community Cloud with all
four .py files in the same repo root.
"""

import streamlit as st
import pandas as pd

from capacity_engine import PodConfig, RoleComp, MarketingFunnel, run_scenario
from revenue_recognition_engine import bookings_to_contracts, run_recognition, summarize as summarize_p2, BillingFrequency
from renewal_engine import RenewalAssumptions, run_full_lifecycle, summarize_renewals

st.set_page_config(page_title="Revenue Architecture Model", layout="wide")
st.title("Revenue Architecture — Pipeline, Recognition & Renewal Model")
st.caption("Bowtie Model (Winning by Design) — deterministic, no randomization. Every number below traces to an explicit input.")

# ---------------------------------------------------------------------------
# SIDEBAR — all inputs, one pod at a time
# ---------------------------------------------------------------------------
st.sidebar.header("Pod Configuration")

pod_name = st.sidebar.text_input("Pod name", "MidMarket")
num_months = st.sidebar.slider("Scenario length (months)", 6, 48, 24)

st.sidebar.subheader("Team")
num_aes = st.sidebar.number_input("Number of AEs", 0, 50, 3)
num_bdrs = st.sidebar.number_input("Number of BDRs", 0, 50, 2)
hiring_cadence = st.sidebar.number_input("Hiring cadence (months between hires)", 1, 12, 3)

st.sidebar.subheader("AE Compensation & Quota")
ae_base = st.sidebar.number_input("AE annual base salary ($)", 0, 500_000, 95_000, step=5000)
ae_variable = st.sidebar.number_input("AE annual variable @ 100% ($)", 0, 500_000, 95_000, step=5000)
ae_quota = st.sidebar.number_input("AE annual quota ($ bookings)", 0, 5_000_000, 1_100_000, step=50_000)

st.sidebar.subheader("BDR Compensation & Quota")
bdr_base = st.sidebar.number_input("BDR annual base salary ($)", 0, 300_000, 55_000, step=5000)
bdr_variable = st.sidebar.number_input("BDR annual variable @ 100% ($)", 0, 300_000, 30_000, step=5000)
bdr_monthly_sql_quota = st.sidebar.number_input("BDR monthly SQL quota", 0, 50, 6)

st.sidebar.subheader("Demand")
monthly_leads = st.sidebar.number_input("Marketing leads/month", 0, 20_000, 500)
lead_to_mql = st.sidebar.slider("Lead → MQL rate", 0.0, 1.0, 0.30)
mql_to_sql = st.sidebar.slider("MQL → SQL rate", 0.0, 1.0, 0.25)
ae_self_sourced = st.sidebar.number_input("AE self-sourced SQLs/month (per AE)", 0.0, 20.0, 2.0)

st.sidebar.subheader("Deal Economics")
avg_deal_size = st.sidebar.number_input("Avg deal size — TCV ($)", 0, 5_000_000, 18_000, step=1000)
win_rate_marketing = st.sidebar.slider("Win rate — marketing-sourced", 0.0, 1.0, 0.25)
win_rate_bdr = st.sidebar.slider("Win rate — BDR-sourced", 0.0, 1.0, 0.20)
win_rate_self = st.sidebar.slider("Win rate — AE self-sourced", 0.0, 1.0, 0.35)

st.sidebar.subheader("Execution")
execution_efficiency = st.sidebar.slider("Execution efficiency", 0.0, 1.5, 1.0, help="1.0 = perfect execution vs. theoretical ceiling")

st.sidebar.subheader("Contract & Revenue Recognition")
contract_term = st.sidebar.number_input("Contract term (months)", 1, 60, 12)
implementation_lag = st.sidebar.number_input("Implementation lag (months)", 0, 24, 2)
ps_fee_pct = st.sidebar.slider("Professional services fee (% of ARR)", 0.0, 0.5, 0.0)

st.sidebar.subheader("Renewal Assumptions")
churn_rate = st.sidebar.slider("Annual gross revenue churn rate", 0.0, 1.0, 0.12)
expansion_rate = st.sidebar.slider("Annual expansion rate", 0.0, 1.0, 0.18)
contraction_rate = st.sidebar.slider("Annual contraction rate", 0.0, 1.0, 0.03)

st.sidebar.subheader("Seasonality (optional)")
use_seasonality = st.sidebar.checkbox("Apply seasonal pattern", value=False)
seasonality_pattern = None
if use_seasonality:
    st.sidebar.caption("Monthly multiplier, Jan → Dec")
    months_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    seasonality_pattern = [
        st.sidebar.slider(months_labels[i], 0.0, 2.0, 1.0, key=f"season_{i}") for i in range(12)
    ]

# ---------------------------------------------------------------------------
# BUILD POD & RUN ALL THREE PHASES
# ---------------------------------------------------------------------------

pod = PodConfig(
    pod_name=pod_name,
    num_aes=int(num_aes),
    num_bdrs=int(num_bdrs),
    ae_comp_template=RoleComp(annual_base=ae_base, annual_variable_at_100pct=ae_variable, annual_quota=ae_quota),
    bdr_comp_template=RoleComp(annual_base=bdr_base, annual_variable_at_100pct=bdr_variable, annual_quota=bdr_monthly_sql_quota * 12) if num_bdrs > 0 else None,
    marketing=MarketingFunnel(monthly_leads=monthly_leads, lead_to_mql_rate=lead_to_mql, mql_to_sql_rate=mql_to_sql),
    avg_deal_size=avg_deal_size,
    win_rate_marketing_sourced=win_rate_marketing,
    win_rate_bdr_sourced=win_rate_bdr,
    win_rate_ae_self_sourced=win_rate_self,
    ae_self_sourced_sqls_per_month=ae_self_sourced,
    execution_efficiency=execution_efficiency,
    hiring_cadence_months=int(hiring_cadence),
    contract_term_months=int(contract_term),
    implementation_lag_months=int(implementation_lag),
    professional_services_fee_pct_of_arr=ps_fee_pct,
    seasonality_pattern=seasonality_pattern,
)

try:
    phase1_df = run_scenario(pod.build_scenario(num_months))
    initial_contracts = bookings_to_contracts(pod, phase1_df, billing_frequency=BillingFrequency.ANNUAL_UPFRONT)

    assumptions = {
        pod_name: RenewalAssumptions(
            pod_name=pod_name,
            gross_revenue_churn_rate_annual=churn_rate,
            expansion_rate_annual=expansion_rate,
            contraction_rate_annual=contraction_rate,
        )
    }
    all_contracts, renewals_df, phase2_df = run_full_lifecycle(initial_contracts, assumptions, num_months)

except Exception as e:
    st.error(f"Model error: {e}")
    st.stop()

# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs(["📈 Pipeline & Capacity", "💰 Revenue Recognition", "🔄 Renewals & NRR", "📋 Raw Data"])

with tab1:
    st.subheader("Bookings: Capacity vs. Demand Constraint")
    st.line_chart(phase1_df.set_index("month")[["capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings"]])

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Bookings", f"${phase1_df['actual_bookings'].sum():,.0f}")
    col2.metric("Total Cost of Capacity", f"${phase1_df['total_cost_of_capacity'].sum():,.0f}")
    months_capacity_bound = (phase1_df["binding_constraint"] == "CAPACITY").sum()
    col3.metric("Months Capacity-Bound", f"{months_capacity_bound}/{len(phase1_df)}")

    st.subheader("Full Pipeline & Capacity Table")
    st.dataframe(phase1_df, use_container_width=True)

with tab2:
    st.subheader("Live ARR Trajectory")
    st.line_chart(phase2_df.set_index("month")[["live_arr", "cumulative_arr_booked"]])

    col1, col2, col3 = st.columns(3)
    col1.metric("Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
    col2.metric("Ending Deferred Revenue", f"${phase2_df['deferred_revenue_balance'].iloc[-1]:,.0f}")
    col3.metric("Ending Live Accounts", f"{int(phase2_df['live_accounts'].iloc[-1])}")

    st.subheader("Revenue Streams (Subscription vs. Professional Services)")
    st.bar_chart(phase2_df.set_index("month")[["subscription_revenue_recognized", "ps_fee_revenue_recognized"]])

    st.subheader("Full Revenue Recognition Table")
    st.dataframe(phase2_df, use_container_width=True)

with tab3:
    st.subheader("Renewal Cohort Summary")
    if len(renewals_df) > 0:
        summary = summarize_renewals(renewals_df)
        col1, col2, col3 = st.columns(3)
        col1.metric("Blended NRR", f"{summary['blended_nrr_pct']}%")
        col2.metric("Total Renewal Events", summary['total_renewal_events'])
        col3.metric("Total Expansion ARR", f"${summary['total_expansion_arr']:,.0f}")
        st.info(summary["nrr_benchmark_check"])
        st.dataframe(renewals_df, use_container_width=True)
    else:
        st.info("No renewal events occurred — scenario length may be shorter than the contract term.")

with tab4:
    st.subheader("Raw Phase 1 Output")
    st.dataframe(phase1_df, use_container_width=True)
    st.subheader("Raw Phase 2 Output")
    st.dataframe(phase2_df, use_container_width=True)
    st.subheader("Raw Renewal Events")
    st.dataframe(renewals_df, use_container_width=True)

st.caption("Built on the Bowtie Model (Winning by Design). All math is deterministic — no randomized variables anywhere in this model.")
