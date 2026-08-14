"""
Revenue Architecture Dashboard — Streamlit app
================================================
Single-scenario view, plus a Scenario A vs. B comparison mode with two
waterfall bridges (ARR and Revenue) explaining the gap between them.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from capacity_engine import PodConfig, RoleComp, MarketingFunnel, run_scenario
from revenue_recognition_engine import bookings_to_contracts, run_recognition, BillingFrequency
from renewal_engine import RenewalAssumptions, run_full_lifecycle, summarize_renewals
from existing_book_engine import load_customer_revenue_extract, derive_book_metrics, project_existing_book_runoff, derive_annual_history
from saas_metrics import aggregate_periods
from financial_model_export import generate_multi_pod_workbook_bytes

st.set_page_config(page_title="Revenue Architecture Model", layout="wide")

# Tighter number inputs — Streamlit stretches them to fill their column,
# which looks bulky once columns are wide (desktop, 4-6 per row). Caps
# width so short numbers don't sit in a lot of empty box.
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');


  /* Force all 6 top metric columns to stretch to equal height */
    div[data-testid="stHorizontalBlock"]:has(p:contains("Ending ARR")) {
        align-items: stretch !important;
    }
    
    div[data-testid="stHorizontalBlock"]:has(p:contains("Ending ARR")) > div[data-testid="stColumn"] {
        display: flex !important;
        flex-direction: column !important;
    }
    
    div[data-testid="stHorizontalBlock"]:has(p:contains("Ending ARR")) > div[data-testid="stColumn"] div[data-testid="stVerticalBlockBorderWrapper"] {
        flex: 1 !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
    }

    

    /* 2. Main Title (Responsive) */
    h1.main-title {
        color: #163A63 !important;
        font-weight: 700 !important;
        font-size: 28px !important;
        line-height: 1.15 !important;
        margin-bottom: 2px !important;
        padding-bottom: 0 !important;
    }
    @media (max-width: 768px) { h1.main-title { font-size: 22px !important; } }

    /* Header block vertical rhythm */
    .header-block { margin-bottom: 12px; padding-bottom: 12px; border-bottom: 2px solid #E2E8F0; }
    .header-block .tagline { color: #64748B; font-size: 13px; line-height: 1.4; margin: 0; }
    .dashboard-caption { font-size: 13px; color: #64748B; margin-top: 0 !important; margin-bottom: 4px !important; }
    .dashboard-heading { margin-top: 0 !important; margin-bottom: 2px !important; }

    /* 3. Input Controls (Clean workspace) */
    div[data-testid="stNumberInput"] input { max-width: 110px; }
    div[data-testid="stNumberInput"] { max-width: 150px; }
    div[data-testid="stSelectbox"] { max-width: 260px; }
    
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {
        border-radius: 8px !important;
        border-color: #E2E8F0 !important;
        background-color: #FFFFFF !important;
    }
    .stNumberInput label p, .stSelectbox label p, .stSlider label p {
        font-size: 12px !important;
        font-weight: 500 !important;
        color: #334155 !important;
    }
    .stSlider div[data-testid="stThumbValue"] { color: #163A63 !important; font-weight: 600; }
    
    /* 4. Action Buttons */
    button[kind="primary"] {
        background-color: #163A63 !important;
        color: white !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        border: none !important;
    }
    button[kind="secondary"] {
        background-color: #FFFFFF !important;
        color: #475569 !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }

    /* 5. Executive Dashboard KPI Cards */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        border-radius: 10px !important;
        padding: 16px 20px !important;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06) !important;
    }
    
    div[data-testid="stMetricLabel"] p {
        font-size: 12px !important;
        color: #64748B !important;
        font-weight: 500 !important;
        white-space: normal !important; 
        overflow: visible !important;
    }
    
    div[data-testid="stMetricValue"] {
        font-size: 26px !important;
        font-weight: 700 !important;
        color: #172033 !important;
        line-height: 1.2 !important;
        margin-top: 4px;
    }

    /* 6. KPI Delta Pills */
    div[data-testid="stMetricDelta"] svg { display: none; }
    div[data-testid="stMetricDelta"] {
        font-size: 12px !important;
        font-weight: 600 !important;
        padding: 2px 8px !important;
        border-radius: 6px !important;
        display: inline-flex !important;
        align-items: center !important;
        margin-top: 8px !important;
        width: fit-content;
    }
    /* Green = Positive */
    div[data-testid="stMetricDelta"]:has(div:contains("▲")), 
    div[data-testid="stMetricDelta"][style*="color: rgb(9, 171, 59)"] {
        background-color: #ECFDF3 !important; color: #16A34A !important;
    }
    /* Red = Negative */
    div[data-testid="stMetricDelta"]:has(div:contains("▼")), 
    div[data-testid="stMetricDelta"][style*="color: rgb(255, 43, 43)"] {
        background-color: #FEF2F2 !important; color: #DC2626 !important;
    }

    /* 7. Semantic Chart Colors via CSS */
    div[data-testid="column"]:nth-child(1) div[data-testid="stMetric"] svg { filter: hue-rotate(240deg) saturate(150%) brightness(0.8); } /* Green (ARR) */
    div[data-testid="column"]:nth-child(2) div[data-testid="stMetric"] svg { filter: hue-rotate(100deg); } /* Blue (Rev) */
    div[data-testid="column"]:nth-child(3) div[data-testid="stMetric"] svg { filter: hue-rotate(150deg); } /* Purple (NRR) */
    div[data-testid="column"]:nth-child(4) div[data-testid="stMetric"] svg { filter: grayscale(100%) sepia(100%) hue-rotate(340deg) saturate(300%) brightness(0.9); } /* Orange (Accts) */
    div[data-testid="column"]:nth-child(5) div[data-testid="stMetric"] svg { filter: hue-rotate(60deg) saturate(200%); }  /* Teal (DefRev) */
    div[data-testid="column"]:nth-child(6) div[data-testid="stMetric"] svg { filter: grayscale(100%) brightness(40%) sepia(100%) hue-rotate(-50deg) saturate(600%) contrast(0.8); } /* Red (Cost) */

    /* 8. Tabs */
    button[data-baseweb="tab"] { color: #475569 !important; font-weight: 500 !important; }
    button[data-baseweb="tab"][aria-selected="true"] { 
        color: #163A63 !important; 
        font-weight: 600 !important; 
        border-bottom: 2px solid #163A63 !important; 
    }
    
    /* 9. Segmented Control & Callouts */
    div[data-testid="stSegmentedControl"] label { border-color: #CBD5E1 !important; color: #475569 !important; }
    div[data-testid="stSegmentedControl"] label[data-checked="true"] { background-color: #EFF6FF !important; border-color: #163A63 !important; color: #163A63 !important; font-weight: 600 !important; }
    
    /* Info Box styling */
    div[data-testid="stAlert"] { background-color: #EFF6FF !important; border: 1px solid #DBEAFE !important; border-radius: 8px !important; color: #475569 !important; }
    
    /* Advanced Expander */
    .streamlit-expanderHeader { font-weight: 600 !important; color: #172033 !important; background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 8px;}
    
    /* Market Chips */
    span[data-baseweb="tag"] { background-color: #163A63 !important; color: white !important; opacity: 0.9;}

    /* 10. Bold dataframe headers (Glide Data Grid renders via canvas,
       so Styler.set_table_styles is ignored — these CSS variables are
       the only lever available for header font weight/color.) */
    .stDataFrameGlideDataEditor {
        --gdg-header-font-style: 700 14px !important;
        --gdg-text-header: rgba(26, 34, 51, 0.9) !important;
    }

    /* 11. Sidebar tweaks */
    section[data-testid="stSidebar"] .block-container { padding-top: 1rem; }

    /* 12. Reduce top whitespace in main content */
    .stMainBlockContainer { padding-top: 1rem !important; }
    header[data-testid="stHeader"] { height: auto !important; }

</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar width presets (Narrow / Normal / Wide)
# ---------------------------------------------------------------------------
_SIDEBAR_WIDTHS = [260, 340, 480]
_SIDEBAR_LABELS = ["Narrow", "Normal", "Wide"]

if "sidebar_width_step" not in st.session_state:
    st.session_state.sidebar_width_step = 1

_sw = _SIDEBAR_WIDTHS[st.session_state.sidebar_width_step]
st.markdown(
    f"<style>section.stSidebar {{ min-width: {_sw}px !important; max-width: {_sw}px !important; width: {_sw}px !important; }}</style>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# State management — Set Default / Undo / Reset
# ---------------------------------------------------------------------------
_MAX_HISTORY = 50

def _is_resettable_key(k: str) -> bool:
    if k.startswith("sm_"):
        return False
    reset_prefixes = ("s_", "a_", "b_", "smb_", "mm_", "ent_", "inb_", "fc_")
    reset_exact = {"scenario_a_label", "scenario_b_label"}
    return k.startswith(reset_prefixes) or k in reset_exact or k.endswith("_applied_preset")

def _snapshot() -> dict:
    return {k: v for k, v in st.session_state.items() if _is_resettable_key(k)}

def _restore(snapshot: dict):
    for k in list(st.session_state.keys()):
        if _is_resettable_key(k):
            del st.session_state[k]
    for k, v in snapshot.items():
        st.session_state[k] = v

def push_state():
    """Push current assumption state onto the undo history stack.
    Call this before applying any programmatic change (AI assistant, etc.)."""
    snap = _snapshot()
    history = st.session_state.get("sm_history", [])
    history.append(snap)
    if len(history) > _MAX_HISTORY:
        history = history[-_MAX_HISTORY:]
    st.session_state["sm_history"] = history
    st.session_state["sm_last_known"] = snap

if "sm_history" not in st.session_state:
    st.session_state["sm_history"] = []
if "sm_default" not in st.session_state:
    st.session_state["sm_default"] = None
if "sm_last_known" not in st.session_state:
    st.session_state["sm_last_known"] = None

if not st.session_state.get("sm_skip_push"):
    current = _snapshot()
    last = st.session_state["sm_last_known"]
    if last is not None and current != last:
        history = st.session_state["sm_history"]
        history.append(last)
        if len(history) > _MAX_HISTORY:
            history = history[-_MAX_HISTORY:]
        st.session_state["sm_history"] = history
    if current:
        st.session_state["sm_last_known"] = current
else:
    st.session_state["sm_skip_push"] = False
    st.session_state["sm_last_known"] = _snapshot()

# ---------------------------------------------------------------------------
# AI ASSISTANT — Claude Haiku chat via FAB (floating action button)
# ---------------------------------------------------------------------------
_HAS_API_KEY = False
try:
    _api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    if _api_key:
        _HAS_API_KEY = True
except Exception:
    _api_key = ""


def _render_ai_fab():
    """Render a fixed-position FAB that opens the AI chat popover."""
    st.markdown("""
    <style>
    /* ── AI FAB: fix the popover's layout wrapper to bottom-right ── */
    /* The stLayoutWrapper parent must be fixed so its child popover
       leaves normal document flow entirely. */
    div[data-testid="stVerticalBlock"] > div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stPopover"]) {
        position: fixed !important;
        bottom: 24px !important;
        right: 24px !important;
        z-index: 999 !important;
        width: auto !important;
        height: auto !important;
    }
    /* Circular button — filled navy, white icon, no caret */
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] {
        width: 56px !important;
        height: 56px !important;
        border-radius: 50% !important;
        background: #163A63 !important;
        color: #fff !important;
        border: none !important;
        font-size: 24px !important;
        padding: 0 !important;
        min-height: 0 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: 0 4px 14px rgba(22, 58, 99, 0.35) !important;
        cursor: pointer !important;
    }
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"]:hover {
        background: #1e4d7a !important;
        box-shadow: 0 6px 20px rgba(22, 58, 99, 0.5) !important;
    }
    /* Hide the dropdown caret icon inside the popover button */
    div[data-testid="stPopover"] button[data-testid="stPopoverButton"] span[data-testid="stIconMaterial"] {
        display: none !important;
    }
    /* Hide the tooltip wrapper's flex layout that adds spacing */
    div[data-testid="stPopover"] span[data-testid="stTooltipHoverTarget"] {
        display: contents !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with st.popover("✦", use_container_width=False, help="Chat with AI assistant"):
        st.markdown(
            '<p style="font-weight: 600; font-size: 15px; color: #1E293B; margin-bottom: 8px;">'
            '🤖 AI Assistant</p>',
            unsafe_allow_html=True,
        )
        if not _HAS_API_KEY:
            st.caption(
                "Add `ANTHROPIC_API_KEY` in Streamlit Secrets to enable. "
                "Uses Claude Haiku for what-if questions about your model."
            )
        else:
            import anthropic

            if "ai_messages" not in st.session_state:
                st.session_state.ai_messages = []

            def _build_system_prompt() -> str:
                snap = _snapshot()
                lines = ["You are a concise SaaS revenue modeling assistant embedded in a B2B revenue architecture dashboard.",
                         "The model is deterministic — capacity-constrained pipeline × win rates × contract terms → bookings → ratable revenue recognition → renewals/NRR.",
                         "Answer what-if questions about the user's current assumptions and outputs. Be specific, reference numbers, and keep answers under 150 words.",
                         "", "CURRENT ASSUMPTIONS:"]
                for k, v in sorted(snap.items()):
                    lines.append(f"  {k}: {v}")
                return "\n".join(lines)

            if not st.session_state.ai_messages:
                st.caption("Ask what-if questions about your revenue model.")

            for msg in st.session_state.ai_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if prompt := st.chat_input("Ask about your model…", key="ai_chat_input"):
                st.session_state.ai_messages.append({"role": "user", "content": prompt})

                client = anthropic.Anthropic(api_key=_api_key)
                api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.ai_messages]

                try:
                    with st.spinner("Thinking…"):
                        response = client.messages.create(
                            model="claude-haiku-4-5-20251001",
                            max_tokens=512,
                            system=_build_system_prompt(),
                            messages=api_messages,
                        )
                    assistant_text = response.content[0].text
                except Exception as e:
                    assistant_text = f"⚠️ API error: {e}"

                st.session_state.ai_messages.append({"role": "assistant", "content": assistant_text})
                st.rerun()


# ---------------------------------------------------------------------------
# Header — title + state buttons + Export
# ---------------------------------------------------------------------------
_hdr_left, _hdr_right = st.columns([4, 1], vertical_alignment="bottom")
with _hdr_left:
    st.markdown(
        '<div class="header-block">'
        '<h1 class="main-title">Revenue Architecture Model</h1>'
        '<p class="tagline">Pipeline, recognition & renewal model for B2B SaaS. '
        'Adjust segment assumptions in the sidebar.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
with _hdr_right:
    _b1, _b2, _b3 = st.columns(3, vertical_alignment="center")
    with _b1:
        if st.button("📌", key="sm_btn_default", type="tertiary",
                      help="Set current assumptions as default"):
            st.session_state["sm_default"] = _snapshot()
            st.toast("Current assumptions saved as default.")
    with _b2:
        has_history = bool(st.session_state.get("sm_history"))
        if st.button("↩", key="sm_btn_undo", type="tertiary",
                      disabled=not has_history, help="Undo last change"):
            history = st.session_state["sm_history"]
            if history:
                prev = history.pop()
                st.session_state["sm_skip_push"] = True
                _restore(prev)
                st.rerun()
    with _b3:
        has_default = st.session_state.get("sm_default") is not None
        reset_help = "Reset to saved default" if has_default else "Reset all assumptions"
        if st.button("⟲", key="sm_btn_reset", type="tertiary", help=reset_help):
            st.session_state["sm_skip_push"] = True
            if has_default:
                _restore(st.session_state["sm_default"])
            else:
                for k in list(st.session_state.keys()):
                    if _is_resettable_key(k):
                        del st.session_state[k]
            st.session_state["sm_history"] = []
            st.rerun()


# ---------------------------------------------------------------------------
# Reusable: transpose a df for display so months run left-to-right as
# columns, metrics as rows — matches how finance models are normally read,
# instead of the long/tidy format the engines compute in.
# ---------------------------------------------------------------------------
def wide(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0 or "month" not in df.columns:
        return df
    transposed = df.set_index("month").T
    transposed.columns = [f"M{c}" for c in transposed.columns]
    return transposed


# ---------------------------------------------------------------------------
# Formatting layer — every metric across every engine's output, mapped to
# how it should actually display (currency, percent, ratio/multiplier,
# or count). Applied to WIDE-format tables (metrics as rows) after
# transposing, so each row gets one consistent format across all its
# period columns. Unlisted fields (e.g. free-text like binding_constraint,
# pod_name) pass through as plain strings.
# ---------------------------------------------------------------------------
_CURRENCY_FIELDS = {
    "capacity_constrained_bookings", "demand_constrained_bookings", "theoretical_bookings", "actual_bookings",
    "ae_cost", "bdr_cost", "total_cost_of_capacity", "new_bookings_tcv", "new_arr_booked", "new_arr_live", "arpa_new_accounts",
    "cumulative_arr_booked", "blended_arpa_booked", "live_arr", "blended_arpa_live", "subscription_billings",
    "subscription_revenue_recognized", "ps_fee_billings", "ps_fee_revenue_recognized", "total_billings",
    "total_revenue_recognized", "cumulative_billings", "cumulative_revenue_recognized", "deferred_revenue_balance",
    "implementation_backlog_value", "arr_up_for_renewal", "churned_arr", "expansion_arr", "contraction_arr",
    "renewed_arr", "existing_book_arr", "existing_book_monthly_revenue", "existing_book_churn_dollar",
    "existing_book_expansion_dollar", "existing_book_contraction_dollar", "new_business_live_arr", "total_arr",
    "beginning_arr", "ending_arr", "revenue", "arpa_ending", "ltv", "other_boundary_effect",
}
_CURRENCY_PRECISE_FIELDS = {"cost_per_dollar_booked"}  # small $-per-$ figures, needs decimals not rounding to whole $
_PERCENT_FIELDS = {
    "overall_attainment_pct", "churn_rate_applied_pct", "nrr_this_cohort_pct", "nrr_pct",
    "gross_dollar_churn_rate_pct", "logo_churn_rate_pct",
}
_RATIO_FIELDS = {"execution_efficiency", "seasonal_multiplier", "pipeline_coverage_ratio", "coverage_target"}
_COUNT_FIELDS = {
    "active_aes", "active_bdrs", "new_accounts_signed", "cumulative_accounts_signed", "live_accounts",
    "implementation_backlog_count", "logos_up_for_renewal", "month", "customers_matched", "customers_churned",
    "base_logo_count",
}
_COUNT_DECIMAL_FIELDS = {  # counts that are legitimately fractional ("expected value", not a literal integer)
    "logos_retained_expected", "existing_book_logo_count", "existing_book_logos_churned", "beginning_logos",
    "ending_logos", "new_logos", "churned_logos", "sqls_marketing", "sqls_bdr", "sqls_ae_self_sourced",
}


def _format_cell(value, field_name: str) -> str:
    if pd.isna(value):
        return "—"
    if field_name in _CURRENCY_FIELDS:
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:,.1f}M"
        elif abs(value) >= 1_000:
            return f"${value / 1_000:,.1f}K"
        return f"${value:,.0f}"
    if field_name in _CURRENCY_PRECISE_FIELDS:
        return f"${value:,.3f}"
    if field_name in _PERCENT_FIELDS:
        return f"{value:.1f}%"
    if field_name in _RATIO_FIELDS:
        return f"{value:.2f}x"
    if field_name in _COUNT_FIELDS:
        return f"{value:,.0f}"
    if field_name in _COUNT_DECIMAL_FIELDS:
        return f"{value:,.1f}"
    return str(value)


_LABELS = {
    "month": "Month", "period": "Period",
    "active_aes": "Active AEs", "active_bdrs": "Active BDRs",
    "sqls_marketing": "SQLs — Marketing", "sqls_bdr": "SQLs — BDR", "sqls_ae_self_sourced": "SQLs — AE Self-Sourced",
    "capacity_constrained_bookings": "Capacity-Constrained Bookings (TCV)", "demand_constrained_bookings": "Demand-Constrained Bookings (TCV)",
    "theoretical_bookings": "Theoretical Bookings (TCV)", "execution_efficiency": "Execution Efficiency",
    "seasonal_multiplier": "Seasonal Multiplier", "actual_bookings": "Actual Bookings (TCV)",
    "overall_attainment_pct": "Attainment", "binding_constraint": "Binding Constraint",
    "pipeline_coverage_ratio": "Pipeline Coverage", "coverage_target": "Coverage Target",
    "ae_cost": "AE Cost", "bdr_cost": "BDR Cost", "total_cost_of_capacity": "Total Cost of Capacity",
    "cost_per_dollar_booked": "Cost per $ Booked",
    "new_bookings_tcv": "New Bookings (TCV)", "new_accounts_signed": "New Accounts Signed",
    # "new_arr_booked" is genuinely signed-date-based here (Phase 2 output —
    # revenue_recognition_engine.py, c.signed_month == month). The SAME field
    # name is reused in saas_metrics.py's annual/quarterly rollup for a
    # go-live-date-based figure instead — a real naming collision across two
    # dataframes. That one is renamed to "new_arr_live" locally in app.py
    # (see aggregate_periods() call sites) precisely so it doesn't share this
    # label and get misread as booking-date-based.
    "new_arr_booked": "New ARR Booked (Signed)", "new_arr_live": "New ARR (Went Live)",
    "arpa_new_accounts": "ARPA — New Accounts",
    "cumulative_accounts_signed": "Cumulative Accounts Signed", "cumulative_arr_booked": "Cumulative ARR Booked",
    "blended_arpa_booked": "Blended ARPA — Booked", "live_accounts": "Live Accounts", "live_arr": "Live ARR",
    "blended_arpa_live": "ARPA (Live)", "subscription_billings": "Subscription Billings",
    "subscription_revenue_recognized": "Subscription Revenue Recognized", "ps_fee_billings": "PS Fee Billings",
    "ps_fee_revenue_recognized": "PS Fee Revenue Recognized", "total_billings": "Total Billings",
    "total_revenue_recognized": "Total Revenue Recognized", "cumulative_billings": "Cumulative Billings",
    "cumulative_revenue_recognized": "Cumulative Revenue Recognized", "deferred_revenue_balance": "Deferred Revenue",
    "implementation_backlog_value": "Implementation Backlog ($)", "implementation_backlog_count": "Implementation Backlog (#)",
    "pod_name": "Pod", "logos_up_for_renewal": "Logos Up for Renewal", "arr_up_for_renewal": "ARR Up for Renewal",
    "churn_rate_applied_pct": "Churn Rate Applied", "churned_arr": "Churned ARR", "expansion_arr": "Expansion ARR",
    "contraction_arr": "Contraction ARR", "renewed_arr": "Renewed ARR", "logos_retained_expected": "Logos Retained (Expected)",
    "nrr_this_cohort_pct": "NRR — This Cohort",
    "existing_book_arr": "Existing Book ARR", "new_business_live_arr": "New Business ARR (Live)", "total_arr": "Total ARR",
    "existing_book_monthly_revenue": "Existing Book Revenue", "existing_book_churn_dollar": "Existing Book Churn ($)",
    "existing_book_expansion_dollar": "Existing Book Expansion ($)", "existing_book_contraction_dollar": "Existing Book Contraction ($)",
    "existing_book_logo_count": "Existing Book Customers", "existing_book_logos_churned": "Existing Book Customers Churned",
    "beginning_arr": "Beginning ARR", "ending_arr": "Ending ARR", "nrr_pct": "Net Revenue Retention (NRR)",
    "gross_dollar_churn_rate_pct": "Gross $ Churn Rate", "beginning_logos": "Beginning Customers",
    "ending_logos": "Ending Customers", "new_logos": "New Customers", "churned_logos": "Churned Customers",
    "logo_churn_rate_pct": "Logo Churn Rate", "revenue": "Recognized Revenue", "arpa_ending": "ARPA",
    "ltv": "Customer LTV", "other_boundary_effect": "Other / Boundary Effect",
}


def _relabel(name: str) -> str:
    return _LABELS.get(name, name.replace("_", " ").title())


def style_wide(df: pd.DataFrame, relabel: bool = True) -> pd.DataFrame:
    """Applies proper per-metric formatting to a WIDE table (metrics as rows,
    periods as columns) — the shape produced by wide() or .set_index('period').T."""
    if len(df) == 0:
        return df
    formatted = df.copy().astype(object)
    for row_label in formatted.index:
        formatted.loc[row_label] = formatted.loc[row_label].apply(lambda v: _format_cell(v, row_label))
    if relabel:
        formatted.index = [_relabel(name) for name in formatted.index]
    return formatted


def _bold_headers(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """Returns a Styler with bold row and column headers for st.dataframe()."""
    return df.style.set_table_styles([
        {"selector": "th", "props": [("font-weight", "700")]},
        {"selector": "th.row_heading", "props": [("font-weight", "700")]},
    ])


# ---------------------------------------------------------------------------
# Sidebar input renderer — used for both single-scenario mode and each side
# of a comparison. `key` namespaces every widget so two instances can run
# side by side without Streamlit key collisions.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Segment presets — each one actually differs on the underlying economics,
# not just the label. Field names match the widget key suffixes used below
# exactly, so they can be injected straight into session_state.
# ---------------------------------------------------------------------------
_PRESET_DEFAULTS = {
    "SMB": dict(
        existing_aes=0, existing_bdrs=0, num_aes=4, num_bdrs=6, cadence=2,
        ae_quota_m=0.65, bdr_sql=8,
        marketing_sqls=126.0, selfsrc=1.0,  # was leads=1200*0.35*0.30 — preserved effective SQL output
        deal=6000, wm=0.28, wb=0.22, ws=0.30,
        term=12, lag=1, psfee=0.0, churn=0.15, exp=0.12, contr=0.04,
    ),
    "Mid-Market": dict(
        existing_aes=0, existing_bdrs=0, num_aes=3, num_bdrs=2, cadence=3,
        ae_quota_m=1.1, bdr_sql=6,
        marketing_sqls=37.5, selfsrc=2.0,  # was leads=500*0.30*0.25
        deal=18000, wm=0.25, wb=0.20, ws=0.35,
        term=12, lag=2, psfee=0.0, churn=0.12, exp=0.18, contr=0.03,
    ),
    "Enterprise": dict(
        existing_aes=0, existing_bdrs=0, num_aes=2, num_bdrs=3, cadence=4,
        ae_quota_m=1.7, bdr_sql=4,
        marketing_sqls=13.1, selfsrc=1.5,  # was leads=150*0.25*0.35
        deal=75000, wm=0.20, wb=0.15, ws=0.30,
        term=12, lag=4, psfee=0.10, churn=0.08, exp=0.20, contr=0.02,
    ),
    "Inbound": dict(
        existing_aes=0, existing_bdrs=0, num_aes=2, num_bdrs=0, cadence=3,
        ae_quota_m=0.6, bdr_sql=6,  # bdr_sql unused — 0 BDRs on this segment
        marketing_sqls=393.75, selfsrc=0.0,  # was leads=2500*0.45*0.35
        deal=3500, wm=0.32, wb=0.0, ws=0.0,
        term=12, lag=1, psfee=0.0, churn=0.18, exp=0.10, contr=0.05,
    ),
}
# Comp (ae_base/ae_var/bdr_base/bdr_var) intentionally not in presets — it now
# lives in the Advanced section with a smart default derived from quota,
# consistent with keeping comp detail out of the headline assumptions.


def render_inputs(key: str, label: str, num_months_default: int = 24, show_gross_margin: bool = False,
                   fixed_segment: str = None, show_horizon: bool = True) -> dict:
    st.subheader(label)

    if fixed_segment is not None:
        # Full Company mode: segment is fixed to this box (no dropdown), and
        # horizon/gross margin are shared top-level controls collected once,
        # outside this function — so this box skips that whole top row.
        pod_preset = fixed_segment
        gross_margin_pct = None
        num_months = num_months_default
    else:
        top1, top2, top3 = st.columns(3)
        if show_gross_margin:
            gross_margin_pct = top3.number_input("Gross margin %", 0.0, 1.0, 0.75, step=0.01, key=f"{key}_gm",
                                                  help="Used for LTV. Blended gross margin on subscription revenue. Used only in the LTV formula: LTV = ARPA × Gross Margin ÷ Annual Churn Rate.")
        else:
            gross_margin_pct = None
        pod_preset = top1.selectbox(
            "Segment", ["SMB", "Mid-Market", "Enterprise", "Inbound", "Other (custom)"],
            index=1, key=f"{key}_pod_preset",
            help="Loads a starting set of assumptions for that segment (team size, deal size, win rates, renewal rates). Every field below is still editable after — this just sets sensible defaults.",
        )
        if show_horizon:
            num_months = top2.number_input("Horizon (months)", 6, 48, num_months_default, key=f"{key}_num_months",
                                            help="How many months forward the model projects, starting from month 1 of new bookings.")
        else:
            num_months = num_months_default

    # Detect a preset CHANGE and inject its defaults into session_state
    # *before* the affected widgets are created below — Streamlit widgets
    # read their initial value from session_state if already set, ignoring
    # the value= parameter in code once a key has been touched.
    prev_key = f"{key}_applied_preset"
    if st.session_state.get(prev_key) != pod_preset and pod_preset in _PRESET_DEFAULTS:
        for suffix, val in _PRESET_DEFAULTS[pod_preset].items():
            st.session_state[f"{key}_{suffix}"] = val
        st.session_state[prev_key] = pod_preset

    if pod_preset == "Other (custom)":
        pod_name = st.text_input("Custom segment name", "MidMarket", key=f"{key}_pod_name_custom",
                                  help="Just a label — doesn't affect any of the math.")
    else:
        pod_name = pod_preset

    # --- Horizontal assumptions grid — headline inputs only. Matches how a
    # real financial model keeps assumptions in one visible band (top row
    # or frozen pane), not buried in a long vertical sidebar. Secondary/
    # detail inputs (comp breakdown, hiring cadence, seasonality) live in
    # the collapsed "Advanced" section below, the same way a real model
    # keeps headcount/comp detail on its own separate sheet. ---
    st.caption("Team & Quota")
    tq1, tq2 = st.columns(2)
    num_existing_aes = tq1.number_input("Existing AEs", 0, 100, 0, key=f"{key}_existing_aes",
                                        help="Already on the team — fully productive from month 1, no ramp-up period.")
    num_aes = tq2.number_input("New AEs", 0, 50, 3, key=f"{key}_num_aes",
                               help="New hires — ramp up over 3 months (33%/66%/100% of full quota-carrying capacity), phased in per the hiring cadence set in Advanced.")
    tq3, tq4 = st.columns(2)
    num_existing_bdrs = tq3.number_input("Existing BDRs", 0, 100, 0, key=f"{key}_existing_bdrs",
                                         help="Already on the team — fully productive from month 1.")
    num_bdrs = tq4.number_input("New BDRs", 0, 50, 2, key=f"{key}_num_bdrs",
                                help="New hires — same 3-month ramp as new AEs.")
    tq5, tq6 = st.columns(2)
    ae_quota_millions = tq5.number_input("AE quota ($M)", 0.0, 10.0, 1.1, step=0.1, key=f"{key}_ae_quota_m",
                                         help="Annual bookings quota per fully-ramped AE, in TCV (Total Contract Value) — the same unit as Avg Deal Size, not ARR. Only equals an ARR quota when the contract term is 12 months. Sets the hard capacity ceiling on how much this team can close, and drives the default comp split in Advanced (5.5x quota:OTE).")
    bdr_sql = tq6.number_input("BDR SQLs/mo", 0, 50, 6, key=f"{key}_bdr_sql",
                               help="SQLs (sales-qualified leads) each fully-ramped BDR produces per month, feeding the AE pipeline.")
    tq7, tq8 = st.columns(2)
    marketing_sqls = tq7.number_input("Mktg SQLs/mo", 0.0, 500.0, 12.0, key=f"{key}_marketing_sqls",
                                      help="Marketing/inbound-sourced SQLs per month — a flat number, not a lead→MQL→SQL funnel. Channel mix (content, paid, partnerships) is too company-specific to model generically; see README.")
    ae_self_sourced = tq8.number_input("AE self-src/mo", 0.0, 20.0, 2.0, step=1.0, key=f"{key}_selfsrc",
                                       help="SQLs each AE generates on their own (existing network, outbound), on top of what BDRs and marketing feed them.")

    st.caption("Deal Economics & Win Rates")
    de1, de2 = st.columns(2)
    avg_deal_size = de1.number_input("Avg deal size — TCV ($)", 0, 5_000_000, 18_000, step=1000, key=f"{key}_deal",
                                     help="Average Total Contract Value per deal — the full value over the entire contract term, not annualized. Used to convert monthly bookings $ into individual synthetic contracts.")
    win_marketing = de2.slider("Win % — marketing", 0.0, 1.0, 0.25, key=f"{key}_wm",
                               help="% of marketing-sourced SQLs that close as won deals.")
    de3, de4 = st.columns(2)
    win_bdr = de3.slider("Win % — BDR", 0.0, 1.0, 0.20, key=f"{key}_wb",
                         help="% of BDR-sourced SQLs that close as won deals. Typically lower than marketing/self-sourced — colder outbound leads.")
    win_self = de4.slider("Win % — self-sourced", 0.0, 1.0, 0.35, key=f"{key}_ws",
                          help="% of AE-self-sourced SQLs that close as won deals. Typically the highest — warmest, highest-intent source.")

    st.caption("Contract & Renewal")
    cr1, cr2 = st.columns(2)
    contract_term = cr1.number_input("Term (mo)", 1, 60, 12, key=f"{key}_term",
                                     help="Subscription contract length. Revenue is recognized ratably (evenly) over this period, starting at go-live.")
    implementation_lag = cr2.number_input("Impl. lag (mo)", 0, 24, 2, key=f"{key}_lag",
                                          help="Months between signing and go-live. Revenue recognition can't start until go-live, even though the deal is already booked — this is the gap that breaks naive 'bookings = revenue' models.")
    cr3, cr4 = st.columns(2)
    churn_rate = cr3.number_input("Churn %", 0.0, 1.0, 0.12, step=0.01, key=f"{key}_churn",
                                  help="Annual gross revenue churn rate — % of ARR lost at renewal from customers who don't renew at all.")
    expansion_rate = cr4.number_input("Expansion %", 0.0, 1.0, 0.18, step=0.01, key=f"{key}_exp",
                                      help="Annual expansion rate — % ARR gained from upsell/cross-sell among renewing accounts (applied after churn, to the retained base).")
    cr5, cr6 = st.columns(2)
    contraction_rate = cr5.number_input("Contraction %", 0.0, 1.0, 0.03, step=0.01, key=f"{key}_contr",
                                        help="Annual contraction rate — % ARR lost from downgrades among renewing accounts (distinct from full churn — the account stays, just pays less).")
    execution_efficiency = cr6.number_input("Exec. efficiency", 0.0, 1.5, 1.0, step=0.01, key=f"{key}_exec",
                                            help="Real-world execution quality, independent of funnel/capacity math — deal slippage, discounting, a rep having a bad quarter. 1.0 = perfect execution. Still capped by capacity even above 1.0.")

    # --- Advanced: comp breakdown, hiring cadence, custom schedules,
    # seasonality, PS fee. Collapsed by default — a smart comp default is
    # derived from quota so the model runs correctly even if never opened. ---
    with st.expander("Advanced: Comp, Hiring Schedule, Seasonality"):
        st.caption("AE comp defaults to a 5.5x quota:OTE split (mid of the healthy 4-6x band) unless overridden.")
        default_ae_ote = (ae_quota_millions * 1_000_000) / 5.5
        ac1, ac2 = st.columns(2)
        ae_base = ac1.number_input("AE annual base ($)", 0, 500_000, int(default_ae_ote / 2), step=5000, key=f"{key}_ae_base",
                                    help="AE annual base salary. Paid every month regardless of ramp or attainment.")
        ae_variable = ac2.number_input("AE annual variable @ 100% ($)", 0, 500_000, int(default_ae_ote / 2), step=5000, key=f"{key}_ae_var",
                                        help="AE commission/bonus at 100% quota attainment. Paid proportionally to actual attainment, scaled by ramp.")

        bc1, bc2 = st.columns(2)
        bdr_base = bc1.number_input("BDR annual base ($)", 0, 300_000, 55_000, step=5000, key=f"{key}_bdr_base",
                                     help="BDR annual base salary.")
        bdr_variable = bc2.number_input("BDR annual variable @ 100% ($)", 0, 300_000, 30_000, step=5000, key=f"{key}_bdr_var",
                                         help="BDR commission/bonus at 100% SQL quota attainment.")

        hiring_cadence = st.number_input("Default hiring cadence (months between hires)", 1, 12, 3, key=f"{key}_cadence",
                                          help="New hires are staggered this many months apart by default (e.g. 3 = one new hire every 3 months). Overridden by a custom schedule below if you set one.")
        custom_ae_schedule_raw = st.text_input(
            "Custom AE hire-month schedule (optional, comma-separated)", "", key=f"{key}_ae_custom_sched",
            help=f"e.g. '0,0,6,6' to hire 2 now and 2 more in month 6. Must have exactly {num_aes} entries if used. Leave blank to use the cadence above.",
        )
        custom_bdr_schedule_raw = st.text_input(
            "Custom BDR hire-month schedule (optional, comma-separated)", "", key=f"{key}_bdr_custom_sched",
            help=f"Same format. Must have exactly {num_bdrs} entries if used. Leave blank to use the cadence above.",
        )
        ae_hire_months = None
        if custom_ae_schedule_raw.strip():
            try:
                ae_hire_months = [int(x.strip()) for x in custom_ae_schedule_raw.split(",")]
                if len(ae_hire_months) != num_aes:
                    st.error(f"Custom AE schedule has {len(ae_hire_months)} entries, need {num_aes}. Using default cadence.")
                    ae_hire_months = None
            except ValueError:
                st.error("Couldn't parse custom AE schedule. Using default cadence.")

        bdr_hire_months = None
        if custom_bdr_schedule_raw.strip():
            try:
                bdr_hire_months = [int(x.strip()) for x in custom_bdr_schedule_raw.split(",")]
                if len(bdr_hire_months) != num_bdrs:
                    st.error(f"Custom BDR schedule has {len(bdr_hire_months)} entries, need {num_bdrs}. Using default cadence.")
                    bdr_hire_months = None
            except ValueError:
                st.error("Couldn't parse custom BDR schedule. Using default cadence.")

        ps_fee_pct = st.slider("Professional services fee (% of ARR)", 0.0, 0.5, 0.0, key=f"{key}_psfee",
                                help="One-time implementation fee, as a % of the account's ARR. Billed upfront at signing, but recognized as revenue only at go-live (point-in-time, distinct performance obligation under ASC 606).")

        use_seasonality = st.checkbox("Apply seasonal pattern", value=False, key=f"{key}_useseason",
                                       help="Apply a repeating 12-month multiplier pattern to realized bookings (e.g. December slowdown, Q4 push). Still capped by the hard capacity ceiling.")
        seasonality_pattern = None
        if use_seasonality:
            months_labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            seasonality_pattern = []
            for row_start in range(0, 12, 3):
                scols = st.columns(3)
                for j in range(3):
                    i = row_start + j
                    seasonality_pattern.append(
                        scols[j].slider(months_labels[i], 0.0, 2.0, 1.0, key=f"{key}_season_{i}",
                                        help=f"Bookings multiplier for {months_labels[i]}. 1.0 = normal, 0.5 = half, 1.5 = 50% above normal.")
                    )

    return dict(
        pod_name=pod_name, num_aes=num_aes, num_bdrs=num_bdrs, hiring_cadence=hiring_cadence,
        num_existing_aes=num_existing_aes, num_existing_bdrs=num_existing_bdrs,
        ae_hire_months=ae_hire_months, bdr_hire_months=bdr_hire_months,
        ae_base=ae_base, ae_variable=ae_variable, ae_quota=ae_quota_millions * 1_000_000,
        bdr_base=bdr_base, bdr_variable=bdr_variable, bdr_monthly_sql_quota=bdr_sql,
        marketing_sqls=marketing_sqls,
        ae_self_sourced=ae_self_sourced, avg_deal_size=avg_deal_size,
        win_marketing=win_marketing, win_bdr=win_bdr, win_self=win_self,
        execution_efficiency=execution_efficiency, contract_term=contract_term,
        implementation_lag=implementation_lag, ps_fee_pct=ps_fee_pct,
        churn_rate=churn_rate, expansion_rate=expansion_rate, contraction_rate=contraction_rate,
        seasonality_pattern=seasonality_pattern, num_months=num_months, gross_margin_pct=gross_margin_pct,
    )


# ---------------------------------------------------------------------------
# Runs all three phases for one config dict. Returns everything needed for
# display AND for cross-scenario bridging (all_contracts is needed for the
# origin-split revenue bridge).
# ---------------------------------------------------------------------------
def build_pod(cfg: dict) -> PodConfig:
    return PodConfig(
        pod_name=cfg["pod_name"], num_aes=int(cfg["num_aes"]), num_bdrs=int(cfg["num_bdrs"]),
        num_existing_aes=int(cfg["num_existing_aes"]), num_existing_bdrs=int(cfg["num_existing_bdrs"]),
        ae_comp_template=RoleComp(annual_base=cfg["ae_base"], annual_variable_at_100pct=cfg["ae_variable"], annual_quota=cfg["ae_quota"]),
        bdr_comp_template=RoleComp(annual_base=cfg["bdr_base"], annual_variable_at_100pct=cfg["bdr_variable"],
                                    annual_quota=cfg["bdr_monthly_sql_quota"] * 12) if (cfg["num_bdrs"] > 0 or cfg["num_existing_bdrs"] > 0) else None,
        # Marketing funnel mechanics (lead->MQL->SQL conversion) are deliberately
        # not modeled — channel mix is too company/product-specific to generalize
        # honestly (see README). marketing_sqls is a flat pass-through: leads=SQLs,
        # both conversion rates=100%, so sqls_generated() reduces to marketing_sqls
        # exactly. Same treatment BDR output already gets (a flat SQL quota, not
        # a simulated call->connect->meeting funnel) — kept consistent on purpose.
        marketing=MarketingFunnel(monthly_leads=cfg["marketing_sqls"], lead_to_mql_rate=1.0, mql_to_sql_rate=1.0),
        avg_deal_size=cfg["avg_deal_size"], win_rate_marketing_sourced=cfg["win_marketing"],
        win_rate_bdr_sourced=cfg["win_bdr"], win_rate_ae_self_sourced=cfg["win_self"],
        ae_self_sourced_sqls_per_month=cfg["ae_self_sourced"], execution_efficiency=cfg["execution_efficiency"],
        hiring_cadence_months=int(cfg["hiring_cadence"]), contract_term_months=int(cfg["contract_term"]),
        implementation_lag_months=int(cfg["implementation_lag"]), professional_services_fee_pct_of_arr=cfg["ps_fee_pct"],
        seasonality_pattern=cfg["seasonality_pattern"],
        ae_hire_months=cfg.get("ae_hire_months"), bdr_hire_months=cfg.get("bdr_hire_months"),
    )


def attainment_summary(cfg: dict, num_months: int) -> dict:
    """Cheap Phase-1-only preview (no Phase 2/3) — used to show AE quota
    attainment right under a market's assumptions, before running the full
    model. Attainment is actual_bookings/capacity_constrained_bookings, which
    is mathematically capped at 100% (capacity is a hard ceiling) — so it
    can never itself "exceed 100%". The actionable signal for "is this
    assumption realistic" is how FAR BELOW 100% it sits, plus how many
    months are capacity- vs. demand-bound: low attainment + mostly
    demand-bound months means AEs have slack, so more pipeline (e.g. one
    more BDR) can close a lot more without hitting the capacity ceiling.
    """
    pod = build_pod(cfg)
    phase1_df = run_scenario(pod.build_scenario(num_months))
    if len(phase1_df) == 0:
        return {"avg_attainment_pct": None, "months_capacity_bound": 0, "total_months": 0}
    return {
        "avg_attainment_pct": round(phase1_df["overall_attainment_pct"].mean(), 1),
        "months_capacity_bound": int((phase1_df["binding_constraint"] == "CAPACITY").sum()),
        "total_months": len(phase1_df),
    }


def run_full_model(cfg: dict, num_months: int):
    pod = build_pod(cfg)
    phase1_df = run_scenario(pod.build_scenario(num_months))
    initial_contracts = bookings_to_contracts(pod, phase1_df, billing_frequency=BillingFrequency.ANNUAL_UPFRONT)
    assumptions = {cfg["pod_name"]: RenewalAssumptions(
        pod_name=cfg["pod_name"], gross_revenue_churn_rate_annual=cfg["churn_rate"],
        expansion_rate_annual=cfg["expansion_rate"], contraction_rate_annual=cfg["contraction_rate"],
    )}
    all_contracts, renewals_df, phase2_df = run_full_lifecycle(initial_contracts, assumptions, num_months)
    return dict(pod=pod, phase1_df=phase1_df, phase2_df=phase2_df, renewals_df=renewals_df, all_contracts=all_contracts)


def revenue_by_origin(contracts: list, num_months: int) -> dict:
    """Exact partition of cumulative recognized revenue: new-origin subscription,
    renewal-origin subscription, and PS fees (always new-origin in practice,
    since renewal contracts carry no PS fee — you don't re-charge implementation
    on a renewal). These three sum exactly to total revenue recognized."""
    sub_new = sub_renewal = ps_fee = 0.0
    for month in range(num_months):
        for c in contracts:
            rev = c.revenue_recognized_in(month)
            if c.origin == "new":
                sub_new += rev
            else:
                sub_renewal += rev
            ps_fee += c.ps_fee_revenue_recognized_in(month)
    return {"subscription_new": sub_new, "subscription_renewal": sub_renewal, "ps_fee": ps_fee}


def make_waterfall(labels, values, title, measure=None):
    if measure is None:
        measure = ["absolute"] + ["relative"] * (len(values) - 2) + ["total"]
        
    fig = go.Figure(go.Waterfall(
        x=labels, y=values, measure=measure,
        connector={"line": {"color": "#E2E8F0", "width": 1}},
        increasing_marker_color="#16A34A", # Green for New ARR / Expansion
        decreasing_marker_color="#DC2626", # Red for Contraction / Churn
        totals_marker_color="#163A63"      # Navy for Beginning / Ending
    ))
    
    fig.update_layout(
        title=title, showlegend=False, height=420, margin=dict(t=50, b=20),
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(gridcolor="#F1F5F9", zerolinecolor="#E2E8F0"),
        font=dict(family="Inter, sans-serif", color="#475569")
    )
    return fig


# ---------------------------------------------------------------------------
# MULTI-MARKET COMBINING — sums genuinely additive columns across markets'
# Phase 1 / Phase 2 output, then RE-DERIVES ratio/categorical fields
# (binding_constraint, attainment, ARPA, cost-per-dollar) from the summed
# components using the same formulas the engines use — a blind sum of a
# ratio or a string field would be wrong. Fields that are set per-pod and
# have no meaningful combined value (execution_efficiency, seasonal
# multiplier, coverage) are dropped from the combined view rather than
# faked; they're still visible in each market's own per-market breakdown.
# ---------------------------------------------------------------------------
def combine_phase1_dfs(phase1_dfs: list) -> pd.DataFrame:
    if len(phase1_dfs) == 1:
        return phase1_dfs[0].copy()
    additive_cols = ["active_aes", "active_bdrs", "sqls_marketing", "sqls_bdr", "sqls_ae_self_sourced",
                      "capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings",
                      "ae_cost", "bdr_cost", "total_cost_of_capacity"]
    combined = phase1_dfs[0][["month"]].copy()
    for col in additive_cols:
        combined[col] = sum(df[col].values for df in phase1_dfs)

    combined["theoretical_bookings"] = combined[["capacity_constrained_bookings", "demand_constrained_bookings"]].min(axis=1)

    def _binding(row):
        if row["capacity_constrained_bookings"] < row["demand_constrained_bookings"]:
            return "CAPACITY"
        elif row["demand_constrained_bookings"] < row["capacity_constrained_bookings"]:
            return "DEMAND"
        return "BALANCED"
    combined["binding_constraint"] = combined.apply(_binding, axis=1)

    combined["overall_attainment_pct"] = combined.apply(
        lambda r: round(100 * r["actual_bookings"] / r["capacity_constrained_bookings"], 1)
        if r["capacity_constrained_bookings"] > 0 else 0.0, axis=1,
    )
    combined["cost_per_dollar_booked"] = combined.apply(
        lambda r: round(r["total_cost_of_capacity"] / r["actual_bookings"], 3)
        if r["actual_bookings"] > 0 else None, axis=1,
    )
    return combined


def combine_phase2_dfs(phase2_dfs: list) -> pd.DataFrame:
    if len(phase2_dfs) == 1:
        return phase2_dfs[0].copy()
    additive_cols = ["new_bookings_tcv", "new_accounts_signed", "new_arr_booked", "cumulative_accounts_signed",
                      "cumulative_arr_booked", "live_accounts", "live_arr", "subscription_billings",
                      "subscription_revenue_recognized", "ps_fee_billings", "ps_fee_revenue_recognized",
                      "total_billings", "total_revenue_recognized", "cumulative_billings",
                      "cumulative_revenue_recognized", "deferred_revenue_balance",
                      "implementation_backlog_value", "implementation_backlog_count"]
    combined = phase2_dfs[0][["month"]].copy()
    for col in additive_cols:
        combined[col] = sum(df[col].values for df in phase2_dfs)

    combined["arpa_new_accounts"] = combined.apply(
        lambda r: round(r["new_arr_booked"] / r["new_accounts_signed"], 2) if r["new_accounts_signed"] else None, axis=1)
    combined["blended_arpa_booked"] = combined.apply(
        lambda r: round(r["cumulative_arr_booked"] / r["cumulative_accounts_signed"], 2) if r["cumulative_accounts_signed"] else None, axis=1)
    combined["blended_arpa_live"] = combined.apply(
        lambda r: round(r["live_arr"] / r["live_accounts"], 2) if r["live_accounts"] else None, axis=1)
    return combined


def combine_renewals_for_display(renewals_df: pd.DataFrame) -> pd.DataFrame:
    """renewals_df (from concatenating multiple markets) can have several rows
    per month — one per pod whose cohort ended that month. That's correct
    for summarize_renewals() (an accurate per-event count) and for
    aggregate_periods() (which groups by month internally either way), but
    wide()'s month-indexed transpose needs exactly one row per month or it
    produces duplicate column labels, which breaks Arrow serialization.
    Sums the $ /count columns per month and re-derives the 2 rate fields
    from the summed components, dropping pod_name (mixed across pods here).
    """
    if len(renewals_df) == 0:
        return renewals_df
    sum_cols = ["logos_up_for_renewal", "arr_up_for_renewal", "churned_arr", "expansion_arr",
                "contraction_arr", "renewed_arr", "logos_retained_expected"]
    combined = renewals_df.groupby("month", as_index=False)[sum_cols].sum()
    combined["churn_rate_applied_pct"] = combined.apply(
        lambda r: round(100 * r["churned_arr"] / r["arr_up_for_renewal"], 2) if r["arr_up_for_renewal"] else None, axis=1)
    combined["nrr_this_cohort_pct"] = combined.apply(
        lambda r: round(100 * r["renewed_arr"] / r["arr_up_for_renewal"], 1) if r["arr_up_for_renewal"] else None, axis=1)
    return combined.sort_values("month").reset_index(drop=True)


# ---------------------------------------------------------------------------
# SIDEBAR — Mode, Navigation, Settings & Assumptions
# ---------------------------------------------------------------------------
if "app_mode" not in st.session_state:
    st.session_state.app_mode = "Full Company (All Segments)"

with st.sidebar:
    _export_container = st.container()

    _step = st.session_state.sidebar_width_step
    _sw_narrower, _sw_wider = st.columns(2)
    with _sw_narrower:
        if st.button("−", use_container_width=True, type="tertiary",
                      disabled=(_step == 0), key="sw_narrower",
                      help=f"Narrower ({_SIDEBAR_LABELS[max(_step - 1, 0)]})"):
            st.session_state.sidebar_width_step = _step - 1
            st.rerun()
    with _sw_wider:
        if st.button("+", use_container_width=True, type="tertiary",
                      disabled=(_step == len(_SIDEBAR_WIDTHS) - 1), key="sw_wider",
                      help=f"Wider ({_SIDEBAR_LABELS[min(_step + 1, len(_SIDEBAR_WIDTHS) - 1)]})"):
            st.session_state.sidebar_width_step = _step + 1
            st.rerun()

    st.markdown(
        '<p style="font-weight: 700; font-size: 15px; margin-bottom: 4px;">Mode</p>',
        unsafe_allow_html=True,
    )
    mode_selection = st.segmented_control(
        "mode_selector", ["All Segments", "Compare Scenarios"],
        default="All Segments" if st.session_state.app_mode == "Full Company (All Segments)" else "Compare Scenarios",
        label_visibility="collapsed",
    )
    if mode_selection == "All Segments":
        st.session_state.app_mode = "Full Company (All Segments)"
    elif mode_selection == "Compare Scenarios":
        st.session_state.app_mode = "Compare Two Scenarios"

    st.divider()

    sc1, sc2 = st.columns(2)
    with sc1:
        global_horizon = st.number_input("Forecast Horizon", 6, 48, 24, key="global_horizon")
    with sc2:
        global_margin = st.number_input("Gross Margin %", 0.0, 1.0, 0.75, step=0.01, key="global_margin")

    st.divider()

# ===========================================================================
# FULL COMPANY MODE
# ===========================================================================
if st.session_state.app_mode == "Full Company (All Segments)":
    MARKET_NAMES = ["SMB", "Mid-Market", "Enterprise", "Inbound"]
    MARKET_KEYS = {"SMB": "smb", "Mid-Market": "mm", "Enterprise": "ent", "Inbound": "inb"}

    num_months = global_horizon
    gross_margin_pct = global_margin

    cfgs = {}
    with st.sidebar:
        st.markdown(
            '<p style="font-weight: 700; font-size: 15px; margin-bottom: 4px;">Segment Assumptions</p>',
            unsafe_allow_html=True,
        )
        for market in MARKET_NAMES:
            with st.expander(market, expanded=False):
                cfg_m = render_inputs(MARKET_KEYS[market], market, num_months_default=num_months,
                                       fixed_segment=market, show_horizon=False)
                att = attainment_summary(cfg_m, num_months)
                if att["avg_attainment_pct"] is not None:
                    st.caption(
                        f"📊 AE Attainment: {att['avg_attainment_pct']:.1f}% — "
                        f"Cap-bound {att['months_capacity_bound']}/{att['total_months']} months."
                    )
            cfgs[market] = cfg_m

        st.divider()

        include_existing = st.checkbox("Historical customer data", value=False, key="fc_include_existing",
                                        help="Upload customer-level monthly revenue to derive historical NRR, churn and expansion.")

    existing_book_df = None
    derived_metrics = None
    historical_annual = None

    if include_existing:
        with st.sidebar:
            with st.expander("Existing Customer Book", expanded=True):
                uploaded = st.file_uploader("Upload revenue extract", type=["csv", "xlsx"],
                                             help="Long format: one row per customer per month.")
                if uploaded is not None:
                    try:
                        raw_df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
                    except Exception as e:
                        st.error(f"Couldn't read file: {e}")
                        raw_df = None

                    if raw_df is not None:
                        cols = list(raw_df.columns)
                        customer_col = st.selectbox("Customer column", cols, index=0)
                        month_col = st.selectbox("Month column", cols, index=min(1, len(cols) - 1))
                        revenue_col = st.selectbox("Revenue column", cols, index=min(2, len(cols) - 1))
                        lookback = st.number_input("Lookback (months)", 1, 24, 12)

                        try:
                            matrix = load_customer_revenue_extract(raw_df, customer_col, month_col, revenue_col)
                            derived_metrics = derive_book_metrics(matrix, lookback_months=lookback)
                        except Exception as e:
                            st.error(f"Couldn't derive metrics: {e}")
                            derived_metrics = None

                        if derived_metrics is not None:
                            st.success(
                                f"NRR: {derived_metrics.nrr_pct}% "
                                f"({derived_metrics.customers_matched} matched, {derived_metrics.customers_churned} churned)"
                            )
                            historical_annual = derive_annual_history(matrix).rename(columns={"new_arr_booked": "new_arr_live"})

                            override = st.checkbox("Override rates manually", value=False)
                            if override:
                                eb_churn = st.slider("Annual churn", 0.0, 1.0, derived_metrics.implied_annual_churn_rate or 0.10)
                                eb_expansion = st.slider("Annual expansion", 0.0, 1.0, derived_metrics.implied_annual_expansion_rate or 0.10)
                                eb_contraction = st.slider("Annual contraction", 0.0, 1.0, derived_metrics.implied_annual_contraction_rate or 0.02)
                            else:
                                eb_churn = derived_metrics.implied_annual_churn_rate or 0.0
                                eb_expansion = derived_metrics.implied_annual_expansion_rate or 0.0
                                eb_contraction = derived_metrics.implied_annual_contraction_rate or 0.0

                            existing_book_df = project_existing_book_runoff(
                                base_arr=derived_metrics.base_arr,
                                annual_churn_rate=eb_churn,
                                annual_expansion_rate=eb_expansion,
                                annual_contraction_rate=eb_contraction,
                                num_months=num_months,
                                base_logo_count=derived_metrics.base_logo_count,
                            )

    try:
        results = {m: run_full_model(cfgs[m], num_months) for m in MARKET_NAMES}
    except Exception as e:
        st.error(f"Model error: {e}")
        st.stop()

    with st.sidebar:
        st.divider()
        selected_markets = st.multiselect(
            "Markets to include", MARKET_NAMES, default=MARKET_NAMES, key="fc_market_filter",
        )
    if not selected_markets:
        st.warning("Select at least one market above to see results.")
        st.stop()

    phase1_df = combine_phase1_dfs([results[m]["phase1_df"] for m in selected_markets])
    phase2_df = combine_phase2_dfs([results[m]["phase2_df"] for m in selected_markets])
    renewals_df = pd.concat([results[m]["renewals_df"] for m in selected_markets], ignore_index=True)
    all_contracts = [c for m in selected_markets for c in results[m]["all_contracts"]]

    eb_base_arr = derived_metrics.base_arr if derived_metrics is not None else 0.0
    eb_base_logos = derived_metrics.base_logo_count if derived_metrics is not None else 0

    fc_pages = ["📐 Executive Dashboard", "📈 Pipeline & Capacity", "💰 Revenue Recognition", "🔄 Renewals & NRR"]
    if existing_book_df is not None:
        fc_pages.insert(1, "🏢 Total Company")

    with _export_container:
        try:
            cfg_list = [cfgs[m] for m in selected_markets]
            xlsx_bytes = generate_multi_pod_workbook_bytes(cfg_list, num_months)
            st.download_button(
                label="📥 Export Excel",
                data=xlsx_bytes,
                file_name="company_financial_model.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
                help=f"Download an auditable Excel model covering: {', '.join(selected_markets)}.",
            )
        except Exception:
            st.caption("Configure segments to export")

    fc_tab_labels = [pg.split(" ", 1)[1] for pg in fc_pages]
    selected_tab = st.segmented_control(
        "fc_nav", fc_tab_labels,
        default=fc_tab_labels[0],
        key="fc_page_seg",
        label_visibility="collapsed",
    )
    if selected_tab is None:
        selected_tab = fc_tab_labels[0]
    selected_page = fc_pages[fc_tab_labels.index(selected_tab)]

    if selected_page == "📐 Executive Dashboard":
        st.markdown('<p class="dashboard-caption">ARR, revenue, retention and key forecast drivers.</p>', unsafe_allow_html=True)
        annual = aggregate_periods(
            phase2_df, renewals_df, existing_book_df, all_contracts, num_months,
            period_months=12, gross_margin_pct=gross_margin_pct,
            existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
        )
        # aggregate_periods()'s "new_arr_booked" is go-live-date-based (see
        # saas_metrics.py docstring), not signed-date — renamed locally so it
        # doesn't collide with the genuinely signed-date "new_arr_booked" that
        # comes straight from Phase 2 (revenue_recognition_engine.py) elsewhere
        # in this app. See _LABELS for the full explanation.
        annual = annual.rename(columns={"new_arr_booked": "new_arr_live"})
        # Per-period deferred revenue for the "By Year" table below — not an
        # aggregate_periods() field (it's a point-in-time balance, not a
        # period sum), so pulled from combined phase2_df at each forecast
        # period's last month. annual's row order matches period index p
        # exactly (aggregate_periods builds it that way), so position i's
        # end month is min((i+1)*12, num_months).
        annual["deferred_revenue"] = [
            (lambda match: match.iloc[0] if len(match) else None)(
                phase2_df.loc[phase2_df["month"] == min((i + 1) * 12, num_months), "deferred_revenue_balance"]
            )
            for i in range(len(annual))
        ]
        annual["type"] = "Forecast"

        if historical_annual is not None and len(historical_annual) > 0:
            historical_annual = historical_annual.copy()
            historical_annual["deferred_revenue"] = None  # no deferred-revenue concept in a revenue extract
            combined_annual = pd.concat([historical_annual, annual], ignore_index=True)
        else:
            combined_annual = annual

        latest = combined_annual.iloc[-1]
        prior = combined_annual.iloc[-2] if len(combined_annual) > 1 else None

        def _delta(field):
            if prior is None or pd.isna(prior[field]) or prior[field] == 0 or pd.isna(latest[field]):
                return None
            return latest[field] - prior[field]

        st.markdown(
            f'<h3 class="dashboard-heading" style="font-size: 20px; font-weight: 700; color: #1E293B;">'
            f'Full Company — {latest["period"]}</h3>'
            f'<p class="dashboard-caption" style="margin-bottom: 8px;">Markets included: {", ".join(selected_markets)}.</p>',
            unsafe_allow_html=True,
        )
        if historical_annual is not None and len(historical_annual) > 0:
            st.caption(f"Showing {len(historical_annual)} year(s) of actuals from your extract, "
                       f"continuing into {len(annual)} year(s) of forecast.")

        # Hero tiles: primary audience is FP&A/CFO, not investors — accounting-
        # operational metrics (Recognized Revenue, Deferred Revenue) take
        # priority over investor-deck metrics (LTV, GRR), which move to the
        # secondary "More metrics" expander below instead of disappearing.
        ending_deferred_revenue = phase2_df["deferred_revenue_balance"].iloc[-1]

        revenue_delta = _delta("revenue")
        logos_delta = _delta("ending_logos")
        nrr_delta = _delta("nrr_pct")

        # Sparklines plot the REAL underlying series at the finest resolution
        # each metric is actually computed at, not the 2-3-point annual
        # rollup — a straight line between 2 annual points is indistinguishable
        # from synthetic data even though it's real, since it can't show any
        # month-to-month texture (AE ramp curves, capacity-bound plateaus).
        # Ending ARR / Live Accounts / Deferred Revenue are genuinely monthly
        # quantities in phase2_df already. NRR is only ever computed at
        # cohort (quarterly/annual) resolution by design — see saas_metrics.py
        # docstring, "a single quarter's churn rate is too noisy" — so its
        # sparkline uses quarterly data, the finest real resolution available,
        # rather than annual or fabricated monthly interpolation.
        quarterly_for_sparkline = aggregate_periods(
            phase2_df, renewals_df, existing_book_df, all_contracts, num_months,
            period_months=3, existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
        )

        # Helper function for $XX.XM formatting
        # Helper function for millions formatting
        def _fmt_millions(val):
            if val is None or pd.isna(val):
                return "—"
            if abs(val) >= 1_000_000:
                return f"${val / 1_000_000:,.1f}M"
            return f"${val:,.0f}"

        # Re-compute delta strings for the metrics
        arr_growth_pct = ((latest["ending_arr"] / prior["ending_arr"]) - 1) * 100 if prior is not None and prior["ending_arr"] else None
        arr_delta_str = f"▲ {arr_growth_pct:.1f}% YoY" if arr_growth_pct and arr_growth_pct >= 0 else (f"▼ {abs(arr_growth_pct):.1f}% YoY" if arr_growth_pct else None)
        rev_delta_str = f"▲ {_fmt_millions(revenue_delta)}" if revenue_delta and revenue_delta >= 0 else (f"▼ {_fmt_millions(abs(revenue_delta))}" if revenue_delta else None)
        nrr_delta_str = f"▲ {nrr_delta:.1f} pts" if nrr_delta and nrr_delta >= 0 else (f"▼ {abs(nrr_delta):.1f} pts" if nrr_delta else None)
        logos_delta_str = f"▲ {logos_delta:,.0f}" if logos_delta and logos_delta >= 0 else (f"▼ {abs(logos_delta):,.0f}" if logos_delta else None)

        # Helper for hex color conversion to area fill opacity
        def _hex_to_rgba(hex_str, alpha):
            hex_str = hex_str.lstrip('#')
            r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
            return f"rgba({r}, {g}, {b}, {alpha})"

        metrics_data = [
            ("Ending ARR", _fmt_millions(latest['ending_arr']), arr_delta_str, phase2_df["live_arr"], "#16A34A"),       # Green
            ("Recognized Rev", _fmt_millions(latest['revenue']), rev_delta_str, phase2_df["total_revenue_recognized"], "#2563EB"), # Blue
            ("Blended NRR", f"{latest['nrr_pct']:.1f}%" if latest["nrr_pct"] is not None else "—", nrr_delta_str, quarterly_for_sparkline["nrr_pct"].fillna(0), "#9333EA"), # Purple
            ("Live Accounts", f"{int(latest['ending_logos']):,}" if latest["ending_logos"] is not None else "—", logos_delta_str, phase2_df["live_accounts"], "#0EA5E9"), # Teal/Cyan
            ("Deferred Revenue", _fmt_millions(ending_deferred_revenue), None, phase2_df["deferred_revenue_balance"], "#D97706"), # Amber
            ("Capacity Cost", _fmt_millions(phase1_df['total_cost_of_capacity'].sum()), None, phase1_df["total_cost_of_capacity"], "#DC2626") # Red/Coral
        ]

        row1_cols = st.columns(3)
        row2_cols = st.columns(3)
        all_cols = row1_cols + row2_cols

        for i, (label, val, delta, chart_vals, val_color) in enumerate(metrics_data):
            with all_cols[i]:
                with st.container(border=True):
                    mc_left, mc_right = st.columns([1.1, 1.3], vertical_alignment="center")
                    with mc_left:
                        st.markdown(f"<p style='color: #64748B; font-size: 11px; font-weight: 500; margin-bottom: 0px;'>{label}</p>", unsafe_allow_html=True)
                        
                        # Value and delta placed nicely inline or tightly stacked together
                        if delta:
                            d_color = "#16A34A" if "▲" in delta else "#DC2626"
                            d_bg = "#ECFDF3" if "▲" in delta else "#FEF2F2"
                            st.markdown(
                                f"<div style='display: flex; align-items: baseline; gap: 6px; margin-top: 2px;'>"
                                f"<span style='color: {val_color}; font-size: 18px; font-weight: 700;'>{val}</span>"
                                f"<span style='background-color: {d_bg}; color: {d_color}; font-size: 9px; font-weight: 600; padding: 1px 4px; border-radius: 4px; white-space: nowrap;'>{delta}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                        else:
                            st.markdown(f"<p style='color: {val_color}; font-size: 18px; font-weight: 700; margin-top: 2px; margin-bottom: 0px;'>{val}</p>", unsafe_allow_html=True)
                            
                    with mc_right:
                        if chart_vals is not None and len(chart_vals) > 0:
                            fig_mini = go.Figure(go.Scatter(
                                y=chart_vals,
                                mode='lines',
                                fill='tozeroy',
                                line=dict(color=val_color, width=2),
                                fillcolor=_hex_to_rgba(val_color, 0.12)
                            ))
                            fig_mini.update_layout(
                                height=50, margin=dict(l=0, r=0, t=2, b=2),
                                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                xaxis=dict(visible=False), yaxis=dict(visible=False),
                                showlegend=False
                            )
                            st.plotly_chart(fig_mini, use_container_width=True, config={"displayModeBar": False})

        with st.expander("More metrics (GRR, Logo Churn, LTV)"):
            m1, m2, m3 = st.columns(3)
            grr = 100 - latest["gross_dollar_churn_rate_pct"] if latest["gross_dollar_churn_rate_pct"] is not None else None
            m1.metric("Gross Revenue Retention", f"{grr:.1f}%" if grr is not None else "—")
            logo_churn_delta = _delta("logo_churn_rate_pct")
            m2.metric("Logo Churn Rate", f"{latest['logo_churn_rate_pct']:.1f}%" if latest["logo_churn_rate_pct"] is not None else "—",
                       delta=f"{logo_churn_delta:.1f} pts" if logo_churn_delta is not None else None, delta_color="inverse")
            m3.metric("Customer LTV", f"${latest['ltv']:,.0f}" if latest["ltv"] is not None else "—")

        # ---------------------------------------------------------------
        # Row A: Annual Performance | Key Drivers | ARR Bridge
        # ---------------------------------------------------------------
        year1_row, latest_forecast_row = annual.iloc[0], annual.iloc[-1]

        def _pct_change(new, old):
            if old in (None, 0) or pd.isna(old) or pd.isna(new):
                return None
            return (new - old) / abs(old) * 100

        row_a_col1, row_a_col2, row_a_col3 = st.columns([1.1, 0.7, 1.4])

        with row_a_col1:
            st.markdown("**Annual Performance**")
            _by_year_labeled = combined_annual.copy()
            _by_year_labeled["period"] = _by_year_labeled.apply(
                lambda r: f"{r['period']} ({r['type']})" if pd.notna(r.get("type")) else r["period"], axis=1
            )
            _by_year_src = _by_year_labeled.set_index("period")
            by_year = pd.DataFrame({
                "Ending ARR": _by_year_src["ending_arr"].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—"),
                "Recognized Revenue": _by_year_src["revenue"].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—"),
                "NRR": _by_year_src["nrr_pct"].apply(lambda v: f"{v:.1f}%" if pd.notna(v) else "—"),
                "Live Accounts": _by_year_src["ending_logos"].apply(lambda v: f"{int(v):,}" if pd.notna(v) else "—"),
                "Deferred Revenue": _by_year_src["deferred_revenue"].apply(lambda v: f"${v:,.0f}" if pd.notna(v) else "—"),
            }).T
            st.dataframe(_bold_headers(by_year), use_container_width=True)

        with row_a_col2:
            st.markdown(f"**Key Drivers — {latest['period']}**")
            driver_fields = [
                ("New Business (ARR)", "new_arr_live"), ("Expansion", "expansion_arr"),
                ("Contraction", "contraction_arr"), ("Churn", "churned_arr"),
            ]
            drivers_rows = []
            for d_label, d_field in driver_fields:
                impact = latest_forecast_row[d_field]
                pct = _pct_change(impact, year1_row[d_field])
                drivers_rows.append({
                    "Driver": d_label,
                    "Impact on ARR": f"${impact:,.0f}" if pd.notna(impact) else "—",
                    "vs Year 1": f"{pct:+.1f}%" if pct is not None else "—",
                })
            st.dataframe(_bold_headers(pd.DataFrame(drivers_rows).set_index("Driver")), use_container_width=True)

        with row_a_col3:
            st.markdown(f"**ARR Bridge — {latest['period']}**")
            wf_labels = ["Begin", "New ARR", "Expand", "Contract", "Churn", "Other", "End"]
            wf_values = [latest["beginning_arr"], latest["new_arr_live"], latest["expansion_arr"],
                         -latest["contraction_arr"], -latest["churned_arr"], latest["other_boundary_effect"], latest["ending_arr"]]
            _wf_fig = make_waterfall(wf_labels, wf_values, "")
            _wf_fig.update_layout(height=300, margin=dict(t=10, b=30, l=40, r=10))
            st.plotly_chart(_wf_fig, use_container_width=True)

        # ---------------------------------------------------------------
        # Row B: ARR Actuals → Forecast chart | Executive Takeaway
        # ---------------------------------------------------------------
        row_b_col1, row_b_col2 = st.columns([1.6, 1])

        with row_b_col1:
            _has_actuals = historical_annual is not None and len(historical_annual) > 0
            if _has_actuals:
                title_col, filter_col = st.columns([2, 1])
                title_col.caption("ARR — Actuals → Forecast")
                arr_view = filter_col.selectbox(
                    "View", ["All Markets"] + selected_markets, key="arr_chart_view",
                    label_visibility="collapsed",
                    help="Display-only filter for this chart — doesn't affect the hero tiles, other tabs, or the 'Markets to include' selection above.",
                )
                if arr_view == "All Markets":
                    chart_annual = combined_annual
                else:
                    chart_annual = aggregate_periods(
                        results[arr_view]["phase2_df"], results[arr_view]["renewals_df"], None,
                        results[arr_view]["all_contracts"], num_months, period_months=12,
                    )
                    chart_annual["type"] = "Forecast"

                arr_fig = go.Figure()
                actual_rows = chart_annual[chart_annual["type"] == "Actual"]
                forecast_rows = chart_annual[chart_annual["type"] == "Forecast"]
                if len(actual_rows) > 0:
                    arr_fig.add_trace(go.Bar(x=actual_rows["period"], y=actual_rows["ending_arr"],
                                              name="Actual", marker_color="#2563EB"))
                if len(forecast_rows) > 0:
                    arr_fig.add_trace(go.Bar(x=forecast_rows["period"], y=forecast_rows["ending_arr"],
                                              name="Forecast", marker_color="#93C5FD"))
                arr_fig.update_layout(showlegend=True, height=320, margin=dict(t=20, b=20))
                st.plotly_chart(arr_fig, use_container_width=True)
            else:
                title_col, filter_col = st.columns([2, 1])
                title_col.caption("ARR Trajectory — Monthly")
                arr_view = filter_col.selectbox(
                    "View", ["All Markets"] + selected_markets, key="arr_chart_view",
                    label_visibility="collapsed",
                    help="Display-only filter for this chart — doesn't affect the hero tiles, other tabs, or the 'Markets to include' selection above.",
                )
                if arr_view == "All Markets":
                    chart_series = phase2_df["live_arr"]
                else:
                    chart_series = results[arr_view]["phase2_df"]["live_arr"]

                arr_fig = go.Figure(go.Scatter(
                    x=list(range(1, len(chart_series) + 1)), y=chart_series,
                    mode="lines", line=dict(color="#2563EB", width=2.5),
                    fill="tozeroy", fillcolor="rgba(37, 99, 235, 0.08)",
                    name="Live ARR",
                ))
                arr_fig.update_layout(
                    showlegend=False, height=320, margin=dict(t=20, b=20),
                    xaxis_title="Month", yaxis_title="Live ARR ($)",
                    plot_bgcolor="white", paper_bgcolor="white",
                    xaxis=dict(gridcolor="#F1F5F9"), yaxis=dict(gridcolor="#F1F5F9"),
                )
                st.plotly_chart(arr_fig, use_container_width=True)

        with row_b_col2:
            # Executive Takeaway — deterministic narrative, no LLM call
            _NRR_STRONG_THRESHOLD = 110.0
            _NRR_STABLE_FLOOR = 95.0
            _DEFERRED_REV_VISIBILITY_THRESHOLD = 0.40

            ending_arr_val = latest["ending_arr"]
            nrr_val = latest["nrr_pct"]
            new_biz_impact = abs(latest_forecast_row["new_arr_live"]) if pd.notna(latest_forecast_row["new_arr_live"]) else 0
            expansion_impact = abs(latest_forecast_row["expansion_arr"]) if pd.notna(latest_forecast_row["expansion_arr"]) else 0

            if new_biz_impact >= expansion_impact:
                primary_driver_label = "new business"
                primary_driver_impact = latest_forecast_row["new_arr_live"]
            else:
                primary_driver_label = "expansion"
                primary_driver_impact = latest_forecast_row["expansion_arr"]

            if nrr_val is not None and not pd.isna(nrr_val):
                if nrr_val >= _NRR_STRONG_THRESHOLD:
                    nrr_classification = "strong"
                elif nrr_val >= _NRR_STABLE_FLOOR:
                    nrr_classification = "stable"
                else:
                    nrr_classification = "declining"
                nrr_display = f"{nrr_val:.1f}%"
            else:
                nrr_classification = "unmeasured"
                nrr_display = "N/A"

            deferred_rev_val = ending_deferred_revenue if ending_deferred_revenue is not None and not pd.isna(ending_deferred_revenue) else 0
            if ending_arr_val and not pd.isna(ending_arr_val) and ending_arr_val > 0:
                deferred_ratio = deferred_rev_val / ending_arr_val
            else:
                deferred_ratio = 0
            visibility_classification = "strong forward revenue visibility" if deferred_ratio >= _DEFERRED_REV_VISIBILITY_THRESHOLD else "limited forward revenue visibility"

            takeaway_text = (
                f"ARR is projected to grow to {_fmt_millions(ending_arr_val)} in {latest['period']}, "
                f"driven primarily by {_fmt_millions(abs(primary_driver_impact))} of {primary_driver_label}. "
                f"Blended NRR of {nrr_display} indicates {nrr_classification} retention, "
                f"while deferred revenue of {_fmt_millions(deferred_rev_val)} provides {visibility_classification}."
            )

            st.markdown(
                f'<div style="background-color: #F0FDF4; border-left: 4px solid #16A34A; border-radius: 8px; '
                f'padding: 16px 20px; margin-top: 8px;">'
                f'<p style="color: #15803D; font-size: 13px; font-weight: 600; margin: 0 0 8px 0;">💡 Executive Takeaway</p>'
                f'<p style="color: #1A2233; font-size: 14px; line-height: 1.6; margin: 0;">{takeaway_text}</p>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with st.expander("View underlying data"):
            st.caption(
                "'New ARR (Went Live)' is ARR that went LIVE this period (by go-live date), not ARR signed — "
                "those differ once implementation lag is involved. That's distinct from 'New ARR Booked (Signed)', "
                "shown in the Revenue Recognition tab's raw data, which is signed-date-based. LTV is annual-only: a single "
                "quarter's churn rate is too noisy to use as an LTV input. Historical actual years "
                "have no LTV (gross margin isn't in a revenue extract) and the earliest actual year "
                "has no NRR/churn (no prior-year baseline to compare against)."
            )
            st.markdown("**Annual (Actual + Forecast)**")
            st.dataframe(_bold_headers(style_wide(combined_annual.set_index("period").T)), width='stretch')


            st.markdown("**Quarterly**")
            quarterly = aggregate_periods(
                phase2_df, renewals_df, existing_book_df, all_contracts, num_months,
                period_months=3, existing_book_base_arr=eb_base_arr, existing_book_base_logos=eb_base_logos,
            )
            quarterly = quarterly.rename(columns={"new_arr_booked": "new_arr_live"})
            num_years = (num_months + 11) // 12
            for y in range(num_years):
                year_quarters = quarterly[quarterly["period"].str.startswith(f"Y{y+1}-")]
                if len(year_quarters) > 0:
                    st.markdown(f"*Year {y+1}*")
                    st.dataframe(_bold_headers(style_wide(year_quarters.set_index("period").T)), width='stretch')

    elif existing_book_df is not None and selected_page == "🏢 Total Company":
        combined = pd.DataFrame({
            "month": phase2_df["month"],
            "existing_book_arr": existing_book_df["existing_book_arr"],
            "new_business_live_arr": phase2_df["live_arr"],
        })
        combined["total_arr"] = combined["existing_book_arr"] + combined["new_business_live_arr"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Existing Book — Ending ARR", f"${existing_book_df['existing_book_arr'].iloc[-1]:,.0f}")
        c2.metric("New Business — Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
        c3.metric("Total Company — Ending ARR", f"${combined['total_arr'].iloc[-1]:,.0f}")
        st.line_chart(combined.set_index("month")[["existing_book_arr", "new_business_live_arr", "total_arr"]].rename(
            columns={"existing_book_arr": "Existing Book ARR", "new_business_live_arr": "New Business ARR (Live)", "total_arr": "Total ARR"}
        ))

        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Extract — Base ARR", f"${derived_metrics.base_arr:,.0f}")
        d2.metric("Extract — Trailing-12 NRR", f"{derived_metrics.nrr_pct}%")
        d3.metric("Extract — Churned ARR (TTM)", f"${derived_metrics.churned_arr:,.0f}")
        d4.metric("Extract — Expansion ARR (TTM)", f"${derived_metrics.expansion_arr:,.0f}")

        with st.expander("View underlying data"):
            st.caption(
                "Existing book is a top-line ARR/revenue overlay derived from your uploaded extract "
                "(smooth monthly runoff, no individual contract dates). New business runs through the "
                "full Bowtie engine (Phase 1-3) with real deferred revenue mechanics."
            )
            st.dataframe(_bold_headers(style_wide(wide(combined))), width='stretch')

    elif selected_page == "📈 Pipeline & Capacity":
        st.subheader("Bookings: Capacity vs. Demand Constraint")
        st.caption("Actual bookings are constrained by whichever is lower: qualified demand or sales capacity. "
                    "All bookings figures on this page are TCV (Total Contract Value) — the same unit as Avg Deal Size and AE quota — not ARR.")
        with st.expander("What do these terms mean?"):
            st.markdown(
                "- **Capacity-Constrained Bookings (TCV)** — what AEs *could* close this month given headcount, ramp, and quota alone.\n"
                "- **Demand-Constrained Bookings (TCV)** — what the pipeline *could* support this month, given SQLs (marketing + BDR + AE self-sourced) × win rate × deal size.\n"
                "- **Theoretical Bookings (TCV)** — the lower of the two above: the hard ceiling before execution/seasonality are applied.\n"
                "- **Execution Efficiency** — a realism multiplier applied on top of that ceiling (deal slippage, discounting, a rep having a bad quarter). 1.0 = perfect execution.\n"
                "- **Binding Constraint** — which side (CAPACITY or DEMAND) is actually limiting Actual Bookings this month. CAPACITY means AEs are maxed out; DEMAND means AEs have slack and more pipeline would close more."
            )
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Bookings (TCV)", f"${phase1_df['actual_bookings'].sum():,.0f}")
        col2.metric("Total Cost of Capacity", f"${phase1_df['total_cost_of_capacity'].sum():,.0f}")
        months_capacity_bound = (phase1_df["binding_constraint"] == "CAPACITY").sum()
        col3.metric("Months Capacity-Bound", f"{months_capacity_bound}/{len(phase1_df)}")
        st.info(f"Binding constraint: Capacity in {months_capacity_bound} of {len(phase1_df)} months.")
        st.line_chart(phase1_df.set_index("month")[["capacity_constrained_bookings", "demand_constrained_bookings", "actual_bookings"]].rename(
            columns={"capacity_constrained_bookings": "Capacity-Constrained Bookings (TCV)",
                     "demand_constrained_bookings": "Demand-Constrained Bookings (TCV)", "actual_bookings": "Actual Bookings (TCV)"}
        ))

        with st.expander("View underlying data"):
            st.caption("Execution Efficiency, Seasonal Multiplier and Pipeline Coverage aren't shown in the combined "
                       "view — they're set per market and have no single meaningful combined value. See each market below.")
            st.markdown("**Combined (selected markets)**")
            st.dataframe(_bold_headers(style_wide(wide(phase1_df))), width='stretch')
            for m in selected_markets:
                st.markdown(f"**{m}**")
                st.dataframe(_bold_headers(style_wide(wide(results[m]["phase1_df"]))), width='stretch')

    elif selected_page == "💰 Revenue Recognition":
        st.subheader("Live ARR Trajectory")
        st.caption("Bookings ≠ revenue. Implementation lag delays go-live and revenue recognition, creating a gap between contracted ARR, billings and recognized revenue.")
        col1, col2, col3 = st.columns(3)
        col1.metric("Ending Live ARR", f"${phase2_df['live_arr'].iloc[-1]:,.0f}")
        col2.metric("Ending Deferred Revenue", f"${phase2_df['deferred_revenue_balance'].iloc[-1]:,.0f}")
        col3.metric("Ending Live Accounts", f"{int(phase2_df['live_accounts'].iloc[-1])}")
        st.line_chart(phase2_df.set_index("month")[["live_arr", "cumulative_arr_booked"]].rename(
            columns={"live_arr": "Live ARR", "cumulative_arr_booked": "Cumulative ARR Booked"}
        ))
        st.subheader("Revenue Streams")
        st.bar_chart(phase2_df.set_index("month")[["subscription_revenue_recognized", "ps_fee_revenue_recognized"]].rename(
            columns={"subscription_revenue_recognized": "Subscription Revenue Recognized", "ps_fee_revenue_recognized": "PS Fee Revenue Recognized"}
        ))

        with st.expander("View underlying data"):
            st.markdown("**Combined (selected markets)**")
            st.dataframe(_bold_headers(style_wide(wide(phase2_df))), width='stretch')
            for m in selected_markets:
                st.markdown(f"**{m}**")
                st.dataframe(_bold_headers(style_wide(wide(results[m]["phase2_df"]))), width='stretch')

    elif selected_page == "🔄 Renewals & NRR":
        st.subheader("Renewal Cohort Summary")
        if len(renewals_df) > 0:
            summary = summarize_renewals(renewals_df)
            col1, col2, col3 = st.columns(3)
            col1.metric("Blended NRR", f"{summary['blended_nrr_pct']}%")
            col2.metric("Total Renewal Events", summary['total_renewal_events'])
            col3.metric("Total Expansion ARR", f"${summary['total_expansion_arr']:,.0f}")
            st.info(summary["nrr_benchmark_check"])
            with st.expander("View underlying data"):
                st.markdown("**Combined (selected markets)**")
                st.dataframe(_bold_headers(style_wide(wide(combine_renewals_for_display(renewals_df)))), width='stretch')
                for m in selected_markets:
                    market_renewals = results[m]["renewals_df"]
                    if len(market_renewals) > 0:
                        st.markdown(f"**{m}**")
                        st.dataframe(_bold_headers(style_wide(wide(market_renewals))), width='stretch')
        else:
            st.info("No renewal events occurred — scenario length may be shorter than the contract term.")

# ===========================================================================
# COMPARE TWO SCENARIOS MODE
# ===========================================================================
else:
    with st.sidebar:
        st.markdown(
            '<p style="font-weight: 700; font-size: 15px; margin-bottom: 4px;">Scenario Labels</p>',
            unsafe_allow_html=True,
        )
        scenario_a_name = st.text_input("Scenario A", "Scenario A — Base Plan", key="scenario_a_label")
        scenario_b_name = st.text_input("Scenario B", "Scenario B — Alternative Plan", key="scenario_b_label")

        st.divider()
        with st.expander(scenario_a_name, expanded=False):
            cfg_a = render_inputs("a", scenario_a_name, num_months_default=global_horizon, show_horizon=False, show_gross_margin=False)
            cfg_a["gross_margin_pct"] = global_margin
        with st.expander(scenario_b_name, expanded=False):
            cfg_b = render_inputs("b", scenario_b_name, num_months_default=global_horizon, show_horizon=False, show_gross_margin=False)
            cfg_b["gross_margin_pct"] = global_margin

    num_months = global_horizon
    cfg_a["num_months"] = num_months
    cfg_b["num_months"] = num_months

    try:
        result_a = run_full_model(cfg_a, num_months)
        result_b = run_full_model(cfg_b, num_months)
    except Exception as e:
        st.error(f"Model error: {e}")
        st.stop()

    p2a, p2b = result_a["phase2_df"], result_b["phase2_df"]
    rna, rnb = result_a["renewals_df"], result_b["renewals_df"]

    cmp_pages = ["📊 KPI Comparison", "🌉 ARR & Revenue Bridges", "📋 Raw Data"]
    cmp_tab_labels = [pg.split(" ", 1)[1] for pg in cmp_pages]
    selected_cmp_tab = st.segmented_control(
        "cmp_nav", cmp_tab_labels,
        default=cmp_tab_labels[0],
        key="cmp_page_seg",
        label_visibility="collapsed",
    )
    if selected_cmp_tab is None:
        selected_cmp_tab = cmp_tab_labels[0]
    selected_page = cmp_pages[cmp_tab_labels.index(selected_cmp_tab)]

    if selected_page == "📊 KPI Comparison":
        col1, col2 = st.columns(2)
        with col1:
            st.subheader(scenario_a_name)
            st.metric("Ending Live ARR", f"${p2a['live_arr'].iloc[-1]:,.0f}")
            st.metric("Total Revenue Recognized", f"${p2a['total_revenue_recognized'].sum():,.0f}")
            st.metric("Ending Deferred Revenue", f"${p2a['deferred_revenue_balance'].iloc[-1]:,.0f}")
        with col2:
            st.subheader(scenario_b_name)
            st.metric("Ending Live ARR", f"${p2b['live_arr'].iloc[-1]:,.0f}",
                       delta=f"${p2b['live_arr'].iloc[-1] - p2a['live_arr'].iloc[-1]:,.0f}")
            st.metric("Total Revenue Recognized", f"${p2b['total_revenue_recognized'].sum():,.0f}",
                       delta=f"${p2b['total_revenue_recognized'].sum() - p2a['total_revenue_recognized'].sum():,.0f}")
            st.metric("Ending Deferred Revenue", f"${p2b['deferred_revenue_balance'].iloc[-1]:,.0f}",
                       delta=f"${p2b['deferred_revenue_balance'].iloc[-1] - p2a['deferred_revenue_balance'].iloc[-1]:,.0f}")

    elif selected_page == "🌉 ARR & Revenue Bridges":
        cmp_annual_a = aggregate_periods(p2a, rna, None, result_a["all_contracts"], num_months, period_months=12)
        cmp_annual_b = aggregate_periods(p2b, rnb, None, result_b["all_contracts"], num_months, period_months=12)
        cmp_latest_a, cmp_latest_b = cmp_annual_a.iloc[-1], cmp_annual_b.iloc[-1]
        capacity_cost_a = result_a["phase1_df"]["total_cost_of_capacity"].sum()
        capacity_cost_b = result_b["phase1_df"]["total_cost_of_capacity"].sum()

        col_a_label = scenario_a_name if scenario_a_name != scenario_b_name else f"{scenario_a_name} (A)"
        col_b_label = scenario_b_name if scenario_a_name != scenario_b_name else f"{scenario_b_name} (B)"

        def _fmt_dollar(v):
            return f"${v:,.0f}" if v is not None and not pd.isna(v) else "—"

        def _fmt_pct(v):
            return f"{v:.1f}%" if v is not None and not pd.isna(v) else "—"

        summary_table = pd.DataFrame([
            {"Metric": "Ending ARR", col_a_label: _fmt_dollar(cmp_latest_a["ending_arr"]), col_b_label: _fmt_dollar(cmp_latest_b["ending_arr"]),
             "Δ (B − A)": _fmt_dollar(cmp_latest_b["ending_arr"] - cmp_latest_a["ending_arr"])},
            {"Metric": "Recognized Revenue", col_a_label: _fmt_dollar(cmp_latest_a["revenue"]), col_b_label: _fmt_dollar(cmp_latest_b["revenue"]),
             "Δ (B − A)": _fmt_dollar(cmp_latest_b["revenue"] - cmp_latest_a["revenue"])},
            {"Metric": "NRR", col_a_label: _fmt_pct(cmp_latest_a["nrr_pct"]), col_b_label: _fmt_pct(cmp_latest_b["nrr_pct"]),
             "Δ (B − A)": (f"{cmp_latest_b['nrr_pct'] - cmp_latest_a['nrr_pct']:.1f} pts"
                            if pd.notna(cmp_latest_a["nrr_pct"]) and pd.notna(cmp_latest_b["nrr_pct"]) else "—")},
            {"Metric": "Capacity Cost", col_a_label: _fmt_dollar(capacity_cost_a), col_b_label: _fmt_dollar(capacity_cost_b),
             "Δ (B − A)": _fmt_dollar(capacity_cost_b - capacity_cost_a)},
        ])
        st.dataframe(_bold_headers(summary_table.set_index("Metric")), width='stretch')
        st.caption("Ending ARR, Recognized Revenue and NRR reflect the latest full year; Capacity Cost is cumulative over the full horizon.")

        st.divider()
        st.subheader(f"ARR Bridge: {scenario_a_name} → {scenario_b_name}")
        st.caption(
            "Decomposed using each scenario's own cumulative New Business / Expansion / "
            "Contraction / Churn totals. This is an additive approximation, not a controlled "
            "marginal attribution — cascading renewal timing across months creates real "
            "interaction effects between drivers, shown explicitly as 'Other / interaction' "
            "below rather than hidden or forced to zero. Note: 'Δ New Business (Booked)' is "
            "signed-date-based (Phase 2 bookings), not go-live-date-based like the Executive "
            "Dashboard's 'New ARR (Went Live)' bridge component — the two aren't directly comparable."
        )
        start_arr = p2a["live_arr"].iloc[-1]
        end_arr = p2b["live_arr"].iloc[-1]
        d_new = p2b["new_arr_booked"].sum() - p2a["new_arr_booked"].sum()
        d_exp = (rnb["expansion_arr"].sum() if len(rnb) else 0) - (rna["expansion_arr"].sum() if len(rna) else 0)
        d_contr = -((rnb["contraction_arr"].sum() if len(rnb) else 0) - (rna["contraction_arr"].sum() if len(rna) else 0))
        d_churn = -((rnb["churned_arr"].sum() if len(rnb) else 0) - (rna["churned_arr"].sum() if len(rna) else 0))
        other = end_arr - (start_arr + d_new + d_exp + d_contr + d_churn)

        fig_arr = make_waterfall(
            [f"{scenario_a_name}<br>Ending ARR", "Δ New Business<br>(Booked)", "Δ Expansion", "Δ Contraction", "Δ Churn", "Other /<br>Interaction", f"{scenario_b_name}<br>Ending ARR"],
            [start_arr, d_new, d_exp, d_contr, d_churn, other, end_arr],
            "ARR Bridge",
        )
        st.plotly_chart(fig_arr, width='stretch')

        st.divider()
        st.subheader(f"Revenue Bridge: {scenario_a_name} → {scenario_b_name}")
        st.caption(
            "Cumulative total revenue recognized over the full window, decomposed by origin "
            "(new-business subscription vs. renewal-driven subscription) plus professional "
            "services fees. This is an EXACT partition — the three buckets sum exactly to "
            "total revenue recognized, no residual needed."
        )
        rev_a = revenue_by_origin(result_a["all_contracts"], num_months)
        rev_b = revenue_by_origin(result_b["all_contracts"], num_months)
        start_rev = sum(rev_a.values())
        end_rev = sum(rev_b.values())
        d_sub_new = rev_b["subscription_new"] - rev_a["subscription_new"]
        d_sub_renewal = rev_b["subscription_renewal"] - rev_a["subscription_renewal"]
        d_ps = rev_b["ps_fee"] - rev_a["ps_fee"]

        fig_rev = make_waterfall(
            [f"{scenario_a_name}<br>Total Revenue<br>Recognized", "Δ New-Business<br>Subscription", "Δ Renewal-Driven<br>Subscription", "Δ PS Fees", f"{scenario_b_name}<br>Total Revenue<br>Recognized"],
            [start_rev, d_sub_new, d_sub_renewal, d_ps, end_rev],
            "Revenue Bridge",
        )
        st.plotly_chart(fig_rev, width='stretch')

    elif selected_page == "📋 Raw Data":
        st.caption("Tables shown with months as columns, metrics as rows.")
        st.subheader(f"{scenario_a_name} — Phase 2 Output")
        st.dataframe(_bold_headers(style_wide(wide(p2a))), width='stretch')
        st.subheader(f"{scenario_b_name} — Phase 2 Output")
        st.dataframe(_bold_headers(style_wide(wide(p2b))), width='stretch')

st.caption("Built on the Bowtie Model (Winning by Design). All math is deterministic — no randomized variables anywhere in this model.")

_render_ai_fab()

if st.session_state["sm_last_known"] is None:
    st.session_state["sm_last_known"] = _snapshot()
