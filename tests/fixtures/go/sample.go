package sample

// MaxRetries is the retry limit.
const MaxRetries = 3

// User represents a user.
type User struct {
    ID   int
    Name string
}

// GetUser returns a user by ID.
func GetUser(id int) User {
    return User{ID: id}
}

// Authenticate checks a token.
func Authenticate(token string) bool {
    return len(token) > 0
}
