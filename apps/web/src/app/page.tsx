import { redirect } from 'next/navigation';
import { PageTransition, TO_PLANNER } from '@/components/PageTransition';
import { LandingPage } from '@/features/landing/LandingPage';
import { legacyPlannerUrl } from '@/features/routing/legacy-url';

type HomePageProps = {
  /** Next 16 hands search parameters to a server component as a promise. */
  readonly searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  // `/?example=…` is the planner's old address; send it on, query intact.
  const legacy = legacyPlannerUrl(await searchParams);
  if (legacy !== null) redirect(legacy);
  // Leaving for the planner by one of the landing page's own links, the page
  // recedes as the planner arrives (globals.css). Any other navigation: none.
  return (
    <PageTransition exit={{ [TO_PLANNER]: 'pa-leave-landing', default: 'none' }} default="none">
      <LandingPage />
    </PageTransition>
  );
}
