"""
Revenue Architecture — Phase 1 (v2): Dual-Constraint Pipeline & Capacity Engine
================================================================================

Left side of the Bowtie Model (Winning by Design / Jacco van der Kooij):
Awareness -> Education -> Selection -> Mutual Commit

v2 changes from the first pass, based on real critique:
1. Demand is no longer single-sourced from marketing MQLs. Pipeline now
   comes from three distinct, separately-modeled motions:
     - Marketing-sourced (lead -> MQL -> SQL)
     - BDR/SDR-sourced (outbound prospecting -> SQL directly)
     - AE self-sourced (reps prospecting their own patch)
2. BDRs are now a modeled role (meetings/SQL quota, ramp, comp) feeding
   SQLs into the AE pipeline — not just an assumed lead pool.
3. Every rep (AE and BDR) now carries real OTE and a quota:OTE ratio,
   so the engine outputs COST OF CAPACITY, not just capacity. This is
   the FP&A lens: what does it cost to unlock $X of bookings capacity,
   and is that ratio healthy vs. B2B SaaS benchmarks (4-6x quota:OTE).

Design principles (unchanged):
- Pure, deterministic math. No AI in this file.
- Every assumption is explicit in a dataclass, nothing hidden in formulas.
- Built standalone so it drops into a CLI, notebook, or Streamlit app.

Benchmark sources for defaults used below (2026 B2B SaaS): quota:OTE
4-6x standard; SDR:AE ratio 1.5:1-2:1; SDR OTE $75K-$120K on 65/35-70/30
mix; SDR productivity ~6 SQLs/mo median; mid-market AE quota $900K-$1.4M/yr,
OTE $160K-$220K, 50/50 mix.
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


# ---------------------------------------------------------------------------
# 1. SHARED: ramp curve (used by both AEs and BDRs)
# ---------------------------------------------------------------------------

@dataclass
class RampSchedule:
    """% of full quota a rep is capable of carrying, by month since hire.
    Default: standard 3-month linear ramp. Note: pay is NOT ramped in this
    model (reps get full base + draw/guarantee during ramp, which is
    standard practice) — only quota-carrying CAPACITY ramps."""
    monthly_productivity: list = field(default_factory=lambda: [0.33, 0.66, 1.0])

    def productivity_in_month(self, months_since_hire: int) -> float:
        if months_since_hire < 0:
            return 0.0
        if months_since_hire >= len(self.monthly_productivity):
            return 1.0
        return self.monthly_productivity[months_since_hire]


# ---------------------------------------------------------------------------
# 2. ROLE COMPENSATION — shared cost model for AE and BDR
# ---------------------------------------------------------------------------

@dataclass
class RoleComp:
    """
    Compensation structure for one rep. Quota:OTE ratio is computed, not
    assumed — so the model will actually tell you if an input scenario is
    unrealistic (e.g. ratio > 7x = under-paid/high-churn-risk per 2026
    benchmarks; < 4x = over-paid/margin-drag).
    """
    annual_base: float
    annual_variable_at_100pct: float   # variable pay at 100% quota attainment
    annual_quota: float                # $ bookings (AE) or SQLs/meetings (BDR)

    @property
    def annual_ote(self) -> float:
        return self.annual_base + self.annual_variable_at_100pct

    @property
    def quota_to_ote_ratio(self) -> float:
        return self.annual_quota / self.annual_ote if self.annual_ote else 0.0

    @property
    def monthly_base_cost(self) -> float:
        """Base salary is paid every month regardless of ramp/attainment."""
        return self.annual_base / 12

    def monthly_variable_cost(self, attainment_pct: float) -> float:
        """Variable pay this month, linear to attainment (no accelerators yet —
        that's a deliberate Phase 1 simplification, flagged for Phase 2)."""
        return (self.annual_variable_at_100pct / 12) * min(attainment_pct, 1.0)


# ---------------------------------------------------------------------------
# 3. BDR — generates SQLs (not $ bookings) that feed the AE pipeline
# ---------------------------------------------------------------------------

@dataclass
class BDR:
    name: str
    hire_month: int
    monthly_sql_quota: float          # SQLs this BDR is expected to produce
    comp: RoleComp
    ramp: RampSchedule = field(default_factory=RampSchedule)

    def effective_sqls(self, month: int) -> float:
        if month < self.hire_month:
            return 0.0
        productivity = self.ramp.productivity_in_month(month - self.hire_month)
        return self.monthly_sql_quota * productivity

    def monthly_cost(self, month: int) -> float:
        if month < self.hire_month:
            return 0.0
        attainment = self.ramp.productivity_in_month(month - self.hire_month)
        return self.comp.monthly_base_cost + self.comp.monthly_variable_cost(attainment)


# ---------------------------------------------------------------------------
# 4. AE — closes bookings; also self-sources a portion of own pipeline
# ---------------------------------------------------------------------------

@dataclass
class SalesRep:
    name: str
    hire_month: int
    comp: RoleComp                    # comp.annual_quota here = $ bookings quota
    self_sourced_sqls_per_month: float = 0.0   # SQLs this AE generates on their own
    ramp: RampSchedule = field(default_factory=RampSchedule)

    @property
    def monthly_quota(self) -> float:
        return self.comp.annual_quota / 12

    def effective_capacity(self, month: int) -> float:
        """$ bookings capacity this rep can carry this month."""
        if month < self.hire_month:
            return 0.0
        productivity = self.ramp.productivity_in_month(month - self.hire_month)
        return self.monthly_quota * productivity

    def effective_self_sourced_sqls(self, month: int) -> float:
        if month < self.hire_month:
            return 0.0
        productivity = self.ramp.productivity_in_month(month - self.hire_month)
        return self.self_sourced_sqls_per_month * productivity

    def monthly_cost(self, month: int, attainment_pct: float) -> float:
        if month < self.hire_month:
            return 0.0
        return self.comp.monthly_base_cost + self.comp.monthly_variable_cost(attainment_pct)


# ---------------------------------------------------------------------------
# 5. MARKETING FUNNEL — one of three demand channels, not the only one
# ---------------------------------------------------------------------------

@dataclass
class MarketingFunnel:
    monthly_leads: float
    lead_to_mql_rate: float
    mql_to_sql_rate: float

    def sqls_generated(self) -> float:
        return self.monthly_leads * self.lead_to_mql_rate * self.mql_to_sql_rate


# ---------------------------------------------------------------------------
# 6. SCENARIO INPUTS — the full shape, incl. per-channel win rates
# ---------------------------------------------------------------------------

@dataclass
class ScenarioInputs:
    scenario_name: str
    num_months: int
    reps: list                        # list[SalesRep]
    bdrs: list                        # list[BDR]
    marketing: MarketingFunnel
    avg_deal_size: float
    win_rate_marketing_sourced: float = 0.25
    win_rate_bdr_sourced: float = 0.20     # outbound typically converts lower
    win_rate_ae_self_sourced: float = 0.35  # warmest, highest-intent source
    pipeline_coverage_target: float = 3.5
    execution_efficiency: float = 1.0
    # Independent lever: even when demand + capacity theoretically support
    # a number, real execution (deal slippage, competitive losses, discounting,
    # forecast inflation, a rep having a bad quarter) can realize less than
    # that ceiling. 1.0 = perfect execution. 0.85 = reps realize 85% of what
    # the funnel/capacity math says is achievable. This is the dial a sales
    # leader or CFO plays with to stress-test "what if execution quality drops."
    seasonality_pattern: Optional[list] = None
    # Optional 12-value list of monthly multipliers (index 0 = the calendar
    # month at season_start_month_index, cycling every 12 months for longer
    # scenarios). E.g. a December slowdown: index for December = 0.7. Fully
    # explicit, user-set — no randomization. None = no seasonality (flat 1.0
    # every month), the default.
    season_start_month_index: int = 0
    # Which entry in seasonality_pattern corresponds to month 1 of the
    # scenario. E.g. if the scenario starts in April and seasonality_pattern
    # is indexed Jan=0..Dec=11, set this to 3 so month 1 of the scenario
    # correctly picks up April's multiplier.

    def __post_init__(self):
        if self.seasonality_pattern is not None and len(self.seasonality_pattern) != 12:
            raise ValueError(
                f"seasonality_pattern must have exactly 12 entries (one per calendar month), "
                f"got {len(self.seasonality_pattern)}."
            )


# ---------------------------------------------------------------------------
# 7. ENGINE
# ---------------------------------------------------------------------------

def run_scenario(inputs: ScenarioInputs) -> pd.DataFrame:
    rows = []

    for month in range(inputs.num_months):
        # --- Demand side: three channels, summed ---
        marketing_sqls = inputs.marketing.sqls_generated()
        bdr_sqls = sum(bdr.effective_sqls(month) for bdr in inputs.bdrs)
        ae_self_sourced_sqls = sum(rep.effective_self_sourced_sqls(month) for rep in inputs.reps)

        marketing_bookings = marketing_sqls * inputs.win_rate_marketing_sourced * inputs.avg_deal_size
        bdr_bookings = bdr_sqls * inputs.win_rate_bdr_sourced * inputs.avg_deal_size
        self_sourced_bookings = ae_self_sourced_sqls * inputs.win_rate_ae_self_sourced * inputs.avg_deal_size

        demand_constrained_bookings = marketing_bookings + bdr_bookings + self_sourced_bookings
        total_pipeline_created = (marketing_sqls + bdr_sqls + ae_self_sourced_sqls) * inputs.avg_deal_size

        # --- Capacity side ---
        capacity_constrained_bookings = sum(rep.effective_capacity(month) for rep in inputs.reps)

        # --- Dual constraint (theoretical ceiling) ---
        theoretical_bookings = min(capacity_constrained_bookings, demand_constrained_bookings)
        if capacity_constrained_bookings < demand_constrained_bookings:
            binding_constraint = "CAPACITY"
        elif demand_constrained_bookings < capacity_constrained_bookings:
            binding_constraint = "DEMAND"
        else:
            binding_constraint = "BALANCED"

        # --- Execution efficiency + seasonality: realized bookings vs. the
        # theoretical ceiling. Both are independent, deterministic, user-set
        # multipliers — never randomized. Capacity remains a HARD ceiling
        # regardless of either multiplier.
        if inputs.seasonality_pattern is not None:
            pattern_index = (month + inputs.season_start_month_index) % 12
            seasonal_multiplier = inputs.seasonality_pattern[pattern_index]
        else:
            seasonal_multiplier = 1.0

        actual_bookings = min(
            theoretical_bookings * inputs.execution_efficiency * seasonal_multiplier,
            capacity_constrained_bookings,
        )

        overall_attainment = (
            actual_bookings / capacity_constrained_bookings
            if capacity_constrained_bookings > 0 else 0.0
        )

        # --- Cost of capacity ---
        ae_cost = sum(rep.monthly_cost(month, overall_attainment) for rep in inputs.reps)
        bdr_cost = sum(bdr.monthly_cost(month) for bdr in inputs.bdrs)
        total_cost_of_capacity = ae_cost + bdr_cost

        cost_per_dollar_booked = (
            total_cost_of_capacity / actual_bookings if actual_bookings > 0 else None
        )

        active_aes = sum(1 for r in inputs.reps if r.hire_month <= month)
        active_bdrs = sum(1 for b in inputs.bdrs if b.hire_month <= month)

        coverage_ratio = (
            total_pipeline_created / actual_bookings if actual_bookings > 0 else None
        )

        rows.append({
            "month": month + 1,
            "active_aes": active_aes,
            "active_bdrs": active_bdrs,
            "sqls_marketing": round(marketing_sqls, 1),
            "sqls_bdr": round(bdr_sqls, 1),
            "sqls_ae_self_sourced": round(ae_self_sourced_sqls, 1),
            "capacity_constrained_bookings": round(capacity_constrained_bookings, 2),
            "demand_constrained_bookings": round(demand_constrained_bookings, 2),
            "theoretical_bookings": round(theoretical_bookings, 2),
            "execution_efficiency": inputs.execution_efficiency,
            "seasonal_multiplier": seasonal_multiplier,
            "actual_bookings": round(actual_bookings, 2),
            "overall_attainment_pct": round(overall_attainment * 100, 1),
            "binding_constraint": binding_constraint,
            "pipeline_coverage_ratio": round(coverage_ratio, 2) if coverage_ratio else None,
            "coverage_target": inputs.pipeline_coverage_target,
            "ae_cost": round(ae_cost, 2),
            "bdr_cost": round(bdr_cost, 2),
            "total_cost_of_capacity": round(total_cost_of_capacity, 2),
            "cost_per_dollar_booked": round(cost_per_dollar_booked, 3) if cost_per_dollar_booked else None,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 8. DIAGNOSTICS
# ---------------------------------------------------------------------------

def summarize(df: pd.DataFrame, inputs: ScenarioInputs) -> dict:
    if len(df) == 0:
        return {
            "total_bookings": 0.0,
            "total_cost_of_capacity": 0.0,
            "blended_cost_per_dollar_booked": None,
            "pct_months_capacity_bound": None,
            "pct_months_demand_bound": None,
            "ae_quota_to_ote_ratios": {},
            "bdr_cost_per_sql_produced": {},
            "bdr_to_ae_ratio": None,
            "bdr_to_ae_benchmark_check": "N/A — zero-month scenario",
            "hiring_signal": "N/A — zero-month scenario, nothing to diagnose",
        }

    capacity_bound = (df["binding_constraint"] == "CAPACITY").sum()
    demand_bound = (df["binding_constraint"] == "DEMAND").sum()
    total_months = len(df)

    ae_quota_to_ote = [round(r.comp.quota_to_ote_ratio, 2) for r in inputs.reps]

    def flag_ratio(r):
        if r > 7:
            return "UNDER-PAID / high churn risk (>7x)"
        if r < 4:
            return "OVER-PAID / margin drag (<4x)"
        return "healthy (4-6x band)"

    # BDR quota is in SQL units, not $ — quota:OTE (a $-to-$ ratio) doesn't
    # apply. The real BDR efficiency metric is cost per SQL produced.
    bdr_cost_per_sql = {}
    for b in inputs.bdrs:
        annual_sqls = b.monthly_sql_quota * 12
        bdr_cost_per_sql[b.name] = round(b.comp.annual_ote / annual_sqls, 2) if annual_sqls else None

    num_aes = len(inputs.reps)
    num_bdrs = len(inputs.bdrs)
    sdr_ae_ratio = round(num_bdrs / num_aes, 2) if num_aes else None

    return {
        "total_bookings": round(df["actual_bookings"].sum(), 2),
        "total_cost_of_capacity": round(df["total_cost_of_capacity"].sum(), 2),
        "blended_cost_per_dollar_booked": round(
            df["total_cost_of_capacity"].sum() / df["actual_bookings"].sum(), 3
        ) if df["actual_bookings"].sum() > 0 else None,
        "pct_months_capacity_bound": round(100 * capacity_bound / total_months, 1),
        "pct_months_demand_bound": round(100 * demand_bound / total_months, 1),
        "ae_quota_to_ote_ratios": {r.name: (ratio, flag_ratio(ratio))
                                    for r, ratio in zip(inputs.reps, ae_quota_to_ote)},
        "bdr_cost_per_sql_produced": bdr_cost_per_sql,
        "bdr_to_ae_ratio": sdr_ae_ratio,
        "bdr_to_ae_benchmark_check": (
            "N/A — no outbound motion in this pod (self-serve/PLG by design)" if num_bdrs == 0
            else "within 1.5-2x healthy band" if sdr_ae_ratio and 1.5 <= sdr_ae_ratio <= 2.0
            else "outside typical 1.5-2x band — review BDR staffing"
        ),
        "hiring_signal": (
            "Capacity is binding most months — hiring more AEs (or more BDRs "
            "to feed them) would likely grow bookings."
            if capacity_bound > total_months / 2
            else "Demand is binding most months — adding AEs won't help until "
                 "marketing/BDR pipeline generation improves."
        ),
    }


# ---------------------------------------------------------------------------
# 9. PODS — segment-based teams (SMB / Mid-Market / Enterprise / Inbound)
# ---------------------------------------------------------------------------
#
# Real GTM orgs don't run one flat team — segments have genuinely different
# economics (deal size, cycle length, BDR:AE staffing ratio). This layer
# wraps the core engine per-pod so num_aes / num_bdrs are simple dynamic
# variables you set per segment, and everything downstream (comp, quota,
# capacity, cost) is generated from those counts automatically.
#
# Simplification flagged: all reps within one pod share the same comp/quota
# template (e.g. every Enterprise AE has identical quota). Real orgs have
# rep-to-rep variance within a segment — that's a legitimate future
# refinement, not built here.

@dataclass
class PodConfig:
    pod_name: str                     # e.g. "Enterprise", "Mid-Market", "SMB", "Inbound"
    num_aes: int                      # dynamic variable — set per pod
    num_bdrs: int                     # dynamic variable — 0 for Inbound (self-serve/PLG, no outbound)
    ae_comp_template: RoleComp        # quota + OTE structure, shared by all AEs in this pod
    bdr_comp_template: Optional[RoleComp] = None   # None if num_bdrs == 0
    marketing: MarketingFunnel = None
    avg_deal_size: float = 0.0
    win_rate_marketing_sourced: float = 0.25
    win_rate_bdr_sourced: float = 0.20
    win_rate_ae_self_sourced: float = 0.35
    ae_self_sourced_sqls_per_month: float = 0.0
    pipeline_coverage_target: float = 3.5
    execution_efficiency: float = 1.0
    seasonality_pattern: Optional[list] = None   # 12 monthly multipliers, see ScenarioInputs
    season_start_month_index: int = 0
    ae_hire_months: Optional[list] = None   # override: e.g. [0,0,3] to stagger hires. None = auto-phased (see below).
    bdr_hire_months: Optional[list] = None
    hiring_cadence_months: int = 3          # if ae_hire_months not given, space hires this many months apart
                                             # (default: hire 1 rep every N months rather than all at once —
                                             # realistic for budget cycles / ramping a growing org)

    # --- Revenue recognition assumptions (Phase 2) ---
    # These live on PodConfig, not duplicated in the recognition engine's
    # bridge function, so Phase 1 and Phase 2 can never drift on what a
    # given pod's contracts actually look like.
    contract_term_months: int = 12          # typical subscription term for this segment
    implementation_lag_months: int = 2      # typical signed->live gap for this segment
                                             # (segments genuinely differ: Enterprise deals
                                             # take longer to implement than SMB/self-serve)
    professional_services_fee_pct_of_arr: float = 0.0
    # Implementation/onboarding fee, expressed as a % of the account's ARR
    # (not TCV — a one-time setup fee scales with account complexity/size,
    # not with how many years the subscription term happens to run).
    # e.g. 0.10 = a 10%-of-ARR one-time implementation fee. Default 0.0 —
    # explicitly opt in per pod, since not every segment charges one
    # (e.g. self-serve/Inbound typically doesn't).

    def __post_init__(self):
        if self.num_bdrs > 0 and self.bdr_comp_template is None:
            raise ValueError(f"Pod '{self.pod_name}' has {self.num_bdrs} BDRs but no bdr_comp_template.")

    def _phased_hire_months(self, count: int) -> list:
        """Default hiring plan: 1 hire every `hiring_cadence_months`, starting month 0.
        e.g. count=4, cadence=3 -> [0, 3, 6, 9]. Override with explicit hire_months for
        a custom plan (e.g. front-loaded, or tied to a specific fundraise/budget event)."""
        return [i * self.hiring_cadence_months for i in range(count)]

    def build_scenario(self, num_months: int) -> ScenarioInputs:
        ae_hires = self.ae_hire_months if self.ae_hire_months is not None else self._phased_hire_months(self.num_aes)
        bdr_hires = self.bdr_hire_months if self.bdr_hire_months is not None else self._phased_hire_months(self.num_bdrs)
        if len(ae_hires) != self.num_aes or len(bdr_hires) != self.num_bdrs:
            raise ValueError(f"Pod '{self.pod_name}': hire_months length must match num_aes/num_bdrs.")

        reps = [
            SalesRep(
                name=f"{self.pod_name}-AE-{i+1}",
                hire_month=ae_hires[i],
                comp=self.ae_comp_template,
                self_sourced_sqls_per_month=self.ae_self_sourced_sqls_per_month,
            )
            for i in range(self.num_aes)
        ]
        bdrs = [
            BDR(
                name=f"{self.pod_name}-BDR-{i+1}",
                hire_month=bdr_hires[i],
                monthly_sql_quota=self.bdr_comp_template.annual_quota / 12,
                comp=self.bdr_comp_template,
            )
            for i in range(self.num_bdrs)
        ]
        return ScenarioInputs(
            scenario_name=self.pod_name,
            num_months=num_months,
            reps=reps,
            bdrs=bdrs,
            marketing=self.marketing,
            avg_deal_size=self.avg_deal_size,
            win_rate_marketing_sourced=self.win_rate_marketing_sourced,
            win_rate_bdr_sourced=self.win_rate_bdr_sourced,
            win_rate_ae_self_sourced=self.win_rate_ae_self_sourced,
            pipeline_coverage_target=self.pipeline_coverage_target,
            execution_efficiency=self.execution_efficiency,
            seasonality_pattern=self.seasonality_pattern,
            season_start_month_index=self.season_start_month_index,
        )


def run_multi_pod_scenario(pods: list, num_months: int) -> dict:
    """
    Runs each pod through the existing single-pod engine independently,
    then rolls up into a combined company-level view. Returns a dict:
      { "by_pod": {pod_name: DataFrame}, "combined": DataFrame }
    """
    by_pod = {}
    for pod in pods:
        scenario = pod.build_scenario(num_months)
        by_pod[pod.pod_name] = run_scenario(scenario)

    combined_rows = []
    for month in range(num_months):
        row = {"month": month + 1}
        total_bookings = 0.0
        total_cost = 0.0
        for pod_name, df in by_pod.items():
            month_row = df[df["month"] == month + 1].iloc[0]
            row[f"{pod_name}_bookings"] = month_row["actual_bookings"]
            row[f"{pod_name}_cost"] = month_row["total_cost_of_capacity"]
            total_bookings += month_row["actual_bookings"]
            total_cost += month_row["total_cost_of_capacity"]
        row["total_bookings"] = round(total_bookings, 2)
        row["total_cost_of_capacity"] = round(total_cost, 2)
        row["blended_cost_per_dollar_booked"] = (
            round(total_cost / total_bookings, 3) if total_bookings > 0 else None
        )
        combined_rows.append(row)

    return {"by_pod": by_pod, "combined": pd.DataFrame(combined_rows)}


# ---------------------------------------------------------------------------
# 10. EXAMPLE RUN — mid-market SaaS benchmarks (2026)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ae_comp = lambda: RoleComp(annual_base=95_000, annual_variable_at_100pct=95_000, annual_quota=1_100_000)

    reps = [
        SalesRep(name="AE-1 (tenured)", hire_month=0, comp=ae_comp(), self_sourced_sqls_per_month=2),
        SalesRep(name="AE-2 (tenured)", hire_month=0, comp=ae_comp(), self_sourced_sqls_per_month=2),
        SalesRep(name="AE-3 (new hire)", hire_month=2, comp=ae_comp(), self_sourced_sqls_per_month=1),
    ]

    # BDR: $85K OTE (65/35 split), ~6 SQLs/month quota -> quota in SQL units, not $
    bdr_comp = lambda: RoleComp(annual_base=55_000, annual_variable_at_100pct=30_000, annual_quota=72)  # 6/mo * 12

    bdrs = [
        BDR(name="BDR-1", hire_month=0, monthly_sql_quota=6, comp=bdr_comp()),
        BDR(name="BDR-2", hire_month=0, monthly_sql_quota=6, comp=bdr_comp()),
    ]

    marketing = MarketingFunnel(monthly_leads=500, lead_to_mql_rate=0.30, mql_to_sql_rate=0.25)

    scenario = ScenarioInputs(
        scenario_name="Mid-market base case — 3 AEs, 2 BDRs, 500 leads/mo",
        num_months=12,
        reps=reps,
        bdrs=bdrs,
        marketing=marketing,
        avg_deal_size=18_000,
    )

    result = run_scenario(scenario)
    print(result.to_string(index=False))
    print("\n--- SUMMARY (execution_efficiency = 1.0) ---")
    for k, v in summarize(result, scenario).items():
        print(f"{k}: {v}")

    # -------------------------------------------------------------------
    # MULTI-POD EXAMPLE — SMB, Mid-Market, Enterprise, Inbound
    # num_aes / num_bdrs are the dynamic variables per pod, as requested.
    # -------------------------------------------------------------------
    print("\n\n=== MULTI-POD SCENARIO ===\n")

    smb_pod = PodConfig(
        pod_name="SMB",
        num_aes=4, num_bdrs=6,          # 1.5x BDR:AE, in the healthy band
        ae_comp_template=RoleComp(annual_base=60_000, annual_variable_at_100pct=60_000, annual_quota=650_000),
        bdr_comp_template=RoleComp(annual_base=50_000, annual_variable_at_100pct=25_000, annual_quota=96),  # 8/mo
        marketing=MarketingFunnel(monthly_leads=1200, lead_to_mql_rate=0.35, mql_to_sql_rate=0.30),
        avg_deal_size=6_000,
        win_rate_marketing_sourced=0.28, win_rate_bdr_sourced=0.22, win_rate_ae_self_sourced=0.30,
        ae_self_sourced_sqls_per_month=1,
    )

    midmarket_pod = PodConfig(
        pod_name="MidMarket",
        num_aes=3, num_bdrs=2,          # deliberately under 1.5x, to see the flag surface
        ae_comp_template=ae_comp(),
        bdr_comp_template=bdr_comp(),
        marketing=MarketingFunnel(monthly_leads=500, lead_to_mql_rate=0.30, mql_to_sql_rate=0.25),
        avg_deal_size=18_000,
        ae_self_sourced_sqls_per_month=2,
    )

    enterprise_pod = PodConfig(
        pod_name="Enterprise",
        num_aes=2, num_bdrs=3,          # 1.5x, healthy
        ae_comp_template=RoleComp(annual_base=140_000, annual_variable_at_100pct=140_000, annual_quota=1_700_000),
        bdr_comp_template=RoleComp(annual_base=65_000, annual_variable_at_100pct=35_000, annual_quota=48),  # 4/mo, harder outbound
        marketing=MarketingFunnel(monthly_leads=150, lead_to_mql_rate=0.25, mql_to_sql_rate=0.35),
        avg_deal_size=75_000,
        win_rate_marketing_sourced=0.20, win_rate_bdr_sourced=0.15, win_rate_ae_self_sourced=0.30,
        ae_self_sourced_sqls_per_month=1.5,
    )

    inbound_pod = PodConfig(
        pod_name="Inbound",
        num_aes=2, num_bdrs=0,          # self-serve/PLG — no outbound motion by definition
        ae_comp_template=RoleComp(annual_base=70_000, annual_variable_at_100pct=50_000, annual_quota=600_000),
        bdr_comp_template=None,
        marketing=MarketingFunnel(monthly_leads=2500, lead_to_mql_rate=0.45, mql_to_sql_rate=0.35),
        avg_deal_size=3_500,
        win_rate_marketing_sourced=0.32, win_rate_bdr_sourced=0.0, win_rate_ae_self_sourced=0.0,
        ae_self_sourced_sqls_per_month=0,
    )

    multi = run_multi_pod_scenario([smb_pod, midmarket_pod, enterprise_pod, inbound_pod], num_months=12)

    print(multi["combined"].to_string(index=False))

    print("\n--- PER-POD DIAGNOSTICS ---")
    for pod in [smb_pod, midmarket_pod, enterprise_pod, inbound_pod]:
        scenario_p = pod.build_scenario(12)
        df_p = multi["by_pod"][pod.pod_name]
        print(f"\n{pod.pod_name}:")
        for k, v in summarize(df_p, scenario_p).items():
            print(f"  {k}: {v}")
