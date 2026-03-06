using AtcoGenie.Server.Application.DTOs;

namespace AtcoGenie.Server.Application.Services;

/// <summary>
/// Mock data service - simulates querying data sources before real TVFs are available
/// </summary>
public interface IMockDataService
{
    Task<List<Dictionary<string, object>>> GetMockDataAsync(string dataSource, string entityName, string userHcmsId);
}

public class MockDataService : IMockDataService
{
    public Task<List<Dictionary<string, object>>> GetMockDataAsync(string dataSource, string entityName, string userHcmsId)
    {
        // Simulate different data for different users
        var mockData = dataSource switch
        {
            "hcms-core" => GetMockAttendanceData(userHcmsId),
            "pharma-pulse" => GetMockSalesData(userHcmsId),
            _ => new List<Dictionary<string, object>>()
        };

        return Task.FromResult(mockData);
    }

    private List<Dictionary<string, object>> GetMockAttendanceData(string userHcmsId)
    {
        // Simulate attendance data filtered by user
        return new List<Dictionary<string, object>>
        {
            new() { ["EmployeeId"] = userHcmsId, ["LogTime"] = DateTime.Today.AddHours(9), ["Direction"] = "In" },
            new() { ["EmployeeId"] = userHcmsId, ["LogTime"] = DateTime.Today.AddHours(13), ["Direction"] = "Out" },
            new() { ["EmployeeId"] = userHcmsId, ["LogTime"] = DateTime.Today.AddHours(14), ["Direction"] = "In" },
            new() { ["EmployeeId"] = userHcmsId, ["LogTime"] = DateTime.Today.AddHours(18), ["Direction"] = "Out" }
        };
    }

    private List<Dictionary<string, object>> GetMockSalesData(string userHcmsId)
    {
        // Simulate sales data - different users see different regions
        var region = userHcmsId == "0009" ? "North" : "South";
        
        return new List<Dictionary<string, object>>
        {
            new() { ["SaleId"] = 101, ["Amount"] = 15000.00m, ["Region"] = region, ["SaleDate"] = DateTime.Today.AddDays(-1) },
            new() { ["SaleId"] = 102, ["Amount"] = 22500.50m, ["Region"] = region, ["SaleDate"] = DateTime.Today.AddDays(-2) },
            new() { ["SaleId"] = 103, ["Amount"] = 8750.25m, ["Region"] = region, ["SaleDate"] = DateTime.Today }
        };
    }
}
