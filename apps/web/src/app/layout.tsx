import type { Metadata, Viewport } from 'next';
import '@/styles/globals.css';

export const metadata: Metadata = {
  title: 'PathAble AI — accessibility-aware pedestrian routing',
  description:
    'PathAble compares the shortest walking route with one that suits how you ' +
    'travel, and explains the difference using what OpenStreetMap actually records. ' +
    'A local engineering build for Waterloo, Ontario: it advises, it does not certify.',
  applicationName: 'PathAble AI',
  // Not deployed and not certified. An early build being surfaced by a search
  // engine as a working accessibility tool would be actively harmful.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Never below 5: capping zoom locks out low-vision users who rely on it.
  maximumScale: 5,
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fffdf9' },
    { media: '(prefers-color-scheme: dark)', color: '#1a1816' },
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
