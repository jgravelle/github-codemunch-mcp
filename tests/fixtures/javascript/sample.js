const MAX_TIMEOUT = 5000;

/**
 * User service class
 */
class UserService {
    getUser(userId) {
        return { id: userId };
    }
}

function authenticate(token) {
    return token.length > 0;
}

export const listUsers = query({
    handler: async (ctx) => { return ctx.db.query('users').collect(); }
});

const API_VERSION = "v2";
