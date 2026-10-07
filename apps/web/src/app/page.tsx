import { redirect } from 'next/navigation';
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
  return <LandingPage />;
}
