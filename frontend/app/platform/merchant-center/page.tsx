import PlatformView from "@/components/PlatformView";

export default function MerchantCenterPlatformPage() {
  return (
    <>
      <div className="topbar">
        <h1>Merchant Center</h1>
      </div>
      <div className="container">
        <PlatformView config={{ field: "merchantCenterId", idLabel: "Merchant Center ID" }} />
      </div>
    </>
  );
}
