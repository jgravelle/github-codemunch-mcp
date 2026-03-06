using JCodeMunch.Mcp.Parser;
using Xunit;

namespace JCodeMunch.Mcp.Tests;

public class LanguageRegistryTests
{
    [Theory]
    [InlineData(".py", "python")]
    [InlineData(".js", "javascript")]
    [InlineData(".jsx", "javascript")]
    [InlineData(".ts", "typescript")]
    [InlineData(".tsx", "typescript")]
    [InlineData(".go", "go")]
    [InlineData(".rs", "rust")]
    [InlineData(".java", "java")]
    [InlineData(".cs", "csharp")]
    [InlineData(".c", "c")]
    [InlineData(".cpp", "cpp")]
    [InlineData(".swift", "swift")]
    [InlineData(".rb", "ruby")]
    [InlineData(".ex", "elixir")]
    [InlineData(".pl", "perl")]
    [InlineData(".php", "php")]
    [InlineData(".dart", "dart")]
    public void GetLanguageForFile_MapsExtensionToLanguage(string extension, string expectedLanguage)
    {
        var result = LanguageRegistry.GetLanguageForFile($"file{extension}");
        Assert.Equal(expectedLanguage, result);
    }

    [Theory]
    [InlineData(".xyz")]
    [InlineData(".unknown")]
    [InlineData(".randomext")]
    [InlineData("")]
    public void GetLanguageForFile_ReturnsNullForUnknownExtensions(string extension)
    {
        var fileName = string.IsNullOrEmpty(extension) ? "noextension" : $"file{extension}";
        var result = LanguageRegistry.GetLanguageForFile(fileName);
        Assert.Null(result);
    }

    [Fact]
    public void GetAllLanguages_ReturnsAtLeast15Languages()
    {
        var languages = LanguageRegistry.GetAllLanguages();
        Assert.True(languages.Count >= 15, $"Expected at least 15 languages, got {languages.Count}");
    }

    [Fact]
    public void GetAllLanguages_ContainsExpectedLanguages()
    {
        var languages = LanguageRegistry.GetAllLanguages();

        Assert.Contains("python", languages);
        Assert.Contains("javascript", languages);
        Assert.Contains("typescript", languages);
        Assert.Contains("go", languages);
        Assert.Contains("rust", languages);
        Assert.Contains("java", languages);
        Assert.Contains("csharp", languages);
        Assert.Contains("ruby", languages);
        Assert.Contains("perl", languages);
    }

    [Fact]
    public void AllRegisteredExtensions_AreUnique()
    {
        var extensions = LanguageRegistry.LanguageExtensions.Keys.ToList();
        var uniqueExtensions = new HashSet<string>(extensions, StringComparer.OrdinalIgnoreCase);

        Assert.Equal(uniqueExtensions.Count, extensions.Count);
    }

    [Fact]
    public void Registry_HasSpecForEveryLanguageInGetAllLanguages()
    {
        var languages = LanguageRegistry.GetAllLanguages();
        foreach (var lang in languages)
        {
            Assert.True(LanguageRegistry.Registry.ContainsKey(lang),
                $"Language '{lang}' is in GetAllLanguages but has no spec in Registry");
        }
    }
}
