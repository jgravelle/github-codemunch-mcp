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

export const createUser = mutation({
    args: { name: v.string() },
    handler: async (ctx, args) => { return ctx.db.insert('users', args); }
});

export const getUser = query({
    args: { id: v.id('users') },
    handler: async (ctx, args) => { return ctx.db.get(args.id); }
});

const API_BASE_URL = "https://api.example.com";
