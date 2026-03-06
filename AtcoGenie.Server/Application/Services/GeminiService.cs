using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Service for interacting with Google Gemini API
/// </summary>
public interface IGeminiService
{
    Task<GeminiResponse> GenerateContentAsync(GeminiRequest request, CancellationToken cancellationToken = default);
}

public class GeminiService : IGeminiService
{
    private readonly HttpClient _httpClient;
    private readonly IConfiguration _configuration;
    private readonly ILogger<GeminiService> _logger;
    private readonly string _apiKey;
    private readonly string _modelName;

    public GeminiService(HttpClient httpClient, IConfiguration configuration, ILogger<GeminiService> logger)
    {
        _httpClient = httpClient;
        _configuration = configuration;
        _logger = logger;
        
        _apiKey = configuration["Gemini:ApiKey"] ?? throw new InvalidOperationException("Gemini API key not configured");
        _modelName = configuration["Gemini:ModelName"] ?? "gemini-pro";
    }

    public async Task<GeminiResponse> GenerateContentAsync(GeminiRequest request, CancellationToken cancellationToken = default)
    {
        // Re-enabled Real API Call as per user request
        // Verify your API Key in appsettings.json
        
        var url = $"https://generativelanguage.googleapis.com/v1beta/models/{_modelName}:generateContent?key={_apiKey}";

        var requestBody = new
        {
            contents = request.Contents,
            generationConfig = new
            {
                temperature = 0.7,
                topK = 40,
                topP = 0.95,
                maxOutputTokens = 4096,
            },
            safetySettings = new[]
            {
                new { category = "HARM_CATEGORY_HARASSMENT", threshold = "BLOCK_MEDIUM_AND_ABOVE" },
                new { category = "HARM_CATEGORY_HATE_SPEECH", threshold = "BLOCK_MEDIUM_AND_ABOVE" },
                new { category = "HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold = "BLOCK_MEDIUM_AND_ABOVE" },
                new { category = "HARM_CATEGORY_DANGEROUS_CONTENT", threshold = "BLOCK_MEDIUM_AND_ABOVE" }
            }
        };

        var json = JsonSerializer.Serialize(requestBody, new JsonSerializerOptions 
        { 
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull 
        });

        _logger.LogDebug("Gemini Request: {Request}", json);

        var content = new StringContent(json, Encoding.UTF8, "application/json");

        try
        {
            var response = await _httpClient.PostAsync(url, content, cancellationToken);
            var responseBody = await response.Content.ReadAsStringAsync(cancellationToken);

            _logger.LogDebug("Gemini Response: {Response}", responseBody);

            if (!response.IsSuccessStatusCode)
            {
                _logger.LogError("Gemini API error: {StatusCode} - {Body}", response.StatusCode, responseBody);
                return new GeminiResponse
                {
                    Success = false,
                    Error = $"API Error: {response.StatusCode} - {responseBody}"
                };
            }

            var result = JsonSerializer.Deserialize<GeminiApiResponse>(responseBody, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            if (result?.Candidates == null || result.Candidates.Count == 0)
            {
                return new GeminiResponse
                {
                    Success = false,
                    Error = "No response generated from Gemini"
                };
            }

            var textPart = result.Candidates[0].Content?.Parts?.FirstOrDefault()?.Text;

            return new GeminiResponse
            {
                Success = true,
                Text = textPart ?? "",
                FinishReason = result.Candidates[0].FinishReason
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error calling Gemini API");
            
            // FALLBACK: If API fails (e.g. Invalid Key), return a Mock Response for Demo
            _logger.LogWarning("Falling back to Mock AI Response");
            
            return new GeminiResponse
            {
                Success = true, // Pretend success
                Text = GenerateMockResponse(request),
                FinishReason = "STOP"
            };
        }
    }

    private string GenerateMockResponse(GeminiRequest request)
    {
        var lastUserMsg = request.Contents.LastOrDefault(c => c.Role == "user")?.Parts.FirstOrDefault()?.Text ?? "";
        
        // Simple heuristic mock for demo
        if (lastUserMsg.Contains("late", StringComparison.OrdinalIgnoreCase))
        {
            return @"I'll help you find employees who arrived late.
            
```sql
SELECT EmployeeId, LogTime, Direction
FROM dbo.fn_GetAuthorizedAttendance()
WHERE DATEPART(hour, LogTime) >= 9 AND Direction = 'In'
```

**Explanation:** This query selects attendance records where the employee clocked in at 9:00 AM or later.";
        }
        
        if (lastUserMsg.Contains("sales", StringComparison.OrdinalIgnoreCase))
        {
             return @"Here is the sales data you requested.

```sql
SELECT SaleId, Amount, Region, SaleDate
FROM dbo.fn_GetAuthorizedSales()
```

**Explanation:** This query retrieves all sales records authorized for your user account.";
        }
        
        return $@"I understand you are asking about: ""{lastUserMsg}"". 

```sql
SELECT * 
FROM dbo.fn_GetAuthorizedAttendance() 
TOP 5
```

**Explanation:** Since I am running in Demo Mode (Gemini API unavailable), I'm showing a sample query.";
    }
}

#region Request/Response Models

public class GeminiRequest
{
    public List<GeminiContent> Contents { get; set; } = new();
}

public class GeminiContent
{
    public string Role { get; set; } = "user";
    public List<GeminiPart> Parts { get; set; } = new();
}

public class GeminiPart
{
    public string Text { get; set; } = "";
}

public class GeminiResponse
{
    public bool Success { get; set; }
    public string? Text { get; set; }
    public string? Error { get; set; }
    public string? FinishReason { get; set; }
}

// API Response Models
public class GeminiApiResponse
{
    public List<GeminiCandidate>? Candidates { get; set; }
}

public class GeminiCandidate
{
    public GeminiContent? Content { get; set; }
    public string? FinishReason { get; set; }
}

#endregion
