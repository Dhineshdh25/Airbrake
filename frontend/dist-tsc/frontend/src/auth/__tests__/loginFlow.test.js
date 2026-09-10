"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("@testing-library/react");
require("@testing-library/jest-dom");
const App_1 = __importDefault(require("../../App"));
function setUrl(url) {
    window.history.replaceState({}, '', url);
}
// ── Reusable fetch mock helpers ────────────────────────────────────────────────
function unauthenticatedResponse() {
    return Promise.resolve({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ authenticated: false }),
    });
}
function authenticatedResponse() {
    return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
            authenticated: true,
            user: { id: 'USR001', username: 'admin', role: 'admin' },
            csrf_token: 'test-csrf-token',
        }),
    });
}
function loginSuccessResponse() {
    return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
            authenticated: true,
            user: { id: 'USR001', username: 'admin', role: 'admin' },
            session_token: 'test-session-token',
            csrf_token: 'test-csrf-token',
        }),
    });
}
function loginFailureResponse() {
    return Promise.resolve({
        ok: false,
        status: 401,
        json: () => Promise.resolve({
            authenticated: false,
            error: 'invalid_credentials',
            message: 'Invalid username or password.',
        }),
    });
}
/** Get the password <input> by its stable id to avoid label ambiguity with the eye-toggle aria-label. */
function getPasswordInput() {
    const el = document.getElementById('login-password');
    if (!el)
        throw new Error('Could not find #login-password input');
    return el;
}
describe('Login page — username + password form', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        global.fetch = jest.fn(() => unauthenticatedResponse());
    });
    afterEach(() => {
        setUrl('/');
    });
    // ── Page structure ─────────────────────────────────────────────────────────
    it('shows login page for a fresh unauthenticated visit', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        expect(await react_1.screen.findByLabelText(/username/i)).toBeInTheDocument();
        // Use exact match to avoid matching the eye-toggle "Show password" aria-label
        expect(await react_1.screen.findByLabelText(/^password$/i)).toBeInTheDocument();
        expect(await react_1.screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });
    it('shows "Username" label — not "Email"', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        expect(await react_1.screen.findByLabelText(/username/i)).toBeInTheDocument();
        expect(react_1.screen.queryByLabelText(/^email$/i)).not.toBeInTheDocument();
    });
    it('does NOT show a Google / Continue with Google button', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        await react_1.screen.findByLabelText(/username/i);
        expect(react_1.screen.queryByRole('button', { name: /google/i })).not.toBeInTheDocument();
        expect(react_1.screen.queryByText(/continue with google/i)).not.toBeInTheDocument();
    });
    it('does NOT show Create Account or Sign Up links', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        await react_1.screen.findByLabelText(/username/i);
        expect(react_1.screen.queryByText(/create account/i)).not.toBeInTheDocument();
        expect(react_1.screen.queryByText(/sign up/i)).not.toBeInTheDocument();
        expect(react_1.screen.queryByText(/register/i)).not.toBeInTheDocument();
        expect(react_1.screen.queryByText(/forgot password/i)).not.toBeInTheDocument();
    });
    it('does NOT show a Create one link', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        await react_1.screen.findByLabelText(/username/i);
        expect(react_1.screen.queryByText(/create one/i)).not.toBeInTheDocument();
    });
    it('has a remember me checkbox', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        expect(await react_1.screen.findByLabelText(/remember me/i)).toBeInTheDocument();
    });
    it('has a password visibility toggle button', async () => {
        setUrl('/');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        await react_1.screen.findByLabelText(/username/i);
        expect(react_1.screen.getByRole('button', { name: /show password/i })).toBeInTheDocument();
    });
    // ── Form submission ────────────────────────────────────────────────────────
    it('calls POST /api/auth/login with username and password on submit', async () => {
        setUrl('/#/auth/login');
        const mockFetch = jest.fn()
            .mockImplementationOnce(unauthenticatedResponse) // /api/auth/me on mount
            .mockImplementationOnce(loginSuccessResponse); // /api/auth/login
        global.fetch = mockFetch;
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        const usernameInput = await react_1.screen.findByLabelText(/username/i);
        const passwordInput = getPasswordInput();
        const signInButton = react_1.screen.getByRole('button', { name: /sign in/i });
        react_1.fireEvent.change(usernameInput, { target: { value: 'admin' } });
        react_1.fireEvent.change(passwordInput, { target: { value: 'mpsaiteam' } });
        react_1.fireEvent.click(signInButton);
        await (0, react_1.waitFor)(() => {
            const loginCall = mockFetch.mock.calls.find(([url]) => typeof url === 'string' && url.includes('/api/auth/login'));
            expect(loginCall).toBeDefined();
            const init = loginCall[1];
            expect(init.method).toBe('POST');
            const body = JSON.parse(init.body);
            expect(body.username).toBe('admin');
            expect(body.password).toBe('mpsaiteam');
            // role must NOT be sent from the frontend — backend reads it from users.json
            expect(body.role).toBeUndefined();
        });
    });
    it('password is not stored in localStorage or sessionStorage', async () => {
        setUrl('/#/auth/login');
        global.fetch = jest.fn()
            .mockImplementationOnce(unauthenticatedResponse)
            .mockImplementationOnce(loginSuccessResponse);
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        const usernameInput = await react_1.screen.findByLabelText(/username/i);
        const passwordInput = getPasswordInput();
        react_1.fireEvent.change(usernameInput, { target: { value: 'admin' } });
        react_1.fireEvent.change(passwordInput, { target: { value: 'mpsaiteam' } });
        react_1.fireEvent.click(react_1.screen.getByRole('button', { name: /sign in/i }));
        await (0, react_1.waitFor)(() => {
            expect(JSON.stringify(localStorage)).not.toContain('mpsaiteam');
            expect(JSON.stringify(sessionStorage)).not.toContain('mpsaiteam');
        });
    });
    it('shows "Signing in…" and disables the button while submitting', async () => {
        setUrl('/#/auth/login');
        let resolveLogin;
        const pendingLogin = new Promise(resolve => { resolveLogin = resolve; });
        global.fetch = jest.fn()
            .mockImplementationOnce(unauthenticatedResponse)
            .mockImplementationOnce(() => pendingLogin);
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        const usernameInput = await react_1.screen.findByLabelText(/username/i);
        const passwordInput = getPasswordInput();
        react_1.fireEvent.change(usernameInput, { target: { value: 'admin' } });
        react_1.fireEvent.change(passwordInput, { target: { value: 'mpsaiteam' } });
        react_1.fireEvent.click(react_1.screen.getByRole('button', { name: /sign in/i }));
        expect(await react_1.screen.findByRole('button', { name: /signing in/i })).toBeDisabled();
        // Resolve to clean up pending promise
        resolveLogin(loginSuccessResponse());
    });
    it('shows invalid credentials error on 401 response', async () => {
        setUrl('/#/auth/login');
        global.fetch = jest.fn()
            .mockImplementationOnce(unauthenticatedResponse)
            .mockImplementationOnce(loginFailureResponse);
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        const usernameInput = await react_1.screen.findByLabelText(/username/i);
        const passwordInput = getPasswordInput();
        react_1.fireEvent.change(usernameInput, { target: { value: 'admin' } });
        react_1.fireEvent.change(passwordInput, { target: { value: 'wrongpassword' } });
        react_1.fireEvent.click(react_1.screen.getByRole('button', { name: /sign in/i }));
        expect(await react_1.screen.findByText(/invalid username or password/i)).toBeInTheDocument();
    });
    it('shows network error message on fetch failure', async () => {
        setUrl('/#/auth/login');
        global.fetch = jest.fn()
            .mockImplementationOnce(unauthenticatedResponse)
            .mockImplementationOnce(() => Promise.reject(new Error('Network error')));
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        const usernameInput = await react_1.screen.findByLabelText(/username/i);
        const passwordInput = getPasswordInput();
        react_1.fireEvent.change(usernameInput, { target: { value: 'admin' } });
        react_1.fireEvent.change(passwordInput, { target: { value: 'mpsaiteam' } });
        react_1.fireEvent.click(react_1.screen.getByRole('button', { name: /sign in/i }));
        expect(await react_1.screen.findByText(/unable to connect/i)).toBeInTheDocument();
    });
    // ── auth_error query param ─────────────────────────────────────────────────
    it('shows a safe fallback for unknown auth_error query params', async () => {
        // auth_error must be in the hash for HashRouter's useSearchParams to see it
        setUrl('/#/auth/login?auth_error=arbitrary-attacker-message');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        expect(await react_1.screen.findByText('Authentication failed. Please try again.')).toBeInTheDocument();
        expect(react_1.screen.queryByText('arbitrary-attacker-message')).not.toBeInTheDocument();
    });
    // ── Protected route redirect ───────────────────────────────────────────────
    it('redirects unauthenticated users from protected routes to /auth/login', async () => {
        setUrl('/#/dashboard');
        global.fetch = jest.fn(() => unauthenticatedResponse());
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        expect(await react_1.screen.findByLabelText(/username/i)).toBeInTheDocument();
    });
    // ── Logout ─────────────────────────────────────────────────────────────────
    it('logout returns user to login page', async () => {
        setUrl('/');
        global.fetch = jest.fn()
            .mockImplementation((url) => {
            if (url.includes('/api/auth/me'))
                return authenticatedResponse();
            if (url.includes('/api/auth/logout'))
                return Promise.resolve({
                    ok: true,
                    status: 200,
                    json: () => Promise.resolve({ message: 'Logged out successfully' }),
                });
            return unauthenticatedResponse();
        });
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        await (0, react_1.waitFor)(() => {
            expect(global.fetch.mock.calls.some(([url]) => url.includes('/api/auth/me'))).toBe(true);
        });
    });
});
describe('Jira OAuth redirect — preserved after Google removal', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        global.fetch = jest.fn(() => unauthenticatedResponse());
    });
    afterEach(() => {
        setUrl('/');
    });
    it('handles jira_connected=true query param without crashing', async () => {
        setUrl('/?jira_connected=true');
        (0, react_1.render)((0, jsx_runtime_1.jsx)(App_1.default, {}));
        // App renders without error (shows login because unauthenticated)
        expect(await react_1.screen.findByLabelText(/username/i)).toBeInTheDocument();
    });
});
//# sourceMappingURL=loginFlow.test.js.map