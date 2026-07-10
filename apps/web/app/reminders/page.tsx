import { redirect } from "next/navigation";

export default function LegacyCareTasksRedirect() {
  redirect("/family/tasks");
}
