const MAX_RETRIES: u32 = 3;

/// A user struct
struct User {
    id: u32,
    name: String,
}

impl User {
    /// Create a new user
    fn new(id: u32, name: String) -> Self {
        User { id, name }
    }
}

/// Authenticate a token
fn authenticate(token: &str) -> bool {
    !token.is_empty()
}
