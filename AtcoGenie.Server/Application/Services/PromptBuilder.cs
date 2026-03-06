using AtcoGenie.Server.Domain.Entities;
using System.Text;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Builds prompts for Gemini API with schema context and chat history
/// </summary>
public interface IPromptBuilder
{
    GeminiRequest BuildQueryPrompt(string userPrompt, List<DataSourceSchema> schemas, List<ChatHistoryItem>? chatHistory = null, List<string>? companyContext = null);
    GeminiRequest BuildChatPrompt(string userPrompt, List<ChatHistoryItem>? chatHistory = null, List<string>? companyContext = null);
    string ExtractSqlFromResponse(string response);
    string ExtractExplanationFromResponse(string response);
}

public class PromptBuilder : IPromptBuilder
{
    private const string SystemPrompt = @"You are ATCO Genie, an intelligent data analytics assistant for enterprise users. Your role is to help users query their authorized data using natural language.

## Your Capabilities:
1. Translate natural language questions into SQL queries
2. Use ONLY the Table-Valued Functions (TVFs) provided - these handle authorization automatically
3. Provide clear explanations of the data returned
4. Ask clarifying questions when the user's intent is unclear

## Critical Rules:
1. ONLY generate SELECT statements - never INSERT, UPDATE, DELETE, or any data modification
2. ALWAYS use the TVFs provided (e.g., dbo.fn_GetAuthorizedXxx()) - NEVER query raw tables directly
3. The TVFs automatically filter data based on the logged-in user's authorization level
4. Keep explanations concise and professional
5. If you cannot determine what the user wants, ask for clarification instead of guessing
6. Format your response with clear sections for SQL and explanation

## Response Format:
When generating a query, use this exact format:

```sql
-- Your SQL query here
SELECT ...
FROM dbo.fn_GetAuthorizedXxx()
WHERE ...
```

**Explanation:** [Brief explanation of what the query does and what data it will return]

---

If you need clarification, respond with:

**Clarification Needed:** [Your question to the user]

**Clarification Needed:** [Your question to the user]

---";

    private const string ChatSystemPrompt = @"You are ATCO Genie, an intelligent assistant for enterprise users.
Your role is to be a helpful, friendly, and knowledgeable AI assistant.
You are currently in 'General Chat' mode as the database connection is being configured.
Answer the user's questions directly based on your general knowledge.
If they ask about specific ATCO internal data, politely explain that you are currently in chat mode and cannot access live data yet, but you can help with general questions.
Format your responses using Markdown for clarity (lists, bolding, code blocks where appropriate).";

    public GeminiRequest BuildQueryPrompt(string userPrompt, List<DataSourceSchema> schemas, List<ChatHistoryItem>? chatHistory = null, List<string>? companyContext = null)
    {
        var request = new GeminiRequest();

        // Add system context as part of the first message
        var contextStr = "";
        if (companyContext != null && companyContext.Count > 0)
        {
            var codes = string.Join("', '", companyContext);
            contextStr = $"\n\n## MANDATORY FILTER:\nThe user has selected specific companies: ['{codes}'].\n" +
                         "You MUST include a filter in your SQL WHERE clause: `CCode IN ('{codes}')`.\n" +
                         "Never return data outside these companies even if the TVF allows it.";
        }
        var systemContext = BuildSystemContext(schemas) + contextStr;
        
        // Build conversation history
        var contents = new List<GeminiContent>();

        // First message includes system prompt + schema context
        contents.Add(new GeminiContent
        {
            Role = "user",
            Parts = new List<GeminiPart>
            {
                new GeminiPart { Text = $"{SystemPrompt}\n\n{systemContext}\n\n---\n\nPlease acknowledge you understand your role." }
            }
        });

        contents.Add(new GeminiContent
        {
            Role = "model",
            Parts = new List<GeminiPart>
            {
                new GeminiPart { Text = "I understand. I am ATCO Genie, your data analytics assistant. I will help you query your authorized data using the provided Table-Valued Functions (TVFs). I will only generate SELECT statements and always use the security functions to ensure you only see data you're authorized to access. How can I help you today?" }
            }
        });

        // Add chat history if provided (for context)
        if (chatHistory != null && chatHistory.Count > 0)
        {
            foreach (var item in chatHistory.TakeLast(10)) // Keep last 10 messages for context
            {
                contents.Add(new GeminiContent
                {
                    Role = item.IsUser ? "user" : "model",
                    Parts = new List<GeminiPart>
                    {
                        new GeminiPart { Text = item.Content }
                    }
                });
            }
        }

        // Add the current user prompt
        contents.Add(new GeminiContent
        {
            Role = "user",
            Parts = new List<GeminiPart>
            {
                new GeminiPart { Text = userPrompt }
            }
        });

        request.Contents = contents;
        return request;
    }

    public GeminiRequest BuildChatPrompt(string userPrompt, List<ChatHistoryItem>? chatHistory = null, List<string>? companyContext = null)
    {
        var request = new GeminiRequest();
        var contents = new List<GeminiContent>();

        // Build Context String
        var contextStr = "";
        if (companyContext != null && companyContext.Count > 0)
        {
            var codes = string.Join(", ", companyContext);
            contextStr = $"\n\n## ACTIVE FILTER CONTEXT:\nThe user has explicitly scoped this query to the following Company Codes: [{codes}].\n" +
                         "If the user asks for data, metrics, or insights, you MUST clarify that you are only considering data from these specific companies.\n" +
                         "If the user asks about a company NOT in this list, politely explain that it is currently excluded from the context.";
        }

        // System Prompt
        contents.Add(new GeminiContent
        {
            Role = "user",
            Parts = new List<GeminiPart>
            {
                new GeminiPart { Text = $"{ChatSystemPrompt}{contextStr}\n\n---\n\nPlease acknowledge." }
            }
        });

        contents.Add(new GeminiContent
        {
            Role = "model",
            Parts = new List<GeminiPart>
            {
                new GeminiPart { Text = "I understand. I am ATCO Genie in General Chat mode. I will answer your questions helpfully using my general knowledge and the provided company context. How can I assist you?" }
            }
        });

        // Chat History
        if (chatHistory != null && chatHistory.Count > 0)
        {
            foreach (var item in chatHistory.TakeLast(10))
            {
                contents.Add(new GeminiContent
                {
                    Role = item.IsUser ? "user" : "model",
                    Parts = new List<GeminiPart>
                    {
                        new GeminiPart { Text = item.Content }
                    }
                });
            }
        }

        // Current Prompt
        contents.Add(new GeminiContent
        {
            Role = "user",
            Parts = new List<GeminiPart>
            {
                new GeminiPart { Text = userPrompt }
            }
        });

        request.Contents = contents;
        return request;
    }

    public string ExtractSqlFromResponse(string response)
    {
        // Look for SQL code block
        var sqlPattern = @"```sql\s*([\s\S]*?)```";
        var match = System.Text.RegularExpressions.Regex.Match(response, sqlPattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        
        if (match.Success)
        {
            var sql = match.Groups[1].Value.Trim();
            // Remove comment lines that start with --
            var lines = sql.Split('\n')
                .Where(line => !line.TrimStart().StartsWith("--") || line.Contains("SELECT"))
                .ToList();
            
            // If we removed all lines, return original
            if (lines.Count == 0) return sql;
            
            return string.Join("\n", lines).Trim();
        }

        // Try without code blocks (plain SQL)
        var plainSqlPattern = @"SELECT\s+[\s\S]*?(?:;|$)";
        match = System.Text.RegularExpressions.Regex.Match(response, plainSqlPattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        
        return match.Success ? match.Value.Trim() : string.Empty;
    }

    public string ExtractExplanationFromResponse(string response)
    {
        // Look for explanation section
        var explanationPattern = @"\*\*Explanation:\*\*\s*([\s\S]*?)(?:---|$)";
        var match = System.Text.RegularExpressions.Regex.Match(response, explanationPattern);
        
        if (match.Success)
        {
            return match.Groups[1].Value.Trim();
        }

        // If no structured explanation, try to extract text after the SQL block
        var afterSqlPattern = @"```\s*([\s\S]*)$";
        match = System.Text.RegularExpressions.Regex.Match(response, afterSqlPattern);
        
        if (match.Success)
        {
            var afterSql = match.Groups[1].Value.Trim();
            // Clean up any markdown
            afterSql = System.Text.RegularExpressions.Regex.Replace(afterSql, @"^\*\*.*\*\*:?\s*", "", System.Text.RegularExpressions.RegexOptions.Multiline);
            return afterSql;
        }

        return string.Empty;
    }

    private string BuildSystemContext(List<DataSourceSchema> schemas)
    {
        var sb = new StringBuilder();
        sb.AppendLine("## Available Data Sources and Their Schemas:");
        sb.AppendLine();

        foreach (var schema in schemas)
        {
            sb.AppendLine($"### {schema.Name} (ID: {schema.Id})");
            sb.AppendLine();
            
            foreach (var entity in schema.Entities)
            {
                sb.AppendLine($"#### TVF: `{entity.TvfName}`");
                if (!string.IsNullOrEmpty(entity.Description))
                {
                    sb.AppendLine($"Description: {entity.Description}");
                }
                sb.AppendLine();
                sb.AppendLine("| Column | Data Type | Description |");
                sb.AppendLine("|--------|-----------|-------------|");
                
                foreach (var column in entity.Columns)
                {
                    var desc = column.Description ?? "";
                    var primary = column.IsPrimary ? " (Primary Key)" : "";
                    sb.AppendLine($"| {column.Name} | {column.DataType} | {desc}{primary} |");
                }
                sb.AppendLine();
            }
        }

        sb.AppendLine("## Business Rules:");
        sb.AppendLine("- Late arrival: Clock-in (Direction='IN') after 09:00");
        sb.AppendLine("- Work hours: 09:00 - 18:00");
        sb.AppendLine("- Use proper date formatting for SQL Server (e.g., '2025-12-01')");
        sb.AppendLine();

        return sb.ToString();
    }
}

public class ChatHistoryItem
{
    public bool IsUser { get; set; }
    public string Content { get; set; } = "";
}
