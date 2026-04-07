using StackExchange.Redis;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using AtcoGenie.Server.Data;
using Microsoft.AspNetCore.Mvc;

namespace AtcoGenie.Server.Endpoints;

public static class AuthEndpoints
{
    public static void MapAuthEndpoints(this IEndpointRouteBuilder routes)
    {
        routes.MapPost("/api/auth/token", async (
            HttpContext context, 
            ImdDbContext dbContext,
            IConnectionMultiplexer redis,
            IWebHostEnvironment env) =>
        {
            // 1. Verify Windows Auth
            if (context.User.Identity?.IsAuthenticated != true)
            {
                return Results.Unauthorized();
            }

            var adUser = context.User.Identity.Name;
            if (string.IsNullOrEmpty(adUser))
                return Results.Unauthorized();

            // Extract username (DOMAIN\user -> user)
            var username = adUser.Contains('\\') ? adUser.Split('\\').Last() : adUser;

            // 2. Lookup user rights
            var rights = await dbContext.UserFormRights
                .Where(u => u.SamAccountName.ToLower() == username.ToLower())
                .ToListAsync();

            if (!rights.Any() && !env.IsDevelopment())
            {
                return Results.Forbid(); 
            }

            object payload;

            if (rights.Any())
            {
                // Real DB Payload
                var primaryUser = rights.First();
                payload = new
                {
                    ad_user_id = primaryUser.SamAccountName ?? username,
                    employee_id = primaryUser.HcmsEmployeeId,
                    email = primaryUser.Email,
                    display_name = primaryUser.DisplayName,
                    department = "N/A", // Not stored in rights table
                    form_rights = rights.Select(r => new
                    {
                        security_user_id = r.SecurityUserId,
                        ccode = r.CCode,
                        application_code = r.ApplicationCode,
                        form_id = r.FormId,
                        add_mode = r.AddMode,
                        edit_mode = r.EditMode,
                        view_mode = r.ViewMode,
                        delete_mode = r.DeleteMode
                    }).ToList()
                };
            }
            else
            {
                // DEVELOPER MOCK PAYLOAD: Used when local IMD DB is empty
                payload = new
                {
                    ad_user_id = username,
                    employee_id = "DEV-001",
                    email = $"{username}@atcolab.local",
                    display_name = $"{username} (Dev Override)",
                    department = "IT", 
                    form_rights = new[]
                    {
                        // Mock Phase 1 Report Access
                        new { security_user_id = 1, ccode = "01", application_code = "PharmaCRM", form_id = "Report1_Placeholder", add_mode=false, edit_mode=false, view_mode=true, delete_mode=false },
                        new { security_user_id = 1, ccode = "01", application_code = "PharmaCRM", form_id = "Report2_Placeholder", add_mode=false, edit_mode=false, view_mode=true, delete_mode=false },
                        new { security_user_id = 1, ccode = "01", application_code = "PharmaCRM", form_id = "Report3_Placeholder", add_mode=false, edit_mode=false, view_mode=true, delete_mode=false }
                    }
                };
            }

            // 4. Generate Session Token and Save to Redis
            var sessionId = Guid.NewGuid().ToString("N");
            var key = $"atcogenie:session:{sessionId}";
            var db = redis.GetDatabase();

            await db.StringSetAsync(key, JsonSerializer.Serialize(payload), TimeSpan.FromMinutes(60));

            // Also store a reverse mapping: username -> sessionId
            // GenieQueryService uses this to forward requests to the Python AI Engine
            var userKey = $"atcogenie:user-token:{username.ToLower()}";
            await db.StringSetAsync(userKey, sessionId, TimeSpan.FromMinutes(60));


            return Results.Ok(new
            {
                access_token = sessionId,
                token_type = "Bearer",
                expires_in = 3600,
                user = new { 
                    display_name = rights.Any() ? rights.First().DisplayName : $"{username} (Dev Override)", 
                    email = rights.Any() ? rights.First().Email : $"{username}@atcolab.local",
                    employee_id = rights.Any() ? rights.First().HcmsEmployeeId : "DEV-001"
                }
            });
        });
    }
}
