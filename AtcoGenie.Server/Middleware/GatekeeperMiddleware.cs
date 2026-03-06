using System.Security.Claims;
// Note: We will need to inject the DbContext here later. 
// For now, using a stub service or assuming the DbContext is available.

namespace AtcoGenie.Server.Middleware;

public class GatekeeperMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<GatekeeperMiddleware> _logger;

    public GatekeeperMiddleware(RequestDelegate next, ILogger<GatekeeperMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context, AtcoGenie.Server.Data.ImdDbContext dbContext) // Injected from DI
    {
        if (context.User.Identity?.IsAuthenticated == true)
        {
            var adUser = context.User.Identity.Name;

            // Attempt to resolve User from DB
            // Assuming we can get the User's Email or SID/GUID from Claims to be more precise
            // For Negotiate/Kerberos, usually we rely on Name or SID.
            // Let's assume we lookup by Name for now if GUID isn't easily available without casting
            
             // Note: In real Kerberos, Name is DOMAIN\User. 
             // We might need to sync SamAccountName or just search by it.
            
            // Simulation logic / Real Logic
            if (adUser != null)
            {
                var claimsIdentity = context.User.Identity as ClaimsIdentity;
                if (claimsIdentity != null)
                {
                    // Extract SamAccountName (e.g., "ATCO\ali" -> "ali")
                    var username = adUser.Contains("\\") ? adUser.Split('\\').Last() : adUser;
                    
                    // Real DB Lookup
                    var mapping = await Microsoft.EntityFrameworkCore.EntityFrameworkQueryableExtensions.FirstOrDefaultAsync(dbContext.UserMappings, u => u.SamAccountName.ToLower() == username.ToLower());
                    
                    if (mapping != null)
                    {
                        claimsIdentity.AddClaim(new Claim("Genie:HcmsId", mapping.HcmsEmployeeId));
                        claimsIdentity.AddClaim(new Claim("Genie:SamAccountName", mapping.SamAccountName ?? username));
                        claimsIdentity.AddClaim(new Claim("Genie:Email", mapping.Email));
                        _logger.LogInformation("Hydrated identity for {User} -> HCMS:{HcmsId}", adUser, mapping.HcmsEmployeeId);
                    }
                    else
                    {
                        _logger.LogWarning("Identity hydration failed for {User}. No mapping found in IMD.", adUser);
                        claimsIdentity.AddClaim(new Claim("Genie:HcmsId", "NOT_MAPPED"));
                    }
                }
            }
        }

        await _next(context);
    }
}
