import type { Metadata, Viewport } from 'next';
import '@/styles/globals.css';

export const metadata: Metadata = {
  title: 'PathAble AI — accessibility-aware pedestrian routing',
  description:
    'An early engineering build of PathAble AI, a project to compare ordinary ' +
    'pedestrian routes against accessibility-aware routes. Phase 0: no routing or ' +
    'machine learning is implemented yet.',
  applicationName: 'PathAble AI',
  // Nothing here is ready to be indexed or shared, and an early build being
  // surfaced as a working accessibility tool would be actively harmful.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Never below 5: capping zoom locks out low-vision users who rely on it.
  maximumScale: 5,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#0f191c' },
  ],
};

export default function RootLayout({ children }: { readonly children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main-content">
          Skip to main content
        </a>
        {children}
      </body>
    </html>
  );
}
