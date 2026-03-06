using JCodeMunch.Mcp.Storage;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// Shared helpers for MCP tool classes.
/// </summary>
internal static class ToolUtils
{
    /// <summary>
    /// Resolve a repo identifier to (Owner, Name).
    /// Accepts "owner/repo" or just "repo" (searches indexed repos).
    /// </summary>
    public static (string Owner, string Name) ResolveRepo(string repo, IndexStore store)
    {
        if (repo.Contains('/'))
        {
            var parts = repo.Split('/', 2);
            return (parts[0], parts[1]);
        }

        var repos = store.ListRepos();
        var matching = repos
            .Where(r => ((string)r["repo"]).EndsWith($"/{repo}"))
            .ToList();

        if (matching.Count == 0)
            throw new ArgumentException($"Repository not found: {repo}");

        var repoStr = (string)matching[0]["repo"];
        var repoParts = repoStr.Split('/', 2);
        return (repoParts[0], repoParts[1]);
    }
}
