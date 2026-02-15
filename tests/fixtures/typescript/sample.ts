const MAX_TIMEOUT: number = 5000;

interface User {
    id: number;
    name: string;
}

class UserService {
    getUser(userId: number): User {
        return { id: userId, name: "" };
    }
}

function authenticate(token: string): boolean {
    return token.length > 0;
}

type UserID = number;
