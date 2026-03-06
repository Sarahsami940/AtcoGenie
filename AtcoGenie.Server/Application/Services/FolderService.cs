using Microsoft.EntityFrameworkCore;
using AtcoGenie.Server.Domain.Entities;
using AtcoGenie.Server.Infrastructure.Data;
using AtcoGenie.Server.Application.DTOs;

namespace AtcoGenie.Server.Application.Services;

public interface IFolderService
{
    Task<List<FolderDto>> GetUserFoldersAsync(string userId);
    Task<FolderDto> CreateFolderAsync(string userId, string name);
    Task<FolderDto> RenameFolderAsync(int folderId, string newName);
    Task DeleteFolderAsync(int folderId);
    Task AddChatToFolderAsync(int folderId, int chatSessionId);
    Task RemoveChatFromFolderAsync(int folderId, int chatSessionId);
    Task<List<ChatSessionDto>> GetFolderChatsAsync(int folderId);
}

public class FolderService : IFolderService
{
    private readonly GenieDbContext _context;
    private const int MAX_FOLDERS_PER_USER = 20;
    private const int MAX_CHATS_PER_FOLDER = 20;

    public FolderService(GenieDbContext context)
    {
        _context = context;
    }

    public async Task<List<FolderDto>> GetUserFoldersAsync(string userId)
    {
        return await _context.Folders
            .Where(f => f.UserId == userId)
            .OrderBy(f => f.SortOrder)
            .Select(f => new FolderDto
            {
                Id = f.Id,
                Name = f.Name,
                ChatCount = f.ChatMappings.Count(cfm => !cfm.ChatSession.IsArchived),
                CreatedAt = f.CreatedAt,
                Chats = f.ChatMappings
                    .Where(cfm => !cfm.ChatSession.IsArchived)
                    .Select(cfm => new ChatSessionDto
                    {
                        Id = cfm.ChatSession.Id,
                        Title = cfm.ChatSession.Title,
                        LastActiveAt = cfm.ChatSession.LastActiveAt,
                        Model = cfm.ChatSession.ModelId ?? "Unknown"
                    }).ToList()
            })
            .ToListAsync();
    }

    public async Task<FolderDto> CreateFolderAsync(string userId, string name)
    {
        var currentCount = await _context.Folders.CountAsync(f => f.UserId == userId);
        if (currentCount >= MAX_FOLDERS_PER_USER)
        {
            throw new InvalidOperationException($"Maximum folder limit ({MAX_FOLDERS_PER_USER}) reached");
        }

        var nameExists = await _context.Folders
            .AnyAsync(f => f.UserId == userId && f.Name.ToLower() == name.ToLower());
        
        if (nameExists)
        {
            throw new InvalidOperationException("A folder with this name already exists");
        }

        var folder = new Folder
        {
            UserId = userId,
            Name = name,
            CreatedAt = DateTime.UtcNow,
            SortOrder = currentCount
        };

        _context.Folders.Add(folder);
        await _context.SaveChangesAsync();

        return new FolderDto
        {
            Id = folder.Id,
            Name = folder.Name,
            ChatCount = 0,
            CreatedAt = folder.CreatedAt
        };
    }

    public async Task<FolderDto> RenameFolderAsync(int folderId, string newName)
    {
        var folder = await _context.Folders.FindAsync(folderId);
        if (folder == null) throw new KeyNotFoundException("Folder not found");

        var nameExists = await _context.Folders
            .AnyAsync(f => f.UserId == folder.UserId && 
                          f.Id != folderId && 
                          f.Name.ToLower() == newName.ToLower());
        
        if (nameExists)
        {
            throw new InvalidOperationException("A folder with this name already exists");
        }

        folder.Name = newName;
        await _context.SaveChangesAsync();

        return new FolderDto
        {
            Id = folder.Id,
            Name = folder.Name,
            ChatCount = await _context.ChatFolderMappings.CountAsync(cfm => cfm.FolderId == folderId && !cfm.ChatSession.IsArchived),
            CreatedAt = folder.CreatedAt
        };
    }

    public async Task DeleteFolderAsync(int folderId)
    {
        var folder = await _context.Folders.FindAsync(folderId);
        if (folder == null) throw new KeyNotFoundException("Folder not found");

        _context.Folders.Remove(folder);
        await _context.SaveChangesAsync();
    }

    public async Task AddChatToFolderAsync(int folderId, int chatSessionId)
    {
        var currentCount = await _context.ChatFolderMappings
            .CountAsync(cfm => cfm.FolderId == folderId);
        
        if (currentCount >= MAX_CHATS_PER_FOLDER)
        {
            throw new InvalidOperationException($"Maximum chat limit ({MAX_CHATS_PER_FOLDER}) for this folder reached");
        }

        var exists = await _context.ChatFolderMappings
            .AnyAsync(cfm => cfm.FolderId == folderId && cfm.ChatSessionId == chatSessionId);
        
        if (exists) return;

        var mapping = new ChatFolderMapping
        {
            FolderId = folderId,
            ChatSessionId = chatSessionId,
            AddedAt = DateTime.UtcNow
        };

        _context.ChatFolderMappings.Add(mapping);
        await _context.SaveChangesAsync();
    }

    public async Task RemoveChatFromFolderAsync(int folderId, int chatSessionId)
    {
        var mapping = await _context.ChatFolderMappings
            .FirstOrDefaultAsync(cfm => cfm.FolderId == folderId && cfm.ChatSessionId == chatSessionId);
        
        if (mapping != null)
        {
            _context.ChatFolderMappings.Remove(mapping);
            await _context.SaveChangesAsync();
        }
    }

    public async Task<List<ChatSessionDto>> GetFolderChatsAsync(int folderId)
    {
        return await _context.ChatFolderMappings
            .Where(cfm => cfm.FolderId == folderId && !cfm.ChatSession.IsArchived)
            .OrderByDescending(cfm => cfm.AddedAt)
            .Select(cfm => new ChatSessionDto
            {
                Id = cfm.ChatSession.Id,
                Title = cfm.ChatSession.Title,
                LastActiveAt = cfm.ChatSession.LastActiveAt,
                Model = cfm.ChatSession.ModelId ?? "Unknown"
            })
            .ToListAsync();
    }
}
