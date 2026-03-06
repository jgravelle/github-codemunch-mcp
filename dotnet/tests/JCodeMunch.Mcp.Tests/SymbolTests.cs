using System.Text;
using JCodeMunch.Mcp.Models;
using Xunit;

namespace JCodeMunch.Mcp.Tests;

public class SymbolTests
{
    [Fact]
    public void MakeSymbolId_WithKind_ReturnsCorrectFormat()
    {
        var id = Symbol.MakeSymbolId("src/main.py", "MyClass.login", "method");
        Assert.Equal("src/main.py::MyClass.login#method", id);
    }

    [Fact]
    public void MakeSymbolId_WithoutKind_ReturnsFormatWithoutHash()
    {
        var id = Symbol.MakeSymbolId("src/main.py", "MyClass.login");
        Assert.Equal("src/main.py::MyClass.login", id);
    }

    [Fact]
    public void MakeSymbolId_WithEmptyKind_ReturnsFormatWithoutHash()
    {
        var id = Symbol.MakeSymbolId("src/main.py", "MyClass.login", "");
        Assert.Equal("src/main.py::MyClass.login", id);
    }

    [Fact]
    public void ComputeContentHash_ReturnsConsistentHexHash()
    {
        var source = Encoding.UTF8.GetBytes("def login(): pass");
        var hash1 = Symbol.ComputeContentHash(source);
        var hash2 = Symbol.ComputeContentHash(source);

        Assert.Equal(hash1, hash2);
        Assert.Equal(64, hash1.Length); // SHA-256 hex is 64 chars
        Assert.Matches("^[0-9a-f]{64}$", hash1);
    }

    [Fact]
    public void ComputeContentHash_DifferentInput_DifferentHash()
    {
        var hash1 = Symbol.ComputeContentHash(Encoding.UTF8.GetBytes("def login(): pass"));
        var hash2 = Symbol.ComputeContentHash(Encoding.UTF8.GetBytes("def logout(): pass"));

        Assert.NotEqual(hash1, hash2);
    }

    [Fact]
    public void Symbol_RecordEquality_SameValuePropertiesShareIdentity()
    {
        // Record equality for Symbol includes List<string> fields which use
        // reference equality. Verify that the same instance compared to itself is equal.
        var sym = new Symbol
        {
            Id = "src/main.py::login#function",
            File = "src/main.py",
            Name = "login",
            QualifiedName = "login",
            Kind = "function",
            Language = "python",
            Signature = "def login():",
        };

        // Same reference is always equal
        Assert.Equal(sym, sym);

        // A 'with' expression that changes nothing shares the same List references
        var sym2 = sym with { };
        Assert.Equal(sym, sym2);
    }

    [Fact]
    public void Symbol_RecordEquality_DifferentIdMeansDifferent()
    {
        var decorators = new List<string>();
        var keywords = new List<string>();

        var sym1 = new Symbol
        {
            Id = "src/main.py::login#function",
            File = "src/main.py",
            Name = "login",
            QualifiedName = "login",
            Kind = "function",
            Language = "python",
            Signature = "def login():",
            Decorators = decorators,
            Keywords = keywords,
        };

        var sym2 = new Symbol
        {
            Id = "src/main.py::logout#function",
            File = "src/main.py",
            Name = "logout",
            QualifiedName = "logout",
            Kind = "function",
            Language = "python",
            Signature = "def logout():",
            Decorators = decorators,
            Keywords = keywords,
        };

        Assert.NotEqual(sym1, sym2);
    }
}
