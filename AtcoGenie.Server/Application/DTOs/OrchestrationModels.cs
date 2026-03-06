namespace AtcoGenie.Server.Application.DTOs;

/// <summary>
/// Represents the result of a query execution from a single data source
/// </summary>
public class QueryResult
{
    public required string Source { get; set; }
    public bool IsSuccess { get; set; }
    public object? Data { get; set; }
    public string? ErrorMessage { get; set; }
    public TimeSpan ExecutionTime { get; set; }
}

/// <summary>
/// Aggregated result from multiple parallel data source queries
/// </summary>
public class AggregatedResult
{
    public IEnumerable<QueryResult> SuccessfulResults { get; set; } = Enumerable.Empty<QueryResult>();
    public IEnumerable<string> FailedSources { get; set; } = Enumerable.Empty<string>();
    public object? Data { get; set; }
    public bool HasPartialFailure => FailedSources.Any();
    public int TotalSources => SuccessfulResults.Count() + FailedSources.Count();
}

/// <summary>
/// User query request
/// </summary>
public class UserQuery
{
    public required string Prompt { get; set; }
    public List<string> RequiredSources { get; set; } = new();
}
