namespace AtcoGenie.Server.Application.DTOs;

/// <summary>
/// Main query request from user
/// </summary>
public class GenieQueryRequest
{
    public required string Prompt { get; set; }
    public List<string>? PreferredSources { get; set; }
    public int? SessionId { get; set; } // Chat session ID for context
}

/// <summary>
/// Response containing data and metadata
/// </summary>
public class GenieQueryResponse
{
    public bool Success { get; set; }
    public string? Error { get; set; }
    public GenieData? Data { get; set; }
    public GenieMetadata? Metadata { get; set; }
    
    /// <summary>
    /// Formatted message for display (ChatGPT-style markdown)
    /// </summary>
    public string? Message { get; set; }
    
    /// <summary>
    /// True if the AI is asking for clarification instead of generating a query
    /// </summary>
    public bool NeedsClarification { get; set; }
}

public class GenieData
{
    public List<Dictionary<string, object>>? Rows { get; set; }
    public int TotalRows { get; set; }
    public string? GeneratedSql { get; set; }
}

public class GenieMetadata
{
    public string? User { get; set; }
    public List<string>? SourcesQueried { get; set; }
    public List<string>? SourcesFailed { get; set; }
    public double ExecutionTimeMs { get; set; }
}

// ===== Chat History & Folders DTOs =====

public class ChatSessionDto
{
    public int Id { get; set; }
    public string Title { get; set; } = string.Empty;
    public DateTime LastActiveAt { get; set; }
    public string Model { get; set; } = string.Empty;
    public bool IsArchived { get; set; }
}

public class FolderDto
{
    public int Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public int ChatCount { get; set; }
    public DateTime CreatedAt { get; set; }
    public List<ChatSessionDto>? Chats { get; set; }
}

