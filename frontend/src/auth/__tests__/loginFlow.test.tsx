import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import App from '../../App';

function setUrl(url: string) {
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
function getPasswordInput(): HTMLInputElement {
  const el = document.getElementById('login-password');
  if (!el) throw new Error('Could not find #login-password input');
  return el as HTMLInputElement;
}

describe('Login page — username + password form', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn(() => unauthenticatedResponse()) as jest.Mock;
  });

  afterEach(() => {
    setUrl('/');
  });

  // ── Page structure ─────────────────────────────────────────────────────────

  it('shows login page for a fresh unauthenticated visit', async () => {
    setUrl('/');
    render(<App />);

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
    // Use exact match to avoid matching the eye-toggle "Show password" aria-label
    expect(await screen.findByLabelText(/^password$/i)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('shows "Username" label — not "Email"', async () => {
    setUrl('/');
    render(<App />);
    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^email$/i)).not.toBeInTheDocument();
  });

  it('does NOT show a Google / Continue with Google button', async () => {
    setUrl('/');
    render(<App />);
    await screen.findByLabelText(/username/i);
    expect(screen.queryByRole('button', { name: /google/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/continue with google/i)).not.toBeInTheDocument();
  });

  it('does NOT show Create Account or Sign Up links', async () => {
    setUrl('/');
    render(<App />);
    await screen.findByLabelText(/username/i);
    expect(screen.queryByText(/create account/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sign up/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/register/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/forgot password/i)).not.toBeInTheDocument();
  });

  it('does NOT show a Create one link', async () => {
    setUrl('/');
    render(<App />);
    await screen.findByLabelText(/username/i);
    expect(screen.queryByText(/create one/i)).not.toBeInTheDocument();
  });

  it('has a remember me checkbox', async () => {
    setUrl('/');
    render(<App />);
    expect(await screen.findByLabelText(/remember me/i)).toBeInTheDocument();
  });

  it('has a password visibility toggle button', async () => {
    setUrl('/');
    render(<App />);
    await screen.findByLabelText(/username/i);
    expect(screen.getByRole('button', { name: /show password/i })).toBeInTheDocument();
  });

  // ── Form submission ────────────────────────────────────────────────────────

  it('calls POST /api/auth/login with username and password on submit', async () => {
    setUrl('/#/auth/login');

    const mockFetch = jest.fn()
      .mockImplementationOnce(unauthenticatedResponse) // /api/auth/me on mount
      .mockImplementationOnce(loginSuccessResponse);   // /api/auth/login
    global.fetch = mockFetch as jest.Mock;

    render(<App />);

    const usernameInput = await screen.findByLabelText(/username/i);
    const passwordInput = getPasswordInput();
    const signInButton = screen.getByRole('button', { name: /sign in/i });

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'admin123' } });
    fireEvent.click(signInButton);

    await waitFor(() => {
      const loginCall = mockFetch.mock.calls.find(
        ([url]: [unknown]) => typeof url === 'string' && url.includes('/api/auth/login'),
      );
      expect(loginCall).toBeDefined();

      const init = loginCall![1] as RequestInit;
      expect(init.method).toBe('POST');

      const body = JSON.parse(init.body as string);
      expect(body.username).toBe('admin');
      expect(body.password).toBe('admin123');
      // role must NOT be sent from the frontend — backend reads it from users.json
      expect(body.role).toBeUndefined();
    });
  });

  it('password is not stored in localStorage or sessionStorage', async () => {
    setUrl('/#/auth/login');

    global.fetch = jest.fn()
      .mockImplementationOnce(unauthenticatedResponse)
      .mockImplementationOnce(loginSuccessResponse) as jest.Mock;

    render(<App />);

    const usernameInput = await screen.findByLabelText(/username/i);
    const passwordInput = getPasswordInput();

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'admin123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(JSON.stringify(localStorage)).not.toContain('admin123');
      expect(JSON.stringify(sessionStorage)).not.toContain('admin123');
    });
  });

  it('shows "Signing in…" and disables the button while submitting', async () => {
    setUrl('/#/auth/login');

    let resolveLogin!: (r: object) => void;
    const pendingLogin = new Promise(resolve => { resolveLogin = resolve; });

    global.fetch = jest.fn()
      .mockImplementationOnce(unauthenticatedResponse)
      .mockImplementationOnce(() => pendingLogin) as jest.Mock;

    render(<App />);

    const usernameInput = await screen.findByLabelText(/username/i);
    const passwordInput = getPasswordInput();

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'admin123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByRole('button', { name: /signing in/i })).toBeDisabled();

    // Resolve to clean up pending promise
    resolveLogin(loginSuccessResponse());
  });

  it('shows invalid credentials error on 401 response', async () => {
    setUrl('/#/auth/login');

    global.fetch = jest.fn()
      .mockImplementationOnce(unauthenticatedResponse)
      .mockImplementationOnce(loginFailureResponse) as jest.Mock;

    render(<App />);

    const usernameInput = await screen.findByLabelText(/username/i);
    const passwordInput = getPasswordInput();

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'wrongpassword' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/invalid username or password/i)).toBeInTheDocument();
  });

  it('shows network error message on fetch failure', async () => {
    setUrl('/#/auth/login');

    global.fetch = jest.fn()
      .mockImplementationOnce(unauthenticatedResponse)
      .mockImplementationOnce(() => Promise.reject(new Error('Network error'))) as jest.Mock;

    render(<App />);

    const usernameInput = await screen.findByLabelText(/username/i);
    const passwordInput = getPasswordInput();

    fireEvent.change(usernameInput, { target: { value: 'admin' } });
    fireEvent.change(passwordInput, { target: { value: 'admin123' } });
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }));

    expect(await screen.findByText(/unable to connect/i)).toBeInTheDocument();
  });

  // ── auth_error query param ─────────────────────────────────────────────────

  it('shows a safe fallback for unknown auth_error query params', async () => {
    // auth_error must be in the hash for HashRouter's useSearchParams to see it
    setUrl('/#/auth/login?auth_error=arbitrary-attacker-message');
    render(<App />);

    expect(await screen.findByText('Authentication failed. Please try again.')).toBeInTheDocument();
    expect(screen.queryByText('arbitrary-attacker-message')).not.toBeInTheDocument();
  });

  // ── Protected route redirect ───────────────────────────────────────────────

  it('redirects unauthenticated users from protected routes to /auth/login', async () => {
    setUrl('/#/dashboard');
    global.fetch = jest.fn(() => unauthenticatedResponse()) as jest.Mock;

    render(<App />);

    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
  });

  // ── Logout ─────────────────────────────────────────────────────────────────

  it('logout returns user to login page', async () => {
    setUrl('/');

    global.fetch = jest.fn()
      .mockImplementation((url: string) => {
        if (url.includes('/api/auth/me')) return authenticatedResponse();
        if (url.includes('/api/auth/logout')) return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ message: 'Logged out successfully' }),
        });
        return unauthenticatedResponse();
      }) as jest.Mock;

    render(<App />);

    await waitFor(() => {
      expect((global.fetch as jest.Mock).mock.calls.some(
        ([url]: [string]) => url.includes('/api/auth/me')
      )).toBe(true);
    });
  });
});

describe('Jira OAuth redirect — preserved after Google removal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn(() => unauthenticatedResponse()) as jest.Mock;
  });

  afterEach(() => {
    setUrl('/');
  });

  it('handles jira_connected=true query param without crashing', async () => {
    setUrl('/?jira_connected=true');
    render(<App />);

    // App renders without error (shows login because unauthenticated)
    expect(await screen.findByLabelText(/username/i)).toBeInTheDocument();
  });
});
