using AtcoGenie.Server.Application.DTOs;
using AtcoGenie.Server.Domain.Entities;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Main query service - processes user prompts using AI and returns data
/// This is the entry point for all Genie queries
/// </summary>
public interface IGenieQueryService
{
    Task<GenieQueryResponse> QueryAsync(GenieQueryRequest request, CancellationToken cancellationToken = default);
}

public class GenieQueryService : IGenieQueryService
{
    private readonly ISchemaService _schemaService;
    private readonly IGeminiService _geminiService;
    private readonly IPromptBuilder _promptBuilder;
    private readonly ISqlValidator _sqlValidator;
    private readonly IChatHistoryService _chatHistoryService;
    private readonly IMockDataService _mockDataService; // Added
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly ILogger<GenieQueryService> _logger;

    public GenieQueryService(
        ISchemaService schemaService,
        IGeminiService geminiService,
        IPromptBuilder promptBuilder,
        ISqlValidator sqlValidator,
        IChatHistoryService chatHistoryService,
        IMockDataService mockDataService, // Added
        IHttpContextAccessor httpContextAccessor,
        ILogger<GenieQueryService> logger)
    {
        _schemaService = schemaService;
        _geminiService = geminiService;
        _promptBuilder = promptBuilder;
        _sqlValidator = sqlValidator;
        _chatHistoryService = chatHistoryService;
        _mockDataService = mockDataService; // Added
        _httpContextAccessor = httpContextAccessor;
        _logger = logger;
    }

    public async Task<GenieQueryResponse> QueryAsync(GenieQueryRequest request, CancellationToken cancellationToken = default)
    {
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();

        try
        {
            // Get user identity
            var user = _httpContextAccessor.HttpContext?.User;
            var hcmsId = user?.FindFirst("Genie:HcmsId")?.Value ?? "unknown";
            var userName = user?.Identity?.Name ?? "anonymous";

            _logger.LogInformation("Processing AI query for user {User}: {Prompt}", userName, request.Prompt);

            // CHAT MODE: Bypass schema and SQL generation for now
            // var schemas = await _schemaService.GetSchemasAsync();

            // Build chat history context if session ID provided
            List<ChatHistoryItem>? chatHistory = null;
            if (request.SessionId.HasValue)
            {
                var session = await _chatHistoryService.GetSessionAsync(request.SessionId.Value);
                if (session?.Messages != null)
                {
                    chatHistory = session.Messages
                        .OrderByDescending(m => m.Timestamp) // Newest first
                        .Take(10) // Cap at 10 messages for Token Optimization
                        .OrderBy(m => m.Timestamp) // Re-order chronologically for prompt
                        .Select(m => new ChatHistoryItem
                        {
                            IsUser = m.Sender == "user",
                            Content = m.Content
                        })
                        .ToList();
                }
            }

            // Build CHAT prompt (No SQL)
            var geminiRequest = _promptBuilder.BuildChatPrompt(request.Prompt, chatHistory);

            // Call Gemini API
            var geminiResponse = await _geminiService.GenerateContentAsync(geminiRequest, cancellationToken);

            if (!geminiResponse.Success)
            {
                _logger.LogError("Gemini API failed: {Error}", geminiResponse.Error);
                return CreateErrorResponse("I'm having trouble processing your request right now. Please try again.", stopwatch);
            }

            var responseText = geminiResponse.Text ?? "";
            _logger.LogDebug("Gemini response: {Response}", responseText);

            stopwatch.Stop();

            // --- PERSISTENCE LOGIC START ---
            if (request.SessionId.HasValue)
            {
                var sessionId = request.SessionId.Value;
                
                // 1. Save User Message
                await _chatHistoryService.AddMessageAsync(sessionId, "user", request.Prompt);

                // 2. Save AI Response
                await _chatHistoryService.AddMessageAsync(sessionId, "bot", responseText);

                // 3. Auto-Title: If this is the first interaction (or title is still default), rename it
                var currentSession = await _chatHistoryService.GetSessionAsync(sessionId);
                if (currentSession != null && (currentSession.Title == "New Chat" || string.IsNullOrWhiteSpace(currentSession.Title)))
                {
                    // Simple heuristic: Use first 30 chars of user prompt
                    var newTitle = request.Prompt.Split('\n')[0]; // First line
                    if (newTitle.Length > 30) newTitle = newTitle.Substring(0, 30) + "...";
                    if (string.IsNullOrWhiteSpace(newTitle)) newTitle = "Chat";
                    
                    await _chatHistoryService.RenameSessionAsync(sessionId, newTitle);
                }
            }
            // --- PERSISTENCE LOGIC END ---
            
            // Return text response directly
            return new GenieQueryResponse
            {
                Success = true,
                Data = new GenieData
                {
                    GeneratedSql = null,
                    Rows = null,
                    TotalRows = 0
                },
                Message = FormatAIResponse(responseText),
                Metadata = new GenieMetadata
                {
                    User = userName,
                    ExecutionTimeMs = stopwatch.Elapsed.TotalMilliseconds
                }
            };
        }
        catch (Exception ex)
        {
            stopwatch.Stop();
            _logger.LogError(ex, "Query failed");

            return new GenieQueryResponse
            {
                Success = false,
                Error = "An unexpected error occurred. Please try again.",
                Metadata = new GenieMetadata
                {
                    ExecutionTimeMs = stopwatch.Elapsed.TotalMilliseconds
                }
            };
        }
    }

    private string BuildFormattedResponse(string sql, string explanation)
    {
        var response = new System.Text.StringBuilder();
        
        if (!string.IsNullOrEmpty(explanation))
        {
            response.AppendLine(explanation);
            response.AppendLine();
        }
        
        // HIDE SQL from user as requested
        // response.AppendLine("**Generated Query:**");
        // response.AppendLine("```sql");
        // response.AppendLine(sql);
        // response.AppendLine("```");
        // response.AppendLine();
        
        return response.ToString();
    }

    private string FormatAIResponse(string response)
    {
        // Clean up the response for display
        return response
            .Replace("**Clarification Needed:**", "")
            .Replace("**Explanation:**", "")
            .Trim();
    }

    private GenieQueryResponse CreateErrorResponse(string message, System.Diagnostics.Stopwatch stopwatch)
    {
        stopwatch.Stop();
        return new GenieQueryResponse
        {
            Success = true, // Success=true because it's a valid response, just no data
            Data = null,
            Message = message,
            Metadata = new GenieMetadata
            {
                ExecutionTimeMs = stopwatch.Elapsed.TotalMilliseconds
            }
        };
    }

    private List<string> DetermineDataSources(string sql, List<DataSourceSchema> schemas)
    {
        var sources = new List<string>();
        var upperSql = sql.ToUpperInvariant();

        foreach (var schema in schemas)
        {
            foreach (var entity in schema.Entities)
            {
                if (upperSql.Contains(entity.TvfName.ToUpperInvariant()))
                {
                    if (!sources.Contains(schema.Name))
                    {
                        sources.Add(schema.Name);
                    }
                }
            }
        }

        return sources.Count > 0 ? sources : new List<string> { "Unknown" };
    }
}
