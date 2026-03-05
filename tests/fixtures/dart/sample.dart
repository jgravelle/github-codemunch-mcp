/// User service for managing users.
class UserService {
  /// Get user by ID.
  String getUser(int userId) {
    return 'user-$userId';
  }

  /// Delete a user.
  bool deleteUser(int userId) {
    return true;
  }
}

/// Authenticate a token.
bool authenticate(String token) {
  return token.isNotEmpty;
}

/// Status of a request.
enum Status { pending, active, done }

/// JSON map alias.
typedef JsonMap = Map<String, dynamic>;
