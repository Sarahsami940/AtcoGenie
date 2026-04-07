"""
AtcoGenie AI Engine — Report Stored Procedure Metadata

Defines the available Stored Procedures (Reports) that the AI can call.
The AI uses this metadata to understand which report to run and what parameters
to extract from the user's prompt.

Phase 1: 3 Reports from PharmaCRM
"""
from typing import Dict, Any

# =====================================================================
# Helper SPs (called internally, not exposed as LangChain Tools)
# =====================================================================
HELPER_SPS = {
    "get_employee_teams": {
        "sp_name": "Sp_GetEmployeeWiseTeam",
        "database": "PharmaCRM",
        "description": "Returns TeamID and TeamName for a given employee. One employee may have multiple teams.",
        "parameters": [
            {"name": "@EmpId", "type": "int", "required": True, "description": "Employee ID"}
        ]
    },
    "get_user_role": {
        "sp_name": "SP_GetRole",
        "database": "PharmaCRM",
        "description": "Returns the user's role (e.g., Admin, Normal) within the system.",
        "parameters": [
            {"name": "@CompanyId", "type": "int", "required": True, "description": "Login Company ID"},
            {"name": "@UserId", "type": "nvarchar", "required": True, "description": "Login User ID (SamAccountName)"},
            {"name": "@EmpID", "type": "int", "required": True, "description": "Employee/Party ID"},
            {"name": "@DesgID", "type": "int", "required": False, "description": "Designation ID (optional, can be 0)"},
            {"name": "@DBName", "type": "nvarchar", "required": False, "description": "Database name (unused)"},
        ]
    }
}

# =====================================================================
# Phase 1: PharmaCRM Reports
# =====================================================================
PHARMA_CRM_REPORTS: Dict[str, Any] = {
    "database_name": "PharmaCRM",
    "pool_name": "pharma",
    "description": "Executes predefined analytical reports via Stored Procedures.",
    "reports": {
        "customer_sales_ytd": {
            "sp_name": "SS_sp_CustomerSales_YTD_Excel",
            "description": (
                "Customer Sales Report (YTD). Returns sales units and value for the logged-in "
                "employee's team. Shows distributor-wise customer data (Trade and Institution types), "
                "customer and brick breakdown against distributors, product-wise sales, and identifies "
                "customers not buying specific products. Key marketing concern: customer count and "
                "sale against a distributor or brick."
            ),
            "max_date_range_years": 2,
            "parameters": [
                {"name": "@CompCode", "type": "varchar", "required": True, "source": "system", "description": "Company code", "default": "1"},
                {"name": "@FromYear", "type": "int", "required": True, "source": "user", "description": "Start year (e.g., 2025)"},
                {"name": "@FromMonth", "type": "int", "required": True, "source": "user", "description": "Start month (1-12)"},
                {"name": "@ToYear", "type": "int", "required": True, "source": "user", "description": "End year (e.g., 2026)"},
                {"name": "@ToMonth", "type": "int", "required": True, "source": "user", "description": "End month (1-12)"},
                {"name": "@DistributorType", "type": "varchar", "required": False, "source": "user", "description": "Distributor type filter (01=Trade, 02=Institution). Pass '0' for all.", "default": "0"},
                {"name": "@DistributorID", "type": "varchar", "required": False, "source": "user", "description": "Specific distributor ID. Pass '0' for all.", "default": "0"},
                {"name": "@CustomerID", "type": "varchar", "required": False, "source": "user", "description": "Specific customer ID. Pass '0' for all.", "default": "0"},
                {"name": "@BrickID", "type": "varchar", "required": False, "source": "user", "description": "Specific brick ID. Pass '0' for all.", "default": "0"},
                {"name": "@TeamID", "type": "varchar", "required": True, "source": "system", "description": "Team ID of the logged-in user (resolved at runtime)"},
                {"name": "@ProductID", "type": "varchar", "required": False, "source": "user", "description": "Specific product ID. Pass '0' for all.", "default": "0"},
                {"name": "@UserRole", "type": "varchar", "required": True, "source": "system", "description": "Login user role (resolved at runtime via SP_GetRole)"},
                {"name": "@EntUserEmpID", "type": "varchar", "required": True, "source": "system", "description": "Employee ID of logged-in user"},
            ]
        },
        "sales_vs_target": {
            "sp_name": "Sp_PharmaCRM_SVT",
            "description": (
                "Sales vs Target Report. Shows territory-wise sale figures compared against targets "
                "and previous period sales. Bricks are tagged with territories."
            ),
            "parameters": [
                {"name": "@Param_GroupId", "type": "varchar", "required": False, "source": "user", "description": "Group filter. Pass '' for all.", "default": ""},
                {"name": "@Param_TeamId", "type": "varchar", "required": True, "source": "system", "description": "Comma-separated Team IDs (resolved at runtime)"},
                {"name": "@Param_ProductId", "type": "varchar", "required": False, "source": "user", "description": "Product ID filter. Pass '' for all.", "default": ""},
                {"name": "@Param_TerritoryId", "type": "varchar", "required": False, "source": "user", "description": "Territory filter. Pass '' for all.", "default": ""},
                {"name": "@Param_RegionId", "type": "varchar", "required": False, "source": "user", "description": "Region filter. Pass '' for all.", "default": ""},
                {"name": "@Param_DistrictId", "type": "varchar", "required": False, "source": "user", "description": "District filter. Pass '' for all.", "default": ""},
                {"name": "@Param_SalesChannel", "type": "varchar", "required": False, "source": "user", "description": "Sales channel (1=default).", "default": "1"},
                {"name": "@Param_IsActualPrice", "type": "int", "required": False, "source": "user", "description": "Use actual price (1) or standard price (0).", "default": 1},
                {"name": "@Param_InvoiceDate_From", "type": "varchar", "required": True, "source": "user", "description": "Start date in YYYY/MM/DD format"},
                {"name": "@Param_InvoiceDate_To", "type": "varchar", "required": True, "source": "user", "description": "End date in YYYY/MM/DD format"},
                {"name": "@Param_MonthID", "type": "int", "required": False, "source": "user", "description": "Month ID for period breakdown.", "default": 1},
            ]
        },
        "incentive_summary": {
            "sp_name": "Sp_PharmaCRM_GetIncentiveProcessReport",
            "description": (
                "Incentive Finalized Summary. Returns insights related to employee incentives "
                "including finalized incentive data grouped by team, role, and territory."
            ),
            "parameters": [
                {"name": "@Compcode", "type": "nvarchar", "required": True, "source": "system", "description": "Company code", "default": "1"},
                {"name": "@FiscalYearCode", "type": "nvarchar", "required": True, "source": "user", "description": "Fiscal year code (e.g., '20242025')"},
                {"name": "@MonthYear", "type": "nvarchar", "required": True, "source": "user", "description": "Month/year filter (e.g., '2024/07/01')"},
                {"name": "@TeamIDs", "type": "nvarchar", "required": True, "source": "system", "description": "Comma-separated Team IDs (resolved at runtime)"},
                {"name": "@RoleIDs", "type": "nvarchar", "required": False, "source": "user", "description": "Comma-separated Role IDs. Pass all available if '--All--'.", "default": ""},
                {"name": "@AreaIDs", "type": "nvarchar", "required": False, "source": "user", "description": "Comma-separated Territory/Area IDs. Pass all if '--All--'.", "default": ""},
                {"name": "@GroupByIDs", "type": "nvarchar", "required": True, "source": "user", "description": "Report hierarchy (e.g., 'Team,Role,'). Defines Group by 1, 2, 3.", "default": "Team,Role,"},
            ]
        }
    }
}


def get_report_metadata(system: str) -> Dict[str, Any]:
    """Return the available reports for a given system."""
    if system.lower() == "pharma":
        return PHARMA_CRM_REPORTS
    return {}
