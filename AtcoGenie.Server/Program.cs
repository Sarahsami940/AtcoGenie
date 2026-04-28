using Microsoft.AspNetCore.Authentication.Negotiate;
using AtcoGenie.Server.Middleware;
using Microsoft.EntityFrameworkCore;
using AtcoGenie.Server.Data;
using AtcoGenie.Server.Application;
using AtcoGenie.Server.Endpoints;
using StackExchange.Redis;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
// Add services to the container.
builder.Services.AddDbContext<ImdDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("ImdConnection")));

// PRODUCTION: Use PostgreSQL for Chat History (Persistent) - ENABLED
builder.Services.AddDbContext<AtcoGenie.Server.Infrastructure.Data.GenieDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("ImdConnection"))); // Re-using IMD DB for chat persistence

// DEV ONLY: InMemory Database (Chats lost on restart) - DISABLED
// builder.Services.AddDbContext<AtcoGenie.Server.Infrastructure.Data.GenieDbContext>(options =>
//     options.UseInMemoryDatabase("GenieChats"));

builder.Services.AddScoped<AtcoGenie.Server.Application.Services.IChatHistoryService, AtcoGenie.Server.Application.Services.ChatHistoryService>();

builder.Services.AddApplicationServices();

// Redis setup for Sessions
var redisConnection = builder.Configuration.GetConnectionString("Redis") ?? "localhost:6379,defaultDatabase=0";
builder.Services.AddSingleton<IConnectionMultiplexer>(ConnectionMultiplexer.Connect(redisConnection));


// Fix for ChatPersistence: Handle Entity Framework circular references in JSON
builder.Services.Configure<Microsoft.AspNetCore.Http.Json.JsonOptions>(options =>
{
    options.SerializerOptions.ReferenceHandler = System.Text.Json.Serialization.ReferenceHandler.IgnoreCycles;
});

builder.Services.AddAuthentication(NegotiateDefaults.AuthenticationScheme)
   .AddNegotiate();

builder.Services.AddHostedService<AtcoGenie.Server.Services.IdentitySyncService>();

builder.Services.AddAuthorization(options =>
{
   options.FallbackPolicy = options.DefaultPolicy;
});

// Learn more about configuring OpenAPI at https://aka.ms/aspnet/openapi
builder.Services.AddOpenApi();

var app = builder.Build();

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseHttpsRedirection();

// Serve SPA static files (Module 3 Frontend)
app.UseDefaultFiles();
app.UseStaticFiles();

app.UseAuthentication();
// app.UseMiddleware<MockAuthMiddleware>(); // DISABLED FOR DEPLOYMENT (Use Real Windows Auth)

// DIAGNOSTIC: Log auth headers for troubleshooting
app.Use(async (context, next) =>
{
    var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
    
    // Low noise level
    // logger.LogWarning("Request: {Method} {Path} User: {User}", context.Request.Method, context.Request.Path, context.User.Identity?.Name);
    
    await next();
});

app.UseMiddleware<GatekeeperMiddleware>(); // Hydrate Identity
app.UseAuthorization();

var summaries = new[]
{
    "Freezing", "Bracing", "Chilly", "Cool", "Mild", "Warm", "Balmy", "Hot", "Sweltering", "Scorching"
};

app.MapGet("/weatherforecast", () =>
{
    var forecast =  Enumerable.Range(1, 5).Select(index =>
        new WeatherForecast
        (
            DateOnly.FromDateTime(DateTime.Now.AddDays(index)),
            Random.Shared.Next(-20, 55),
            summaries[Random.Shared.Next(summaries.Length)]
        ))
        .ToArray();
    return forecast;
})
.WithName("GetWeatherForecast");

// DIAGNOSTIC: Who Am I? (Verifies Auth + Gatekeeper)
app.MapGet("/api/whoami", (HttpContext context) =>
{
    var user = context.User;
    
    var info = new
    {
        IsAuthenticated = user.Identity?.IsAuthenticated ?? false,
        Name = user.Identity?.Name ?? "Anonymous",
        AuthType = user.Identity?.AuthenticationType ?? "None",
        Claims = user.Claims.Select(c => new { c.Type, c.Value }).ToList(),
        
        // This claim is injected by our 'GatekeeperMiddleware' if IMD lookup succeeded
        HcmsEmployeeId = user.FindFirst("Genie:HcmsId")?.Value ?? "NOT FOUND (Hydration Failed)",
        
        Message = user.Identity?.IsAuthenticated == true 
            ? "✅ You are logged in!" 
            : "❌ You are NOT logged in. (Check Windows Auth / Browser Settings)"
    };
    
    return info;
}); 


// Authentication Endpoint for Python frontend
app.MapAuthEndpoints();

// MODULE 3: User Company Context
app.MapGet("/api/user/companies", async (AtcoGenie.Server.Data.ImdDbContext db, HttpContext context) =>
{
    var email = context.User.FindFirst("Genie:Email")?.Value;
    // Fallback to SamAccountName claim or Identity Name (Windows Auth)
    var identityName = context.User.Identity?.Name;
    var samAccount = context.User.FindFirst("Genie:SamAccountName")?.Value 
                     ?? (identityName?.Contains('\\') == true ? identityName.Split('\\').Last() : identityName);

    if (string.IsNullOrEmpty(email) && string.IsNullOrEmpty(samAccount))
    {
        return Results.Ok(new List<string>()); 
    }

    // Query UserFormRights for distinct CCode
    var query = db.UserFormRights.AsQueryable();

    if (!string.IsNullOrEmpty(email))
    {
        query = query.Where(r => r.Email.ToLower() == email.ToLower());
    }
    else
    {
        query = query.Where(r => r.SamAccountName.ToLower() == samAccount!.ToLower());
    }

    var companies = await query
        .Where(r => r.CCode != null && r.CCode != "")
        .Select(r => r.CCode!)
        .Distinct()
        .ToListAsync();

    return Results.Ok(companies);
});

// MODULE 2 TEST: Orchestration + Session Context + Partial Failure Handling
app.MapGet("/api/test-orchestration", async (AtcoGenie.Server.Application.Services.OrchestrationService orchestrator) =>
{
    var testQuery = new AtcoGenie.Server.Application.DTOs.UserQuery
    {
        Prompt = "Test partial failure handling",
        RequiredSources = new List<string> 
        { 
            "HcmsConnection",      // Valid - should succeed
            "InvalidConnection",   // Invalid - should fail gracefully
            "ImdConnection"        // Valid - should succeed
        }
    };
    
    var result = await orchestrator.ExecuteAsync(testQuery);
    
    return new
    {
        TotalSources = result.TotalSources,
        SuccessfulCount = result.SuccessfulResults.Count(),
        FailedCount = result.FailedSources.Count(),
        FailedSources = result.FailedSources,
        HasPartialFailure = result.HasPartialFailure,
        Data = result.Data,
        Message = result.HasPartialFailure 
            ? "⚠️ Partial success - some data sources failed but operation completed"
            : "✅ All data sources responded successfully"
    };
});

// MODULE 3 TEST: Schema Registry
app.MapGet("/api/schema", async (AtcoGenie.Server.Application.Services.ISchemaService schemaService) =>
{
    return await schemaService.GetSchemasAsync();
});

// ─── USER MODEL PREFERENCE API ───────────────────────────────────────────────
// Persists the user's selected LLM model in Redis so it survives page refresh.
// The frontend interceptor calls PUT on model change; the query endpoint reads it.

var VALID_MODELS = new HashSet<string> {
    "gemini-3.1-flash-lite-preview", // Fast / lightweight (default)
    "gemini-3.1-pro-preview",        // Thinking / deep reasoning
};
const string DEFAULT_MODEL = "gemini-3.1-flash-lite-preview";


app.MapGet("/api/preferences/model", async (IConnectionMultiplexer redis, HttpContext httpContext) =>
{
    var user = httpContext.User?.Identity?.Name ?? "anonymous";
    var username = user.Contains('\\') ? user.Split('\\').Last() : user;
    var redisDb = redis.GetDatabase();
    var model = (string?)await redisDb.StringGetAsync($"atcogenie:model-pref:{username.ToLower()}");
    return Results.Ok(new { model = model ?? DEFAULT_MODEL });
});

app.MapPut("/api/preferences/model", async (
    HttpContext httpContext,
    IConnectionMultiplexer redis) =>
{
    var user = httpContext.User?.Identity?.Name ?? "anonymous";
    var username = user.Contains('\\') ? user.Split('\\').Last() : user;

    string? model = null;
    try
    {
        using var doc = await System.Text.Json.JsonDocument.ParseAsync(httpContext.Request.Body);
        doc.RootElement.TryGetProperty("model", out var modelProp);
        model = modelProp.GetString();
    }
    catch { }

    if (string.IsNullOrWhiteSpace(model) || !VALID_MODELS.Contains(model))
        return Results.BadRequest(new { error = "Invalid model", valid = VALID_MODELS });

    var redisDb = redis.GetDatabase();
    await redisDb.StringSetAsync(
        $"atcogenie:model-pref:{username.ToLower()}",
        model,
        TimeSpan.FromDays(90));   // persist for 90 days
    return Results.Ok(new { model });
});

// MAIN GENIE API: Query endpoint (returns JSON, consumes Python SSE stream internally)
app.MapPost("/api/query", async (
    AtcoGenie.Server.Application.DTOs.GenieQueryRequest request,
    AtcoGenie.Server.Application.Services.IChatHistoryService chatService,
    IHttpClientFactory httpClientFactory,
    IConnectionMultiplexer redis,
    IConfiguration configuration,
    ILogger<Program> logger,
    HttpContext httpContext) =>
{
    var stopwatch = System.Diagnostics.Stopwatch.StartNew();
    var user = httpContext.User;
    var userName = user?.Identity?.Name ?? "anonymous";
    var adUser = userName;
    var username = adUser.Contains('\\') ? adUser.Split('\\').Last() : adUser;

    // 1. Resolve Python session token from Redis
    var redisDb = redis.GetDatabase();
    var userKey = $"atcogenie:user-token:{username.ToLower()}";
    var sessionToken = (string?)await redisDb.StringGetAsync(userKey);

    if (string.IsNullOrEmpty(sessionToken))
    {
        // Auto-provision session inline
        try
        {
            using var scope = app.Services.CreateScope();
            var dbContext = scope.ServiceProvider.GetRequiredService<ImdDbContext>();
            var rights = await dbContext.UserFormRights
                .Where(u => u.SamAccountName.ToLower() == username.ToLower())
                .ToListAsync(httpContext.RequestAborted);

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

            var newSessionId = Guid.NewGuid().ToString("N");
            var sessionKey = $"atcogenie:session:{newSessionId}";
            await redisDb.StringSetAsync(sessionKey, System.Text.Json.JsonSerializer.Serialize(sessionPayload), TimeSpan.FromMinutes(60));
            await redisDb.StringSetAsync(userKey, newSessionId, TimeSpan.FromMinutes(60));
            sessionToken = newSessionId;
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to auto-provision session for {User}", username);
            stopwatch.Stop();
            return Results.Ok(new { success = true, data = (object?)null, message = "Session initialization failed. Please refresh.", metadata = new { executionTimeMs = stopwatch.Elapsed.TotalMilliseconds } });
        }
    }

    // 2. Build chat history
    var chatHistory = new List<object>();
    if (request.SessionId.HasValue)
    {
        var session = await chatService.GetSessionAsync(request.SessionId.Value);
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

    // 3. Forward to Python AI Engine — consume SSE stream efficiently
    var aiEngineUrl = configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000";
    var client = httpClientFactory.CreateClient("AiEngine");
    client.BaseAddress = new Uri(aiEngineUrl);
    client.Timeout = System.Threading.Timeout.InfiniteTimeSpan;

    // Resolve effective model: explicit request body > Redis user preference > null (Python .env default)
    var effectiveModel = request.Model;
    if (string.IsNullOrWhiteSpace(effectiveModel))
    {
        var savedModel = (string?)await redisDb.StringGetAsync($"atcogenie:model-pref:{username.ToLower()}");
        effectiveModel = string.IsNullOrWhiteSpace(savedModel) ? null : savedModel;
    }

    var payload = new { message = request.Prompt, chat_history = chatHistory, model = effectiveModel };
    var jsonPayload = System.Text.Json.JsonSerializer.Serialize(payload);
    var httpRequest = new HttpRequestMessage(HttpMethod.Post, "/api/chat/stream")
    {
        Content = new StringContent(jsonPayload, System.Text.Encoding.UTF8, "application/json")
    };
    httpRequest.Headers.Add("Authorization", $"Bearer {sessionToken}");
    // Forward the chat session ID so Python can scope dataset lookups to this session
    if (request.SessionId.HasValue)
    {
        httpRequest.Headers.Add("X-Session-Id", request.SessionId.Value.ToString());
    }

    string replyText = "";

    try
    {
        var httpResponse = await client.SendAsync(httpRequest, HttpCompletionOption.ResponseHeadersRead, httpContext.RequestAborted);
        
        httpContext.Response.ContentType = "text/event-stream";
        httpContext.Response.Headers.Append("Cache-Control", "no-cache");
        httpContext.Response.Headers.Append("Connection", "keep-alive");

        if (!httpResponse.IsSuccessStatusCode)
        {
            var errorBody = await httpResponse.Content.ReadAsStringAsync(httpContext.RequestAborted);
            logger.LogError("AI Engine returned {Status}: {Body}", httpResponse.StatusCode, errorBody);
            await httpContext.Response.WriteAsync("data: {\"type\":\"error\", \"reply\":\"AI Engine error (" + httpResponse.StatusCode + ").\"}\n\n", httpContext.RequestAborted);
            return Results.Empty;
        }

        using var stream = await httpResponse.Content.ReadAsStreamAsync(httpContext.RequestAborted);
        using var reader = new System.IO.StreamReader(stream);

        while (!reader.EndOfStream && !httpContext.RequestAborted.IsCancellationRequested)
        {
            var line = await reader.ReadLineAsync(httpContext.RequestAborted);
            if (line == null) break;

            await httpContext.Response.WriteAsync(line + "\n", httpContext.RequestAborted);
            
            if (string.IsNullOrEmpty(line))
            {
                await httpContext.Response.Body.FlushAsync(httpContext.RequestAborted);
            }

            if (line.StartsWith("data: "))
            {
                try
                {
                    var json = System.Text.Json.JsonSerializer.Deserialize<System.Text.Json.JsonElement>(line[6..]);
                    if (json.TryGetProperty("type", out var typeProp) && typeProp.GetString() == "done" && json.TryGetProperty("reply", out var replyProp))
                    {
                        replyText = replyProp.GetString() ?? "";
                    }
                }
                catch { }
            }
        }
    }
    catch (OperationCanceledException)
    {
        return Results.Empty;
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Query proxy failed for {User}: {Error}", username, ex.Message);
        if (!httpContext.Response.HasStarted)
        {
            httpContext.Response.ContentType = "text/event-stream";
            await httpContext.Response.WriteAsync("data: {\"type\":\"error\", \"reply\":\"An unexpected proxy error occurred.\"}\n\n");
        }
        return Results.Empty;
    }

    stopwatch.Stop();

    // 4. Persist chat history
    if (request.SessionId.HasValue && !string.IsNullOrWhiteSpace(replyText))
    {
        try
        {
            var sessionId = request.SessionId.Value;
            await chatService.AddMessageAsync(sessionId, "user", request.Prompt);
            await chatService.AddMessageAsync(sessionId, "bot", replyText);

            var currentSession = await chatService.GetSessionAsync(sessionId);
            if (currentSession != null && (currentSession.Title == "New Chat" || string.IsNullOrWhiteSpace(currentSession.Title)))
            {
                var newTitle = request.Prompt.Split('\n')[0];
                if (newTitle.Length > 40) newTitle = newTitle[..40] + "...";
                if (string.IsNullOrWhiteSpace(newTitle)) newTitle = "Chat";
                await chatService.RenameSessionAsync(sessionId, newTitle);
            }
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to persist chat history for {User}", username);
        }
    }

    return Results.Empty;
});

// --- UPLOAD PROXY --- same-origin proxy so browser never hits Python directly (no CORS)
// Auto-provisions a Python session token exactly like /api/query does.
async Task<string?> GetOrProvisionPythonToken(
    IConnectionMultiplexer redis, string username,
    IServiceProvider services, ILogger<Program> logger)
{
    var redisDb = redis.GetDatabase();
    var userKey = $"atcogenie:user-token:{username.ToLower()}";
    var token = (string?)await redisDb.StringGetAsync(userKey);
    if (!string.IsNullOrEmpty(token)) return token;

    // Token missing — auto-provision same as /api/query
    try
    {
        using var scope = services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<ImdDbContext>();
        var rights = await db.UserFormRights
            .Where(u => u.SamAccountName.ToLower() == username.ToLower())
            .ToListAsync();

        object payload;
        if (rights.Any())
        {
            var primary = rights.First();
            payload = new
            {
                ad_user_id    = primary.SamAccountName ?? username,
                employee_id   = primary.HcmsEmployeeId,
                email         = primary.Email,
                display_name  = primary.DisplayName,
                department    = "N/A",
                form_rights   = rights.Select(r => new
                {
                    security_user_id = r.SecurityUserId,
                    ccode            = r.CCode,
                    application_code = r.ApplicationCode,
                    form_id          = r.FormId,
                    add_mode         = r.AddMode,
                    edit_mode        = r.EditMode,
                    view_mode        = r.ViewMode,
                    delete_mode      = r.DeleteMode
                }).ToList()
            };
        }
        else
        {
            payload = new
            {
                ad_user_id   = username,
                employee_id  = "DEV-001",
                email        = $"{username}@atcolab.local",
                display_name = $"{username} (Dev)",
                department   = "IT",
                form_rights  = new[] { new { security_user_id=1, ccode="01", application_code="PharmaCRM", form_id="Report1", add_mode=false, edit_mode=false, view_mode=true, delete_mode=false } }
            };
        }

        var newSid = Guid.NewGuid().ToString("N");
        await redisDb.StringSetAsync($"atcogenie:session:{newSid}",
            System.Text.Json.JsonSerializer.Serialize(payload), TimeSpan.FromMinutes(60));
        await redisDb.StringSetAsync(userKey, newSid, TimeSpan.FromMinutes(60));
        return newSid;
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "Failed to auto-provision session for {User}", username);
        return null;
    }
}

app.MapPost("/api/data/uploads", async (HttpContext httpContext,
    IHttpClientFactory httpClientFactory, IConfiguration configuration, IConnectionMultiplexer redis) =>
{
    var user = httpContext.User?.Identity?.Name ?? "anonymous";
    var username = user.Contains('\\') ? user.Split('\\').Last() : user;
    var tok = await GetOrProvisionPythonToken(redis, username, app.Services, httpContext.RequestServices.GetRequiredService<ILogger<Program>>());
    if (string.IsNullOrEmpty(tok)) return Results.Unauthorized();

    var client = httpClientFactory.CreateClient("AiEngine");
    client.BaseAddress = new Uri(configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000");
    client.Timeout = TimeSpan.FromMinutes(2);

    var content = new StreamContent(httpContext.Request.Body);
    content.Headers.ContentType = System.Net.Http.Headers.MediaTypeHeaderValue.Parse(
        httpContext.Request.ContentType ?? "multipart/form-data");

    var req = new HttpRequestMessage(HttpMethod.Post, "/api/data/uploads") { Content = content };
    req.Headers.Add("Authorization", $"Bearer {tok}");
    var sid = httpContext.Request.Headers["X-Session-Id"].FirstOrDefault();
    if (!string.IsNullOrEmpty(sid)) req.Headers.Add("X-Session-Id", sid);

    try
    {
        var resp = await client.SendAsync(req);
        var body = await resp.Content.ReadAsStringAsync();
        return Results.Content(body, "application/json", statusCode: (int)resp.StatusCode);
    }
    catch (Exception ex)
    {
        httpContext.RequestServices.GetRequiredService<ILogger<Program>>().LogError(ex, "Upload proxy failed");
        return Results.Problem("Upload proxy error");
    }
});

app.MapGet("/api/data/uploads/{uploadId}/status", async (string uploadId,
    HttpContext httpContext, IHttpClientFactory httpClientFactory,
    IConfiguration configuration, IConnectionMultiplexer redis) =>
{
    var user = httpContext.User?.Identity?.Name ?? "anonymous";
    var username = user.Contains('\\') ? user.Split('\\').Last() : user;
    var tok = await GetOrProvisionPythonToken(redis, username, app.Services, httpContext.RequestServices.GetRequiredService<ILogger<Program>>());
    if (string.IsNullOrEmpty(tok)) return Results.Unauthorized();

    var client = httpClientFactory.CreateClient("AiEngine");
    client.BaseAddress = new Uri(configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000");
    var req = new HttpRequestMessage(HttpMethod.Get, $"/api/data/uploads/{uploadId}/status");
    req.Headers.Add("Authorization", $"Bearer {tok}");
    var resp = await client.SendAsync(req);
    return Results.Content(await resp.Content.ReadAsStringAsync(), "application/json", statusCode: (int)resp.StatusCode);
});

app.MapGet("/api/data/uploads", async (HttpContext httpContext,
    IHttpClientFactory httpClientFactory, IConfiguration configuration, IConnectionMultiplexer redis) =>
{
    var user = httpContext.User?.Identity?.Name ?? "anonymous";
    var username = user.Contains('\\') ? user.Split('\\').Last() : user;
    var tok = await GetOrProvisionPythonToken(redis, username, app.Services, httpContext.RequestServices.GetRequiredService<ILogger<Program>>());
    if (string.IsNullOrEmpty(tok)) return Results.Unauthorized();

    var client = httpClientFactory.CreateClient("AiEngine");
    client.BaseAddress = new Uri(configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000");
    var req = new HttpRequestMessage(HttpMethod.Get, "/api/data/uploads");
    req.Headers.Add("Authorization", $"Bearer {tok}");
    var sid = httpContext.Request.Headers["X-Session-Id"].FirstOrDefault();
    if (!string.IsNullOrEmpty(sid)) req.Headers.Add("X-Session-Id", sid);
    var resp = await client.SendAsync(req);
    return Results.Content(await resp.Content.ReadAsStringAsync(), "application/json", statusCode: (int)resp.StatusCode);
});

app.MapDelete("/api/data/uploads/{uploadId}", async (string uploadId,
    HttpContext httpContext, IHttpClientFactory httpClientFactory,
    IConfiguration configuration, IConnectionMultiplexer redis) =>
{
    var user = httpContext.User?.Identity?.Name ?? "anonymous";
    var username = user.Contains('\\') ? user.Split('\\').Last() : user;
    var tok = await GetOrProvisionPythonToken(redis, username, app.Services,
        httpContext.RequestServices.GetRequiredService<ILogger<Program>>());
    if (string.IsNullOrEmpty(tok)) return Results.Unauthorized();

    var client = httpClientFactory.CreateClient("AiEngine");
    client.BaseAddress = new Uri(configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000");
    var req = new HttpRequestMessage(HttpMethod.Delete, $"/api/data/uploads/{uploadId}");
    req.Headers.Add("Authorization", $"Bearer {tok}");
    var resp = await client.SendAsync(req);
    return Results.Content(await resp.Content.ReadAsStringAsync(), "application/json", statusCode: (int)resp.StatusCode);
});

// --- CHAT HISTORY API ---

// Register DB Context (InMemory for Prototype)
// Note: In Production, switch to SQL Server:
// builder.Services.AddDbContext<GenieDbContext>(options => options.UseSqlServer(builder.Configuration.GetConnectionString("GenieConnection")));

app.MapGet("/api/chats", async (string? archived, AtcoGenie.Server.Application.Services.IChatHistoryService chatService, HttpContext context) =>
{
    // USER ISOLATION: Prefer mapped EmpCode, otherwise use Windows Auth Name
    var userId = context.User.FindFirst("Genie:HcmsId")?.Value 
                 ?? context.User.Identity?.Name 
                 ?? "Anonymous";
                 
    bool isArchived = archived?.ToLower() == "true";
    return await chatService.GetUserSessionsAsync(userId, isArchived);
});

app.MapGet("/api/chats/{id}", async (int id, AtcoGenie.Server.Application.Services.IChatHistoryService chatService, HttpContext context) =>
{
    var userId = context.User.FindFirst("Genie:HcmsId")?.Value 
                 ?? context.User.Identity?.Name 
                 ?? "Anonymous";

    var session = await chatService.GetSessionAsync(id);
    
    // SECURITY CHECK: Ensure user owns this session (IDOR Protection)
    if (session != null && session.UserId != userId)
    {
        return Results.Forbid();
    }

    return session is not null ? Results.Ok(session) : Results.NotFound();
});

app.MapPost("/api/chats", async (AtcoGenie.Server.Application.Services.IChatHistoryService chatService, HttpContext context) =>
{
    var userId = context.User.FindFirst("Genie:HcmsId")?.Value 
                 ?? context.User.Identity?.Name 
                 ?? "Anonymous";
                 
    var session = await chatService.CreateSessionAsync(userId, "New Chat", "gemini-3-pro");
    return Results.Created($"/api/chats/{session.Id}", session);
});

app.MapPost("/api/chats/{id}/messages", async (int id, AtcoGenie.Server.Domain.Entities.ChatMessage message, AtcoGenie.Server.Application.Services.IChatHistoryService chatService) =>
{
    await chatService.AddMessageAsync(id, message.Sender, message.Content);
    return Results.Ok();
});

app.MapPut("/api/chats/{id}/rename", async (int id, string title, AtcoGenie.Server.Application.Services.IChatHistoryService chatService) =>
{
    await chatService.RenameSessionAsync(id, title);
    return Results.Ok();
});

app.MapPut("/api/chats/{id}/archive", async (int id, AtcoGenie.Server.Application.Services.IChatHistoryService chatService) =>
{
    await chatService.ArchiveSessionAsync(id);
    return Results.Ok();
});

app.MapDelete("/api/chats/{id}", async (
    int id,
    AtcoGenie.Server.Application.Services.IChatHistoryService chatService,
    IHttpClientFactory httpClientFactory,
    IConfiguration configuration,
    IConnectionMultiplexer redis,
    HttpContext httpContext) =>
{
    var user = httpContext.User;
    var userName = user?.Identity?.Name ?? "anonymous";
    var adUser = userName;
    var username = adUser.Contains('\\') ? adUser.Split('\\').Last() : adUser;

    await chatService.DeleteSessionAsync(id);

    // Cascade: remove all uploaded datasets tied to this chat session
    try
    {
        var aiEngineUrl = configuration["AiEngine:BaseUrl"] ?? "http://localhost:8000";
        var redisDb = redis.GetDatabase();
        var userKey = $"atcogenie:user-token:{username.ToLower()}";
        var sessionToken = (string?)await redisDb.StringGetAsync(userKey);

        if (!string.IsNullOrEmpty(sessionToken))
        {
            var client = httpClientFactory.CreateClient("AiEngine");
            client.BaseAddress = new Uri(aiEngineUrl);
            var deleteRequest = new HttpRequestMessage(
                HttpMethod.Delete,
                $"/api/data/uploads/by-session/{id}");
            deleteRequest.Headers.Add("Authorization", $"Bearer {sessionToken}");
            await client.SendAsync(deleteRequest);
        }
    }
    catch (Exception ex)
    {
        // Non-fatal: log and continue. Files will remain on disk but DB row is already gone.
        var logger = httpContext.RequestServices.GetRequiredService<ILogger<Program>>();
        logger.LogWarning(ex, "Failed to cascade-delete uploads for session {SessionId}", id);
    }

    return Results.Ok();
});

// ===== FOLDER MANAGEMENT API =====

// GET: Retrieve all folders for current user
app.MapGet("/api/folders", async (AtcoGenie.Server.Application.Services.IFolderService folderService, HttpContext context) =>
{
    var userId = context.User.FindFirst("Genie:HcmsId")?.Value 
                 ?? context.User.Identity?.Name 
                 ?? "Anonymous";
                 
    return Results.Ok(await folderService.GetUserFoldersAsync(userId));
});

// POST: Create new folder
app.MapPost("/api/folders", async (AtcoGenie.Server.Application.DTOs.FolderDto request, AtcoGenie.Server.Application.Services.IFolderService folderService, HttpContext context) =>
{
    var userId = context.User.FindFirst("Genie:HcmsId")?.Value 
                 ?? context.User.Identity?.Name 
                 ?? "Anonymous";
    
    try
    {
        var folder = await folderService.CreateFolderAsync(userId, request.Name);
        return Results.Created($"/api/folders/{folder.Id}", folder);
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

// PUT: Rename folder
app.MapPut("/api/folders/{id}/rename", async (int id, string name, AtcoGenie.Server.Application.Services.IFolderService folderService) =>
{
    try
    {
        var folder = await folderService.RenameFolderAsync(id, name);
        return Results.Ok(folder);
    }
    catch (KeyNotFoundException)
    {
        return Results.NotFound();
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

// DELETE: Delete folder (does NOT delete chats)
app.MapDelete("/api/folders/{id}", async (int id, AtcoGenie.Server.Application.Services.IFolderService folderService) =>
{
    try
    {
        await folderService.DeleteFolderAsync(id);
        return Results.Ok();
    }
    catch (KeyNotFoundException)
    {
        return Results.NotFound();
    }
});

// POST: Add chat to folder
app.MapPost("/api/folders/{folderId}/chats/{chatId}", async (int folderId, int chatId, AtcoGenie.Server.Application.Services.IFolderService folderService) =>
{
    try
    {
        await folderService.AddChatToFolderAsync(folderId, chatId);
        return Results.Ok();
    }
    catch (InvalidOperationException ex)
    {
        return Results.BadRequest(new { error = ex.Message });
    }
});

// DELETE: Remove chat from folder (does NOT delete chat)
app.MapDelete("/api/folders/{folderId}/chats/{chatId}", async (int folderId, int chatId, AtcoGenie.Server.Application.Services.IFolderService folderService) =>
{
    await folderService.RemoveChatFromFolderAsync(folderId, chatId);
    return Results.Ok();
});

// GET: Get all chats in a folder
app.MapGet("/api/folders/{id}/chats", async (int id, AtcoGenie.Server.Application.Services.IFolderService folderService) =>
{
    var chats = await folderService.GetFolderChatsAsync(id);
    return Results.Ok(chats);
});

// Initialize Database
using (var scope = app.Services.CreateScope())
{
    var services = scope.ServiceProvider;
    var logger = services.GetRequiredService<ILogger<Program>>();
    
    try
    {
        var context = services.GetRequiredService<ImdDbContext>();
        context.Database.EnsureCreated();
        
        var sql = @"
CREATE TABLE IF NOT EXISTS imd_userformrights (
    id              SERIAL PRIMARY KEY,
    adobjectguid    UUID NOT NULL,
    hcmsemployeeid  VARCHAR(50) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    displayname     VARCHAR(255),
    samaccountname  VARCHAR(100),
    isactive        BOOLEAN DEFAULT TRUE,
    securityuserid  INT NULL,
    ccode           VARCHAR(50) NULL,
    applicationcode VARCHAR(50) NULL,
    formid          VARCHAR(100) NULL,
    addmode         BOOLEAN NULL,
    editmode        BOOLEAN NULL,
    viewmode        BOOLEAN NULL,
    deletemode      BOOLEAN NULL,
    lastsyncedat    TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ufr_hcmsemployeeid ON imd_userformrights(hcmsemployeeid);
CREATE INDEX IF NOT EXISTS ix_ufr_email ON imd_userformrights(email);
";
        context.Database.ExecuteSqlRaw(sql);
        logger.LogInformation("IMD Database initialized successfully.");
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "An error occurred creating the IMD database.");
    }
    
    // Initialize Genie chat & folders database
    try
    {
        var genieDb = services.GetRequiredService<AtcoGenie.Server.Infrastructure.Data.GenieDbContext>();
        genieDb.Database.EnsureCreated();
        
        var genieSql = @"
CREATE SCHEMA IF NOT EXISTS genie;
CREATE TABLE IF NOT EXISTS genie.""ChatSessions"" (
    ""Id"" SERIAL PRIMARY KEY,
    ""Title"" VARCHAR(200) NOT NULL,
    ""UserId"" VARCHAR(100) NOT NULL,
    ""CreatedAt"" TIMESTAMP NOT NULL,
    ""LastActiveAt"" TIMESTAMP NOT NULL,
    ""IsArchived"" BOOLEAN NOT NULL DEFAULT FALSE,
    ""ModelId"" VARCHAR(50) NULL
);
CREATE TABLE IF NOT EXISTS genie.""ChatMessages"" (
    ""Id"" SERIAL PRIMARY KEY,
    ""ChatSessionId"" INT NOT NULL,
    ""Sender"" VARCHAR(10) NOT NULL CHECK (""Sender"" IN ('user', 'bot')),
    ""Content"" TEXT NOT NULL,
    ""Timestamp"" TIMESTAMP NOT NULL,
    CONSTRAINT ""FK_ChatMessages_ChatSessions"" FOREIGN KEY (""ChatSessionId"") REFERENCES genie.""ChatSessions""(""Id"") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS genie.""Folders"" (
    ""Id"" SERIAL PRIMARY KEY,
    ""UserId"" VARCHAR(100) NOT NULL,
    ""Name"" VARCHAR(100) NOT NULL,
    ""CreatedAt"" TIMESTAMP NOT NULL,
    ""SortOrder"" INT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS genie.""ChatFolderMappings"" (
    ""Id"" SERIAL PRIMARY KEY,
    ""FolderId"" INT NOT NULL,
    ""ChatSessionId"" INT NOT NULL,
    ""AddedAt"" TIMESTAMP NOT NULL,
    CONSTRAINT ""FK_ChatFolderMappings_Folders"" FOREIGN KEY (""FolderId"") REFERENCES genie.""Folders""(""Id"") ON DELETE CASCADE,
    CONSTRAINT ""FK_ChatFolderMappings_ChatSessions"" FOREIGN KEY (""ChatSessionId"") REFERENCES genie.""ChatSessions""(""Id"") ON DELETE CASCADE
);
";
        genieDb.Database.ExecuteSqlRaw(genieSql);
        logger.LogInformation("Genie Database initialized successfully.");
    }
    catch (Exception ex)
    {
        logger.LogWarning(ex, "Genie Database initialization failed - folders feature will not work.");
    }
}

// SPA Fallback (Must be last)
app.MapFallbackToFile("index.html");

app.Run();

record WeatherForecast(DateOnly Date, int TemperatureC, string? Summary)
{
    public int TemperatureF => 32 + (int)(TemperatureC / 0.5556);
}
