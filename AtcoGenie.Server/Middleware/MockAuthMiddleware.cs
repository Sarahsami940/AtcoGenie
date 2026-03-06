using System.Security.Claims;

namespace AtcoGenie.Server.Middleware;

public class MockAuthMiddleware
{
    private readonly RequestDelegate _next;
    private readonly IConfiguration _config;

    public MockAuthMiddleware(RequestDelegate next, IConfiguration config)
    {
        _next = next;
        _config = config;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        // Only run in Development and if not already authenticated
        if (context.RequestServices.GetService<IHostEnvironment>()!.IsDevelopment() && 
            !context.User.Identity!.IsAuthenticated)
        {
            var mockUser = "ATCO\\Sarah.Sami";
            var claims = new[]
            {
                new Claim(ClaimTypes.Name, mockUser),
                new Claim("Genie:HcmsId", "SS_01"), // Mock Employee ID logic
                new Claim(ClaimTypes.PrimarySid, "S-1-5-21-MOCK-GUID"), // Mock AD Object GUID
                new Claim(ClaimTypes.WindowsAccountName, mockUser)
            };

            var identity = new ClaimsIdentity(claims, "MockWindows");
            context.User = new ClaimsPrincipal(identity);
        }

        await _next(context);
    }
}
