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
import duckdb
from collections import Counter
from datetime import datetime
import asyncio
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
# In-Memory Last-Result Cache — keyed by user_id
# Each user gets their own entry so concurrent users never overwrite each other.
# =====================================================================
_last_report_params: dict = {}  # {user_id: {"sp_name": ..., "args": ..., ...}}


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

class QueryDatasetInput(BaseModel):
    upload_id: str = Field(description="The UUID of the dataset to query")
    query: str = Field(description="The exact DuckDB SQL query to execute against the 'read_parquet' file")


class AggregatedSalesInput(BaseModel):
    date_from: str = Field(description="Start date in YYYY/MM/DD format, e.g. '2024/07/01'. Earliest available: 2024/07/01.")
    date_to: str = Field(description="End date in YYYY/MM/DD format, e.g. '2026/06/30'.")
    team_name: Optional[str] = Field(default=None, description="Team name or ID to filter by. Leave empty to use the user's assigned team(s).")
    product_id: Optional[str] = Field(default="", description="Product ID filter. Empty string for all products.")
    territory_id: Optional[str] = Field(default="", description="Territory ID filter. Empty string for all territories.")
    sales_channel: Optional[str] = Field(default="1", description="Sales channel code. Default is '1'.")


# =====================================================================
# Fiscal Year Splitter (module-level utility)
# =====================================================================

def _split_into_fiscal_years(date_from: str, date_to: str) -> list:
    """
    Given a user's date range, returns the FULL fiscal year boundaries needed
    to query Sp_PharmaCRM_SVT.

    CRITICAL: The SP uses exact equality matching on FiscalYearFromDate/FiscalYearToDate,
    so we MUST always pass full boundaries (Jul 1 → Jun 30), never partial months.

    Returns list of (fy_label, fy_start_str, fy_end_str, user_range_note) tuples.
    user_range_note tells the LLM which months within this FY the user actually cares about.
    """
    start = datetime.strptime(date_from, "%Y/%m/%d")
    end = datetime.strptime(date_to, "%Y/%m/%d")

    fy_start_year = start.year if start.month >= 7 else start.year - 1

    windows = []
    while True:
        fy_start = datetime(fy_start_year, 7, 1)
        fy_end = datetime(fy_start_year + 1, 6, 30)

        if fy_start > end:
            break

        # Only include if this FY overlaps the user's range
        if fy_end >= start:
            label = f"FY {fy_start_year}/{fy_start_year + 1}"

            # Compute which months within this FY the user actually requested
            overlap_start = max(start, fy_start)
            overlap_end = min(end, fy_end)
            if overlap_start == fy_start and overlap_end == fy_end:
                range_note = "Full fiscal year"
            else:
                range_note = f"User requested: {overlap_start.strftime('%b %Y')} – {overlap_end.strftime('%b %Y')}"

            windows.append((
                label,
                fy_start.strftime("%Y/%m/%d"),   # ALWAYS full FY start
                fy_end.strftime("%Y/%m/%d"),      # ALWAYS full FY end
                range_note,
            ))

        fy_start_year += 1

    return windows


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

    # Cache for admin all-teams lookup within a single request
    _all_team_ids_cache: list[str] = []

    # Semaphore to serialize SVT SP calls.
    # Sp_PharmaCRM_SVT uses a global temp table (##TerritoryIds) which collides
    # when two pyodbc connections execute the SP simultaneously.
    # Semaphore(1) acts as a mutex — guaranteed serialization regardless of
    # how the async event loop schedules the coroutines.
    _svt_semaphore = asyncio.Semaphore(1)


    async def _fetch_all_team_ids_csv() -> tuple[str, str]:
        """Fetches all active team IDs from SS_Team and returns (csv, display_name).
        Result is cached within this tool-factory closure so repeated calls in the
        same request don't hit the DB twice.
        """
        if _all_team_ids_cache:
            csv = ",".join(_all_team_ids_cache)
            return csv, "All Teams"
        try:
            rows = await db_manager.execute_raw(
                "pharma",
                "SELECT TeamId, Name FROM SS_Team WHERE Active = 1 ORDER BY TeamId"
            )
            if rows:
                ids = [str(r["TeamId"]) for r in rows]
                _all_team_ids_cache.extend(ids)
                csv = ",".join(ids)
                logger.info("admin_all_teams_fetched", count=len(ids))
                return csv, "All Teams"
        except Exception as e:
            logger.error("admin_all_teams_fetch_error", error=str(e))
        # Final fallback — empty means SP returns all in some SPs, but user said this
        # doesn't work; log a warning so we can track it.
        logger.warning("admin_all_teams_fetch_failed_fallback")
        return "", "All Teams"

    async def _resolve_team_ids(team_name: Optional[str]) -> tuple[str, str]:
        """
        Resolves which TeamIDs to pass to the SP.
        Returns (team_ids_csv, resolved_display_name) tuple.

        Handles four cases:
        1. User types a team NAME  → fuzzy-match against user's known teams → return matched ID
        2. User types a numeric ID → validate it's in user's own teams (or allow if admin) → return it
        3. DB fallback (admin)     → query SS_Team master table to resolve name → ID
        4. Nothing specified       → use all of user's default team IDs
                                     Admin with no team specified → ALL teams as CSV from DB
        """
        if team_name:
            candidate = team_name.strip()

            # Case 2: user gave a raw numeric team ID
            # Special case: "0" is not a real team ID — admin intent is "all teams".
            # SVT SP natively treats '' as all-teams; passing a CSV causes partial data.
            if candidate == "0" and user_context.is_admin:
                logger.info("admin_all_teams_empty_string", reason="0_sentinel")
                return "", "All Teams"

            if candidate.isdigit():
                user_ids = {t.team_id for t in user_context.teams}
                if candidate in user_ids or user_context.is_admin:
                    # Look up name from local teams first, then DB
                    name = next((t.team_name for t in user_context.teams if t.team_id == candidate), None)
                    if not name:
                        rows = await db_manager.execute_raw("pharma", "SELECT Name FROM SS_Team WHERE TeamId = ? AND Active = 1", int(candidate))
                        name = rows[0]["Name"] if rows else f"Team {candidate}"
                    logger.info("team_resolved_by_id", input=candidate, name=name)
                    return candidate, name
                logger.warning("team_id_not_in_user_teams", input=candidate,
                               user_teams=list(user_ids))
                return candidate, f"Team {candidate}"

            # Case 1: user gave a team name — fuzzy match against local teams
            matched_id = user_context.get_team_id_by_name(candidate)
            if matched_id:
                name = next((t.team_name for t in user_context.teams if t.team_id == matched_id), candidate)
                logger.info("team_resolved_by_name", input=candidate, matched_id=matched_id, name=name)
                return matched_id, name

            # Case 3: DB fallback — query SS_Team master table directly
            try:
                db_team_id, db_team_name = await _lookup_team_from_db_with_name(candidate)
                if db_team_id:
                    logger.info("team_resolved_by_db", input=candidate, matched_id=db_team_id, name=db_team_name)
                    return db_team_id, db_team_name
            except Exception as e:
                logger.warning("team_db_lookup_failed", input=candidate, error=str(e))

            logger.warning("team_name_no_match", input=candidate,
                           available=[t.team_name for t in user_context.teams])
            # Last resort for admin — empty string = all teams (SP handles natively)
            if user_context.is_admin:
                logger.info("admin_all_teams_empty_string", reason="name_no_match")
                return "", "All Teams"
            return candidate, candidate

        # Case 4: No team mentioned → use the user's own teams
        if user_context.team_ids_csv:
            names = ", ".join(user_context.team_names) if user_context.team_names else user_context.team_ids_csv
            return user_context.team_ids_csv, names

        # Admin with no direct team assignment → fetch ALL active teams from DB as CSV
        if user_context.is_admin:
            return "", "All Teams"

        return "", ""

    async def _lookup_team_from_db_with_name(name: str) -> tuple[Optional[str], str]:
        """Query SS_Team master table to resolve a team name to its numeric TeamId and display name."""
        rows = await db_manager.execute_raw(
            "pharma",
            "SELECT TeamId, Name FROM SS_Team WHERE Active = 1 ORDER BY Name"
        )
        if not rows:
            return None, name

        name_lower = name.lower().strip()

        # 1. Exact match
        for r in rows:
            if r["Name"].strip().lower() == name_lower:
                return str(r["TeamId"]), r["Name"].strip()
        # 2. Input is substring of DB name
        for r in rows:
            if name_lower in r["Name"].strip().lower():
                return str(r["TeamId"]), r["Name"].strip()
        # 3. DB name is substring of input (e.g. "Team Jaguar" matches "Jaguar")
        for r in rows:
            if r["Name"].strip().lower() in name_lower:
                return str(r["TeamId"]), r["Name"].strip()
        # 4. Word-level overlap
        input_words = {w for w in name_lower.split() if len(w) > 2}
        for r in rows:
            team_words = {w for w in r["Name"].strip().lower().split() if len(w) > 2}
            if input_words & team_words:
                return str(r["TeamId"]), r["Name"].strip()
        return None, name


    async def _fetch_and_summarize(sp_name: str, report_name: str, args: tuple, max_sample: int = 20) -> str:
        """
        Fetches SP output via sync pyodbc (fast, no hang) and computes
        global + per-group aggregates for LLM consumption.
        """
        logger.info("sp_sync_call", sp=sp_name, args=str(args))
        await progress.emit("Fetching data from the database...")

        try:
            # Sp_PharmaCRM_SVT uses ##TerritoryIds (global temp table) — must serialize.
            # Other SPs are fine with concurrency.
            if sp_name == "Sp_PharmaCRM_SVT":
                async with _svt_semaphore:
                    logger.debug("svt_semaphore_acquired", sp=sp_name)
                    columns, all_rows = await db_manager.execute_sp_sync("pharma", sp_name, *args)
            else:
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

        # Per-group aggregates — NO cap: render ALL groups so the LLM sees complete data.
        # SVT returns 12 month-rows; customer SP may return hundreds of customer groups.
        # A 200-group warning is emitted but data is never truncated.
        priority_keywords = ["month", "date", "period", "year", "customer", "product", "employee", "territory", "region", "team", "brick"]
        selected_groups = []
        found_keywords = set()
        
        for kw in priority_keywords:
            for i in categorical_indices:
                col_lower = columns[i].lower()
                if kw in col_lower and kw not in found_keywords:
                    # Prefer name columns over ID columns
                    if "id" in col_lower or "code" in col_lower:
                        # See if there's a non-ID version
                        has_name_version = any(kw in columns[j].lower() and "id" not in columns[j].lower() for j in categorical_indices)
                        if has_name_version:
                            continue # Skip the ID column
                    
                    selected_groups.append(i)
                    found_keywords.add(kw)
                    if len(selected_groups) >= 3:
                        break
            if len(selected_groups) >= 3:
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

        # Cache for export — scoped to this user so concurrent users don't interfere
        _last_report_params[security_context.user_id] = {
            "sp_name": sp_name, "report_name": report_name,
            "args": args, "columns": columns, "total": total
        }

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

        # Per-group breakdowns
        TIME_SERIES_KEYWORDS = ["month", "date", "period", "year"]
        MONTH_ORDER = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }

        def _chrono_key(item):
            """Sort key for MonthYear values like 'Jul 24', 'Jan 2025', '2025/07'."""
            gv = str(item[0]).strip()
            parts = gv.split()
            if len(parts) == 2:  # e.g. "Jul 24" or "Jul 2024"
                month_num = MONTH_ORDER.get(parts[0][:3].capitalize(), 0)
                try:
                    yr = int(parts[1])
                    year_num = yr if yr > 100 else 2000 + yr
                except ValueError:
                    year_num = 0
                return (year_num, month_num)
            return (0, 0)

        for gi in selected_groups:
            gsums = group_sums[gi]
            gcol = columns[gi]
            if not gsums:
                continue

            is_time_series = any(kw in gcol.lower() for kw in TIME_SERIES_KEYWORDS)

            if is_time_series:
                # --- Time-series: chronological markdown table ---
                # Show all numeric columns directly (no misleading cross-year sums).
                num_cols_to_show = [c for c in columns if c in numeric_sums]
                chrono_sorted = sorted(gsums.items(), key=_chrono_key)

                summary_parts.append(
                    f"\n### {gcol} Breakdown — {len(gsums)} months (chronological)"
                )
                header = "| " + gcol + " | " + " | ".join(num_cols_to_show) + " |"
                divider = "|" + "|".join(["---"] * (1 + len(num_cols_to_show))) + "|"
                summary_parts.append(header)
                summary_parts.append(divider)
                for gv, gnums_row in chrono_sorted:
                    row_vals = [f"{gnums_row.get(c, 0):,.2f}" for c in num_cols_to_show]
                    summary_parts.append("| " + str(gv) + " | " + " | ".join(row_vals) + " |")

            else:
                # --- Non-time-series: ranked list (customers, products, etc.) ---
                rev_cols = [c for c in numeric_sums if any(kw in c.lower() for kw in ["value", "amount", "revenue", "net", "sale", "price"])]
                unit_cols = [c for c in numeric_sums if any(kw in c.lower() for kw in ["unit", "qty", "quantity", "box", "pack"])]

                for gval, gnums in gsums.items():
                    total_rev_col = next((c for c in rev_cols if any(kw in c.lower() for kw in ["total", "ytd", "overall"])), None)
                    total_unit_col = next((c for c in unit_cols if any(kw in c.lower() for kw in ["total", "ytd", "overall"])), None)
                    gnums["_Period_Total_Revenue"] = gnums[total_rev_col] if total_rev_col else sum(gnums.get(c, 0) for c in rev_cols[:1])
                    gnums["_Period_Total_Units"] = gnums[total_unit_col] if total_unit_col else sum(gnums.get(c, 0) for c in unit_cols[:1])

                unique_count = len(gsums)
                all_sorted = sorted(gsums.items(), key=lambda x: x[1].get("_Period_Total_Revenue", 0), reverse=True)

                HIGH_CARDINALITY_THRESHOLD = 50
                HIGH_CARDINALITY_CAP = 200

                if unique_count <= HIGH_CARDINALITY_THRESHOLD:
                    summary_parts.append(f"\n### All {unique_count} **{gcol}** (ranked by revenue, highest first)")
                    display_sorted = all_sorted
                    metric_col_limit = None
                else:
                    display_sorted = all_sorted[:HIGH_CARDINALITY_CAP]
                    summary_parts.append(
                        f"\n### Top {HIGH_CARDINALITY_CAP} of {unique_count} **{gcol}** by revenue "
                        f"(overall totals above already include ALL {unique_count}; "
                        f"say 'export CSV' for the complete {unique_count}-row breakdown)"
                    )
                    metric_col_limit = 6

                for rank, (gval, gnums) in enumerate(display_sorted, 1):
                    count = group_counts[gi].get(gval, 0)
                    rev_val = gnums.get("_Period_Total_Revenue", 0)
                    unit_val = gnums.get("_Period_Total_Units", 0)
                    num_line = f"Revenue: {rev_val:,.2f} | Units: {unit_val:,.2f}"
                    orig_cols_all = [(k, v) for k, v in gnums.items() if not str(k).startswith("_") and isinstance(v, (int, float))]
                    orig_cols_all.sort(key=lambda x: abs(x[1]), reverse=True)
                    orig_cols_slice = orig_cols_all if metric_col_limit is None else orig_cols_all[:metric_col_limit]
                    orig_cols = [f"{k}={v:,.2f}" for k, v in orig_cols_slice]
                    if orig_cols:
                        num_line += f" | {', '.join(orig_cols)}"
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

        # Automatically export to CSV if the result set is large (> 1,500 rows)
        export_md = ""
        if total > 1500:
            try:
                from app.config import get_settings as _get_settings
                export_dir = _get_settings().export_dir
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
        import decimal
        for col in columns:
            vals = [r.get(col) for r in sample_rows if r.get(col) is not None]
            if vals and all(isinstance(v, (int, float, decimal.Decimal)) for v in vals):
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
                vals = [r[col] for r in results if isinstance(r.get(col), (int, float, decimal.Decimal))]
                if vals:
                    float_vals = [float(v) for v in vals]
                    summary_parts.append(
                        f"- **{col}**: Total={sum(float_vals):,.2f}, Avg={sum(float_vals)/len(float_vals):,.2f}, "
                        f"Min={min(float_vals):,.2f}, Max={max(float_vals):,.2f}"
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

        team_ids, resolved_team_name = await _resolve_team_ids(team_name)
        if not team_ids and not user_context.is_admin:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return f"I could not resolve your team. Your available teams are: {available}. Please specify which team you'd like to see."

        # SS_sp_CustomerSales_YTD_Excel does NOT support '' for all-teams (unlike SVT).
        # If admin got the empty-string sentinel, fetch the real CSV of all active team IDs.
        if not team_ids and user_context.is_admin:
            team_ids, resolved_team_name = await _fetch_all_team_ids_csv()
            logger.info("customer_sales_admin_team_csv_override",
                        team_count=len(team_ids.split(",")) if team_ids else 0)

        # ── SCOPE GATE ────────────────────────────────────────────────────────
        # SS_sp_CustomerSales_YTD_Excel pivots every customer×product row per month.
        # All-teams + multi-month = 2M+ rows that hit the 120-second cursor timeout.
        # Safe envelope: < 5 teams OR ≤ 3 months.
        team_count   = len(team_ids.split(",")) if team_ids else 0
        date_span_months = (to_year - from_year) * 12 + (to_month - from_month + 1)
        if team_count > 5 and date_span_months > 3:
            period_label = f"{from_year}/{from_month:02d} – {to_year}/{to_month:02d}"
            logger.warning(
                "customer_sales_scope_limit",
                team_count=team_count, months=date_span_months, period=period_label
            )
            return (
                f"⚠️ **Scope too large for Customer Sales SP** ({team_count} teams × {date_span_months} months) — "
                f"this would return 2M+ rows and will time out.\n\n"
                f"To get what you need, choose one of these options:\n"
                f"- **Specific team**: “which products in Team Jaguar had highest revenue {from_year}?” — fast, full detail\n"
                f"- **Shorter window**: ask for 1–3 months at a time for all teams — fast, full detail\n"
                f"- **Monthly revenue summary** (no per-product breakdown): I can pull this via the "
                f"aggregated sales report instantly for the full period ({period_label})."
            )


        team_context_note = f"[Context: **All Teams**]\n\n" if resolved_team_name == "All Teams" else f"[Context: Team **{resolved_team_name}**]\n\n"

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

            # Point 4: fetch all product SPs in PARALLEL using the fast sync path
            async def _fetch_one_product(search_name: str, pid: str, matched_name: str) -> str:
                """Runs a single product SP via the fast sync path and returns a formatted section."""
                try:
                    logger.info("product_comparison_sp", product=matched_name, pid=pid, team=team_ids)
                    args = (
                        "1", from_year, from_month, to_year, to_month,
                        distributor_type or "0", "0", "0", "0",
                        team_ids, pid,
                        user_context.user_role, security_context.employee_id
                    )
                    section = await _fetch_and_summarize(
                        sp_name,
                        f"Customer Sales — {matched_name} (ID: {pid})",
                        args,
                    )
                    return f"\n### {search_name} (matched: **{matched_name}** | ID: {pid})\n{section}"
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
            result = await _fetch_and_summarize(sp_name, "Customer Sales Report", args)
            return team_context_note + result

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

        team_ids, resolved_team_name = await _resolve_team_ids(team_name)
        if not team_ids and not user_context.is_admin:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return f"I could not resolve your team. Your available teams are: {available}. Please specify which team you'd like to see."

        team_context_note = f"[Context: **All Teams**]\n\n" if resolved_team_name == "All Teams" else f"[Context: Team **{resolved_team_name}**]\n\n"

        # '' is the native SVT all-teams value; team_ids is already '' for admin all-teams
        sp_team_param = team_ids

        # --- Enforce full FY boundaries (SP uses exact equality on FiscalYearFromDate/FiscalYearToDate) ---
        fy_windows = _split_into_fiscal_years(date_from, date_to)
        if not fy_windows:
            return "No valid fiscal year data windows found for the given date range."

        try:
            logger.info("executing_sp_stream", sp=sp_name, user=security_context.user_id, team=sp_team_param)

            async def _svt_fetch_fy(fy_label: str, fy_start: str, fy_end: str, range_note: str) -> str:
                args = (
                    "",               # @Param_GroupId
                    sp_team_param,    # @Param_TeamId
                    product_id,       # @Param_ProductId
                    territory_id,     # @Param_TerritoryId
                    "",               # @Param_RegionId
                    "",               # @Param_DistrictId
                    sales_channel,    # @Param_SalesChannel
                    1,                # @Param_IsActualPrice
                    fy_start,         # @Param_InvoiceDate_From  (ALWAYS full FY boundary)
                    fy_end,           # @Param_InvoiceDate_To    (ALWAYS full FY boundary)
                    1,                # @Param_MonthID
                )
                result = await _fetch_and_summarize(sp_name, f"Sales vs Target ({fy_label})", args)
                return f"## {fy_label} ({fy_start} → {fy_end})\n*{range_note}*\n\n{result}"

            # Sp_PharmaCRM_SVT uses a global temp table (##TerritoryIds).
            # Parallel calls cause SQL 2714 "object already exists" — run sequentially.
            fy_results = []
            for label, fy_start, fy_end, range_note in fy_windows:
                fy_results.append(await _svt_fetch_fy(label, fy_start, fy_end, range_note))

            header = (
                f"# Sales vs Target Report\n"
                f"**Period:** {date_from} → {date_to} | **Fiscal Years Queried:** {len(fy_windows)}\n\n"
            )
            return team_context_note + header + "\n\n".join(fy_results)

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

        team_ids, resolved_team_name = await _resolve_team_ids(team_name)
        if not team_ids and not user_context.is_admin:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return f"I could not resolve your team. Your available teams are: {available}. Please specify which team you'd like to see."

        team_context_note = f"[Context: **All Teams**]\n\n" if resolved_team_name == "All Teams" else f"[Context: Team **{resolved_team_name}**]\n\n"

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
            result = await _fetch_and_summarize(sp_name, "Incentive Summary Report", args)
            return team_context_note + result

        except Exception as e:
            logger.error("sp_execution_error", sp=sp_name, error=str(e))
            return f"Error executing Incentive Summary Report: {str(e)}"

    # -----------------------------------------------------------------
    # Tool: Aggregated Sales Report (Sp_PharmaCRM_SVT — pre-aggregated monthly tables)
    #
    # Use when: broad date range, no customer-level detail needed, multi-FY analysis,
    # negative revenue detection, or when customer_sales_report would time out.
    # Data available from: July 2024 onwards.
    # Authorization: enforced by TeamID per call (same as SVT).
    # Multi-year: automatically splits into per-FY calls and runs them in parallel.
    # -----------------------------------------------------------------
    async def run_aggregated_sales(
        date_from: str,
        date_to: str,
        team_name: Optional[str] = None,
        product_id: str = "",
        territory_id: str = "",
        sales_channel: str = "1",
    ) -> str:
        """Retrieves aggregated monthly sales data across one or more fiscal years.
        Automatically runs parallel SP calls per fiscal year and merges results."""

        sp_name = "Sp_PharmaCRM_SVT"

        denied = _check_access(sp_name, "Aggregated Sales Report")
        if denied:
            return denied

        # --- Date validation ---
        MIN_DATE_STR = "2024/07/01"
        MIN_DATE = datetime(2024, 7, 1)
        try:
            from_dt = datetime.strptime(date_from, "%Y/%m/%d")
            to_dt = datetime.strptime(date_to, "%Y/%m/%d")
        except ValueError:
            return (
                "Invalid date format. Please use YYYY/MM/DD format (e.g. '2024/07/01'). "
                f"Received: from='{date_from}', to='{date_to}'."
            )

        if from_dt > to_dt:
            return "Invalid date range: start date must be before end date."

        if to_dt < MIN_DATE:
            return (
                "⚠️ The Aggregated Sales Report only contains data from **July 2024 onwards**. "
                f"Your requested range ({date_from} → {date_to}) is entirely before this. "
                "For older historical data, please use the `customer_sales_report` tool."
            )

        early_warning = ""
        if from_dt < MIN_DATE:
            date_from = MIN_DATE_STR
            early_warning = "⚠️ *Aggregated data is only available from July 2024. Results are shown from 2024/07/01.*\n\n"

        # --- Team resolution (enforces authorization) ---
        team_ids, resolved_team_name = await _resolve_team_ids(team_name)
        if not team_ids and not user_context.is_admin:
            available = ", ".join(user_context.team_names) if user_context.team_names else "none found"
            return (
                f"I could not resolve your team. Your available teams are: {available}. "
                "Please specify which team you'd like to see."
            )

        team_context_note = (
            "[Context: **All Teams**]\n\n" if resolved_team_name == "All Teams"
            else f"[Context: Team **{resolved_team_name}**]\n\n"
        )

        # --- Split requested range into fiscal year windows ---
        fy_windows = _split_into_fiscal_years(date_from, date_to)
        if not fy_windows:
            return "No valid fiscal year data windows found for the given date range."

        # Sp_PharmaCRM_SVT expects an empty string '' for all-teams when no filter.
        # Since we now pass an actual CSV of team IDs, we can pass it directly.
        # Keep the empty-string fallback only if team_ids somehow ended up blank.
        sp_team_param = team_ids if team_ids else ""

        logger.info(
            "aggregated_sales_start",
            sp=sp_name, user=security_context.user_id,
            team=sp_team_param, fy_count=len(fy_windows),
        )
        await progress.emit(
            f"Running aggregated sales query across {len(fy_windows)} "
            f"fiscal year(s) in parallel..."
        )

        # --- One SP call per fiscal year, all fired in parallel ---
        async def _fetch_one_fy(fy_label: str, fy_start: str, fy_end: str, range_note: str) -> str:
            args = (
                "",               # @Param_GroupId
                sp_team_param,    # @Param_TeamId  ← authorization boundary
                product_id,       # @Param_ProductId
                territory_id,     # @Param_TerritoryId
                "",               # @Param_RegionId
                "",               # @Param_DistrictId
                sales_channel,    # @Param_SalesChannel
                1,                # @Param_IsActualPrice
                fy_start,         # @Param_InvoiceDate_From  (ALWAYS full FY boundary)
                fy_end,           # @Param_InvoiceDate_To    (ALWAYS full FY boundary)
                1,                # @Param_MonthID
            )
            logger.info(
                "aggregated_sales_fy_call",
                fy=fy_label, from_=fy_start, to_=fy_end, team=sp_team_param,
            )
            result = await _fetch_and_summarize(
                sp_name, f"Aggregated Sales ({fy_label})", args
            )
            # Tell the AI explicitly: use the MonthYear table row-by-row
            render_hint = (
                "\n> ⚡ **RENDER INSTRUCTION**: The MonthYear Breakdown table below contains "
                f"individual month rows covering **{range_note}**. "
                "Extract only the months that fall within the user's requested calendar range and "
                "render each one as a separate row. Do NOT aggregate into H1/H2."
            )
            return f"## {fy_label} ({fy_start} \u2192 {fy_end})\n*{range_note}*{render_hint}\n\n{result}"

        # Sp_PharmaCRM_SVT uses a global temp table (##TerritoryIds) internally.
        # Running two FY calls in PARALLEL causes SQL error 2714:
        #   "There is already an object named '##TerritoryIds' in the database"
        # because both connections try to CREATE ##TerritoryIds at the same time.
        # Solution: run FY calls SEQUENTIALLY.
        fy_results = []
        for label, fy_start, fy_end, range_note in fy_windows:
            fy_results.append(await _fetch_one_fy(label, fy_start, fy_end, range_note))

        # --- Merge all fiscal year sections into a single response ---
        parts = [
            early_warning + team_context_note,
            "# Aggregated Sales Report",
            f"**Period:** {date_from} → {date_to} | **Fiscal Years Queried:** {len(fy_windows)}",
            "",
        ]
        parts.extend(fy_results)

        if len(fy_windows) > 1:
            parts.append(
                "\n> 📊 **Multi-Year Query**: Results are broken down by fiscal year (Jul\u2013Jun). "
                "Each section's MonthYear Breakdown table shows individual months. "
                "Combine the relevant months from each FY section into ONE chronological "
                "month-by-month table in your response — do NOT summarise into H1/H2."
            )

        return "\n".join(parts)

    # -----------------------------------------------------------------
    # Tool 4: On-Demand CSV Export (only triggered when user asks)
    # -----------------------------------------------------------------
    async def run_export_csv(report_name: str) -> str:
        """Exports the last fetched report to a downloadable CSV file.
        Only call this when the user explicitly asks to download, export, or get a CSV."""
        user_cache = _last_report_params.get(security_context.user_id, {})
        if not user_cache.get("sp_name"):
            return "No report has been fetched in this session yet. Please run a report first, then ask to download it."

        sp_name = user_cache["sp_name"]
        cached_report_name = user_cache.get("report_name", report_name)
        args = user_cache["args"]
        total = user_cache.get("total", 0)

        from app.config import get_settings as _get_settings
        export_dir = _get_settings().export_dir
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

    async def run_query_user_dataset(upload_id: str, query: str) -> str:
        """
        Execute a DuckDB SQL query against a user-uploaded Parquet file.

        Security:
        - Verifies ownership (user_id match) in Postgres
        - Verifies status=='ready' — no reads during conversion
        - Path is passed explicitly into the thread (not via closure) to prevent
          stale-reference issues in concurrent scenarios

        The table is exposed as a view named 'data':
            SELECT * FROM data
            SELECT * FROM data WHERE _sheet = 'Sales Q1'
            SELECT _sheet, COUNT(*) FROM data GROUP BY _sheet
        """
        pool = db_manager.get_pool("postgres")
        if not pool:
            return "Error: Database not available."

        # ── Step 1: Fetch row + verify ownership + check status ──────────────
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT parquet_path, user_id, status, filename, sheet_names, error_message
                    FROM document_uploads
                    WHERE id = $1
                    """,
                    uuid.UUID(upload_id),
                )
        except Exception as e:
            logger.error("dataset_query_db_failed", error=str(e))
            return f"Database error while looking up dataset: {str(e)}"

        if not row:
            return "Error: Dataset not found. It may have been deleted or the ID is incorrect."

        if row["user_id"].lower() != security_context.user_id.lower():
            logger.warning(
                "unauthorized_dataset_access",
                user=security_context.user_id,
                upload_id=upload_id,
            )
            return "Error: You are not authorized to access this dataset."

        if row["status"] == "processing":
            return (
                f"Dataset '{row['filename']}' is still being processed. "
                "Please wait a moment, then try again."
            )
        if row["status"] == "error":
            return (
                f"Dataset '{row['filename']}' failed to convert: "
                f"{row['error_message'] or 'Unknown error.'}"
            )
        if row["status"] != "ready":
            return f"Dataset is in an unexpected state: {row['status']}."

        parquet_path: str = row["parquet_path"]
        filename: str = row["filename"]

        try:
            import json as _json
            sheet_names = _json.loads(row["sheet_names"]) if isinstance(row["sheet_names"], str) else (row["sheet_names"] or [])
        except Exception:
            sheet_names = []

        # ── Step 2: Validate the Parquet file still exists on disk ───────────
        if not os.path.exists(parquet_path):
            return (
                f"Error: The dataset file for '{filename}' is missing from disk. "
                "It may have been cleaned up. Please re-upload the file."
            )

        # ── Step 3: Run DuckDB in a thread — no event loop blocking ──────────
        ROW_CAP = 200

        def _duck_execute(path: str, sql: str) -> str:
            # Use posix-style forward slashes — DuckDB on Windows requires it
            safe_path = path.replace("\\", "/")
            con = duckdb.connect(database=":memory:")
            try:
                con.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{safe_path}')")
                df = con.execute(sql).fetchdf()
            finally:
                con.close()

            truncated = len(df) > ROW_CAP
            df = df.head(ROW_CAP)
            result_md = df.to_markdown(index=False)
            if truncated:
                result_md += (
                    f"\n\n> ⚠️ Results capped at {ROW_CAP} rows. "
                    "Refine your query with a WHERE clause or LIMIT to see specific rows."
                )
            return result_md

        try:
            await progress.emit(f"Querying dataset '{filename}'...")
            logger.info("duckdb_execute", upload_id=upload_id, query=query[:200])
            result_md = await asyncio.to_thread(_duck_execute, parquet_path, query)

            # Prepend sheet context if multi-sheet file
            header = f"**File:** {filename}"
            if len(sheet_names) > 1:
                header += f"\n**Sheets available:** {', '.join(f'`{s}`' for s in sheet_names)} — filter with `WHERE _sheet = '<name>'`"
            return f"{header}\n\n{result_md}"

        except Exception as e:
            err = str(e)
            logger.error("duckdb_query_failed", upload_id=upload_id, query=query[:200], error=err)
            # Give the AI a helpful hint for common SQL mistakes
            if "does not exist" in err.lower() or "no such" in err.lower():
                return (
                    f"Query error: {err}\n\n"
                    "**Hint:** The table is always named `data`. "
                    f"Available columns: {', '.join(['`_sheet`'] if sheet_names else [])}"
                )
            return f"Query failed: {err}"

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
                "Detailed product-level and customer-level sales data (per-customer, per-product rows). "
                "Use when the user asks: which specific customers bought X, distributor-wise sales, "
                "brick-wise breakdown, or a per-product table for a SPECIFIC TEAM or SHORT DATE RANGE. "
                "If product names are mentioned, pass them in 'product_names'. "
                "⚠️ SCOPE LIMIT — this SP returns one row per customer×product and will TIME OUT "
                "when all teams are queried for more than 3 months. "
                "For product RANKINGS across all teams or for periods longer than 3 months, "
                "use 'aggregated_sales_report' instead (it handles wide scopes without timing out). "
                "Max supported range: 2 years, but wide-scope queries must be scoped to 1 team or ≤3 months."
            ),
            args_schema=CustomerSalesInput,
        ),
        StructuredTool.from_function(
            func=None,
            coroutine=run_aggregated_sales,
            name="aggregated_sales_report",
            description=(
                "Aggregated monthly sales totals and sales-vs-target data. "
                "Use for: month-over-month trends, year-over-year comparison, target achievement %, "
                "fiscal year revenue totals, wide date ranges (multi-month or multi-year), "
                "and ANY query covering more than 3 months OR more than 5 teams simultaneously. "
                "This tool is the ONLY one that handles all-teams + full-year queries without timing out. "
                "It provides monthly aggregated totals by territory; it does NOT break data down "
                "by individual customer row, but it does give overall revenue trends efficiently. "
                "Data available from July 2024 onwards. Multi-year queries run parallel FY calls automatically."
            ),
            args_schema=AggregatedSalesInput,
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
        StructuredTool.from_function(
            func=None,
            coroutine=run_query_user_dataset,
            name="query_user_dataset",
            description=(
                "Query an uploaded Excel/CSV dataset using DuckDB SQL. "
                "The table is exposed as a view named 'data' (e.g. SELECT * FROM data)."
                "You must provide the upload_id of the dataset to query."
            ),
            args_schema=QueryDatasetInput,
        ),
    ]

    return tools
