using System.Text.Json;
using AtcoGenie.Server.Domain.Entities;

namespace AtcoGenie.Server.Application.Services;

public interface ISchemaService
{
    Task<List<DataSourceSchema>> GetSchemasAsync();
    Task<DataSourceSchema?> GetSchemaByIdAsync(string id);
}

public class SchemaService : ISchemaService
{
    private readonly string _registryPath;
    private List<DataSourceSchema>? _cachedSchemas;

    public SchemaService(IWebHostEnvironment env)
    {
        // For development, we keep it in Infrastructure/Data
        // In production, we'll look in the app root
        _registryPath = Path.Combine(env.ContentRootPath, "Infrastructure", "Data", "SchemaRegistry.json");
    }

    public async Task<List<DataSourceSchema>> GetSchemasAsync()
    {
        if (_cachedSchemas != null) return _cachedSchemas;

        if (!File.Exists(_registryPath))
        {
            return new List<DataSourceSchema>();
        }

        using var stream = File.OpenRead(_registryPath);
        _cachedSchemas = await JsonSerializer.DeserializeAsync<List<DataSourceSchema>>(stream);
        
        return _cachedSchemas ?? new List<DataSourceSchema>();
    }

    public async Task<DataSourceSchema?> GetSchemaByIdAsync(string id)
    {
        var schemas = await GetSchemasAsync();
        return schemas.FirstOrDefault(s => s.Id == id);
    }
}
