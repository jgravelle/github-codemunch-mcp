using System.Text.Json;
using JCodeMunch.Mcp.Models;
using Xunit;

namespace JCodeMunch.Mcp.Tests;

public class CodeIndexTests
{
    private static Dictionary<string, JsonElement> MakeSymbolDict(
        string id, string name, string kind, string file,
        string signature = "", string summary = "", string docstring = "",
        List<string>? keywords = null)
    {
        var obj = new
        {
            id,
            name,
            kind,
            file,
            signature,
            summary,
            docstring,
            keywords = keywords ?? [],
            qualified_name = name,
            language = "python",
            decorators = Array.Empty<string>(),
            parent = (string?)null,
            line = 1,
            end_line = 10,
            byte_offset = 0,
            byte_length = 50,
            content_hash = "",
        };
        var json = JsonSerializer.Serialize(obj);
        return JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(json)!;
    }

    private static CodeIndex MakeTestIndex(params Dictionary<string, JsonElement>[] symbols)
    {
        return new CodeIndex
        {
            Repo = "test/repo",
            Owner = "test",
            Name = "repo",
            IndexedAt = "2025-01-01T00:00:00Z",
            SourceFiles = ["src/main.py"],
            Languages = new Dictionary<string, int> { ["python"] = 1 },
            Symbols = [..symbols],
        };
    }

    [Fact]
    public void GetSymbol_FindsById()
    {
        var sym = MakeSymbolDict("src/main.py::login#function", "login", "function", "src/main.py");
        var index = MakeTestIndex(sym);

        var found = index.GetSymbol("src/main.py::login#function");

        Assert.NotNull(found);
        Assert.Equal("login", found["name"].GetString());
    }

    [Fact]
    public void GetSymbol_ReturnsNullForMissingId()
    {
        var sym = MakeSymbolDict("src/main.py::login#function", "login", "function", "src/main.py");
        var index = MakeTestIndex(sym);

        var found = index.GetSymbol("nonexistent::id#function");

        Assert.Null(found);
    }

    [Fact]
    public void Search_ReturnsScoredResults()
    {
        var sym1 = MakeSymbolDict("s1", "login", "function", "src/main.py", signature: "def login():");
        var sym2 = MakeSymbolDict("s2", "logout", "function", "src/main.py", signature: "def logout():");
        var index = MakeTestIndex(sym1, sym2);

        var results = index.Search("login");

        Assert.NotEmpty(results);
        // "login" should be the top result (exact name match)
        Assert.Equal("login", results[0]["name"].GetString());
    }

    [Fact]
    public void Search_WithKindFilter()
    {
        var func = MakeSymbolDict("s1", "login", "function", "src/main.py");
        var cls = MakeSymbolDict("s2", "LoginService", "class", "src/main.py",
            summary: "login service");
        var index = MakeTestIndex(func, cls);

        var results = index.Search("login", kind: "class");

        Assert.All(results, r => Assert.Equal("class", r["kind"].GetString()));
    }

    [Fact]
    public void Search_WithFilePatternFilter()
    {
        var sym1 = MakeSymbolDict("s1", "login", "function", "src/main.py");
        var sym2 = MakeSymbolDict("s2", "login", "function", "tests/test_main.py");
        var index = MakeTestIndex(sym1, sym2);

        var results = index.Search("login", filePattern: "src/*.py");

        Assert.Single(results);
        Assert.Equal("src/main.py", results[0]["file"].GetString());
    }

    [Fact]
    public void Search_ScoreWeighting_ExactNameMatchHigherThanContains()
    {
        // "login" exact match should score higher than "login_handler" (contains)
        var exact = MakeSymbolDict("s1", "login", "function", "src/a.py");
        var contains = MakeSymbolDict("s2", "login_handler", "function", "src/b.py");
        var index = MakeTestIndex(exact, contains);

        var results = index.Search("login");

        Assert.True(results.Count >= 2);
        Assert.Equal("login", results[0]["name"].GetString());
    }

    [Fact]
    public void Search_NoResults_ReturnsEmptyList()
    {
        var sym = MakeSymbolDict("s1", "login", "function", "src/main.py");
        var index = MakeTestIndex(sym);

        var results = index.Search("zzzznonexistent");

        Assert.Empty(results);
    }
}
