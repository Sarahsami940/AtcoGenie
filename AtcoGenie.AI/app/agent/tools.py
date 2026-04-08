"""
AtcoGenie AI Engine — LangChain Tools (Phase 1)

Each tool maps to a PharmaCRM Stored Procedure.
Security is enforced BEFORE execution via the SecurityContext.
Team/Role parameters are auto-injected from ResolvedUserContext.
"""

import json
import csv
import os
import uuid
from collections import Counter
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from app.security.context import SecurityContext
from app.database.manager import DatabaseManager
from app.agent.user_context import ResolvedUserContext
from app.logging_config import get_logger
from app.agent import progress

logger = get_logger(__name__)


# =====================================================================
# In-Memory Last-Result Cache (per tool call, keyed by report+args)
# Allows the export tool to re-query without user re-describing parameters
# =====================================================================
_last_report_params: dict = {}  # e.g. {"report": "customer_sales", "args": (...)}


# =====================================================================
# Input Schemas (What the LLM can extract from user prompts)
# =====================================================================

class CustomerSalesInput(BaseModel):
    from_year: int = Field(description="Start year, e.g. 2025")
    from_month: int = Field(description="Start month (1-12)")
    to_year: int = Field(description="End year, e.g. 2026")
    to_month: int = Field(description="End month (1-12)")
    team_name: Optional[str] = Field(default=None, description="Optional team name or ID to filter by. Leave empty to use the user's default team(s).")
    distributor_type: Optional[str] = Field(default="0", description="Distributor type: '01' for Trade, '02' for Institution, '0' for all")
    product_id: Optional[str] = Field(default="0", description="Product ID filter. '0' for all products. Use search_products tool first if user gives a product name.")
    product_names: Optional[List[str]] = Field(default=None, description="Product names to filter by (e.g. ['Ascard', 'Betaderm']). If provided, IDs are resolved automatically.")


class SearchProductsInput(BaseModel):
    query: str = Field(description="Product name or partial name to search for, e.g. 'Ascard' or 'Betaderm'")


class SalesVsTargetInput(BaseModel):
    date_from: str = Field(description="Start date in YYYY/MM/DD format, e.g. '2024/07/01'")
    date_to: str = Field(description="End date in YYYY/MM/DD format, e.g. '2025/06/30'")
    team_name: Optional[str] = Field(default=None, description="Optional team name to filter by. Leave empty to use the user's default team(s).")
    product_id: Optional[str] = Field(default="", description="Product ID filter. Empty string for all.")
    territory_id: Optional[str] = Field(default="", description="Territory ID filter. Empty string for all.")
    sales_channel: Optional[str] = Field(default="1", description="Sales channel. Default is '1'.")


class IncentiveSummaryInput(BaseModel):
    fiscal_year_code: str = Field(description="Fiscal year code, e.g. '20242025' for the year starting July 2024")
    month_year: str = Field(description="Month/year filter in YYYY/MM/DD format, e.g. '2024/07/01'")
    team_name: Optional[str] = Field(default=None, description="Optional team name to filter. Leave empty for all user's teams.")
    group_by: Optional[str] = Field(default="Team,Role,", description="Report hierarchy grouping, e.g. 'Team,Role,'")


class ExportReportInput(BaseModel):
    report_name: str = Field(description="Name of the last report to export, e.g. 'Customer Sales Report', 'Sales vs Target Report', 'Incentive Summary Report'")
# =====================================================================
# Tool Factory
# =====================================================================

def get_agent_tools(
    security_context: SecurityContext,
    db_manager: DatabaseManager,
    user_context: ResolvedUserContext,
) -> List[StructuredTool]:
    """
    Generates LangChain tools bound to the user's SecurityContext and resolved teams/role.
    """

    # Map: SP name → keywords that appear in the DB form_id for that SP
    # This bridges the gap between raw SP names (used in code) and UI form_ids (stored in DB)
    SP_FORM_ID_KEYWORDS: dict[str, list[str]] = {
        "SS_sp_CustomerSales_YTD_Excel":          ["customersales", "ytd_customer"],
        "Sp_PharmaCRM_SVT":                       ["svt", "salestarget", "salesvstarget"],
        "Sp_PharmaCRM_GetIncentiveProcessReport": ["incentive"],
    }
    # Accept only the current application_code value from the DB
    PHARMA_APP_CODES = {"pharmacrmv2"}

    def _check_access(sp_name: str, report_label: str) -> Optional[str]:
        """Returns an error message if access is denied, or None if allowed.
        Admins always bypass. Non-admins need a matching form_right in Redis.
        """
        if user_context.is_admin:
            logger.info("access_granted_admin", tool=sp_name, user=security_context.user_id)
            return None

        keywords = SP_FORM_ID_KEYWORDS.get(sp_name, [])

        for right in security_context.role_profile.form_rights:
            app = (right.application_code or "").lower()
            fid = (right.form_id or "").lower()

            if app not in PHARMA_APP_CODES:
                continue

            # Match by: exact SP name OR any keyword present in form_id
            if fid == sp_name.lower() or any(kw in fid for kw in keywords):
                if right.view_mode is True:
                    logger.info("access_granted", tool=sp_name, matched_form_id=right.form_id, user=security_context.user_id)
                    return None

        logger.warning("security_block", tool=sp_name, user=security_context.user_id,
                       role=user_context.user_role, is_admin=user_context.is_admin,
                       rights_count=len(security_context.role_profile.form_rights))
        return f"ACCESS DENIED: You do not have permission to view the {report_label}."

    def _resolve_team_ids(team_name: Optional[str]) -> str:
        """Resolves which TeamIDs to pass to the SP."""
        if team_name:
            matched_id = user_context.get_team_id_by_name(team_name)
            if matched_id:
                return matched_id
            return team_name

        # No team specified by user
        if user_context.team_ids_csv:
            return user_context.team_ids_csv

        # Admin with no direct team assignment — '0' means "all" in the SPs
        if user_context.is_admin:
            return "0"

        return ""

    async def _fetch_and_summarize(sp_name: str, report_name: str, args: tuple, max_sample: int = 20) -> str:
        """
        Fetches SP output via sync pyodbc (fast, no hang) and computes
        global + per-group aggregates for LLM consumption.
        """
        logger.info("sp_sync_call", sp=sp_name, args=str(args))
        await progress.emit("Fetching data from the database...")

        try:
            columns, all_rows = await db_manager.execute_sp_sync("pharma", sp_name, *args)
        except Exception as e:
            logger.error("sp_sync_error", sp=sp_name, error=str(e))
            return f"Error executing {report_name}: {str(e)}"

        total = len(all_rows)
        if total == 0 or not columns:
            return f"The {report_name} returned no data for the specified criteria."

        await progress.emit(f"Analyzing {total:,} records...")

        # Detect numeric vs categorical columns
        import decimal
        numeric_indices = []
        categorical_indices = []
        for i, col in enumerate(columns):
            for r in all_rows[:100]:
                if r[i] is not None:
                    if isinstance(r[i], (int, float, decimal.Decimal)):
                        numeric_indices.append(i)
                    elif isinstance(r[i], str):
                        categorical_indices.append(i)
                    break

        # Global aggregates
        numeric_sums = {columns[i]: 0.0 for i in numeric_indices}
        numeric_mins = {columns[i]: float('inf') for i in numeric_indices}
        numeric_maxs = {columns[i]: float('-inf') for i in numeric_indices}

        # Per-group aggregates
        GROUP_TOP_N = 15
        priority_keywords = ["customer", "product", "employee", "territory", "region", "team", "brick"]
        selected_groups = []
        for kw in priority_keywords:
            for i in categorical_indices:
                if kw in columns[i].lower() and i not in selected_groups:
                    selected_groups.append(i)
                    if len(selected_groups) >= 2:
                        break
            if len(selected_groups) >= 2:
                break
        if not selected_groups:
            selected_groups = categorical_indices[:2]

        group_sums = {gi: {} for gi in selected_groups}
        group_counts = {gi: Counter() for gi in selected_groups}

        for row in all_rows:
            # Global numeric
            for i in numeric_indices:
                v = row[i]
                if v is not None:
                    fv = float(v)
                    col = columns[i]
                    numeric_sums[col] += fv
                    if fv < numeric_mins[col]: numeric_mins[col] = fv
                    if fv > numeric_maxs[col]: numeric_maxs[col] = fv

            # Per-group numeric
            for gi in selected_groups:
                gval = row[gi]
                if gval is None:
                    continue
                group_counts[gi][gval] += 1
                if gval not in group_sums[gi]:
                    group_sums[gi][gval] = {columns[ni]: 0.0 for ni in numeric_indices}
                for ni in numeric_indices:
                    v = row[ni]
                    if v is not None:
                        group_sums[gi][gval][columns[ni]] += float(v)

        # Cache for export
        _last_report_params.update({
            "sp_name": sp_name, "report_name": report_name,
            "args": args, "columns": columns, "total": total
        })

        # Build clean summary for LLM — aggregates only, no raw data
        summary_parts = [
            f"## {report_name}",
        ]

        # Global totals
        if numeric_sums:
            summary_parts.append("\n### Overall Totals (aggregated from ALL records)")
            for col in list(numeric_sums.keys())[:8]:
                summary_parts.append(
                    f"- **{col}**: Total={numeric_sums[col]:,.2f}, "
                    f"Min={numeric_mins[col]:,.2f}, Max={numeric_maxs[col]:,.2f}, "
                    f"Avg={numeric_sums[col]/total:,.4f}"
                )

        # Per-group breakdowns (revenue-first)
        for gi in selected_groups:
            gsums = group_sums[gi]
            gcol = columns[gi]
            if not gsums:
                continue

            sort_col = None
            for nc in numeric_sums:
                if any(kw in nc.lower() for kw in ["value", "amount", "revenue", "net", "sale", "price"]):
                    sort_col = nc
                    break
            if sort_col is None and numeric_indices:
                sort_col = columns[numeric_indices[0]]

            unique_count = len(gsums)
            if sort_col:
                top_groups = sorted(gsums.items(), key=lambda x: x[1].get(sort_col, 0), reverse=True)[:GROUP_TOP_N]
                summary_parts.append(f"\n### Top {len(top_groups)} of {unique_count} unique **{gcol}** (by {sort_col}, aggregated from ALL records)")
                for rank, (gval, gnums) in enumerate(top_groups, 1):
                    count = group_counts[gi][gval]
                    num_line = ", ".join(f"{k}={v:,.2f}" for k, v in list(gnums.items())[:4])
                    summary_parts.append(f"{rank}. **{gval}** — Records: {count:,} | {num_line}")

        if total > 500:
            first_group = selected_groups[0] if selected_groups else None
            entity_count = len(group_sums.get(first_group, {})) if first_group is not None else 0
            entity_name = columns[first_group] if first_group is not None else "entities"
            summary_parts.append(
                f"\n💡 Dataset has {total:,} records across {entity_count} unique {entity_name}s. "
                f"Say 'export CSV' for full raw data."
            )

        return "\n".join(summary_parts)

    def _summarize_results(results: list[dict], report_name: str, max_sample: int = 20) -> str:
        """Produces a concise summary of large result sets for the LLM."""
        # Strip truncation sentinel if present
        was_truncated = False
        cap = 0
        if results and results[-1].get("__truncated__"):
            was_truncated = True
            cap = results[-1].get("__cap__", 0)
            results = results[:-1]

        total = len(results)
        if total == 0:
            return f"The {report_name} returned no data."

        # Automatically export to CSV if the result set is large (e.g., > 1,500 rows)
        export_md = ""
        if total > 1500:
            try:
                # Target the .NET Server's wwwroot directory so it serves the file automatically
                export_dir = r"d:\Office Stuff\AtcoGenie\AtcoGenie.Server\wwwroot\exports"
                os.makedirs(export_dir, exist_ok=True)
                
                safe_name = report_name.replace(' ', '_').replace('/', '')
                filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.csv"
                filepath = os.path.join(export_dir, filename)
                
                with open(filepath, 'w', newline='', encoding='utf-8') as f:
                    columns = list(results[0].keys())
                    writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(results)
                
                # Resolves safely on whatever domain the frontend is hosted
                export_url = f"/exports/{filename}"
                export_md = f"\n\n🚨 **LARGE DATASET DETECTED**: I have generated a full downloadable CSV report here: [Download Full {report_name}]({export_url}). Please provide this link to the user!"
            except Exception as e:
                logger.error("csv_export_failed", error=str(e))
                export_md = "\n\n*(Note: Could not generate CSV export due to an internal error.)*"

        columns = list(results[0].keys())
        sample_rows = results[:100]
        numeric_cols = []
        categorical_cols = []
        for col in columns:
            vals = [r.get(col) for r in sample_rows if r.get(col) is not None]
            if vals and all(isinstance(v, (int, float)) for v in vals):
                numeric_cols.append(col)
            elif vals and all(isinstance(v, str) for v in vals):
                categorical_cols.append(col)

        summary_parts = [
            f"## {report_name} Summary",
            f"**Rows analysed:** {total:,}" + (f" ⚠️ *(results capped at {cap:,} — actual dataset is larger. Narrow by team or product for complete data.)*" if was_truncated else ""),
            f"**Columns ({len(columns)}):** {', '.join(columns)}",
        ]

        if numeric_cols:
            summary_parts.append("\n### Numeric Aggregates")
            for col in numeric_cols[:8]:
                vals = [r[col] for r in results if isinstance(r.get(col), (int, float))]
                if vals:
                    summary_parts.append(
                        f"- **{col}**: Total={sum(vals):,.2f}, Avg={sum(vals)/len(vals):,.2f}, "
                        f"Min={min(vals):,.2f}, Max={max(vals):,.2f}"
                    )

        if categorical_cols:
            summary_parts.append("\n### Top Categories")
            for col in categorical_cols[:5]:
                counter = Counter(r.get(col, "") for r in results)
                top5 = counter.most_common(5)
                summary_parts.append(f"- **{col}**: {', '.join(f'{k} ({v:,})' for k, v in top5)}")

        sample = results[:max_sample]
        summary_parts.append(f"\n### Sample Data (first {len(sample)} rows)")
        summary_parts.append(json.dumps(sample, default=str, indent=2))
        
        if export_md:
            summary_parts.append(export_md)

        return "\n".join(summary_parts)

    async def resolve_product_ids_by_names(names: List[str]) -> dict[str, tuple[str, str]]:
        """Looks up the SINGLE best-matching ProductID for each product name.
        Priority: exact match > starts-with > contains.
        Returns dict: name -> (product_id, matched_product_name)
        """
        mapping: dict[str, tuple[str, str]] = {}
        for name in names:
            try:
                rows = await db_manager.execute_raw(
                    "pharma",
                    "SELECT DISTINCT ProductID, Product FROM SS_Product_Setup WHERE Product LIKE ? ORDER BY Product",
                    f"%{name}%"
                )
                if not rows:
                    mapping[name] = ("", "")
                    logger.warning("product_name_not_found", name=name)
                    continue

                # Pick single best match: exact > starts-with > any
                name_lower = name.lower()
                exact = [r for r in rows if r["Product"].lower() == name_lower]
                starts = [r for r in rows if r["Product"].lower().startswith(name_lower)]
                best = (exact or starts or rows)[0]

                pid = str(best["ProductID"]).strip()
                pname = str(best["Product"]).strip()
                mapping[name] = (pid, pname)
                logger.info("product_name_resolved", search=name, matched=pname, id=pid)
            except Exception as e:
                logger.error("product_resolve_error", name=name, error=str(e))
                mapping[name] = ("", "")
        return mapping

    # -----------------------------------------------------------------
    # Tool 0: Product Search  (SS_Product_Setup)
    # -----------------------------------------------------------------
    async def run_search_products(query: str) -> str:
        """Search for products by name in PharmaCRM."""
        try:
            rows = await db_manager.execute_raw(
                "pharma",
                "SELECT DISTINCT ProductID, Product FROM SS_Product_Setup WHERE Product LIKE ? ORDER BY Product",
                f"%{query}%"
            )
            if not rows:
                return f"No products found matching '{query}'. Please check the spelling."

            results = [{"ProductID": r["ProductID"], "ProductName": r["Product"]} for r in rows[:30]]
            return json.dumps(results, default=str)
        except Exception as e:
            logger.error("product_search_error", query=query, error=str(e))
            return f"Error searching products: {str(e)}"

    # -----------------------------------------------------------------
    # Tool 1: Customer Sales Report (SS_sp_CustomerSales_YTD_Excel)
    # -----------------------------------------------------------------
    async def run_customer_sales(
        from_year: int,
        from_month: int,
        to_year: int,
        to_month: int,
        team_name: Optional[str] = None,
        distributor_type: Optional[str] = "0",
        product_id: Optional[str] = "0",
        product_names: Optional[List[str]] = None,
    ) -> str:
        """Retrieves the Customer Sales YTD report showing distributor-wise customer data,
        sales units and value, brick-wise breakdown, and customers not buying products."""

        sp_name = "SS_sp_CustomerSales_YTD_Excel"

        # Security Check
        denied = _check_access(sp_name, "Customer Sales Report")
        if denied:
            return denied

        # Validate date range (max 2 years)
        total_months = (to_year - from_year) * 12 + (to_month - from_month)
        if total_months > 24 or total_months < 0:
            return "Invalid date range. The Customer Sales Report supports a maximum of 2 years."

        team_ids = _resolve_team_ids(team_name)
        if not team_ids:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return f"I could not resolve your team. Your available teams are: {available}. Please specify which team you'd like to see."

        # If product names provided, resolve them to best-matched single IDs and run comparison
        if product_names:
            name_to_match = await resolve_product_ids_by_names(product_names)
            not_found = [n for n, (pid, _) in name_to_match.items() if not pid]
            if not_found:
                return (
                    f"Could not find products matching: {', '.join(not_found)}. "
                    f"Please check the spelling or try the `search_products` tool to explore available product names."
                )

            period = f"{from_year}/{from_month:02d}–{to_year}/{to_month:02d}"

            # Point 4: fetch all product SPs in PARALLEL instead of sequentially
            async def _fetch_one_product(search_name: str, pid: str, matched_name: str) -> str:
                """Runs a single product SP and returns a formatted markdown section."""
                try:
                    logger.info("product_comparison_sp", product=matched_name, pid=pid, team=team_ids)
                    results = await db_manager.execute_sp(
                        "pharma", sp_name,
                        "1", from_year, from_month, to_year, to_month,
                        distributor_type or "0", "0", "0", "0",
                        team_ids, pid,
                        user_context.user_role, security_context.employee_id
                    )
                    if not results:
                        return (
                            f"\n### {search_name} (matched: **{matched_name}** | ID: {pid})"
                            f"\n- ⚠️ No sales data found for this product in team {team_ids} during {period}."
                        )

                    cust_key = next((k for k in results[0] if k.lower() == "customer"), None)
                    customers = list({r.get(cust_key, "") for r in results if r.get(cust_key)}) if cust_key else []

                    numeric_totals = {}
                    for col in results[0]:
                        vals = [r[col] for r in results if isinstance(r.get(col), (int, float))]
                        if vals:
                            numeric_totals[col] = sum(vals)

                    lines = [f"\n### {search_name} (matched: **{matched_name}** | ID: {pid})"]
                    lines.append(f"- **Records:** {len(results):,}")
                    lines.append(f"- **Unique customers:** {len(customers):,}")
                    for col, total in list(numeric_totals.items())[:8]:
                        lines.append(f"- **{col} Total:** {total:,.2f}")
                    if customers:
                        lines.append(f"- **Top customers (sample):** {', '.join(customers[:10])}")
                    lines.append(f"- **Sample rows (3):** {json.dumps(results[:3], default=str)}")
                    return "\n".join(lines)
                except Exception as e:
                    return f"\n### {search_name}: ⚠️ Error — {str(e)}"

            # Fire all SP calls simultaneously
            import asyncio as _asyncio
            product_sections = await _asyncio.gather(*[
                _fetch_one_product(sname, pid, mname)
                for sname, (pid, mname) in name_to_match.items()
            ])

            comparison_parts = [
                f"## Customer Sales Comparison: {', '.join(product_names)}",
                f"**Period:** {period} | **Team:** {team_ids}",
            ] + list(product_sections)

            return "\n".join(comparison_parts)

        try:
            logger.info("executing_sp_stream", sp=sp_name, user=security_context.user_id, team=team_ids)
            await progress.emit(f"Preparing customer sales query for team {team_ids}...")
            args = (
                "1",                          # @CompCode
                from_year,                    # @FromYear
                from_month,                   # @FromMonth
                to_year,                      # @ToYear
                to_month,                     # @ToMonth
                distributor_type,             # @DistributorType
                "0",                          # @DistributorID
                "0",                          # @CustomerID
                "0",                          # @BrickID
                team_ids,                     # @TeamID
                product_id,                   # @ProductID
                user_context.user_role,       # @UserRole
                security_context.employee_id  # @EntUserEmpID
            )
            return await _fetch_and_summarize(sp_name, "Customer Sales Report", args)

        except Exception as e:
            logger.error("sp_execution_error", sp=sp_name, error=str(e))
            return f"Error executing Customer Sales Report: {str(e)}"

    # -----------------------------------------------------------------
    # Tool 2: Sales vs Target (Sp_PharmaCRM_SVT)
    # -----------------------------------------------------------------
    async def run_sales_vs_target(
        date_from: str,
        date_to: str,
        team_name: Optional[str] = None,
        product_id: str = "",
        territory_id: str = "",
        sales_channel: str = "1",
    ) -> str:
        """Retrieves the Sales vs Target report showing territory-wise sales compared against
        targets and previous period performance."""

        sp_name = "Sp_PharmaCRM_SVT"

        denied = _check_access(sp_name, "Sales vs Target Report")
        if denied:
            return denied

        team_ids = _resolve_team_ids(team_name)
        if not team_ids:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return f"I could not resolve your team. Your available teams are: {available}. Please specify which team you'd like to see."

        try:
            logger.info("executing_sp_stream", sp=sp_name, user=security_context.user_id, team=team_ids)
            args = (
                "",                  # @Param_GroupId
                team_ids,            # @Param_TeamId
                product_id,          # @Param_ProductId
                territory_id,        # @Param_TerritoryId
                "",                  # @Param_RegionId
                "",                  # @Param_DistrictId
                sales_channel,       # @Param_SalesChannel
                1,                   # @Param_IsActualPrice
                date_from,           # @Param_InvoiceDate_From
                date_to,             # @Param_InvoiceDate_To
                1                    # @Param_MonthID
            )
            return await _fetch_and_summarize(sp_name, "Sales vs Target Report", args)

        except Exception as e:
            logger.error("sp_execution_error", sp=sp_name, error=str(e))
            return f"Error executing Sales vs Target Report: {str(e)}"

    # -----------------------------------------------------------------
    # Tool 3: Incentive Summary (Sp_PharmaCRM_GetIncentiveProcessReport)
    # -----------------------------------------------------------------
    async def run_incentive_summary(
        fiscal_year_code: str,
        month_year: str,
        team_name: Optional[str] = None,
        group_by: str = "Team,Role,",
    ) -> str:
        """Retrieves the Incentive Finalized Summary showing employee incentive data
        grouped by team, role, and territory for a given fiscal year and month."""

        sp_name = "Sp_PharmaCRM_GetIncentiveProcessReport"

        denied = _check_access(sp_name, "Incentive Summary Report")
        if denied:
            return denied

        team_ids = _resolve_team_ids(team_name)
        if not team_ids:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return f"I could not resolve your team. Your available teams are: {available}. Please specify which team you'd like to see."

        try:
            logger.info("executing_sp_stream", sp=sp_name, user=security_context.user_id, team=team_ids)
            args = (
                "1",                 # @Compcode
                fiscal_year_code,    # @FiscalYearCode
                month_year,          # @MonthYear
                team_ids,            # @TeamIDs
                "",                  # @RoleIDs (all)
                "",                  # @AreaIDs (all)
                group_by             # @GroupByIDs
            )
            return await _fetch_and_summarize(sp_name, "Incentive Summary Report", args)

        except Exception as e:
            logger.error("sp_execution_error", sp=sp_name, error=str(e))
            return f"Error executing Incentive Summary Report: {str(e)}"

    # -----------------------------------------------------------------
    # Tool 4: On-Demand CSV Export (only triggered when user asks)
    # -----------------------------------------------------------------
    async def run_export_csv(report_name: str) -> str:
        """Exports the last fetched report to a downloadable CSV file.
        Only call this when the user explicitly asks to download, export, or get a CSV."""
        if not _last_report_params.get("sp_name"):
            return "No report has been fetched in this session yet. Please run a report first, then ask to download it."

        sp_name = _last_report_params["sp_name"]
        cached_report_name = _last_report_params.get("report_name", report_name)
        args = _last_report_params["args"]
        total = _last_report_params.get("total", 0)

        export_dir = r"d:\Office Stuff\AtcoGenie\AtcoGenie.Server\wwwroot\exports"
        os.makedirs(export_dir, exist_ok=True)
        safe_name = cached_report_name.replace(' ', '_').replace('/', '')
        filename = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.csv"
        filepath = os.path.join(export_dir, filename)

        try:
            logger.info("csv_export_start", sp=sp_name, file=filename)
            await progress.emit(f"Exporting {cached_report_name} to CSV...")
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = None
                written = 0
                async for chunk_cols, chunk_rows in db_manager.execute_sp_stream("pharma", sp_name, *args):
                    if writer is None:
                        writer = csv.writer(f)
                        writer.writerow(chunk_cols)
                    writer.writerows(chunk_rows)
                    written += len(chunk_rows)

            export_url = f"/exports/{filename}"
            logger.info("csv_export_done", file=filename, rows=written)
            return (
                f"✅ **CSV Export Ready!** Your full {cached_report_name} with **{written:,} rows** has been exported.\n\n"
                f"[⬇️ Download {cached_report_name}]({export_url})"
            )
        except Exception as e:
            logger.error("csv_export_failed", error=str(e))
            return f"Export failed: {str(e)}"

    # -----------------------------------------------------------------
    # Build Tool List
    # -----------------------------------------------------------------
    tools = [
        StructuredTool.from_function(
            func=None,
            coroutine=run_search_products,
            name="search_products",
            description=(
                "Search for products by name in PharmaCRM. Use this FIRST whenever the user mentions "
                "a product name (e.g. 'Ascard', 'Betaderm') before running any report. "
                "Returns ProductID and ProductName matches. Never ask the user for a product ID."
            ),
            args_schema=SearchProductsInput,
        ),
        StructuredTool.from_function(
            func=None,
            coroutine=run_customer_sales,
            name="customer_sales_report",
            description=(
                "Use this tool when the user asks about customer sales, distributor-wise data, "
                "brick-wise sales, product sales by customer, or which customers are not buying products. "
                "Requires a date range (year/month). Maximum 2 years range. "
                "If product names are given, pass them in 'product_names' list — do NOT ask user for product IDs."
            ),
            args_schema=CustomerSalesInput,
        ),
        StructuredTool.from_function(
            func=None,
            coroutine=run_sales_vs_target,
            name="sales_vs_target_report",
            description=(
                "Use this tool when the user asks about sales vs target, territory-wise performance, "
                "target achievement, or comparing current sales with previous period. "
                "Requires a date range in YYYY/MM/DD format."
            ),
            args_schema=SalesVsTargetInput,
        ),
        StructuredTool.from_function(
            func=None,
            coroutine=run_incentive_summary,
            name="incentive_summary_report",
            description=(
                "Use this tool when the user asks about incentives, employee incentive data, "
                "incentive finalization, or performance-based rewards. "
                "Requires a fiscal year code (e.g., '20242025') and a month/year."
            ),
            args_schema=IncentiveSummaryInput,
        ),
        StructuredTool.from_function(
            func=None,
            coroutine=run_export_csv,
            name="export_report_to_csv",
            description=(
                "Exports the most recently fetched report to a downloadable CSV file. "
                "ONLY call this tool when the user explicitly asks to download, export, or get a CSV or Excel file. "
                "Do NOT call this automatically after every report — only on explicit user request."
            ),
            args_schema=ExportReportInput,
        ),
    ]

    return tools
