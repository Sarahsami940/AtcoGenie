using System.DirectoryServices;
using System.Runtime.Versioning;
using Microsoft.EntityFrameworkCore;

namespace AtcoGenie.Server.Services;

public class IdentitySyncService : BackgroundService
{
    private readonly ILogger<IdentitySyncService> _logger;
    private readonly IConfiguration _config;
    private readonly IServiceProvider _serviceProvider;

    public IdentitySyncService(ILogger<IdentitySyncService> logger, IConfiguration config, IServiceProvider serviceProvider)
    {
        _logger = logger;
        _config = config;
        _serviceProvider = serviceProvider;
    }

    [SupportedOSPlatform("windows")]
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Identity Sync Service started.");

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                _logger.LogInformation("--- SYNC CYCLE [V3.9 - Robust Loop] STARTED at {Time} ---", DateTimeOffset.Now);

                // 0. Scrub DB for consistency
                await ScrubDatabaseAsync(stoppingToken);

                var adUsers = FetchAdUsers();
                var hcmsEmployees = await FetchHcmsEmployeesAsync(stoppingToken);

                _logger.LogInformation("Fetch Results: AD={AdCount}, HCMS={HcmsCount}", adUsers.Count, hcmsEmployees.Count);

                // Step 1: Sync active identities
                await SyncIdentitiesAsync(adUsers, hcmsEmployees, stoppingToken);

                // Step 2: Sync form rights
                await SyncUserFormRightsAsync(adUsers, hcmsEmployees, stoppingToken);

                _logger.LogInformation("Sync cycle completed successfully. Next run in 30 seconds.");
                await Task.Delay(TimeSpan.FromSeconds(30), stoppingToken);
            }
            catch (OperationCanceledException)
            {
                _logger.LogInformation("Identity Sync Service is stopping.");
                break; // Exit loop gracefully
            }
            catch (Exception ex)
            {
                try { _logger.LogError(ex, "Error occurred during Identity Sync. Retrying in 30 seconds..."); }
                catch { /* Logger may be disposed during shutdown */ }
                try 
                { 
                    await Task.Delay(TimeSpan.FromSeconds(30), stoppingToken); 
                } 
                catch (OperationCanceledException) { break; }
            }
        }
        _logger.LogInformation("Identity Sync Service stopped.");
    }

    // ─────────────────────────────────────────────────────
    // STEP 1: Sync AD + HCMS → imd_usermapping
    // ─────────────────────────────────────────────────────
    private async Task SyncIdentitiesAsync(List<AdUserInfo> adUsersRaw, List<HcmsEmployee> hcmsEmployeesRaw, CancellationToken stoppingToken)
    {
        var adUsers = adUsersRaw
            .Where(u => !string.IsNullOrEmpty(u.Email))
            .GroupBy(u => u.Email.ToLower())
            .Select(g => g.First())
            .ToDictionary(u => u.Email.ToLower());

        var hcmsDeduped = hcmsEmployeesRaw
            .Where(e => !string.IsNullOrEmpty(e.Email))
            .GroupBy(e => e.Email.ToLower())
            .Select(g => g.First())
            .ToDictionary(e => e.Email.ToLower());

        var matchedEmails = adUsers.Keys.Intersect(hcmsDeduped.Keys).ToList();
        _logger.LogInformation("Identity Sync: Found {MatchCount} matches between AD and HCMS.", matchedEmails.Count);

        using var scope = _serviceProvider.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AtcoGenie.Server.Data.ImdDbContext>();

        foreach (var emailKey in matchedEmails)
        {
            var adUser = adUsers[emailKey];
            var hcmsEmployee = hcmsDeduped[emailKey];

            var existing = await db.UserMappings.FirstOrDefaultAsync(u => u.Email.ToLower() == emailKey, stoppingToken);

            if (existing == null)
            {
                db.UserMappings.Add(new AtcoGenie.Server.Data.UserMapping
                {
                    AdObjectGuid = adUser.ObjectGuid,
                    Email = adUser.Email,
                    DisplayName = adUser.DisplayName,
                    SamAccountName = adUser.SamAccountName,
                    HcmsEmployeeId = hcmsEmployee.EmployeeId,
                    IsActive = true,
                    LastSyncedAt = DateTime.UtcNow
                });
            }
            else
            {
                existing.HcmsEmployeeId = hcmsEmployee.EmployeeId; // Force update to EmpId (int)
                existing.AdObjectGuid = adUser.ObjectGuid;
                existing.SamAccountName = adUser.SamAccountName;
                existing.DisplayName = adUser.DisplayName;
                existing.LastSyncedAt = DateTime.UtcNow;
            }
        }

        await db.SaveChangesAsync(stoppingToken);
        _logger.LogInformation("Successfully updated {Count} records in imd_usermapping.", matchedEmails.Count);
    }

    // ─────────────────────────────────────────────────────
    // STEP 2: Sync Form Rights → imd_userformrights
    // ─────────────────────────────────────────────────────
    private async Task SyncUserFormRightsAsync(List<AdUserInfo> adUsersRaw, List<HcmsEmployee> hcmsEmployeesRaw, CancellationToken stoppingToken)
    {
        _logger.LogInformation("Starting UserFormRights sync (Direct Source AD+HCMS)...");

        using var scope = _serviceProvider.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AtcoGenie.Server.Data.ImdDbContext>();

        // 1. Identify valid users by EmpId (Group by EmpId to handle duplicate emails)
        var hcmsLookup = hcmsEmployeesRaw
            .Where(e => !string.IsNullOrEmpty(e.Email))
            .GroupBy(e => e.Email.ToLower())
            .Select(g => g.First())
            .ToDictionary(e => e.Email.ToLower());

        var matchedEmpIds = new HashSet<string>();
        var empIdToAdInfo = new Dictionary<string, AdUserInfo>();

        foreach (var adUser in adUsersRaw.Where(u => !string.IsNullOrEmpty(u.Email)))
        {
            if (hcmsLookup.TryGetValue(adUser.Email.ToLower(), out var hcmsEmp))
            {
                var empId = hcmsEmp.EmployeeId;
                if (!matchedEmpIds.Contains(empId))
                {
                    matchedEmpIds.Add(empId);
                    empIdToAdInfo[empId] = adUser; // Keep first AD info found for this EmpId
                }
            }
        }

        _logger.LogInformation("FormRights Sync: Processing {EmpCount} unique Employee IDs.", matchedEmpIds.Count);

        if (matchedEmpIds.Count == 0) return;

        // 2. Fetch all rights from Security DB using the triple-join
        var flatRights = await FetchAllFormRightsAsync(stoppingToken);
        var rightsByEmpId = flatRights
            .GroupBy(r => r.HcmsEmpId)
            .ToDictionary(g => g.Key, g => g.ToList());

        // 3. Fetch baseline security User IDs for all users (even those with no form rights)
        var baseSecurityUserIds = await FetchSecurityUserIdsOnlyAsync(stoppingToken);

        int rowsProcessed = 0;

        foreach (var empId in matchedEmpIds)
        {
            var adUser = empIdToAdInfo[empId]; // Use the representative AD user for this EmpId

            // IMPORTANT: Match by EMAIL, not just EmpId, to avoid duplicates if EmpId changes (e.g. EmpCode vs EmpId)
            var existingRights = await db.UserFormRights
                .Where(r => r.Email.ToLower() == adUser.Email.ToLower())
                .ToListAsync(stoppingToken);
            
            if (rightsByEmpId.TryGetValue(empId, out var rawRights))
            {
                // DEDUPLICATE: Ensure only one rights entry per App/Form combo.
                // If duplicates exist in source, take the first one found.
                var securityRights = rawRights
                    .GroupBy(r => new { r.ApplicationCode, r.FormId })
                    .Select(g => g.First())
                    .ToList();

                // USER HAS RIGHTS -> Create/Update right-specific rows
                foreach (var right in securityRights)
                {
                    var existing = existingRights.FirstOrDefault(r => r.ApplicationCode == right.ApplicationCode && r.FormId == right.FormId);

                    if (existing == null)
                    {
                        var newRight = new AtcoGenie.Server.Data.UserFormRight
                        {
                            AdObjectGuid = adUser.ObjectGuid,
                            HcmsEmployeeId = empId, // Set to the current correct EmpId from HCMS fetch
                            Email = adUser.Email,
                            DisplayName = adUser.DisplayName,
                            SamAccountName = adUser.SamAccountName,
                            IsActive = true,
                            SecurityUserId = right.SecurityUserId,
                            CCode = right.CCode,
                            ApplicationCode = right.ApplicationCode,
                            FormId = right.FormId,
                            AddMode = right.AddMode,
                            EditMode = right.EditMode,
                            ViewMode = right.ViewMode,
                            DeleteMode = right.DeleteMode,
                            LastSyncedAt = DateTime.UtcNow
                        };
                        db.UserFormRights.Add(newRight);
                        existingRights.Add(newRight); // Track locally to prevent re-adding if loop circles back
                    }
                    else
                    {
                        existing.AdObjectGuid = adUser.ObjectGuid;
                        existing.SecurityUserId = right.SecurityUserId;
                        existing.CCode = right.CCode;
                        existing.AddMode = right.AddMode;
                        existing.EditMode = right.EditMode;
                        existing.ViewMode = right.ViewMode;
                        existing.DeleteMode = right.DeleteMode;
                        existing.DisplayName = adUser.DisplayName;
                        existing.Email = adUser.Email;
                        existing.LastSyncedAt = DateTime.UtcNow;
                    }
                }

                // Cleanup placeholders: If real rights rows were just added/updated,
                // find and delete the row where ApplicationCode is null (the "identity-only" row)
                var ghosts = existingRights.Where(r => r.ApplicationCode == null).ToList();
                if (ghosts.Any())
                {
                    db.UserFormRights.RemoveRange(ghosts);
                }
            }
            else
            {
                // USER HAS NO RIGHTS -> Create/Update a single placeholder row
                baseSecurityUserIds.TryGetValue(empId, out int baseSecurityUserId);
                int? nullableSecurityUserId = baseSecurityUserId > 0 ? baseSecurityUserId : null;

                var existing = existingRights.FirstOrDefault(r => r.ApplicationCode == null);
                if (existing == null)
                {
                    db.UserFormRights.Add(new AtcoGenie.Server.Data.UserFormRight
                    {
                        AdObjectGuid = adUser.ObjectGuid,
                        HcmsEmployeeId = empId,
                        Email = adUser.Email,
                        DisplayName = adUser.DisplayName,
                        SamAccountName = adUser.SamAccountName,
                        IsActive = true,
                        SecurityUserId = nullableSecurityUserId,
                        LastSyncedAt = DateTime.UtcNow
                    });
                }
                else
                {
                    existing.AdObjectGuid = adUser.ObjectGuid;
                    existing.DisplayName = adUser.DisplayName;
                    existing.Email = adUser.Email;
                    existing.SecurityUserId = nullableSecurityUserId;
                    existing.LastSyncedAt = DateTime.UtcNow;
                }
            }

            rowsProcessed++;
            if (rowsProcessed % 100 == 0) await db.SaveChangesAsync(stoppingToken);
        }

        await db.SaveChangesAsync(stoppingToken);
        _logger.LogInformation("imd_userformrights sync complete.");
    }

    // ─────────────────────────────────────────────────────
    // DATA FETCHERS (SQL Server)
    // ─────────────────────────────────────────────────────

    private async Task<List<SecurityRawRight>> FetchAllFormRightsAsync(CancellationToken stoppingToken)
    {
        var results = new List<SecurityRawRight>();
        var connectionString = _config.GetConnectionString("HcmsConnection");

        try
        {
            using var conn = new Microsoft.Data.SqlClient.SqlConnection(connectionString);
            await conn.OpenAsync(stoppingToken);

            // User's provided query logic:
            // JOIN [Security].[dbo].[UserMapping] As D2 ON D1.EmpId = D2.EmployeeID
            // JOIN [Security].[dbo].[UserFormRights] As D3 ON D2.UserID = D3.UserID
            var sql = @"
            SELECT DISTINCT 
                   D1.[EmpId],
                   D2.[UserId] as SecurityUserId,
                   D3.[CCode],
                   D3.[ApplicationCode],
                   D3.[FormID],
                   D3.[AddMode],
                   D3.[EditMode],
                   D3.[DeleteMode],
                   D3.[ViewMode]
            FROM [HCMS].[dbo].[tblEmployee] As D1
            JOIN [Security].[dbo].[UserMapping] As D2 ON D1.EmpId = D2.EmployeeID
            JOIN [Security].[dbo].[UserFormRights] As D3 ON D2.UserID = D3.UserID
            WHERE (D1.Active = 1 OR D1.Active = 2) 
              AND D3.[ApplicationCode] IN ('PharmaCRM', 'HCMS', 'PharmaCRMv2');";

            using var cmd = new Microsoft.Data.SqlClient.SqlCommand(sql, conn);
            using var reader = await cmd.ExecuteReaderAsync(stoppingToken);
            int count = 0;
            while (await reader.ReadAsync(stoppingToken))
            {
                var row = new SecurityRawRight
                {
                    HcmsEmpId = NormalizeId(reader["EmpId"]?.ToString()),
                    SecurityUserId = reader["SecurityUserId"] == DBNull.Value ? 0 : Convert.ToInt32(reader["SecurityUserId"]),
                    CCode = reader["CCode"]?.ToString(),
                    ApplicationCode = reader["ApplicationCode"]?.ToString() ?? "",
                    FormId = reader["FormID"]?.ToString(),
                    AddMode = SafeToBoolean(reader["AddMode"]),
                    EditMode = SafeToBoolean(reader["EditMode"]),
                    ViewMode = SafeToBoolean(reader["ViewMode"]),
                    DeleteMode = SafeToBoolean(reader["DeleteMode"])
                };
                results.Add(row);

                if (count < 5)
                {
                    _logger.LogInformation("TRACE: FetchAllFormRights - Row {N}: EmpId={EmpId}, RawUserId={RawUserId} (Type={Type}), ParsedUserId={UserId}", 
                        count, row.HcmsEmpId, 
                        reader.IsDBNull(reader.GetOrdinal("SecurityUserId")) ? "NULL" : reader["SecurityUserId"].ToString(),
                        reader.IsDBNull(reader.GetOrdinal("SecurityUserId")) ? "DBNull" : reader["SecurityUserId"].GetType().Name,
                        row.SecurityUserId);
                }
                count++;
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "FetchAllFormRights: Failed to execute joined security query.");
        }

        return results;
    }

    private async Task<Dictionary<string, int>> FetchSecurityUserIdsOnlyAsync(CancellationToken stoppingToken)
    {
        var results = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var connectionString = _config.GetConnectionString("HcmsConnection");

        try
        {
            using var conn = new Microsoft.Data.SqlClient.SqlConnection(connectionString);
            await conn.OpenAsync(stoppingToken);

            var sql = @"
            SELECT DISTINCT [EmployeeID], [UserId] 
            FROM [Security].[dbo].[UserMapping] 
            WHERE [EmployeeID] IS NOT NULL AND [UserId] IS NOT NULL;";

            using var cmd = new Microsoft.Data.SqlClient.SqlCommand(sql, conn);
            using var reader = await cmd.ExecuteReaderAsync(stoppingToken);
            while (await reader.ReadAsync(stoppingToken))
            {
                var rsEmpId = NormalizeId(reader["EmployeeID"]?.ToString());
                var rsUserId = reader["UserId"] != DBNull.Value ? Convert.ToInt32(reader["UserId"]) : (int?)null;
                if (!string.IsNullOrEmpty(rsEmpId) && rsUserId.HasValue)
                {
                    results.TryAdd(rsEmpId, rsUserId.Value);
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "FetchSecurityUserIdsOnly: Failed.");
        }
        return results;
    }

    private async Task<List<HcmsEmployee>> FetchHcmsEmployeesAsync(CancellationToken stoppingToken)
    {
        var results = new List<HcmsEmployee>();
        var connectionString = _config.GetConnectionString("HcmsConnection");

        try
        {
            using var conn = new Microsoft.Data.SqlClient.SqlConnection(connectionString);
            await conn.OpenAsync(stoppingToken);

            var sql = @"
            SELECT DISTINCT D1.[EmpId], D1.[Email]
            FROM [HCMS].[dbo].[tblEmployee] as D1
            INNER JOIN [Security].[dbo].[UserMapping] AS D2 ON D1.EmpId = D2.EmployeeId
            WHERE (D1.Active = 1 or D1.Active = 2) AND D1.[Email] IS NOT NULL AND D1.[Email] <> '';";

            using var cmd = new Microsoft.Data.SqlClient.SqlCommand(sql, conn);
            using var reader = await cmd.ExecuteReaderAsync(stoppingToken);
            int count = 0;
            while (await reader.ReadAsync(stoppingToken))
            {
                var email = reader["Email"]?.ToString();
                var empId = NormalizeId(reader["EmpId"]?.ToString());
                if (!string.IsNullOrEmpty(email) && !string.IsNullOrEmpty(empId))
                {
                    results.Add(new HcmsEmployee { Email = email, EmployeeId = empId });
                    if (count < 5)
                    {
                        _logger.LogInformation("TRACE: FetchHcms - Row {N}: RawEmpId={Raw}, NormEmpId={Norm}, Email={Email}", 
                            count, reader["EmpId"], empId, email);
                    }
                }
                count++;
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "FetchHcmsEmployees: SQL Error.");
        }
        return results;
    }

    [SupportedOSPlatform("windows")]
    private List<AdUserInfo> FetchAdUsers()
    {
        var results = new List<AdUserInfo>();
        var ldapPath = _config["Identity:LdapPath"] ?? "LDAP://DC=atco,DC=local";
        
        try
        {
            using var entry = new DirectoryEntry(ldapPath);
            using var searcher = new DirectorySearcher(entry);
            searcher.Filter = "(&(objectClass=user)(objectCategory=person)(!userAccountControl:1.2.840.113556.1.4.803:=2))";
            searcher.PropertiesToLoad.Add("objectGUID");
            searcher.PropertiesToLoad.Add("mail");
            searcher.PropertiesToLoad.Add("displayName");
            searcher.PropertiesToLoad.Add("sAMAccountName");

            using var collection = searcher.FindAll();
            foreach (SearchResult result in collection)
            {
                var email = GetProperty(result, "mail");
                if (string.IsNullOrEmpty(email)) continue;

                results.Add(new AdUserInfo
                {
                    ObjectGuid = new Guid((byte[])result.Properties["objectGUID"][0]),
                    Email = email,
                    DisplayName = GetProperty(result, "displayName"),
                    SamAccountName = GetProperty(result, "sAMAccountName")
                });
            }
        }
        catch (Exception ex) { _logger.LogError(ex, "AD Query Error."); }
        return results;
    }

    [SupportedOSPlatform("windows")]
    private string? GetProperty(SearchResult result, string propName) =>
        result.Properties.Contains(propName) ? result.Properties[propName][0].ToString() : null;

    private bool SafeToBoolean(object? value)
    {
        if (value == null || value == DBNull.Value) return false;
        var s = value.ToString()?.Trim().ToLower();
        return s == "1" || s == "true" || s == "yes" || s == "t" || s == "y";
    }

    private string NormalizeId(string? rawId)
    {
        if (string.IsNullOrWhiteSpace(rawId)) return "";
        // Extreme normalization: Strip everything except digits and then trim zeros
        // But for now, just trim leading zeros to keep logic safe
        return rawId.Trim().TrimStart('0');
    }

    private async Task ScrubDatabaseAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("SCRUB: Starting Database deduplication scrub...");
        try 
        {
            using var scope = _serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<AtcoGenie.Server.Data.ImdDbContext>();

            // 1. Scrub UserMappings (Keep one per NormalizedId, Delete others)
            var allMappings = await db.UserMappings.OrderByDescending(m => m.LastSyncedAt).ToListAsync(stoppingToken);
            var seenEmails = new HashSet<string>();
            var mappingsToRemove = new List<AtcoGenie.Server.Data.UserMapping>();

            foreach (var m in allMappings)
            {
                var email = m.Email?.Trim().ToLower() ?? "";
                var normId = NormalizeId(m.HcmsEmployeeId);
                m.HcmsEmployeeId = normId; // Normalize while scrubbing

                if (string.IsNullOrEmpty(email) || !seenEmails.Add(email)) 
                {
                    mappingsToRemove.Add(m); // Delete if duplicate Email or empty
                }
            }
            if(mappingsToRemove.Any()) db.UserMappings.RemoveRange(mappingsToRemove);
            await db.SaveChangesAsync(stoppingToken);

            // 2. Scrub UserFormRights (Keep one per NormalizedId + App + Form)
            var allRights = await db.UserFormRights.OrderByDescending(r => r.LastSyncedAt).ToListAsync(stoppingToken);
            var seenRights = new HashSet<string>();
            var rightsToRemove = new List<AtcoGenie.Server.Data.UserFormRight>();

            foreach (var r in allRights)
            {
                var email = r.Email?.Trim().ToLower() ?? "";
                var norm = NormalizeId(r.HcmsEmployeeId);
                r.HcmsEmployeeId = norm;
                
                // Composite unique key: Email + Application + Form
                var compositeKey = $"{email}|{r.ApplicationCode}|{r.FormId}".ToLower();
                if (string.IsNullOrEmpty(email) || !seenRights.Add(compositeKey)) 
                {
                    rightsToRemove.Add(r);
                }
            }
            if (rightsToRemove.Any()) db.UserFormRights.RemoveRange(rightsToRemove);

            await db.SaveChangesAsync(stoppingToken);
            _logger.LogInformation("SCRUB: Deduplication complete.");
        }
        catch (Exception ex) 
        { 
            try { _logger.LogWarning("SCRUB: Partial failure. Error: {Msg}", ex.Message); }
            catch { /* Logger itself may be disposed during shutdown — swallow safely */ }
            // Continue - the main loop will attempt to fix
        }
    }
}

public class AdUserInfo
{
    public Guid ObjectGuid { get; set; }
    public required string Email { get; set; }
    public string? DisplayName { get; set; }
    public string? SamAccountName { get; set; }
}

public class HcmsEmployee
{
    public required string Email { get; set; }
    public required string EmployeeId { get; set; }
}

public class SecurityFormRight
{
    public int SecurityUserId { get; set; }
    public string? CCode { get; set; }
    public required string ApplicationCode { get; set; }
    public string? FormId { get; set; }
    public bool AddMode { get; set; }
    public bool EditMode { get; set; }
    public bool ViewMode { get; set; }
    public bool DeleteMode { get; set; }
}

public class SecurityRawRight
{
    public required string HcmsEmpId { get; set; }
    public int SecurityUserId { get; set; }
    public string? CCode { get; set; }
    public required string ApplicationCode { get; set; }
    public string? FormId { get; set; }
    public bool AddMode { get; set; }
    public bool EditMode { get; set; }
    public bool ViewMode { get; set; }
    public bool DeleteMode { get; set; }
}
