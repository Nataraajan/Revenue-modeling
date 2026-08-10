"""
Generates a traditional financial-model-format Excel workbook for WHATEVER
scenario is currently configured (any team size, any contract term, any
horizon) — not a fixed example. Called from app.py's download button.

Key generalizations beyond the v1 proof-of-concept:
- TCV and ARR are tracked as separate formula columns. They're only equal
  when term=12; for any other term, monthly recognition uses TCV/term while
  renewal churn/expansion/contraction math uses the annualized ARR
  (TCV*12/term) — mixing them up silently breaks correctness the moment
  someone picks a 6- or 24-month term.
- Renewal generations are computed dynamically: however many fit in
  num_months given the term and implementation lag, not a fixed count.
- The AE/BDR roster mirrors PodConfig's actual hire-month logic (phased
  cadence or custom schedule) instead of a hardcoded example team.

Known limitations, stated plainly (not silently dropped):
- No professional services fee recognition in this export (doubles the
  revenue-row complexity; a defensible v2 extension, not built here).
- No seasonality pattern support (flat 1.0 multiplier assumed).
- No Existing Book overlay in this export.
- Annual summary only covers FULL years that fit in num_months; any
  trailing partial year's months still appear in the monthly grids but
  aren't rolled into the Summary sheet's year columns.
"""

import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

BLUE = Font(color="0000FF")
BLACK = Font(color="000000")
GREEN = Font(color="008000")
BOLD = Font(bold=True)
HEADER_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
CURRENCY_FMT = '$#,##0;($#,##0);"-"'
PCT_FMT = '0.0%'
NUM_FMT = '#,##0'


def _phased_hire_months(count: int, cadence: int) -> list:
    return [i * cadence for i in range(count)]  # 0-indexed, matches PodConfig exactly


def generate_workbook_bytes(cfg: dict, num_months: int) -> bytes:
    term = int(cfg["contract_term"])
    lag = int(cfg["implementation_lag"])

    ae_hires_0idx = cfg.get("ae_hire_months") or _phased_hire_months(int(cfg["num_aes"]), int(cfg["hiring_cadence"]))
    bdr_hires_0idx = cfg.get("bdr_hire_months") or _phased_hire_months(int(cfg["num_bdrs"]), int(cfg["hiring_cadence"]))
    # Convert to 1-indexed display months for the spreadsheet
    ae_hires = [h + 1 for h in ae_hires_0idx]
    bdr_hires = [h + 1 for h in bdr_hires_0idx]

    ae_roster = [(f"AE-existing-{i+1}", 1, "Instant") for i in range(int(cfg["num_existing_aes"]))]
    ae_roster += [(f"AE-new-{i+1}", ae_hires[i], "Standard") for i in range(int(cfg["num_aes"]))]
    bdr_roster = [(f"BDR-existing-{i+1}", 1, "Instant") for i in range(int(cfg["num_existing_bdrs"]))]
    bdr_roster += [(f"BDR-new-{i+1}", bdr_hires[i], "Standard") for i in range(int(cfg["num_bdrs"]))]

    # How many renewal generations fit? Gen g's earliest possible go-live
    # (for the month-1 cohort) is 1 + lag + g*term. Include gen g only if
    # that's <= num_months (otherwise it contributes zero within the window).
    num_generations = 1
    g = 1
    while (1 + lag + g * term) <= num_months:
        num_generations += 1
        g += 1

    wb = openpyxl.Workbook()

    # =======================================================================
    # SHEET: Assumptions
    # =======================================================================
    ws = wb.active
    ws.title = "Assumptions"
    ws["A1"] = f"Revenue Architecture Model — {cfg['pod_name']}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Blue = input. Black = formula. Green = link to another sheet."
    ws["A2"].font = Font(italic=True, size=9)
    ws["A3"] = ("No PS fees, seasonality, or Existing Book overlay in this export. "
                "Annual summary covers full years only.")
    ws["A3"].font = Font(italic=True, size=9, color="808080")

    input_rows = [
        ("Horizon (months)", num_months), ("Contract term (months)", term),
        ("Implementation lag (months)", lag), ("", ""),
        ("AE — annual base ($)", cfg["ae_base"]), ("AE — annual variable @ 100% ($)", cfg["ae_variable"]),
        ("AE — annual quota ($)", cfg["ae_quota"]), ("BDR — annual base ($)", cfg["bdr_base"]),
        ("BDR — annual variable @ 100% ($)", cfg["bdr_variable"]), ("BDR — monthly SQL quota", cfg["bdr_monthly_sql_quota"]),
        ("", ""),
        ("Marketing leads/month", cfg["monthly_leads"]), ("Lead → MQL rate", cfg["lead_to_mql"]),
        ("MQL → SQL rate", cfg["mql_to_sql"]), ("AE self-sourced SQLs/month (per AE)", cfg["ae_self_sourced"]),
        ("", ""),
        ("Avg deal size — TCV ($)", cfg["avg_deal_size"]), ("Win rate — marketing-sourced", cfg["win_marketing"]),
        ("Win rate — BDR-sourced", cfg["win_bdr"]), ("Win rate — AE self-sourced", cfg["win_self"]),
        ("Execution efficiency", cfg["execution_efficiency"]), ("", ""),
        ("Renewal — annual gross churn rate", cfg["churn_rate"]), ("Renewal — annual expansion rate", cfg["expansion_rate"]),
        ("Renewal — annual contraction rate", cfg["contraction_rate"]),
    ]
    r = 5
    ref = {}
    key_map = {
        "Horizon (months)": "horizon", "Contract term (months)": "term", "Implementation lag (months)": "lag",
        "AE — annual quota ($)": "ae_quota", "BDR — monthly SQL quota": "bdr_sql_quota",
        "Marketing leads/month": "leads", "Lead → MQL rate": "l2m", "MQL → SQL rate": "m2s",
        "AE self-sourced SQLs/month (per AE)": "self_sourced", "Avg deal size — TCV ($)": "deal_size",
        "Win rate — marketing-sourced": "win_mkt", "Win rate — BDR-sourced": "win_bdr",
        "Win rate — AE self-sourced": "win_self", "Execution efficiency": "exec_eff",
        "Renewal — annual gross churn rate": "churn", "Renewal — annual expansion rate": "expansion",
        "Renewal — annual contraction rate": "contraction",
    }
    for label, value in input_rows:
        ws.cell(row=r, column=1, value=label)
        if label:
            c = ws.cell(row=r, column=2, value=value)
            c.font = BLUE
            if isinstance(value, float) and value <= 1.0:
                c.number_format = PCT_FMT
            elif "$" in label:
                c.number_format = CURRENCY_FMT
            else:
                c.number_format = NUM_FMT
            if label in key_map:
                ref[key_map[label]] = f"Assumptions!$B${r}"
        r += 1
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 14

    # =======================================================================
    # SHEET: Capacity & Bookings
    # =======================================================================
    ws2 = wb.create_sheet("Capacity & Bookings")
    ws2["A1"] = "Capacity & Bookings"
    ws2["A1"].font = Font(bold=True, size=14)
    CAP_FIRST_COL = 5

    ws2.cell(row=3, column=4, value="Month →").font = BOLD
    for m in range(1, num_months + 1):
        c = ws2.cell(row=3, column=CAP_FIRST_COL + m - 1, value=m)
        c.font = BOLD
        c.fill = HEADER_FILL

    def _write_ramp_row(ws, row, hire_month, ramp_type_cell_row):
        for m in range(1, num_months + 1):
            col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
            month_cell = f"{col_letter}$3"
            hire_ref = f"$B{row}"
            ramp_ref = f"$C{row}"
            formula = (
                f'=IF({month_cell}<{hire_ref},0,'
                f'IF({ramp_ref}="Instant",1,'
                f'IF({month_cell}-{hire_ref}>=2,1,'
                f'IF({month_cell}-{hire_ref}=1,0.66,0.33))))'
            )
            c = ws.cell(row=row, column=CAP_FIRST_COL + m - 1, value=formula)
            c.font = BLACK
            c.number_format = PCT_FMT

    row = 5
    ws2.cell(row=row, column=1, value="AE Roster").font = BOLD
    row += 1
    ae_ramp_rows = []
    for name, hire_month, ramp_type in ae_roster:
        ws2.cell(row=row, column=1, value=name)
        ws2.cell(row=row, column=2, value=hire_month).font = BLUE
        ws2.cell(row=row, column=3, value=ramp_type).font = BLUE
        _write_ramp_row(ws2, row, hire_month, row)
        ae_ramp_rows.append(row)
        row += 1

    row += 1
    ws2.cell(row=row, column=1, value="AE $ Capacity by Rep").font = BOLD
    row += 1
    ae_capacity_rows = []
    for i, _ in enumerate(ae_roster):
        ramp_row = ae_ramp_rows[i]
        ws2.cell(row=row, column=1, value=ae_roster[i][0])
        for m in range(1, num_months + 1):
            col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
            c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f'={col_letter}{ramp_row}*({ref["ae_quota"]}/12)')
            c.font = BLACK
            c.number_format = CURRENCY_FMT
        ae_capacity_rows.append(row)
        row += 1

    total_ae_capacity_row = row
    ws2.cell(row=row, column=1, value="Total AE $ Capacity").font = BOLD
    for m in range(1, num_months + 1):
        col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
        refs = "+".join(f"{col_letter}{rr}" for rr in ae_capacity_rows) if ae_capacity_rows else "0"
        c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f"={refs}")
        c.font = BOLD
        c.number_format = CURRENCY_FMT
    row += 2

    ws2.cell(row=row, column=1, value="AE Self-Sourced SQLs by Rep").font = BOLD
    row += 1
    self_sourced_rows = []
    for i, _ in enumerate(ae_roster):
        ramp_row = ae_ramp_rows[i]
        ws2.cell(row=row, column=1, value=ae_roster[i][0])
        for m in range(1, num_months + 1):
            col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
            c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f'={col_letter}{ramp_row}*{ref["self_sourced"]}')
            c.font = BLACK
            c.number_format = NUM_FMT
        self_sourced_rows.append(row)
        row += 1

    total_self_sourced_row = row
    ws2.cell(row=row, column=1, value="Total AE Self-Sourced SQLs").font = BOLD
    for m in range(1, num_months + 1):
        col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
        refs = "+".join(f"{col_letter}{rr}" for rr in self_sourced_rows) if self_sourced_rows else "0"
        c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f"={refs}")
        c.font = BOLD
        c.number_format = NUM_FMT
    row += 2

    ws2.cell(row=row, column=1, value="BDR Roster").font = BOLD
    row += 1
    bdr_ramp_rows = []
    for name, hire_month, ramp_type in bdr_roster:
        ws2.cell(row=row, column=1, value=name)
        ws2.cell(row=row, column=2, value=hire_month).font = BLUE
        ws2.cell(row=row, column=3, value=ramp_type).font = BLUE
        _write_ramp_row(ws2, row, hire_month, row)
        bdr_ramp_rows.append(row)
        row += 1

    row += 1
    ws2.cell(row=row, column=1, value="BDR SQLs by Rep").font = BOLD
    row += 1
    bdr_sql_rows = []
    for i, _ in enumerate(bdr_roster):
        ramp_row = bdr_ramp_rows[i]
        ws2.cell(row=row, column=1, value=bdr_roster[i][0])
        for m in range(1, num_months + 1):
            col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
            c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f'={col_letter}{ramp_row}*{ref["bdr_sql_quota"]}')
            c.font = BLACK
            c.number_format = NUM_FMT
        bdr_sql_rows.append(row)
        row += 1

    total_bdr_sql_row = row
    ws2.cell(row=row, column=1, value="Total BDR SQLs").font = BOLD
    for m in range(1, num_months + 1):
        col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
        refs = "+".join(f"{col_letter}{rr}" for rr in bdr_sql_rows) if bdr_sql_rows else "0"
        c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f"={refs}")
        c.font = BOLD
        c.number_format = NUM_FMT
    row += 2

    marketing_sql_row = row
    ws2.cell(row=row, column=1, value="Marketing SQLs").font = BOLD
    for m in range(1, num_months + 1):
        col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
        c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f'={ref["leads"]}*{ref["l2m"]}*{ref["m2s"]}')
        c.font = BLACK
        c.number_format = NUM_FMT
    row += 2

    demand_row = row
    ws2.cell(row=row, column=1, value="Demand-Constrained Bookings ($)").font = BOLD
    for m in range(1, num_months + 1):
        col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
        mkt = f"{col_letter}{marketing_sql_row}*{ref['win_mkt']}*{ref['deal_size']}"
        bdr = f"{col_letter}{total_bdr_sql_row}*{ref['win_bdr']}*{ref['deal_size']}"
        slf = f"{col_letter}{total_self_sourced_row}*{ref['win_self']}*{ref['deal_size']}"
        c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1, value=f"={mkt}+{bdr}+{slf}")
        c.font = BLACK
        c.number_format = CURRENCY_FMT
    row += 1

    bookings_row = row
    ws2.cell(row=row, column=1, value="Actual Bookings ($ TCV)").font = Font(bold=True, size=11)
    for m in range(1, num_months + 1):
        col_letter = get_column_letter(CAP_FIRST_COL + m - 1)
        c = ws2.cell(row=row, column=CAP_FIRST_COL + m - 1,
                      value=f'=MIN({col_letter}{total_ae_capacity_row},{col_letter}{demand_row})*{ref["exec_eff"]}')
        c.font = Font(bold=True)
        c.number_format = CURRENCY_FMT

    ws2.column_dimensions["A"].width = 28
    ws2.column_dimensions["B"].width = 10
    ws2.column_dimensions["C"].width = 10

    wb.save("/tmp/_fm_stage1.xlsx")  # stage save; continued in-memory below via reload
    return _build_revenue_and_summary(wb, ref, term, lag, num_months, num_generations,
                                       CAP_FIRST_COL, bookings_row)


def _build_revenue_and_summary(wb, ref, term, lag, num_months, num_generations, cap_first_col, bookings_row):
    ws = wb.create_sheet("Revenue Recognition")
    ws["A1"] = "Revenue Recognition — Cohort Waterfall"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"{num_generations} generation(s) fit in this {num_months}-month horizon at a "
                f"{term}-month term. ARR and TCV are tracked separately since term may not be 12.")
    ws["A2"].font = Font(italic=True, size=9)

    RR_FIRST_COL = 11  # columns 1-10: Cohort/Signed/GoLive/RecEnd/TCV/ARR/Churned/Retained/Expansion/Contraction

    ws.cell(row=4, column=4, value="Month →").font = BOLD
    for m in range(1, num_months + 1):
        c = ws.cell(row=4, column=RR_FIRST_COL + m - 1, value=m)
        c.font = BOLD
        c.fill = HEADER_FILL

    headers = ["Cohort", "Signed Mo.", "Go-Live Mo.", "Rec. End Mo.", "Cohort TCV", "Cohort ARR",
               "Churned $", "Retained $", "Expansion $", "Contraction $"]
    for i, h in enumerate(headers):
        ws.cell(row=5, column=1 + i, value=h).font = BOLD

    row = 6
    all_gen_rows = []  # list of dicts: {gen: g, month: m, row: r}
    prev_gen_row_lookup = {}  # (gen-1, month) -> row number

    for gen in range(num_generations):
        if gen > 0:
            row += 1
            ws.cell(row=row, column=1, value=f"Renewal Generation {gen}").font = BOLD
            row += 1
        gen_row_lookup = {}
        for m in range(1, num_months + 1):
            label = f"Gen {gen} — Month {m}" if gen == 0 else f"Gen {gen} — renews Month {m}"
            ws.cell(row=row, column=1, value=label)

            if gen == 0:
                ws.cell(row=row, column=2, value=m).font = BLACK
                ws.cell(row=row, column=3, value=f"=B{row}+{ref['lag']}").font = BLACK
                tcv_cell = ws.cell(row=row, column=5, value=f"='Capacity & Bookings'!{get_column_letter(cap_first_col + m - 1)}{bookings_row}")
                tcv_cell.font = GREEN
                tcv_cell.number_format = CURRENCY_FMT
            else:
                prev_row = prev_gen_row_lookup.get((gen - 1, m))
                if prev_row is None:
                    row += 1
                    continue
                ws.cell(row=row, column=2, value=f"=D{prev_row}+1").font = BLACK
                ws.cell(row=row, column=3, value=f"=B{row}").font = BLACK  # renewals: 0 lag
                # TCV = renewed ARR converted back to TCV: ARR * (term/12)
                # Renewed ARR = Retained(H) + Expansion(I) - Contraction(J) from the PREVIOUS
                # generation's row — not G/H/I, which are Churned/Retained/Expansion instead.
                tcv_cell = ws.cell(row=row, column=5, value=f"=(H{prev_row}+I{prev_row}-J{prev_row})*({ref['term']}/12)")
                tcv_cell.font = BLACK
                tcv_cell.number_format = CURRENCY_FMT

            ws.cell(row=row, column=4, value=f"=C{row}+{ref['term']}-1").font = BLACK

            # ARR = TCV annualized: TCV * (12/term)
            arr_cell = ws.cell(row=row, column=6, value=f"=E{row}*(12/{ref['term']})")
            arr_cell.font = BLACK
            arr_cell.number_format = CURRENCY_FMT

            if gen >= 1 or gen < num_generations - 1:
                # Two distinct reasons a row needs these columns, not a redundant OR:
                # (a) gen>=1 rows ARE renewal outcomes that need reporting on the
                #     Summary sheet, even if nothing renews further from them.
                # (b) gen < num_generations-1 rows (including Gen0) need to FEED
                #     the next generation's TCV formula, which reads these columns
                #     from the PREVIOUS row. Gen0 satisfies (b) but not (a); the
                #     last generation satisfies (a) but not (b) — both are real,
                #     neither condition alone covers both cases.
                ws.cell(row=row, column=7, value=f"=F{row}*{ref['churn']}").font = BLACK
                ws.cell(row=row, column=7).number_format = CURRENCY_FMT
                ws.cell(row=row, column=8, value=f"=F{row}-G{row}").font = BLACK
                ws.cell(row=row, column=8).number_format = CURRENCY_FMT
                ws.cell(row=row, column=9, value=f"=H{row}*{ref['expansion']}").font = BLACK
                ws.cell(row=row, column=9).number_format = CURRENCY_FMT
                ws.cell(row=row, column=10, value=f"=H{row}*{ref['contraction']}").font = BLACK
                ws.cell(row=row, column=10).number_format = CURRENCY_FMT

            # Monthly recognition: TCV/term within [go-live, rec_end]
            for mm in range(1, num_months + 1):
                col_letter = get_column_letter(RR_FIRST_COL + mm - 1)
                month_header_cell = f"{col_letter}$4"
                formula = f'=IF(AND({month_header_cell}>=$C{row},{month_header_cell}<=$D{row}),$E{row}/{ref["term"]},0)'
                c = ws.cell(row=row, column=RR_FIRST_COL + mm - 1, value=formula)
                c.font = BLACK
                c.number_format = CURRENCY_FMT

            gen_row_lookup[m] = row
            all_gen_rows.append({"gen": gen, "month": m, "row": row})
            row += 1
        prev_gen_row_lookup = {(gen, m): r for m, r in gen_row_lookup.items()}

    row += 1
    total_rev_row = row
    ws.cell(row=row, column=1, value="Total Recognized Revenue").font = Font(bold=True, size=11)
    all_data_rows = [d["row"] for d in all_gen_rows]
    for mm in range(1, num_months + 1):
        col_letter = get_column_letter(RR_FIRST_COL + mm - 1)
        refs = "+".join(f"{col_letter}{r}" for r in all_data_rows)
        c = ws.cell(row=row, column=RR_FIRST_COL + mm - 1, value=f"={refs}")
        c.font = Font(bold=True)
        c.number_format = CURRENCY_FMT
    row += 1

    live_arr_row = row
    ws.cell(row=row, column=1, value="Live ARR").font = Font(bold=True, size=11)
    for mm in range(1, num_months + 1):
        col_letter = get_column_letter(RR_FIRST_COL + mm - 1)
        month_header_cell = f"{col_letter}$4"
        terms = [f'IF(AND({month_header_cell}>=$C{r},{month_header_cell}<=$D{r}),$F{r},0)' for r in all_data_rows]
        formula = "=" + "+".join(terms) if terms else "=0"
        c = ws.cell(row=row, column=RR_FIRST_COL + mm - 1, value=formula)
        c.font = Font(bold=True)
        c.number_format = CURRENCY_FMT

    ws.column_dimensions["A"].width = 26
    for cl in ["E", "F", "G", "H", "I", "J"]:
        ws.column_dimensions[cl].width = 13

    # =======================================================================
    # SHEET: Summary
    # =======================================================================
    ws3 = wb.create_sheet("Summary")
    ws3["A1"] = "Annual Summary"
    ws3["A1"].font = Font(bold=True, size=14)
    ws3["A2"] = "Covers full years only; a trailing partial year (if any) is excluded from this rollup."
    ws3["A2"].font = Font(italic=True, size=9)

    rr = "'Revenue Recognition'!"
    num_full_years = num_months // 12
    years = [(y + 1, y * 12 + 1, y * 12 + 12) for y in range(num_full_years)]

    def rr_col(month):
        return get_column_letter(RR_FIRST_COL + month - 1)

    ws3.cell(row=4, column=1, value="Metric").font = BOLD
    for yi, (yr, s, e) in enumerate(years):
        c = ws3.cell(row=4, column=2 + yi, value=f"Year {yr}")
        c.font = BOLD
        c.fill = HEADER_FILL

    metric_row = {}
    r = 5
    labels = ["Beginning ARR", "New ARR (went live)", "Expansion ARR", "Contraction ARR", "Churned ARR",
              "Other / Boundary Effect", "Ending ARR", "", "Net Revenue Retention (NRR)", "Gross $ Churn Rate",
              "", "Total Revenue Recognized"]
    for label in labels:
        ws3.cell(row=r, column=1, value=label).font = BOLD if label and "Other" not in label else BLACK
        if label:
            metric_row[label] = r
        r += 1

    gen0_rows = sorted([d["row"] for d in all_gen_rows if d["gen"] == 0])
    gen1_rows = sorted([d["row"] for d in all_gen_rows if d["gen"] == 1]) if num_generations > 1 else []

    for yi, (yr, s, e) in enumerate(years):
        col = 2 + yi
        col_letter = get_column_letter(col)

        beg_cell = ws3.cell(row=metric_row["Beginning ARR"], column=col)
        if yi == 0:
            beg_cell.value = 0
            beg_cell.font = BLUE
        else:
            prev_col_letter = get_column_letter(col - 1)
            beg_cell.value = f"={prev_col_letter}{metric_row['Ending ARR']}"
            beg_cell.font = BLACK
        beg_cell.number_format = CURRENCY_FMT

        end_cell = ws3.cell(row=metric_row["Ending ARR"], column=col, value=f"={rr}{rr_col(e)}{live_arr_row}")
        end_cell.font = GREEN
        end_cell.number_format = CURRENCY_FMT

        if gen0_rows:
            new_arr_cell = ws3.cell(
                row=metric_row["New ARR (went live)"], column=col,
                value=(f"=SUMIFS({rr}F{gen0_rows[0]}:F{gen0_rows[-1]},"
                       f"{rr}C{gen0_rows[0]}:C{gen0_rows[-1]},\">=\"&{s},"
                       f"{rr}C{gen0_rows[0]}:C{gen0_rows[-1]},\"<=\"&{e})")
            )
        else:
            new_arr_cell = ws3.cell(row=metric_row["New ARR (went live)"], column=col, value=0)
        new_arr_cell.font = GREEN
        new_arr_cell.number_format = CURRENCY_FMT

        if gen1_rows:
            for label, gcol in [("Expansion ARR", "I"), ("Contraction ARR", "J"), ("Churned ARR", "G")]:
                c = ws3.cell(
                    row=metric_row[label], column=col,
                    value=(f"=SUMIFS({rr}{gcol}{gen1_rows[0]}:{gcol}{gen1_rows[-1]},"
                           f"{rr}D{gen0_rows[0]}:D{gen0_rows[-1]},\">=\"&{s},"
                           f"{rr}D{gen0_rows[0]}:D{gen0_rows[-1]},\"<=\"&{e})")
                )
                c.font = GREEN
                c.number_format = CURRENCY_FMT
        else:
            for label in ["Expansion ARR", "Contraction ARR", "Churned ARR"]:
                c = ws3.cell(row=metric_row[label], column=col, value=0)
                c.font = BLACK
                c.number_format = CURRENCY_FMT

        beg_ref = f"{col_letter}{metric_row['Beginning ARR']}"
        new_ref = f"{col_letter}{metric_row['New ARR (went live)']}"
        exp_ref = f"{col_letter}{metric_row['Expansion ARR']}"
        contr_ref = f"{col_letter}{metric_row['Contraction ARR']}"
        churn_ref = f"{col_letter}{metric_row['Churned ARR']}"
        end_ref = f"{col_letter}{metric_row['Ending ARR']}"
        other_cell = ws3.cell(row=metric_row["Other / Boundary Effect"], column=col,
                               value=f"={end_ref}-({beg_ref}+{new_ref}+{exp_ref}-{contr_ref}-{churn_ref})")
        other_cell.font = BLACK
        other_cell.number_format = CURRENCY_FMT

        nrr_cell = ws3.cell(row=metric_row["Net Revenue Retention (NRR)"], column=col,
                             value=f'=IFERROR(({beg_ref}+{exp_ref}-{contr_ref}-{churn_ref})/{beg_ref},"N/A")')
        nrr_cell.font = BLACK
        nrr_cell.number_format = PCT_FMT

        churnrate_cell = ws3.cell(row=metric_row["Gross $ Churn Rate"], column=col,
                                   value=f'=IFERROR({churn_ref}/{beg_ref},"N/A")')
        churnrate_cell.font = BLACK
        churnrate_cell.number_format = PCT_FMT

        rev_cell = ws3.cell(row=metric_row["Total Revenue Recognized"], column=col,
                             value=f"=SUM({rr}{rr_col(s)}{total_rev_row}:{rr_col(e)}{total_rev_row})")
        rev_cell.font = GREEN
        rev_cell.number_format = CURRENCY_FMT

    ws3.column_dimensions["A"].width = 30
    ws3.column_dimensions["B"].width = 15
    ws3.column_dimensions["C"].width = 15

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
