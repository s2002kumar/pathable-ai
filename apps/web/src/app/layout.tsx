import type { Metadata, Viewport } from 'next';
// Self-hosted, so no request leaves for a font CDN and the browser suite draws
// the same glyphs offline. Both faces are OFL 1.1.
import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import '@/styles/globals.css';

export const metadata: Metadata = {
  title: 'PathAble — accessibility-aware pedestrian routing',
  description:
    'PathAble compares the shortest walking route with one that suits how you ' +
    'travel, and explains the difference using what OpenStreetMap actually records. ' +
    'A local engineering build for Waterloo, Ontario: it advises, it does not certify.',
  applicationName: 'PathAble',
  // Not deployed and not certified. An early build being surfaced by a search
  // engine as a working accessibility tool would be actively harmful.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Never below 5: capping zoom locks out low-vision users who rely on it.
  maximumScale: 5,
  colorScheme: 'dark',
  themeColor: '#060e20',
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
