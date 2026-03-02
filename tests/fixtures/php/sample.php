<?php

const MAX_RETRIES = 3;

/**
 * Authenticate a user token.
 */
function authenticate(string $token): bool
{
    return strlen($token) > 0;
}

/**
 * Manages user operations.
 */
class UserService
{
    /**
     * Get a user by ID.
     */
    public function getUser(int $userId): array
    {
        return ['id' => $userId];
    }

    /**
     * Create a new user.
     */
    public static function create(string $name): self
    {
        return new self();
    }
}

interface Authenticatable
{
    public function authenticate(string $token): bool;
}

trait Timestampable
{
    public function getCreatedAt(): string
    {
        return date('Y-m-d');
    }
}

enum Status
{
    case Active;
    case Inactive;
    case Pending;
}
