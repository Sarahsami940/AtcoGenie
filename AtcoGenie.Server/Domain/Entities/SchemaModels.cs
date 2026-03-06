namespace AtcoGenie.Server.Domain.Entities;

public class DataSourceSchema
{
    public required string Id { get; set; }
    public required string Name { get; set; }
    public required string ConnectionStringName { get; set; }
    public List<EntitySchema> Entities { get; set; } = new();
}

public class EntitySchema
{
    public required string Name { get; set; }
    public required string TvfName { get; set; } // The name of the Security Function
    public string? Description { get; set; }
    public List<ColumnSchema> Columns { get; set; } = new();
}

public class ColumnSchema
{
    public required string Name { get; set; }
    public required string DataType { get; set; }
    public string? Description { get; set; }
    public bool IsPrimary { get; set; }
}
