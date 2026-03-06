using System;
using System.Collections.Generic;

namespace AtcoGenie.Server.Domain.Entities;

public class ChatSession
{
    public int Id { get; set; }
    public string Title { get; set; } = "New Conversation";
    public string UserId { get; set; } // HcmsEmployeeId or similar
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime LastActiveAt { get; set; } = DateTime.UtcNow;
    public bool IsArchived { get; set; } = false;
    public string ModelId { get; set; } = "gemini-3-pro";

    // Navigation property
    public List<ChatMessage> Messages { get; set; } = new();
}

public class ChatMessage
{
    public int Id { get; set; }
    public int ChatSessionId { get; set; }
    public string Sender { get; set; } // "user" or "bot"
    public string Content { get; set; }
    public DateTime Timestamp { get; set; } = DateTime.UtcNow;

    // Navigation property
    public ChatSession ChatSession { get; set; }
}
