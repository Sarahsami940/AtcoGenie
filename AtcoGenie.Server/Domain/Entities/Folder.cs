namespace AtcoGenie.Server.Domain.Entities;

public class Folder
{
    public int Id { get; set; }
    public string UserId { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; }
    public int SortOrder { get; set; }
    
    // Navigation
    public ICollection<ChatFolderMapping> ChatMappings { get; set; } = new List<ChatFolderMapping>();
}
