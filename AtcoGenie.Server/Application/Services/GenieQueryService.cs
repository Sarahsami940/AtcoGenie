using AtcoGenie.Server.Application.DTOs;
using AtcoGenie.Server.Domain.Entities;
using AtcoGenie.Server.Data;
using System.Text;
using System.Text.Json;
using StackExchange.Redis;
using Microsoft.EntityFrameworkCore;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Main query service - processes user prompts using the Python AI Engine (LangChain).
/// Forwards requests to the Python FastAPI service which runs the LangChain agent
/// with real PharmaCRM stored procedure execution.
/// </summary>
public interface IGenieQueryService
{
    Task<GenieQueryResponse> QueryAsync(GenieQueryRequest request, CancellationToken cancellationToken = default);
}

public class GenieQueryService : IGenieQueryService
{
    private readonly IChatHistoryService _chatHistoryService;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConnectionMultiplexer _redis;
    private readonly IConfiguration _configuration;
    private readonly ILogger<GenieQueryService> _logger;
    private readonly IServiceScopeFactory _scopeFactory;

    public GenieQueryService(
        IChatHistoryService chatHistoryService,
        IHttpContextAccessor httpContextAccessor,
        IHttpClientFactory httpClientFactory,
        IConnectionMultiplexer redis,
        IConfiguration configuration,
        ILogger<GenieQueryService> logger,
        IServiceScopeFactory scopeFactory)
    {
        _chatHistoryService = chatHistoryService;
        _httpContextAccessor = httpContextAccessor;
        _httpClientFactory = httpClientFactory;
        _redis = redis;
        _configuration = configuration;
        _logger = logger;
        _scopeFactory = scopeFactory;
    }

    public async Task<GenieQueryResponse> QueryAsync(GenieQueryRequest request, CancellationToken cancellationToken = default)
    {
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();

        try
        {
            var user = _httpContextAccessor.HttpContext?.User;
            var userName = user?.Identity?.Name ?? "anonymous";

            _logger.LogInformation("Forwarding AI query to Python engine for user {User}: {Prompt}", userName, request.Prompt);

            // 1. Look up the Python session token from Redis using the Windows username
            var adUser = user?.Identity?.Name ?? "";
            var username = adUser.Contains('\\') ? adUser.Split('\\').Last() : adUser;
            
            var redisDb = _redis.GetDatabase();
            var userKey = $"atcogenie:user-token:{username.ToLower()}";
            var sessionToken = (string?)await redisDb.StringGetAsync(userKey);

            if (string.IsNullOrEmpty(sessionToken))
            {
                // Auto-provision: build session directly (avoids fragile NTLM loopback HTTP call)
                _logger.LogInformation("No Python session token for user {User} — auto-provisioning inline...", username);
                try
                {
                    // Use a new scope to get a fresh DbContext (avoids concurrency issues)
                    using var scope = _scopeFactory.CreateScope();
                    var dbContext = scope.ServiceProvider.GetRequiredService<ImdDbContext>();

                    var rights = await dbContext.UserFormRights
                        .Where(u => u.SamAccountName.ToLower() == username.ToLower())
                        .ToListAsync(cancellationToken);

                    object sessionPayload;
                    if (rights.Any())
                    {
                        var primaryUser = rights.First();
                        sessionPayload = new
                        {
                            ad_user_id = primaryUser.SamAccountName ?? username,
                            employee_id = primaryUser.HcmsEmployeeId,
                            email = primaryUser.Email,
                            display_name = primaryUser.DisplayName,
                            department = "N/A",
                            form_rights = rights.Select(r => new
                            {
                                security_user_id = r.SecurityUserId,
                                ccode = r.CCode,
                                application_code = r.ApplicationCode,
                                form_id = r.FormId,
                                add_mode = r.AddMode,
                                edit_mode = r.EditMode,
                                view_mode = r.ViewMode,
                                delete_mode = r.DeleteMode
                            }).ToList()
                        };
                    }
                    else
                    {
                        sessionPayload = new
                        {
                            ad_user_id = username,
                            employee_id = "DEV-001",
                            email = $"{username}@atcolab.local",
                            display_name = $"{username} (Dev Override)",
                            department = "IT",
                            form_rights = new[]
                            {
                                new { security_user_id = 1, ccode = "01", application_code = "PharmaCRM", form_id = "Report1_Placeholder", add_mode = false, edit_mode = false, view_mode = true, delete_mode = false }
                            }
                        };
                    }

                    // Write session to Redis (same logic as AuthEndpoints)
                    var newSessionId = Guid.NewGuid().ToString("N");
                    var sessionKey = $"atcogenie:session:{newSessionId}";
                    await redisDb.StringSetAsync(sessionKey, JsonSerializer.Serialize(sessionPayload), TimeSpan.FromMinutes(60));
                    await redisDb.StringSetAsync(userKey, newSessionId, TimeSpan.FromMinutes(60));

                    sessionToken = newSessionId;
                    _logger.LogInformation("Auto-provisioned session token for user {User} inline.", username);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to auto-provision session for user {User}", username);
                }

                // If still empty after auto-provision attempt, return error
                if (string.IsNullOrEmpty(sessionToken))
                {
                    _logger.LogWarning("Session token still missing for user {User} after auto-provision attempt.", username);
                    return CreateErrorResponse("Your AI session could not be initialized. Please refresh the page.", stopwatch);
                }
            }

            // 2. Build chat history from session (last 10 messages for context)
            var chatHistory = new List<object>();
            if (request.SessionId.HasValue)
            {
                var session = await _chatHistoryService.GetSessionAsync(request.SessionId.Value);
                if (session?.Messages != null)
                {
                    chatHistory = session.Messages
                        .OrderByDescending(m => m.Timestamp)
                        .Take(10)
                        .OrderBy(m => m.Timestamp)
                        .Select(m => (object)new
                        {
                            role = m.Sender == "user" ? "user" : "assistant",
                            content = m.Content
                        })
                        .ToList();
                }
            }

            // 3. Forward to Python AI Engine
            var aiEngineUrl = _configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000";
            var client = _httpClientFactory.CreateClient("AiEngine");
            client.BaseAddress = new Uri(aiEngineUrl);
            client.Timeout = System.Threading.Timeout.InfiniteTimeSpan; // No hard timeout — SP chains with serialization can run long

            var payload = new
            {
                message = request.Prompt,
                chat_history = chatHistory
            };

            var jsonPayload = JsonSerializer.Serialize(payload);
            var httpRequest = new HttpRequestMessage(HttpMethod.Post, "/api/chat/")
            {
                Content = new StringContent(jsonPayload, Encoding.UTF8, "application/json")
            };
            httpRequest.Headers.Add("Authorization", $"Bearer {sessionToken}");

            var httpResponse = await client.SendAsync(httpRequest, cancellationToken);

            if (!httpResponse.IsSuccessStatusCode)
            {
                var errorBody = await httpResponse.Content.ReadAsStringAsync(cancellationToken);
                _logger.LogError("AI Engine returned {Status}: {Body}", httpResponse.StatusCode, errorBody);
                return CreateErrorResponse($"The AI Engine returned an error ({httpResponse.StatusCode}). Please try again.", stopwatch);
            }

            // 4. Parse AI Engine response
            var responseJson = await httpResponse.Content.ReadAsStringAsync(cancellationToken);
            var aiResponse = JsonSerializer.Deserialize<JsonElement>(responseJson);

            var replyText = aiResponse.TryGetProperty("reply", out var replyProp)
                ? replyProp.GetString() ?? ""
                : "";

            if (string.IsNullOrWhiteSpace(replyText))
            {
                return CreateErrorResponse("The AI Engine returned an empty response. Please try again.", stopwatch);
            }

            stopwatch.Stop();

            // 5. Persist messages to chat history
            if (request.SessionId.HasValue)
            {
                var sessionId = request.SessionId.Value;
                await _chatHistoryService.AddMessageAsync(sessionId, "user", request.Prompt);
                await _chatHistoryService.AddMessageAsync(sessionId, "bot", replyText);

                // Auto-title: rename "New Chat" sessions after first message
                var currentSession = await _chatHistoryService.GetSessionAsync(sessionId);
                if (currentSession != null && (currentSession.Title == "New Chat" || string.IsNullOrWhiteSpace(currentSession.Title)))
                {
                    var newTitle = request.Prompt.Split('\n')[0];
                    if (newTitle.Length > 40) newTitle = newTitle[..40] + "...";
                    if (string.IsNullOrWhiteSpace(newTitle)) newTitle = "Chat";
                    await _chatHistoryService.RenameSessionAsync(sessionId, newTitle);
                }
            }

            return new GenieQueryResponse
            {
                Success = true,
                Data = new GenieData { GeneratedSql = null, Rows = null, TotalRows = 0 },
                Message = replyText,
                Metadata = new GenieMetadata
                {
                    User = userName,
                    ExecutionTimeMs = stopwatch.Elapsed.TotalMilliseconds
                }
            };
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            stopwatch.Stop();
            _logger.LogInformation("Request cancelled by client for user {User}", _httpContextAccessor.HttpContext?.User?.Identity?.Name);
            return CreateErrorResponse("Request was cancelled.", stopwatch);
        }
        catch (TaskCanceledException)
        {
            stopwatch.Stop();
            _logger.LogWarning("AI Engine request timed out for user {User}", _httpContextAccessor.HttpContext?.User?.Identity?.Name);
            return CreateErrorResponse("The request timed out. Large data queries can take a while — please try a more specific query.", stopwatch);
        }
        catch (Exception ex)
        {
            stopwatch.Stop();
            _logger.LogError(ex, "Query failed [{ExType}]: {Message}", ex.GetType().Name, ex.Message);
            return CreateErrorResponse("An unexpected error occurred. Please try again.", stopwatch);
        }
    }

    private GenieQueryResponse CreateErrorResponse(string message, System.Diagnostics.Stopwatch stopwatch)
    {
        stopwatch.Stop();
        return new GenieQueryResponse
        {
            Success = true,
            Data = null,
            Message = message,
            Metadata = new GenieMetadata { ExecutionTimeMs = stopwatch.Elapsed.TotalMilliseconds }
        };
    }
}
