using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using JCodeMunch.Mcp.Parser;
using JCodeMunch.Mcp.Storage;
using ModelContextProtocol.Server;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// MCP tool: get_file_tree
/// Returns a hierarchical file tree for an indexed repository.
/// Port of Python tools/get_file_tree.py.
/// </summary>
[McpServerToolType]
public static class GetFileTreeTool
{
    [McpServerTool(Name = "get_file_tree"), Description("Get the file tree of an indexed repository.")]
    public static string GetFileTree(
        IndexStore store,
        TokenTracker tracker,
        [Description("Repository identifier (owner/repo or repo name)")] string repo,
        [Description("Path prefix filter")] string pathPrefix = "",
        [Description("Include file-level summaries")] bool includeSummaries = false)
    {
        var sw = Stopwatch.StartNew();

        string owner, name;
        try
        {
            (owner, name) = ToolUtils.ResolveRepo(repo, store);
        }
        catch (ArgumentException ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }

        var index = store.LoadIndex(owner, name);
        if (index is null)
            return JsonSerializer.Serialize(new { error = $"Repository not indexed: {owner}/{name}" });

        // Filter files by prefix
        var files = index.SourceFiles
            .Where(f => f.StartsWith(pathPrefix, StringComparison.Ordinal))
            .ToList();

        if (files.Count == 0)
        {
            return JsonSerializer.Serialize(new
            {
                repo = $"{owner}/{name}",
                path_prefix = pathPrefix,
                tree = Array.Empty<object>(),
            });
        }

        // Build tree
        var tree = BuildTree(files, index, pathPrefix, includeSummaries);

        var elapsedMs = sw.Elapsed.TotalMilliseconds;

        // Token savings: sum of raw file sizes vs compact tree response
        var contentDir = store.GetContentDir(owner, name);

        var rawBytes = 0L;
        foreach (var f in files)
        {
            try
            {
                var filePath = Path.Combine(contentDir, f);
                var fullPath = Path.GetFullPath(filePath);
                if (fullPath.StartsWith(Path.GetFullPath(contentDir), StringComparison.Ordinal)
                    && File.Exists(fullPath))
                {
                    rawBytes += new FileInfo(fullPath).Length;
                }
            }
            catch
            {
                // Skip inaccessible files
            }
        }

        var responseJson = JsonSerializer.Serialize(tree);
        var responseBytes = Encoding.UTF8.GetByteCount(responseJson);
        var tokensSaved = TokenTracker.EstimateSavings((int)Math.Min(rawBytes, int.MaxValue), responseBytes);
        var totalSaved = tracker.RecordSaving(tokensSaved);

        var result = new Dictionary<string, object>
        {
            ["repo"] = $"{owner}/{name}",
            ["path_prefix"] = pathPrefix,
            ["tree"] = tree,
            ["_meta"] = BuildMeta(elapsedMs, files.Count, tokensSaved, totalSaved),
        };

        return JsonSerializer.Serialize(result);
    }

    private static List<object> BuildTree(
        List<string> files,
        Models.CodeIndex index,
        string pathPrefix,
        bool includeSummaries)
    {
        // Build language lookup and symbol counts from symbols in a single pass
        var fileLanguages = new Dictionary<string, string>();
        var symbolCounts = new Dictionary<string, int>();
        foreach (var sym in index.Symbols)
        {
            var file = sym.TryGetValue("file", out var fElem) ? fElem.GetString() : null;
            if (file is null) continue;

            symbolCounts[file] = symbolCounts.GetValueOrDefault(file) + 1;

            var lang = sym.TryGetValue("language", out var lElem) ? lElem.GetString() : null;
            if (lang is not null)
                fileLanguages.TryAdd(file, lang);
        }

        // Build nested dict tree
        var root = new Dictionary<string, object>();

        foreach (var filePath in files)
        {
            var relPath = filePath[pathPrefix.Length..].TrimStart('/');
            var parts = relPath.Split('/');
            var current = root;

            for (var i = 0; i < parts.Length; i++)
            {
                var part = parts[i];
                var isLast = i == parts.Length - 1;

                if (isLast)
                {
                    // File node
                    var language = fileLanguages.GetValueOrDefault(filePath, "");
                    if (string.IsNullOrEmpty(language))
                        language = LanguageRegistry.GetLanguageForFile(filePath) ?? "";

                    var node = new Dictionary<string, object>
                    {
                        ["path"] = filePath,
                        ["type"] = "file",
                        ["language"] = language,
                        ["symbol_count"] = symbolCounts.GetValueOrDefault(filePath),
                    };

                    if (includeSummaries)
                        node["summary"] = index.FileSummaries.GetValueOrDefault(filePath, "");

                    current[part] = node;
                }
                else
                {
                    // Directory node - navigate or create
                    if (!current.TryGetValue(part, out var existing))
                    {
                        var dirNode = new Dictionary<string, object>
                        {
                            ["type"] = "dir",
                            ["children"] = new Dictionary<string, object>(),
                        };
                        current[part] = dirNode;
                        current = (Dictionary<string, object>)dirNode["children"];
                    }
                    else
                    {
                        var dirNode = (Dictionary<string, object>)existing;
                        current = (Dictionary<string, object>)dirNode["children"];
                    }
                }
            }
        }

        return DictToList(root);
    }

    private static List<object> DictToList(Dictionary<string, object> nodeDict)
    {
        var result = new List<object>();

        foreach (var (nodeName, node) in nodeDict.OrderBy(kv => kv.Key, StringComparer.Ordinal))
        {
            var dict = (Dictionary<string, object>)node;

            if (dict.TryGetValue("type", out var type) && (string)type == "file")
            {
                result.Add(dict);
            }
            else
            {
                var children = dict.TryGetValue("children", out var c)
                    ? (Dictionary<string, object>)c
                    : new Dictionary<string, object>();

                result.Add(new Dictionary<string, object>
                {
                    ["path"] = nodeName + "/",
                    ["type"] = "dir",
                    ["children"] = DictToList(children),
                });
            }
        }

        return result;
    }

    private static Dictionary<string, object> BuildMeta(
        double elapsedMs, int fileCount, int tokensSaved, int totalSaved)
    {
        var meta = new Dictionary<string, object>
        {
            ["timing_ms"] = Math.Round(elapsedMs, 1),
            ["file_count"] = fileCount,
            ["tokens_saved"] = tokensSaved,
            ["total_tokens_saved"] = totalSaved,
        };

        var costAvoided = TokenTracker.CostAvoided(tokensSaved, totalSaved);
        foreach (var (key, value) in costAvoided)
            meta[key] = value;

        return meta;
    }
}
