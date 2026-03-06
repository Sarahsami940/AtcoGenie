using Microsoft.Extensions.DependencyInjection;

namespace AtcoGenie.Server.Application;

public static class DependencyInjection
{
    public static IServiceCollection AddApplicationServices(this IServiceCollection services)
    {
        // Add HttpContextAccessor for session context
        services.AddHttpContextAccessor();
        
        // Register SecureDbContextFactory for session-aware database connections
        services.AddScoped<Infrastructure.Data.Contexts.SecureDbContextFactory>();
        
        // Register OrchestrationService for parallel query execution
        services.AddScoped<Services.OrchestrationService>();
        
        // Register SchemaService for metadata management
        services.AddScoped<Services.ISchemaService, Services.SchemaService>();
        
        // Register MockDataService for testing without real TVFs
        services.AddScoped<Services.IMockDataService, Services.MockDataService>();
        
        // --- Module 4: AI Integration Services ---
        
        // Register HttpClient for Gemini API calls
        services.AddHttpClient<Services.IGeminiService, Services.GeminiService>(client =>
        {
            client.Timeout = TimeSpan.FromMinutes(5); // Prevent timeouts for complex AI reasoning
        });
        
        // Register PromptBuilder for building schema-aware prompts
        services.AddScoped<Services.IPromptBuilder, Services.PromptBuilder>();
        
        // Register SqlValidator for validating AI-generated SQL
        services.AddScoped<Services.ISqlValidator, Services.SqlValidator>();
        
        // Register GenieQueryService as the main entry point (now with AI integration)
        services.AddScoped<Services.IGenieQueryService, Services.GenieQueryService>();
        
        services.AddScoped<Services.IFolderService, Services.FolderService>();
        
        services.AddMediatR(cfg => {
            cfg.RegisterServicesFromAssembly(typeof(DependencyInjection).Assembly);
        });

        return services;
    }
}
