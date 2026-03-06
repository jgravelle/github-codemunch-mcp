using System.Text.Json;
using JCodeMunch.Mcp.Storage;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// Shared helpers for tool modules.
/// Port of Python tools/_utils.py.
/// </summary>
internal static class ToolUtils
{
    /// <summary>
    /// Parse "owner/repo" or look up a single repo name.
    /// Returns (Owner, Name).
    /// </summary>
    /// <exception cref="ArgumentException">Thrown when the repository is not found.</exception>
    public static (string Owner, string Name) ResolveRepo(string repo, IndexStore store)
    {
        if (repo.Contains('/'))
        {
            var parts = repo.Split('/', 2);
            return (parts[0], parts[1]);
        }

        var repos = store.ListRepos();
        var matching = repos
            .Where(r => r.TryGetValue("repo", out var repoVal)
                        && repoVal is string repoStr
                        && repoStr.EndsWith($"/{repo}", StringComparison.Ordinal))
            .ToList();

        if (matching.Count == 0)
            throw new ArgumentException($"Repository not found: {repo}");

        var fullRepo = (string)matching[0]["repo"];
        var repoParts = fullRepo.Split('/', 2);
        return (repoParts[0], repoParts[1]);
    }

    /// <summary>Get a string value from a symbol dictionary.</summary>
    public static string GetString(Dictionary<string, JsonElement> sym, string key)
    {
        return sym.TryGetValue(key, out var elem) && elem.ValueKind == JsonValueKind.String
            ? elem.GetString() ?? ""
            : "";
    }

    /// <summary>Get an int value from a symbol dictionary.</summary>
    public static int GetInt(Dictionary<string, JsonElement> sym, string key)
    {
        return sym.TryGetValue(key, out var elem) && elem.ValueKind == JsonValueKind.Number
            ? elem.GetInt32()
            : 0;
    }

    /// <summary>Get a string list value from a symbol dictionary.</summary>
    public static List<string> GetStringList(Dictionary<string, JsonElement> sym, string key)
    {
        if (!sym.TryGetValue(key, out var elem) || elem.ValueKind != JsonValueKind.Array)
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
