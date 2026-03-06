namespace AtcoGenie.Server.Domain.Entities;

public class ChatFolderMapping
{
    public int Id { get; set; }
    public int FolderId { get; set; }
    public int ChatSessionId { get; set; }
    public DateTime AddedAt { get; set; }
    
    // Navigation
    public Folder Folder { get; set; } = null!;
    public ChatSession ChatSession { get; set; } = null!;
}
