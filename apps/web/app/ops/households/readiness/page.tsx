import OperatorReadinessWorkspace from "./OperatorReadinessWorkspace";

export default async function OpsHouseholdReadinessPage({
  searchParams,
}: {
  searchParams: Promise<{ household_id?: string }>;
}) {
  const { household_id: householdId } = await searchParams;
  return <OperatorReadinessWorkspace initialHouseholdId={householdId || null} />;
}
