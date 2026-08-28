import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import App from '../../App';

function setUrl(url: string) {
  window.history.replaceState({}, '', url);
}

function unauthenticatedResponse() {
  return Promise.resolve({ ok: false, status: 401 });
}

describe('authentication entry flow', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn(() => unauthenticatedResponse()) as jest.Mock;
  });

  afterEach(() => {
    setUrl('/');
  });

  it('shows login for a fresh unauthenticated visit without starting OAuth', async () => {
    setUrl('/');
    render(<App />);

    expect(await screen.findByRole('button', { name: /continue with google/i })).toBeInTheDocument();
    expect(window.location.search).toBe('');
  });

  it.each([
    '/?auth_error=organization_only',
    '/#/auth/login?auth_error=organization_only',
  ])('shows the organization warning for %s', async (url) => {
    setUrl(url);
    render(<App />);

    expect(await screen.findByText(
      'Access restricted. Please sign in with your organization Google account.',
    )).toBeInTheDocument();
  });

  it('preserves the warning when session initialization resolves with 401', async () => {
    let resolveSession!: (response: { ok: boolean; status: number }) => void;
    global.fetch = jest.fn(() => new Promise(resolve => {
      resolveSession = resolve;
    })) as jest.Mock;
    setUrl('/?auth_error=organization_only');
    render(<App />);

    const warning = await screen.findByText(
      'Access restricted. Please sign in with your organization Google account.',
    );
    resolveSession({ ok: false, status: 401 });

    await waitFor(() => expect(warning).toBeInTheDocument());
  });

  it('uses a safe fallback for unknown authentication errors', async () => {
    setUrl('/?auth_error=arbitrary-attacker-message');
    render(<App />);

    expect(await screen.findByText('Authentication failed. Please try again.')).toBeInTheDocument();
    expect(screen.queryByText('arbitrary-attacker-message')).not.toBeInTheDocument();
  });
});