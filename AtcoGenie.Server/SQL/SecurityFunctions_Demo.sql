-- Module 2: SQL Security Functions (TVFs)
-- These functions filter data based on SESSION_CONTEXT values set by SecureDbContextFactory

-- Example 1: Mock PharmaPulse Sales Data
-- This is a DEMO function to test session context propagation
CREATE OR ALTER FUNCTION dbo.fn_GetAuthorizedSales()
RETURNS TABLE
AS
RETURN
(
    -- In production, this would join actual sales tables with employee access tables
    -- For now, we return mock data filtered by session context
    SELECT 
        CAST(SESSION_CONTEXT(N'HcmsEmployeeId') AS NVARCHAR(50)) AS EmployeeId,
        CAST(SESSION_CONTEXT(N'Email') AS NVARCHAR(255)) AS UserEmail,
        'PharmaPulse' AS DataSource,
        'Sales' AS EntityType,
        GETDATE() AS QueryTime,
        'Mock sales data for user: ' + CAST(SESSION_CONTEXT(N'HcmsEmployeeId') AS NVARCHAR(50)) AS Description
    WHERE SESSION_CONTEXT(N'HcmsEmployeeId') IS NOT NULL
);
GO

-- Example 2: Generic Session Context Viewer (for testing)
CREATE OR ALTER FUNCTION dbo.fn_GetSessionInfo()
RETURNS TABLE
AS
RETURN
(
    SELECT 
        CAST(SESSION_CONTEXT(N'HcmsEmployeeId') AS NVARCHAR(50)) AS HcmsEmployeeId,
        CAST(SESSION_CONTEXT(N'Email') AS NVARCHAR(255)) AS Email,
        CAST(SESSION_CONTEXT(N'SamAccountName') AS NVARCHAR(100)) AS SamAccountName,
        SYSTEM_USER AS DatabaseUser,
        ORIGINAL_LOGIN() AS OriginalLogin,
        GETDATE() AS QueryTime
);
GO

-- Test the functions
-- After setting session context, these should return filtered data
-- SELECT * FROM dbo.fn_GetSessionInfo();
-- SELECT * FROM dbo.fn_GetAuthorizedSales();
