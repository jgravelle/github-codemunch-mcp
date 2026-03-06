using System.ComponentModel;
using System.Text.Json;
using JCodeMunch.Mcp.Storage;
using ModelContextProtocol.Server;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// Delete the index and cached files for a repository.
/// Port of Python tools/invalidate_cache.py — invalidate_cache function.
/// </summary>
[McpServerToolType]
public static class InvalidateCacheTool
{
    [McpServerTool(Name = "invalidate_cache"), Description("Delete the index and cached files for a repository.")]
    public static string InvalidateCache(
        IndexStore store,
        [Description("Repository identifier (owner/repo or just repo name)")] string repo)
    {
        string owner, name;

        if (repo.Contains('/'))
        {
            var parts = repo.Split('/', 2);
            owner = parts[0];
            name = parts[1];
        }
        else
        {
            var repos = store.ListRepos();
            var matching = repos
                .Where(r => r.TryGetValue("repo", out var repoVal)
                            && repoVal is string repoStr
                            && repoStr.EndsWith($"/{repo}", StringComparison.Ordinal))
                .ToList();

            if (matching.Count == 0)
            {
                return JsonSerializer.Serialize(new { error = $"Repository not found: {repo}" });
            }

            var repoStr = (string)matching[0]["repo"];
            var repoParts = repoStr.Split('/', 2);
            owner = repoParts[0];
            name = repoParts[1];
        }

        var deleted = store.DeleteIndex(owner, name);

        if (deleted)
        {
            return JsonSerializer.Serialize(new
            {
                success = true,
                repo = $"{owner}/{name}",
                message = $"Index and cached files deleted for {owner}/{name}",
            });
        }

        return JsonSerializer.Serialize(new
        {
            success = false,
            error = $"No index found for {owner}/{name}",
        });
    }
}
