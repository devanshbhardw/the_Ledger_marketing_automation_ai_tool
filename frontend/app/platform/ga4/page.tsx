import PlatformView from "@/components/PlatformView";

export default function GA4PlatformPage() {
  return (
    <>
      <div className="topbar">
        <h1>GA4</h1>
      </div>
      <div className="container">
        <PlatformView config={{ field: "propertyId", idLabel: "Property ID" }} />
      </div>
    </>
  );
}
