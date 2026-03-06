using JCodeMunch.Mcp.Storage;
using Xunit;

namespace JCodeMunch.Mcp.Tests;

public class TokenTrackerTests : IDisposable
{
    private readonly string _tempDir;
    private readonly TokenTracker _tracker;

    public TokenTrackerTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "jcodemunch-token-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
        _tracker = new TokenTracker(_tempDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    [Fact]
    public void EstimateSavings_CalculatesCorrectly()
    {
        // (rawBytes - responseBytes) / 4
        var savings = TokenTracker.EstimateSavings(rawBytes: 1000, responseBytes: 200);
        Assert.Equal(200, savings); // (1000 - 200) / 4 = 200
    }

    [Fact]
    public void EstimateSavings_ReturnsZeroWhenResponseLarger()
    {
        var savings = TokenTracker.EstimateSavings(rawBytes: 100, responseBytes: 500);
        Assert.Equal(0, savings);
    }

    [Fact]
    public void RecordSaving_Accumulates()
    {
        var total1 = _tracker.RecordSaving(100);
        Assert.Equal(100, total1);

        var total2 = _tracker.RecordSaving(250);
        Assert.Equal(350, total2);

        var total3 = _tracker.RecordSaving(50);
        Assert.Equal(400, total3);

        Assert.Equal(400, _tracker.GetTotalSavings());
    }

    [Fact]
    public void RecordSaving_IgnoresNegativeValues()
    {
        _tracker.RecordSaving(100);
        var total = _tracker.RecordSaving(-50);
        Assert.Equal(100, total); // Negative should be treated as 0
    }

    [Fact]
    public void CostAvoided_ReturnsPricingDict()
    {
        var result = TokenTracker.CostAvoided(tokensSaved: 1000, totalTokensSaved: 5000);

        Assert.True(result.ContainsKey("cost_avoided"));
        Assert.True(result.ContainsKey("total_cost_avoided"));

        var costAvoided = result["cost_avoided"];
        Assert.True(costAvoided.ContainsKey("claude_opus"));
        Assert.True(costAvoided.ContainsKey("gpt5_latest"));

        // Verify calculations: 1000 * (15.00 / 1_000_000) = 0.015
        Assert.Equal(0.015, costAvoided["claude_opus"]);
        // 1000 * (10.00 / 1_000_000) = 0.01
        Assert.Equal(0.01, costAvoided["gpt5_latest"]);

        var totalCostAvoided = result["total_cost_avoided"];
        // 5000 * (15.00 / 1_000_000) = 0.075
        Assert.Equal(0.075, totalCostAvoided["claude_opus"]);
        // 5000 * (10.00 / 1_000_000) = 0.05
        Assert.Equal(0.05, totalCostAvoided["gpt5_latest"]);
    }

    [Fact]
    public void GetTotalSavings_ReturnsZeroInitially()
    {
        Assert.Equal(0, _tracker.GetTotalSavings());
    }
}
