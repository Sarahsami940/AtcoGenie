# Live SP Execution Summary

Server: CRMSRV / 10.10.0.9
Database: PharmaCRM
Date: 2026-04-30
Scope: narrow sample execution after user approval

## Executions
- dbo.SS_sp_CustomerSales_YTD_Excel: 4.63s, output 283136 bytes, error 0 bytes.
- dbo.Sp_PharmaCRM_SVT: 5.38s, output 5978 bytes, error 0 bytes.
- dbo.Sp_PharmaCRM_GetIncentiveProcessReport: 0.40s, output 14232 bytes, error 0 bytes.

## Sample Parameters
- Customer sales: TeamID 1, ProductID 0010550, Jul 2025, Admin/1101.
- SVT: TeamID 1, Territory 939, Region 417, District 245, FY 2025-07-01 to 2026-06-30, SalesChannel 1, SalesType 1.
- Incentive: TeamID 1, RoleID 1, AreaIDs 1015,999,985,1024,1017, MonthYear 2025/07/01.

## Safety Notes
- Pre-execution blocker check returned no active blockers for PharmaCRM.
- No direct data manipulation SQL was issued by Codex.
- SP internals executed as authored by the database.
