package sample;

/**
 * User service
 */
public class Sample {
    public static final int MAX_RETRIES = 3;

    /**
     * Get user by ID
     */
    public String getUser(int userId) {
        return "user-" + userId;
    }

    public static boolean authenticate(String token) {
        return token != null && !token.isEmpty();
    }
}
