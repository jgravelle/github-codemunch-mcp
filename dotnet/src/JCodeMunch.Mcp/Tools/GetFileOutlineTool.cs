using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using JCodeMunch.Mcp.Models;
using JCodeMunch.Mcp.Storage;
using ModelContextProtocol.Server;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// MCP tool that returns a hierarchical outline of symbols in a file.
/// Port of Python tools/get_file_outline.py.
/// </summary>
[McpServerToolType]
public static class GetFileOutlineTool
{
    [McpServerTool(Name = "get_file_outline"),
     Description("Get all symbols in a file with signatures and summaries.")]
    public static string GetFileOutline(
        IndexStore store,
        TokenTracker tracker,
        [Description("Repository identifier (owner/repo or just repo name)")]
        string repo,
        [Description("Path to file within the repository")]
        string filePath)
    {
        var sw = Stopwatch.StartNew();

        // Resolve repo
        string owner, name;
        try
        {
            (owner, name) = ToolUtils.ResolveRepo(repo, store);
        }
        catch (ArgumentException ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }

        // Load index
        var index = store.LoadIndex(owner, name);
        if (index is null)
        {
            return JsonSerializer.Serialize(new { error = $"Repository not indexed: {owner}/{name}" });
        }

        // Filter symbols to this file
        var fileSymbols = index.Symbols
            .Where(s => GetString(s, "file") == filePath)
            .ToList();

        if (fileSymbols.Count == 0)
        {
            return JsonSerializer.Serialize(new
            {
                repo = $"{owner}/{name}",
                file = filePath,
                language = "",
                symbols = Array.Empty<object>(),
            });
        }

        // Convert dicts to Symbol records for tree building
        var symbolObjects = fileSymbols.Select(DictToSymbol).ToList();

        // Build hierarchical tree
        var tree = SymbolNode.BuildTree(symbolObjects);

        // Convert tree to output format
        var symbolsOutput = tree.Select(NodeToDict).ToList();

        // Get language from first symbol
        var language = GetString(fileSymbols[0], "language");

        sw.Stop();
        var elapsedMs = Math.Round(sw.Elapsed.TotalMilliseconds, 1);

        // Token savings: raw file size vs outline response size
        var rawBytes = 0;
        try
        {
            var rawFile = Path.Combine(store.ContentDir(owner, name), filePath);
            if (File.Exists(rawFile))
                rawBytes = (int)new FileInfo(rawFile).Length;
        }
        catch
        {
            // Ignore file access errors
        }

        var responseBytes = fileSymbols.Sum(s =>
            s.TryGetValue("byte_length", out var bl) ? bl.GetInt32() : 0);

        var tokensSaved = TokenTracker.EstimateSavings(rawBytes, responseBytes);
        var totalSaved = tracker.RecordSaving(tokensSaved);

        var fileSummary = index.FileSummaries.GetValueOrDefault(filePath, "");

        var costAvoided = TokenTracker.CostAvoided(tokensSaved, totalSaved);

        var result = new Dictionary<string, object>
        {
            ["repo"] = $"{owner}/{name}",
            ["file"] = filePath,
            ["language"] = language,
            ["file_summary"] = fileSummary,
            ["symbols"] = symbolsOutput,
            ["_meta"] = new Dictionary<string, object>
            {
                ["timing_ms"] = elapsedMs,
                ["symbol_count"] = symbolsOutput.Count,
                ["tokens_saved"] = tokensSaved,
                ["total_tokens_saved"] = totalSaved,
                ["cost_avoided"] = costAvoided["cost_avoided"],
                ["total_cost_avoided"] = costAvoided["total_cost_avoided"],
            },
        };

        return JsonSerializer.Serialize(result);
    }

    private static Symbol DictToSymbol(Dictionary<string, JsonElement> d)
    {
        return new Symbol
        {
            Id = GetString(d, "id"),
            File = GetString(d, "file"),
            Name = GetString(d, "name"),
            QualifiedName = GetString(d, "qualified_name"),
            Kind = GetString(d, "kind"),
            Language = GetString(d, "language"),
            Signature = GetString(d, "signature"),
            Docstring = GetString(d, "docstring"),
            Summary = GetString(d, "summary"),
            Decorators = GetStringList(d, "decorators"),
            Keywords = GetStringList(d, "keywords"),
            Parent = d.TryGetValue("parent", out var p) && p.ValueKind == JsonValueKind.String
                ? p.GetString()
                : null,
            Line = d.TryGetValue("line", out var ln) ? ln.GetInt32() : 0,
            EndLine = d.TryGetValue("end_line", out var el) ? el.GetInt32() : 0,
            ByteOffset = d.TryGetValue("byte_offset", out var bo) ? bo.GetInt32() : 0,
            ByteLength = d.TryGetValue("byte_length", out var bl) ? bl.GetInt32() : 0,
            ContentHash = GetString(d, "content_hash"),
        };
    }

    private static Dictionary<string, object> NodeToDict(SymbolNode node)
    {
        var result = new Dictionary<string, object>
        {
            ["id"] = node.Symbol.Id,
            ["kind"] = node.Symbol.Kind,
            ["name"] = node.Symbol.Name,
            ["signature"] = node.Symbol.Signature,
            ["summary"] = node.Symbol.Summary,
            ["line"] = node.Symbol.Line,
        };

        if (node.Children.Count > 0)
        {
            result["children"] = node.Children.Select(NodeToDict).ToList();
        }

        return result;
    }

    private static string GetString(Dictionary<string, JsonElement> d, string key)
    {
        return d.TryGetValue(key, out var elem) && elem.ValueKind == JsonValueKind.String
            ? elem.GetString() ?? ""
            : "";
    }

    private static List<string> GetStringList(Dictionary<string, JsonElement> d, string key)
    {
        if (!d.TryGetValue(key, out var elem) || elem.ValueKind != JsonValueKind.Array)
            return [];

        var result = new List<string>();
        foreach (var item in elem.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String)
                result.Add(item.GetString() ?? "");
        }

        return result;
    }
}
