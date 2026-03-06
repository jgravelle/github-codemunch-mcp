using JCodeMunch.Mcp.Security;
using Xunit;

namespace JCodeMunch.Mcp.Tests;

public class SecurityValidatorTests
{
    [Theory]
    [InlineData(".env")]
    [InlineData("config/.env")]
    [InlineData(".env.local")]
    [InlineData("credentials.json")]
    [InlineData("id_rsa")]
    [InlineData("id_rsa.pub")]
    [InlineData("server.pem")]
    [InlineData("server.key")]
    [InlineData("keystore.jks")]
    [InlineData("my.secrets")]
    [InlineData("app.token")]
    [InlineData(".htpasswd")]
    [InlineData(".netrc")]
    [InlineData("service-account-key.json")]
    public void IsSecretFile_DetectsSecretFiles(string filePath)
    {
        Assert.True(SecurityValidator.IsSecretFile(filePath));
    }

    [Theory]
    [InlineData("src/main.py")]
    [InlineData("README.md")]
    [InlineData("package.json")]
    [InlineData("app.config")]
    [InlineData("src/utils.ts")]
    [InlineData("Makefile")]
    public void IsSecretFile_AllowsNormalFiles(string filePath)
    {
        Assert.False(SecurityValidator.IsSecretFile(filePath));
    }

    [Theory]
    [InlineData("image.png")]
    [InlineData("photo.jpg")]
    [InlineData("archive.zip")]
    [InlineData("program.exe")]
    [InlineData("library.dll")]
    [InlineData("binary.so")]
    [InlineData("module.wasm")]
    [InlineData("data.sqlite")]
    [InlineData("font.woff2")]
    [InlineData("doc.pdf")]
    public void IsBinaryExtension_DetectsBinaryExtensions(string filePath)
    {
        Assert.True(SecurityValidator.IsBinaryExtension(filePath));
    }

    [Theory]
    [InlineData("main.py")]
    [InlineData("index.js")]
    [InlineData("app.cs")]
    [InlineData("README.md")]
    [InlineData("config.yaml")]
    public void IsBinaryExtension_AllowsTextFiles(string filePath)
    {
        Assert.False(SecurityValidator.IsBinaryExtension(filePath));
    }

    [Fact]
    public void ValidatePath_RejectsPathTraversal()
    {
        var root = Path.GetTempPath();
        var traversal = Path.Combine(root, "..", "..", "etc", "passwd");

        Assert.False(SecurityValidator.ValidatePath(root, traversal));
    }

    [Fact]
    public void ValidatePath_AcceptsValidSubpath()
    {
        // Use a concrete directory without trailing separator to avoid ambiguity
        var root = Path.GetTempPath().TrimEnd(Path.DirectorySeparatorChar);
        var valid = Path.Combine(root, "subdir", "file.txt");

        Assert.True(SecurityValidator.ValidatePath(root, valid));
    }

    [Fact]
    public void ValidatePath_AcceptsRootItself()
    {
        var root = Path.GetTempPath().TrimEnd(Path.DirectorySeparatorChar);

        Assert.True(SecurityValidator.ValidatePath(root, root));
    }

    [Fact]
    public void IsBinaryContent_DetectsNullBytes()
    {
        var data = new byte[] { 0x48, 0x65, 0x6C, 0x00, 0x6F }; // "Hel\0o"
        Assert.True(SecurityValidator.IsBinaryContent(data));
    }

    [Fact]
    public void IsBinaryContent_AllowsTextContent()
    {
        var data = System.Text.Encoding.UTF8.GetBytes("Hello, world!");
        Assert.False(SecurityValidator.IsBinaryContent(data));
    }
}
