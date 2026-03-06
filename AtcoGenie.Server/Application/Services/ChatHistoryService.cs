using AtcoGenie.Server.Domain.Entities;
using AtcoGenie.Server.Infrastructure.Data;
using Microsoft.EntityFrameworkCore;

namespace AtcoGenie.Server.Application.Services;

public interface IChatHistoryService
{
    Task<List<ChatSession>> GetUserSessionsAsync(string userId, bool archived);
    Task<ChatSession> GetSessionAsync(int sessionId);
    Task<ChatSession> CreateSessionAsync(string userId, string title, string modelId);
    Task AddMessageAsync(int sessionId, string sender, string content);
    Task ArchiveSessionAsync(int sessionId);
    Task DeleteSessionAsync(int sessionId);
    Task RenameSessionAsync(int sessionId, string newTitle);
}

public class ChatHistoryService : IChatHistoryService
{
    private readonly GenieDbContext _context;

    public ChatHistoryService(GenieDbContext context)
    {
        _context = context;
    }

    public async Task<List<ChatSession>> GetUserSessionsAsync(string userId, bool archived)
    {
        return await _context.ChatSessions
            .Where(c => c.UserId == userId && c.IsArchived == archived)
            .OrderByDescending(c => c.LastActiveAt)
            .ToListAsync();
    }

    public async Task<ChatSession> GetSessionAsync(int sessionId)
    {
        return await _context.ChatSessions
            .Include(c => c.Messages)
            .FirstOrDefaultAsync(c => c.Id == sessionId);
    }

    public async Task<ChatSession> CreateSessionAsync(string userId, string title, string modelId)
    {
        var session = new ChatSession
        {
            UserId = userId,
            Title = title,
            ModelId = modelId,
            CreatedAt = DateTime.UtcNow,
            LastActiveAt = DateTime.UtcNow
        };

        _context.ChatSessions.Add(session);
        await _context.SaveChangesAsync();
        return session;
    }

    public async Task AddMessageAsync(int sessionId, string sender, string content)
    {
        var message = new ChatMessage
        {
            ChatSessionId = sessionId,
            Sender = sender,
            Content = content,
            Timestamp = DateTime.UtcNow
        };

        _context.ChatMessages.Add(message);
        
        var session = await _context.ChatSessions.FindAsync(sessionId);
        if (session != null)
        {
            session.LastActiveAt = DateTime.UtcNow;
            if (session.Title == "New Conversation" && sender == "user" && content.Length > 0)
            {
                 // Auto-rename logic basic
                 session.Title = content.Length > 30 ? content.Substring(0, 30) + "..." : content;
            }
        }

        await _context.SaveChangesAsync();
    }

    public async Task ArchiveSessionAsync(int sessionId)
    {
        var session = await _context.ChatSessions.FindAsync(sessionId);
        if (session != null)
        {
            session.IsArchived = true;
            await _context.SaveChangesAsync();
        }
    }
    
    public async Task RenameSessionAsync(int sessionId, string newTitle)
    {
        var session = await _context.ChatSessions.FindAsync(sessionId);
        if (session != null)
        {
            session.Title = newTitle;
            await _context.SaveChangesAsync();
        }
    }

    public async Task DeleteSessionAsync(int sessionId)
    {
        var session = await _context.ChatSessions.FindAsync(sessionId);
        if (session != null)
        {
            _context.ChatSessions.Remove(session);
            await _context.SaveChangesAsync();
        }
    }
}
