import ConnectAccounts from "@/components/ConnectAccounts";

export default function ConnectionsPage() {
  return (
    <>
      <div className="topbar">
        <h1>Connections</h1>
      </div>
      <div className="container">
        <ConnectAccounts />
      </div>
    </>
  );
}
