using Microsoft.Data.SqlClient;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.SqlServer;

namespace AtcoGenie.Server.Infrastructure.Data.Contexts;

/// <summary>
/// Factory for creating DbContext instances with session context injection.
/// Injects user identity (HcmsEmployeeId, Email) into SQL Server SESSION_CONTEXT
/// for consumption by security TVFs (Table-Valued Functions).
/// </summary>
public class SecureDbContextFactory
{
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly ILogger<SecureDbContextFactory> _logger;

    public SecureDbContextFactory(
        IHttpContextAccessor httpContextAccessor,
        ILogger<SecureDbContextFactory> logger)
    {
        _httpContextAccessor = httpContextAccessor;
        _logger = logger;
    }

    /// <summary>
    /// Creates a DbContext with session context pre-configured.
    /// Call this before executing any queries that use security TVFs.
    /// </summary>
    public async Task<DbContext> CreateContextAsync(string connectionString, CancellationToken cancellationToken = default)
    {
        var optionsBuilder = new DbContextOptionsBuilder<DbContext>();
        optionsBuilder.UseSqlServer(connectionString);

        var context = new DbContext(optionsBuilder.Options);

        // Extract user identity from claims (set by Gatekeeper Middleware)
        var user = _httpContextAccessor.HttpContext?.User;
        
        if (user?.Identity?.IsAuthenticated == true)
        {
            var hcmsId = user.FindFirst("Genie:HcmsId")?.Value;
            var email = user.FindFirst("Genie:Email")?.Value;
            var samAccountName = user.FindFirst("Genie:SamAccountName")?.Value;

            if (!string.IsNullOrEmpty(hcmsId))
            {
                // Set session context for SQL TVFs to consume
                await SetSessionContextAsync(context, "HcmsEmployeeId", hcmsId, cancellationToken);
                await SetSessionContextAsync(context, "Email", email ?? "unknown", cancellationToken);
                await SetSessionContextAsync(context, "SamAccountName", samAccountName ?? "unknown", cancellationToken);

                _logger.LogInformation("Session context set for user: {HcmsId} ({Email})", hcmsId, email);
            }
            else
            {
                _logger.LogWarning("User authenticated but HcmsId claim is missing. Session context not set.");
            }
        }
        else
        {
            _logger.LogWarning("User not authenticated. Session context not set.");
        }

        return context;
    }

    private async Task SetSessionContextAsync(DbContext context, string key, string value, CancellationToken cancellationToken)
    {
        try
        {
            await context.Database.ExecuteSqlRawAsync(
                "EXEC sp_set_session_context @key=N'{0}', @value=N'{1}'",
                key, value);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to set session context for key: {Key}", key);
            // Don't throw - allow query to proceed but log the failure
        }
    }
}
