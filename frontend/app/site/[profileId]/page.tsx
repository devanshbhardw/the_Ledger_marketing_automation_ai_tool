import SiteView from "@/components/SiteView";

export default async function SitePage({
  params,
}: {
  params: Promise<{ profileId: string }>;
}) {
  const { profileId } = await params;
  return <SiteView profileId={profileId} />;
}
