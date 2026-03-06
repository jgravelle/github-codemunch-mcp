using System.ComponentModel;
using System.Diagnostics;
using System.Text.Json;
using JCodeMunch.Mcp.Storage;
using ModelContextProtocol.Server;
using static JCodeMunch.Mcp.Tools.ToolUtils;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// Get the full source code of multiple symbols in one call.
/// Port of Python tools/get_symbol.py — get_symbols function.
/// </summary>
[McpServerToolType]
public static class GetSymbolsTool
{
    [McpServerTool(Name = "get_symbols"), Description("Get the full source code of multiple symbols by their IDs.")]
    public static string GetSymbols(
        IndexStore store,
        TokenTracker tracker,
        [Description("Repository identifier (owner/repo or just repo name)")] string repo,
        [Description("List of symbol IDs")] string[] symbolIds)
    {
        var sw = Stopwatch.StartNew();

        string owner, name;
        try
        {
            (owner, name) = ResolveRepo(repo, store);
        }
        catch (ArgumentException ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }

        var index = store.LoadIndex(owner, name);
        if (index is null)
            return JsonSerializer.Serialize(new { error = $"Repository not indexed: {owner}/{name}" });

        var symbols = new List<Dictionary<string, object>>();
        var errors = new List<Dictionary<string, string>>();

        // Cache symbol lookups to avoid redundant second pass
        var resolvedSymbols = new Dictionary<string, Dictionary<string, JsonElement>>();

        foreach (var symbolId in symbolIds)
        {
            var symbol = index.GetSymbol(symbolId);
            if (symbol is null)
            {
                errors.Add(new Dictionary<string, string>
                {
                    ["id"] = symbolId,
                    ["error"] = $"Symbol not found: {symbolId}",
                });
                continue;
            }

            resolvedSymbols[symbolId] = symbol;
            var source = store.GetSymbolContent(owner, name, symbolId);

            symbols.Add(new Dictionary<string, object>
            {
                ["id"] = GetString(symbol, "id"),
                ["kind"] = GetString(symbol, "kind"),
                ["name"] = GetString(symbol, "name"),
                ["file"] = GetString(symbol, "file"),
                ["line"] = GetInt(symbol, "line"),
                ["end_line"] = GetInt(symbol, "end_line"),
                ["signature"] = GetString(symbol, "signature"),
                ["decorators"] = GetStringList(symbol, "decorators"),
                ["docstring"] = GetString(symbol, "docstring"),
                ["content_hash"] = GetString(symbol, "content_hash"),
                ["source"] = source ?? "",
            });
        }

        // Token savings: unique file sizes vs sum of symbol byte_lengths
        var rawBytes = 0;
        var seenFiles = new HashSet<string>();
        var responseBytes = 0;
        var contentDir = store.GetContentDir(owner, name);

        foreach (var symbolId in symbolIds)
        {
            if (!resolvedSymbols.TryGetValue(symbolId, out var symbol))
                continue;

            var file = GetString(symbol, "file");
            if (seenFiles.Add(file))
            {
                try
                {
                    var filePath = Path.Combine(contentDir, file);
                    if (File.Exists(filePath))
                        rawBytes += (int)new FileInfo(filePath).Length;
                }
                catch
                {
                    // Ignore
                }
            }

            responseBytes += GetInt(symbol, "byte_length");
        }

        var tokensSaved = TokenTracker.EstimateSavings(rawBytes, responseBytes);
        var totalSaved = tracker.RecordSaving(tokensSaved);

        sw.Stop();

        var meta = new Dictionary<string, object>
        {
            ["timing_ms"] = Math.Round(sw.Elapsed.TotalMilliseconds, 1),
            ["symbol_count"] = symbols.Count,
            ["tokens_saved"] = tokensSaved,
            ["total_tokens_saved"] = totalSaved,
        };

        var costAvoided = TokenTracker.CostAvoided(tokensSaved, totalSaved);
        foreach (var (k, v) in costAvoided)
            meta[k] = v;

        var result = new Dictionary<string, object>
        {
            ["symbols"] = symbols,
            ["errors"] = errors,
            ["_meta"] = meta,
        };

        return JsonSerializer.Serialize(result);
    }
}
