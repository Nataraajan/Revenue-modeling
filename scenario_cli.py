"""
scenario_cli.py — CLI wrapper around the revenue model engine, designed to
be called by an external agent (OpenClaw, or anything else) with a
structured JSON config, not natural language.

Design principle (unchanged from the rest of this project): an LLM/agent
may interpret a plain-English request into JSON matching the schema below,
but it NEVER computes ARR/NRR/revenue itself — only this script's calls
into the existing, tested, deterministic engine modules do that.

Usage:
    python3 scenario_cli.py '{"pod_name": "Mid-Market", "num_aes": 5, ...}'
    python3 scenario_cli.py --file overrides.json
    python3 scenario_cli.py '{"pod_name": "Mid-Market", "num_aes": 5}' --base-preset Mid-Market

Any field omitted from the input JSON falls back to the named preset's
default (see app.py's _PRESET_DEFAULTS) or a hardcoded sane default if no
preset is given. This means a request like {"num_aes": 5} is valid and
only overrides that one field.

Output: a single JSON object to stdout with the key result metrics —
designed to be easy for an agent to parse and relay back in a chat message,
not a full dump of every monthly row.
"""

import sys
import json
import argparse

from capacity_engine import PodConfig, RoleComp, MarketingFunnel, run_scenario
from revenue_recognition_engine import bookings_to_contracts, BillingFrequency
from renewal_engine import RenewalAssumptions, run_full_lifecycle
from saas_metrics import aggregate_periods

# Mirrors app.py's _PRESET_DEFAULTS, kept in sync manually since this script
# is meant to run standalone (no Streamlit import needed). If you change
# presets in app.py, update this dict too.
PRESET_DEFAULTS = {
    "SMB": dict(
        num_existing_aes=0, num_existing_bdrs=0, num_aes=4, num_bdrs=6, hiring_cadence=2,
        ae_base=60000, ae_variable=60000, ae_quota=650000,
        bdr_base=50000, bdr_variable=25000, bdr_monthly_sql_quota=8,
        marketing_sqls=126.0, ae_self_sourced=1.0,  # was 1200 leads * 0.35 * 0.30
        avg_deal_size=6000, win_marketing=0.28, win_bdr=0.22, win_self=0.30,
        execution_efficiency=1.0, contract_term=12, implementation_lag=1, ps_fee_pct=0.0,
        churn_rate=0.15, expansion_rate=0.12, contraction_rate=0.04,
    ),
    "Mid-Market": dict(
        num_existing_aes=0, num_existing_bdrs=0, num_aes=3, num_bdrs=2, hiring_cadence=3,
        ae_base=95000, ae_variable=95000, ae_quota=1100000,
        bdr_base=55000, bdr_variable=30000, bdr_monthly_sql_quota=6,
        marketing_sqls=37.5, ae_self_sourced=2.0,  # was 500 leads * 0.30 * 0.25
        avg_deal_size=18000, win_marketing=0.25, win_bdr=0.20, win_self=0.35,
        execution_efficiency=1.0, contract_term=12, implementation_lag=2, ps_fee_pct=0.0,
        churn_rate=0.12, expansion_rate=0.18, contraction_rate=0.03,
    ),
    "Enterprise": dict(
        num_existing_aes=0, num_existing_bdrs=0, num_aes=2, num_bdrs=3, hiring_cadence=4,
        ae_base=140000, ae_variable=140000, ae_quota=1700000,
        bdr_base=65000, bdr_variable=35000, bdr_monthly_sql_quota=4,
        marketing_sqls=13.1, ae_self_sourced=1.5,  # was 150 leads * 0.25 * 0.35
        avg_deal_size=75000, win_marketing=0.20, win_bdr=0.15, win_self=0.30,
        execution_efficiency=1.0, contract_term=12, implementation_lag=4, ps_fee_pct=0.10,
        churn_rate=0.08, expansion_rate=0.20, contraction_rate=0.02,
    ),
    "Inbound": dict(
        num_existing_aes=0, num_existing_bdrs=0, num_aes=2, num_bdrs=0, hiring_cadence=3,
        ae_base=70000, ae_variable=50000, ae_quota=600000,
        bdr_base=55000, bdr_variable=30000, bdr_monthly_sql_quota=6,
        marketing_sqls=393.75, ae_self_sourced=0.0,  # was 2500 leads * 0.45 * 0.35
        avg_deal_size=3500, win_marketing=0.32, win_bdr=0.0, win_self=0.0,
        execution_efficiency=1.0, contract_term=12, implementation_lag=1, ps_fee_pct=0.0,
        churn_rate=0.18, expansion_rate=0.10, contraction_rate=0.05,
    ),
}


def run_from_overrides(overrides: dict, base_preset: str = "Mid-Market", num_months: int = 24) -> dict:
    """
    Builds a PodConfig from base_preset's defaults + any fields in `overrides`,
    runs the full three-phase engine, and returns a compact result summary.
    This is the ONLY place natural-language-derived input touches the model
    — as plain field overrides, never as a formula or a direct number the
    agent "computed" itself.
    """
    if base_preset not in PRESET_DEFAULTS:
        raise ValueError(f"Unknown base_preset '{base_preset}'. Choose from: {list(PRESET_DEFAULTS.keys())}")

    cfg = dict(PRESET_DEFAULTS[base_preset])
    cfg["pod_name"] = overrides.get("pod_name", base_preset)
    cfg["ae_hire_months"] = overrides.get("ae_hire_months")
    cfg["bdr_hire_months"] = overrides.get("bdr_hire_months")
    cfg["seasonality_pattern"] = overrides.get("seasonality_pattern")

    known_fields = set(cfg.keys()) | {"pod_name"}
    unknown_fields = set(overrides.keys()) - known_fields - {
        "ae_hire_months", "bdr_hire_months", "seasonality_pattern", "num_months",
    }
    if unknown_fields:
        raise ValueError(f"Unrecognized override field(s): {sorted(unknown_fields)}. "
                          f"Valid fields: {sorted(known_fields)}")

    for k, v in overrides.items():
        if k in cfg:
            cfg[k] = v

    num_months = overrides.get("num_months", num_months)

    pod = PodConfig(
        pod_name=cfg["pod_name"], num_aes=int(cfg["num_aes"]), num_bdrs=int(cfg["num_bdrs"]),
        num_existing_aes=int(cfg["num_existing_aes"]), num_existing_bdrs=int(cfg["num_existing_bdrs"]),
        ae_comp_template=RoleComp(annual_base=cfg["ae_base"], annual_variable_at_100pct=cfg["ae_variable"], annual_quota=cfg["ae_quota"]),
        bdr_comp_template=RoleComp(annual_base=cfg["bdr_base"], annual_variable_at_100pct=cfg["bdr_variable"],
                                    annual_quota=cfg["bdr_monthly_sql_quota"] * 12) if (cfg["num_bdrs"] > 0 or cfg["num_existing_bdrs"] > 0) else None,
        # Lead->MQL->SQL funnel mechanics deliberately not modeled — channel mix is
        # too company/product-specific to generalize honestly (see README). Flat
        # pass-through: leads=SQLs, both conversion rates=100%.
        marketing=MarketingFunnel(monthly_leads=cfg["marketing_sqls"], lead_to_mql_rate=1.0, mql_to_sql_rate=1.0),
        avg_deal_size=cfg["avg_deal_size"], win_rate_marketing_sourced=cfg["win_marketing"],
        win_rate_bdr_sourced=cfg["win_bdr"], win_rate_ae_self_sourced=cfg["win_self"],
        ae_self_sourced_sqls_per_month=cfg["ae_self_sourced"], execution_efficiency=cfg["execution_efficiency"],
        hiring_cadence_months=int(cfg["hiring_cadence"]), contract_term_months=int(cfg["contract_term"]),
        implementation_lag_months=int(cfg["implementation_lag"]), professional_services_fee_pct_of_arr=cfg["ps_fee_pct"],
        seasonality_pattern=cfg["seasonality_pattern"], ae_hire_months=cfg["ae_hire_months"], bdr_hire_months=cfg["bdr_hire_months"],
    )

    phase1_df = run_scenario(pod.build_scenario(num_months))
    initial_contracts = bookings_to_contracts(pod, phase1_df, billing_frequency=BillingFrequency.ANNUAL_UPFRONT)
    assumptions = {cfg["pod_name"]: RenewalAssumptions(
        pod_name=cfg["pod_name"], gross_revenue_churn_rate_annual=cfg["churn_rate"],
        expansion_rate_annual=cfg["expansion_rate"], contraction_rate_annual=cfg["contraction_rate"],
    )}
    all_contracts, renewals_df, phase2_df = run_full_lifecycle(initial_contracts, assumptions, num_months)
    annual = aggregate_periods(phase2_df, renewals_df, None, all_contracts, num_months,
                                period_months=12, gross_margin_pct=0.75)

    latest = annual.iloc[-1]
    return {
        "pod_name": cfg["pod_name"],
        "base_preset": base_preset,
        "overrides_applied": {k: v for k, v in overrides.items() if k in cfg},
        "num_months": num_months,
        "ending_arr": round(latest["ending_arr"], 2),
        "total_bookings": round(phase1_df["actual_bookings"].sum(), 2),
        "total_revenue_recognized": round(phase2_df["total_revenue_recognized"].sum(), 2),
        "nrr_pct_latest_year": latest["nrr_pct"],
        "gross_dollar_churn_rate_pct_latest_year": latest["gross_dollar_churn_rate_pct"],
        "total_cost_of_capacity": round(phase1_df["total_cost_of_capacity"].sum(), 2),
        "months_capacity_bound": int((phase1_df["binding_constraint"] == "CAPACITY").sum()),
        "months_demand_bound": int((phase1_df["binding_constraint"] == "DEMAND").sum()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a revenue model scenario from a JSON config override.")
    parser.add_argument("json_input", nargs="?", help="JSON string of field overrides, e.g. '{\"num_aes\": 5}'")
    parser.add_argument("--file", help="Path to a JSON file of overrides, instead of a literal argument")
    parser.add_argument("--base-preset", default="Mid-Market", choices=list(PRESET_DEFAULTS.keys()))
    parser.add_argument("--num-months", type=int, default=24)
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            overrides = json.load(f)
    elif args.json_input:
        overrides = json.loads(args.json_input)
    else:
        overrides = {}

    try:
        result = run_from_overrides(overrides, base_preset=args.base_preset, num_months=args.num_months)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        sys.exit(1)
