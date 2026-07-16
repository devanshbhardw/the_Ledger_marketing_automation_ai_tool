import { redirect } from "next/navigation";

export default function Home() {
  // With service-account auth there is no login step — go straight to the dashboard.
  redirect("/dashboard");
}
