MAX_RETRIES = 3

class UserService:
    """Manages user operations."""
    def get_user(self, user_id: int) -> dict:
        """Get user by ID."""
        return {"id": user_id}

    def delete_user(self, user_id: int) -> bool:
        """Delete a user."""
        return True

def authenticate(token: str) -> bool:
    """Authenticate a token."""
    return len(token) > 0
