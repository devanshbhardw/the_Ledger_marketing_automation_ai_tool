import AskHistoryAdmin from "@/components/AskHistoryAdmin";

export default function AdminPage() {
  return (
    <>
      <div className="topbar">
        <h1>Admin</h1>
      </div>
      <div className="container">
        <AskHistoryAdmin />
        <div className="card">
          <h3>Administration</h3>
          <p className="muted">
            Coming soon — connected-account health, scheduled-job history, and
            cache controls will live here.
          </p>
        </div>
      </div>
    </>
  );
}
