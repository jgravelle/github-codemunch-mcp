using System;

namespace SampleApp;

/// <summary>
/// User service.
/// </summary>
public class UserService
{
    public const int MAX_RETRIES = 3;

    public string Name { get; set; } = "";

    public UserService()
    {
    }

    public string GetUser(int userId)
    {
        return userId.ToString();
    }
}

public interface IAuthenticator
{
    bool Authenticate(string token);
}

public record UserRecord(int Id, string Name);
