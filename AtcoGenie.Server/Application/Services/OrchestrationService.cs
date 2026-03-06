using AtcoGenie.Server.Application.DTOs;
using AtcoGenie.Server.Infrastructure.Data.Contexts;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Orchestrates parallel execution of queries across multiple data sources
/// with graceful partial failure handling.
/// </summary>
public class OrchestrationService
{
    private readonly SecureDbContextFactory _contextFactory;
    private readonly IConfiguration _configuration;
    private readonly ILogger<OrchestrationService> _logger;
    private readonly IHttpContextAccessor _httpContextAccessor;

    public OrchestrationService(
        SecureDbContextFactory contextFactory,
        IConfiguration configuration,
        ILogger<OrchestrationService> logger,
        IHttpContextAccessor httpContextAccessor)
    {
        _contextFactory = contextFactory;
        _configuration = configuration;
        _logger = logger;
        _httpContextAccessor = httpContextAccessor;
    }

    /// <summary>
    /// Executes a user query by orchestrating parallel data source queries.
    /// </summary>
    public async Task<AggregatedResult> ExecuteAsync(UserQuery query, CancellationToken cancellationToken = default)
    {
        _logger.LogInformation("Starting orchestration for prompt: {Prompt}", query.Prompt);

        var tasks = new List<Task<QueryResult>>();

        // Execute queries in parallel for each required data source
        foreach (var dataSource in query.RequiredSources)
        {
            tasks.Add(ExecuteSourceQueryAsync(dataSource, query.Prompt, cancellationToken));
        }

        // Wait for all tasks to complete (even if some fail)
        var results = await Task.WhenAll(tasks);

        // Aggregate results
        var aggregatedResult = new AggregatedResult
        {
            SuccessfulResults = results.Where(r => r.IsSuccess),
            FailedSources = results.Where(r => !r.IsSuccess).Select(r => r.Source),
            Data = MergeResults(results)
        };

        _logger.LogInformation(
            "Orchestration complete. Successful: {Success}, Failed: {Failed}",
            aggregatedResult.SuccessfulResults.Count(),
            aggregatedResult.FailedSources.Count());

        return aggregatedResult;
    }

    private async Task<QueryResult> ExecuteSourceQueryAsync(
        string dataSource,
        string prompt,
        CancellationToken cancellationToken)
    {
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();

        try
        {
            _logger.LogInformation("Executing query for source: {Source}", dataSource);

            // Get connection string for the data source
            var connectionString = _configuration.GetConnectionString(dataSource);
            if (string.IsNullOrEmpty(connectionString))
            {
                throw new InvalidOperationException($"Connection string for '{dataSource}' not found.");
            }

            // Create session-aware context
            using var context = await _contextFactory.CreateContextAsync(connectionString, cancellationToken);

            // Capture the user info that was set in session context
            var user = _httpContextAccessor.HttpContext?.User;
            var hcmsId = user?.FindFirst("Genie:HcmsId")?.Value;
            var email = user?.FindFirst("Genie:Email")?.Value;
            var samAccount = user?.FindFirst("Genie:SamAccountName")?.Value;

            // Verify we can open the connection (this also sets session context via Factory)
            await context.Database.CanConnectAsync(cancellationToken);

            stopwatch.Stop();

            return new QueryResult
            {
                Source = dataSource,
                IsSuccess = true,
                Data = new 
                { 
                    Message = "Connection successful, session context set",
                    SessionContextValues = new
                    {
                        HcmsEmployeeId = hcmsId ?? "NOT SET",
                        Email = email ?? "NOT SET",
                        SamAccountName = samAccount ?? "NOT SET"
                    },
                    Note = "These values were passed to sp_set_session_context and are available to SQL TVFs"
                },
                ExecutionTime = stopwatch.Elapsed
            };
        }
        catch (Exception ex)
        {
            stopwatch.Stop();
            _logger.LogError(ex, "Failed to execute query for source: {Source}", dataSource);

            return new QueryResult
            {
                Source = dataSource,
                IsSuccess = false,
                ErrorMessage = ex.Message,
                ExecutionTime = stopwatch.Elapsed
            };
        }
    }

    private object MergeResults(QueryResult[] results)
    {
        // Simple merge strategy: return all successful results
        // In Module 4, this will implement smart aggregation based on query type
        return results
            .Where(r => r.IsSuccess)
            .Select(r => new
            {
                r.Source,
                r.Data,
                ExecutionTimeMs = r.ExecutionTime.TotalMilliseconds
            })
            .ToList();
    }
}

/// <summary>
/// Result model for fn_GetSessionInfo() TVF
/// </summary>
public class SessionInfoResult
{
    public string? HcmsEmployeeId { get; set; }
    public string? Email { get; set; }
    public string? SamAccountName { get; set; }
    public string? DatabaseUser { get; set; }
    public string? OriginalLogin { get; set; }
    public DateTime QueryTime { get; set; }
}
