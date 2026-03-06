using System.Text.RegularExpressions;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Validates AI-generated SQL for safety before execution.
/// Only allows SELECT statements, blocks all data modification.
/// </summary>
public interface ISqlValidator
{
    SqlValidationResult Validate(string sql);
    string SanitizeSql(string sql);
}

public class SqlValidator : ISqlValidator
{
    private readonly ILogger<SqlValidator> _logger;
    
    // Blocked keywords - these should never appear in generated SQL
    private static readonly string[] BlockedKeywords = new[]
    {
        "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE",
        "EXEC", "EXECUTE", "sp_", "xp_", "GRANT", "REVOKE", "DENY",
        "OPENROWSET", "OPENDATASOURCE", "BULK", "SHUTDOWN", "BACKUP", "RESTORE",
        "DBCC", "KILL", "RECONFIGURE", "WAITFOR"
    };
    
    // The only allowed statement type
    private static readonly string[] AllowedStatements = new[] { "SELECT" };
    
    // Regex to detect multiple statements (semicolon followed by more SQL)
    private static readonly Regex MultiStatementRegex = new Regex(
        @";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|EXEC|CREATE)", 
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public SqlValidator(ILogger<SqlValidator> logger)
    {
        _logger = logger;
    }

    public SqlValidationResult Validate(string sql)
    {
        if (string.IsNullOrWhiteSpace(sql))
        {
            return new SqlValidationResult
            {
                IsValid = false,
                Error = "SQL query is empty"
            };
        }

        var trimmedSql = sql.Trim();
        
        // Check if it starts with SELECT
        var startsWithSelect = trimmedSql.StartsWith("SELECT", StringComparison.OrdinalIgnoreCase);
        if (!startsWithSelect)
        {
            // Check if it starts with a comment then SELECT (AI sometimes adds comments)
            var withoutComments = RemoveComments(trimmedSql);
            if (!withoutComments.TrimStart().StartsWith("SELECT", StringComparison.OrdinalIgnoreCase))
            {
                _logger.LogWarning("SQL validation failed: Query does not start with SELECT");
                return new SqlValidationResult
                {
                    IsValid = false,
                    Error = "Only SELECT queries are allowed"
                };
            }
        }

        // Check for blocked keywords
        var upperSql = trimmedSql.ToUpperInvariant();
        foreach (var keyword in BlockedKeywords)
        {
            // Use word boundary matching to avoid false positives
            var pattern = $@"\b{keyword}\b";
            if (Regex.IsMatch(upperSql, pattern))
            {
                _logger.LogWarning("SQL validation failed: Blocked keyword '{Keyword}' detected", keyword);
                return new SqlValidationResult
                {
                    IsValid = false,
                    Error = $"Blocked keyword detected: {keyword}"
                };
            }
        }

        // Check for multiple statements
        if (MultiStatementRegex.IsMatch(trimmedSql))
        {
            _logger.LogWarning("SQL validation failed: Multiple statements detected");
            return new SqlValidationResult
            {
                IsValid = false,
                Error = "Multiple SQL statements are not allowed"
            };
        }

        // Check for suspicious patterns
        if (ContainsSuspiciousPatterns(trimmedSql))
        {
            _logger.LogWarning("SQL validation failed: Suspicious pattern detected");
            return new SqlValidationResult
            {
                IsValid = false,
                Error = "Suspicious SQL pattern detected"
            };
        }

        _logger.LogInformation("SQL validation passed");
        return new SqlValidationResult
        {
            IsValid = true,
            SanitizedSql = SanitizeSql(trimmedSql)
        };
    }

    public string SanitizeSql(string sql)
    {
        // Remove any trailing semicolons
        var sanitized = sql.TrimEnd(';', ' ', '\n', '\r', '\t');
        
        // Remove any inline comments that might hide malicious code
        sanitized = Regex.Replace(sanitized, @"/\*.*?\*/", " ", RegexOptions.Singleline);
        
        return sanitized;
    }

    private string RemoveComments(string sql)
    {
        // Remove single-line comments
        var result = Regex.Replace(sql, @"--.*$", "", RegexOptions.Multiline);
        // Remove multi-line comments
        result = Regex.Replace(result, @"/\*.*?\*/", " ", RegexOptions.Singleline);
        return result;
    }

    private bool ContainsSuspiciousPatterns(string sql)
    {
        var suspiciousPatterns = new[]
        {
            @"['\""];\s*--",        // SQL injection attempt
            @"UNION\s+ALL\s+SELECT.*sys\.",  // System table access via UNION
            @"INTO\s+#",            // Temp table creation
            @"INTO\s+@",            // Table variable creation
            @"DECLARE\s+@",         // Variable declaration
            @"SET\s+@",             // Variable assignment
        };

        foreach (var pattern in suspiciousPatterns)
        {
            if (Regex.IsMatch(sql, pattern, RegexOptions.IgnoreCase))
            {
                return true;
            }
        }

        return false;
    }
}

public class SqlValidationResult
{
    public bool IsValid { get; set; }
    public string? Error { get; set; }
    public string? SanitizedSql { get; set; }
}
