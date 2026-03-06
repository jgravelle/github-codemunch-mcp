using System.ComponentModel;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using JCodeMunch.Mcp.Models;
using JCodeMunch.Mcp.Parser;
using JCodeMunch.Mcp.Security;
using JCodeMunch.Mcp.Storage;
using JCodeMunch.Mcp.Summarizer;
using ModelContextProtocol.Server;

namespace JCodeMunch.Mcp.Tools;

/// <summary>
/// MCP tool to index a GitHub repository's source code.
/// Port of Python tools/index_repo.py.
/// </summary>
[McpServerToolType]
public static class IndexRepoTool
{
    private static readonly string[] SkipPatterns =
    [
        "node_modules/", "vendor/", "venv/", ".venv/", "__pycache__/",
        "dist/", "build/", ".git/", ".tox/", ".mypy_cache/",
        "target/", ".gradle/",
        "test_data/", "testdata/", "fixtures/", "snapshots/",
        "migrations/",
        ".min.js", ".min.ts", ".bundle.js",
        "package-lock.json", "yarn.lock", "go.sum",
        "generated/", "proto/",
    ];

    private static readonly string[] PriorityDirs =
        ["src/", "lib/", "pkg/", "cmd/", "internal/"];

    private const int MaxFileSize = 500 * 1024; // 500KB
    private const int ConcurrencyLimit = 10;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    [McpServerTool(Name = "index_repo")]
    [Description("Index a GitHub repository's source code for fast symbol lookup.")]
    public static async Task<string> IndexRepo(
        IndexStore store,
        SymbolExtractor extractor,
        BatchSummarizer summarizer,
        [Description("GitHub repository URL or owner/repo string")] string url,
        [Description("Use AI for symbol summaries")] bool useAiSummaries = true,
        [Description("Only re-index changed files")] bool incremental = true)
    {
        // Parse URL
        string owner, repo;
        try
        {
            (owner, repo) = ParseGitHubUrl(url);
        }
        catch (ArgumentException e)
        {
            return Serialize(new { success = false, error = e.Message });
        }

        var token = Environment.GetEnvironmentVariable("GITHUB_TOKEN");
        var warnings = new List<string>();
        var maxFiles = SecurityValidator.GetMaxIndexFiles();

        try
        {
            using var httpClient = CreateGitHubClient(token);

            // Fetch tree
            List<TreeEntry> treeEntries;
            try
            {
                treeEntries = await FetchRepoTree(httpClient, owner, repo);
            }
            catch (HttpRequestException e)
            {
                if (e.StatusCode == System.Net.HttpStatusCode.NotFound)
                    return Serialize(new { success = false, error = $"Repository not found: {owner}/{repo}" });
                if (e.StatusCode == System.Net.HttpStatusCode.Forbidden)
                    return Serialize(new { success = false, error = "GitHub API rate limit exceeded. Set GITHUB_TOKEN." });
                throw;
            }

            // Fetch .gitignore
            var gitignoreContent = await FetchGitignore(httpClient, owner, repo);

            // Discover source files
            var (sourceFiles, truncated) = DiscoverSourceFiles(treeEntries, gitignoreContent, maxFiles);

            if (sourceFiles.Count == 0)
                return Serialize(new { success = false, error = "No source files found" });

            // Fetch all file contents concurrently
            var currentFiles = await FetchAllFiles(httpClient, owner, repo, sourceFiles);

            // Incremental path
            if (incremental && store.LoadIndex(owner, repo) is not null)
            {
                var (changed, newF, deleted) = store.DetectChanges(owner, repo, currentFiles);

                if (changed.Count == 0 && newF.Count == 0 && deleted.Count == 0)
                {
                    return Serialize(new
                    {
                        success = true,
                        message = "No changes detected",
                        repo = $"{owner}/{repo}",
                        changed = 0,
                        @new = 0,
                        deleted = 0,
                    });
                }

                var filesToParse = new HashSet<string>(changed);
                filesToParse.UnionWith(newF);

                var newSymbols = new List<Symbol>();
                var rawFilesSubset = new Dictionary<string, string>();

                foreach (var path in filesToParse)
                {
                    var content = currentFiles[path];
                    rawFilesSubset[path] = content;

                    var language = LanguageRegistry.GetLanguageForFile(path);
                    if (language is null)
                        continue;

                    try
                    {
                        var symbols = extractor.ExtractSymbols(content, path, language);
                        if (symbols.Count > 0)
                            newSymbols.AddRange(symbols);
                    }
                    catch
                    {
                        warnings.Add($"Failed to parse {path}");
                    }
                }

                newSymbols = summarizer.SummarizeSymbols(newSymbols, useAiSummaries);

                var incrFileSummaries = FileSummarizer.GenerateFileSummaries(
                    GroupSymbolsByFile(newSymbols));

                var updated = store.IncrementalSave(
                    owner: owner,
                    name: repo,
                    changedFiles: changed,
                    newFiles: newF,
                    deletedFiles: deleted,
                    newSymbols: newSymbols,
                    rawFiles: rawFilesSubset,
                    languages: new Dictionary<string, int>(),
                    fileSummaries: incrFileSummaries);

                var incrResult = new Dictionary<string, object>
                {
                    ["success"] = true,
                    ["repo"] = $"{owner}/{repo}",
                    ["incremental"] = true,
                    ["changed"] = changed.Count,
                    ["new"] = newF.Count,
                    ["deleted"] = deleted.Count,
                    ["symbol_count"] = updated?.Symbols.Count ?? 0,
                    ["indexed_at"] = updated?.IndexedAt ?? "",
                };
                if (warnings.Count > 0)
                    incrResult["warnings"] = warnings;

                return Serialize(incrResult);
            }

            // Full index path
            var allSymbols = new List<Symbol>();
            var languages = new Dictionary<string, int>();
            var rawFiles = new Dictionary<string, string>();
            var parsedFiles = new List<string>();

            foreach (var (path, content) in currentFiles)
            {
                var language = LanguageRegistry.GetLanguageForFile(path);
                if (language is null)
                    continue;

                try
                {
                    var symbols = extractor.ExtractSymbols(content, path, language);
                    if (symbols.Count > 0)
                    {
                        allSymbols.AddRange(symbols);
                        var fileLang = symbols[0].Language ?? language;
                        languages[fileLang] = languages.GetValueOrDefault(fileLang) + 1;
                        rawFiles[path] = content;
                        parsedFiles.Add(path);
                    }
                }
                catch
                {
                    warnings.Add($"Failed to parse {path}");
                }
            }

            if (allSymbols.Count == 0)
                return Serialize(new { success = false, error = "No symbols extracted" });

            // Generate summaries
            allSymbols = summarizer.SummarizeSymbols(allSymbols, useAiSummaries);

            // Generate file-level summaries
            var fileSummaries = FileSummarizer.GenerateFileSummaries(
                GroupSymbolsByFile(allSymbols));

            // Compute file hashes for all discovered source files so incremental
            // change detection does not repeatedly report no-symbol files as "new".
            var fileHashes = currentFiles.ToDictionary(
                kv => kv.Key,
                kv => ComputeHash(kv.Value));

            var savedIndex = store.SaveIndex(
                owner: owner,
                name: repo,
                sourceFiles: parsedFiles,
                symbols: allSymbols,
                rawFiles: rawFiles,
                languages: languages,
                fileHashes: fileHashes,
                fileSummaries: fileSummaries);

            var result = new Dictionary<string, object>
            {
                ["success"] = true,
                ["repo"] = $"{owner}/{repo}",
                ["indexed_at"] = savedIndex.IndexedAt,
                ["file_count"] = parsedFiles.Count,
                ["symbol_count"] = allSymbols.Count,
                ["file_summary_count"] = fileSummaries.Count(kv => !string.IsNullOrEmpty(kv.Value)),
                ["languages"] = languages,
                ["files"] = parsedFiles.Take(20).ToList(),
            };

            if (warnings.Count > 0)
                result["warnings"] = warnings;

            if (truncated)
                result["warnings"] = warnings.Concat([$"Repository has many files; indexed first {maxFiles}"]).ToList();

            return Serialize(result);
        }
        catch (Exception e)
        {
            return Serialize(new { success = false, error = $"Indexing failed: {e.Message}" });
        }
    }

    // --- Private helpers ---

    private static (string Owner, string Repo) ParseGitHubUrl(string url)
    {
        // Remove .git suffix
        if (url.EndsWith(".git", StringComparison.OrdinalIgnoreCase))
            url = url[..^4];

        // If it contains / but not ://, treat as owner/repo
        if (url.Contains('/') && !url.Contains("://"))
        {
            var parts = url.Split('/');
            if (parts.Length >= 2)
                return (parts[0], parts[1]);
        }

        // Parse URL
        if (Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            var path = uri.AbsolutePath.Trim('/');
            var parts = path.Split('/');
            if (parts.Length >= 2)
                return (parts[0], parts[1]);
        }

        throw new ArgumentException($"Could not parse GitHub URL: {url}");
    }

    private static HttpClient CreateGitHubClient(string? token)
    {
        var client = new HttpClient();
        client.DefaultRequestHeaders.Add("User-Agent", "JCodeMunch-MCP");
        if (!string.IsNullOrEmpty(token))
            client.DefaultRequestHeaders.Add("Authorization", $"token {token}");
        return client;
    }

    private static async Task<List<TreeEntry>> FetchRepoTree(
        HttpClient client, string owner, string repo)
    {
        var apiUrl = $"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1";
        using var request = new HttpRequestMessage(HttpMethod.Get, apiUrl);
        request.Headers.Add("Accept", "application/vnd.github.v3+json");

        using var response = await client.SendAsync(request);
        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var tree = doc.RootElement.GetProperty("tree");

        var entries = new List<TreeEntry>();
        foreach (var item in tree.EnumerateArray())
        {
            entries.Add(new TreeEntry
            {
                Path = item.GetProperty("path").GetString() ?? "",
                Type = item.GetProperty("type").GetString() ?? "",
                Size = item.TryGetProperty("size", out var sizeElem) ? sizeElem.GetInt64() : 0,
            });
        }

        return entries;
    }

    private static async Task<string?> FetchGitignore(
        HttpClient client, string owner, string repo)
    {
        try
        {
            return await FetchFileContent(client, owner, repo, ".gitignore");
        }
        catch
        {
            return null;
        }
    }

    private static async Task<string> FetchFileContent(
        HttpClient client, string owner, string repo, string path)
    {
        var apiUrl = $"https://api.github.com/repos/{owner}/{repo}/contents/{path}";
        using var request = new HttpRequestMessage(HttpMethod.Get, apiUrl);
        request.Headers.Add("Accept", "application/vnd.github.v3.raw");

        using var response = await client.SendAsync(request);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync();
    }

    private static bool ShouldSkipFile(string path)
    {
        var normalized = path.Replace('\\', '/');
        foreach (var pattern in SkipPatterns)
        {
            if (pattern.EndsWith('/'))
            {
                // Directory pattern: match only complete path segments
                if (normalized.StartsWith(pattern, StringComparison.Ordinal)
                    || normalized.Contains("/" + pattern, StringComparison.Ordinal))
                    return true;
            }
            else
            {
                if (normalized.Contains(pattern, StringComparison.Ordinal))
                    return true;
            }
        }

        return false;
    }

    private static (List<string> Files, bool Truncated) DiscoverSourceFiles(
        List<TreeEntry> treeEntries,
        string? gitignoreContent,
        int? maxFiles = null)
    {
        var resolvedMax = SecurityValidator.GetMaxIndexFiles(maxFiles);
        var gitignorePatterns = ParseGitignorePatterns(gitignoreContent);
        var files = new List<string>();

        foreach (var entry in treeEntries)
        {
            if (entry.Type != "blob")
                continue;

            var path = entry.Path;
            var ext = Path.GetExtension(path);

            if (!LanguageRegistry.LanguageExtensions.ContainsKey(ext))
                continue;
            if (ShouldSkipFile(path))
                continue;
            if (SecurityValidator.IsSecretFile(path))
                continue;
            if (SecurityValidator.IsBinaryExtension(path))
                continue;
            if (entry.Size > MaxFileSize)
                continue;
            if (MatchesGitignore(path, gitignorePatterns))
                continue;

            files.Add(path);
        }

        var truncated = files.Count > resolvedMax;

        if (truncated)
        {
            files.Sort((a, b) => PriorityKey(a).CompareTo(PriorityKey(b)));
            files = files.Take(resolvedMax).ToList();
        }

        return (files, truncated);
    }

    private static (int Priority, int Depth, string Path) PriorityKey(string path)
    {
        for (var i = 0; i < PriorityDirs.Length; i++)
        {
            if (path.StartsWith(PriorityDirs[i], StringComparison.Ordinal))
                return (i, path.Count(c => c == '/'), path);
        }

        return (PriorityDirs.Length, path.Count(c => c == '/'), path);
    }

    private static async Task<Dictionary<string, string>> FetchAllFiles(
        HttpClient client, string owner, string repo, List<string> paths)
    {
        var semaphore = new SemaphoreSlim(ConcurrencyLimit);
        var results = new Dictionary<string, string>();
        var lockObj = new object();

        var tasks = paths.Select(async path =>
        {
            await semaphore.WaitAsync();
            try
            {
                var content = await FetchFileContent(client, owner, repo, path);
                lock (lockObj)
                {
                    if (!string.IsNullOrEmpty(content))
                        results[path] = content;
                }
            }
            catch
            {
                // Skip files that fail to fetch
            }
            finally
            {
                semaphore.Release();
            }
        });

        await Task.WhenAll(tasks);
        return results;
    }

    private static Dictionary<string, List<Symbol>> GroupSymbolsByFile(List<Symbol> symbols)
    {
        var map = new Dictionary<string, List<Symbol>>();
        foreach (var s in symbols)
        {
            if (!map.TryGetValue(s.File, out var list))
            {
                list = [];
                map[s.File] = list;
            }
            list.Add(s);
        }
        return map;
    }

    private static List<string> ParseGitignorePatterns(string? content)
    {
        if (string.IsNullOrEmpty(content))
            return [];

        return content.Split('\n')
            .Select(line => line.Trim())
            .Where(line => !string.IsNullOrEmpty(line) && !line.StartsWith('#'))
            .ToList();
    }

    private static bool MatchesGitignore(string path, List<string> patterns)
    {
        foreach (var pattern in patterns)
        {
            var p = pattern.TrimEnd('/');
            if (p.StartsWith('/'))
            {
                if (path.StartsWith(p[1..], StringComparison.Ordinal))
                    return true;
            }
            else if (p.Contains('/'))
            {
                if (path.Contains(p, StringComparison.Ordinal))
                    return true;
            }
            else
            {
                var fileName = Path.GetFileName(path);
                if (SimpleWildcardMatch(p, fileName) || SimpleWildcardMatch(p, path))
                    return true;
            }
        }

        return false;
    }

    private static bool SimpleWildcardMatch(string pattern, string text)
    {
        if (!pattern.Contains('*'))
            return string.Equals(pattern, text, StringComparison.Ordinal);

        var parts = pattern.Split('*');
        var idx = 0;
        foreach (var part in parts)
        {
            if (string.IsNullOrEmpty(part))
                continue;
            var found = text.IndexOf(part, idx, StringComparison.Ordinal);
            if (found < 0)
                return false;
            idx = found + part.Length;
        }

        return true;
    }

    private static string ComputeHash(string content)
    {
        var bytes = Encoding.UTF8.GetBytes(content);
        var hash = SHA256.HashData(bytes);
        return Convert.ToHexStringLower(hash);
    }

    private static string Serialize(object value)
    {
        return JsonSerializer.Serialize(value, JsonOptions);
    }

    private sealed record TreeEntry
    {
        public required string Path { get; init; }
        public required string Type { get; init; }
        public long Size { get; init; }
    }
}
