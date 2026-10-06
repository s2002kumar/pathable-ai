import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { AppHeader } from './AppHeader';
import { ConfigurationError } from './ConfigurationError';

const READY = { state: 'ready', service: 'pathable-api', version: '0.1.0' } as const;

/**
 * The bar is presentational: the page probes the routing service once and
 * hands the answer down (the planner page tests cover the probe).
 */
describe('AppHeader', () => {
  it('renders the product identity, linked home', () => {
    render(<AppHeader pilotRegionName="Waterloo, Ontario" status={READY} />);

    expect(screen.getByText('PathAble')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'PathAble home' })).toHaveAttribute('href', '/');
  });

  it('shows the configured pilot region, shortened as the design does', () => {
    render(<AppHeader pilotRegionName="Waterloo, Ontario" status={READY} />);

    expect(screen.getByTestId('pilot-region')).toHaveTextContent('Waterloo, ON');
  });

  it('says the service state in a word whenever it is not ready', () => {
    const { rerender } = render(
      <AppHeader
        pilotRegionName="Waterloo, Ontario"
        status={{ ...READY, state: 'preparing', detail: 'loading' }}
      />,
    );
    expect(screen.getByTestId('pilot-region')).toHaveAttribute('data-status', 'preparing');
    expect(screen.getByTestId('header-status')).toHaveTextContent('Preparing');
    expect(screen.getByTestId('header-status')).not.toHaveClass('visually-hidden');

    rerender(
      <AppHeader
        pilotRegionName="Waterloo, Ontario"
        status={{ state: 'unreachable', reason: 'Failed to fetch' }}
      />,
    );
    expect(screen.getByTestId('header-status')).toHaveTextContent('Offline');
  });

  it('sends the search shortcut to the planner’s start field', async () => {
    const user = userEvent.setup();
    render(
      <>
        <AppHeader pilotRegionName="Waterloo, Ontario" status={READY} searchTargetId="start" />
        <input id="start" aria-label="Start location" />
      </>,
    );

    await user.click(screen.getByTestId('header-search'));
    expect(screen.getByLabelText('Start location')).toHaveFocus();
  });

  it('offers no search shortcut where there is no field to send it to', () => {
    render(<AppHeader pilotRegionName="Waterloo, Ontario" status={READY} />);

    expect(screen.queryByTestId('header-search')).not.toBeInTheDocument();
  });
});

describe('ConfigurationError', () => {
  it('lists every invalid variable', () => {
    render(
      <ConfigurationError
        issues={[
          { field: 'NEXT_PUBLIC_PILOT_ZOOM', message: 'must be between 0 and 22' },
          { field: 'NEXT_PUBLIC_API_BASE_URL', message: 'must be an absolute URL' },
        ]}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_PILOT_ZOOM');
    expect(screen.getByRole('alert')).toHaveTextContent('NEXT_PUBLIC_API_BASE_URL');
    expect(screen.getByText('2 environment variables have invalid values:')).toBeInTheDocument();
  });

  it('uses singular wording for a single problem', () => {
    render(
      <ConfigurationError
        issues={[{ field: 'NEXT_PUBLIC_PILOT_ZOOM', message: 'must be between 0 and 22' }]}
      />,
    );

    expect(screen.getByText('One environment variable has an invalid value:')).toBeInTheDocument();
  });

  it('tells the reader how to fix it', () => {
    render(<ConfigurationError issues={[{ field: 'X', message: 'bad' }]} />);

    expect(screen.getByRole('alert')).toHaveTextContent('.env.example');
    expect(screen.getByRole('alert')).toHaveTextContent(/rebuild is required/i);
  });
});
