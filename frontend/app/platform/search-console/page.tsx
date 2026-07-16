import PlatformView from "@/components/PlatformView";

export default function SearchConsolePlatformPage() {
  return (
    <>
      <div className="topbar">
        <h1>Search Console</h1>
      </div>
      <div className="container">
        <PlatformView config={{ field: "searchConsoleSiteUrl", idLabel: "Site URL" }} />
      </div>
    </>
  );
}
