import HouseholdReadinessView from "@/components/HouseholdReadinessView";

export default function OpsHouseholdReadinessPage({
  searchParams,
}: {
  searchParams: { household_id?: string };
}) {
  const householdId = searchParams.household_id;
  return (
    <HouseholdReadinessView
      role="operator"
      title="家庭就绪"
      subtitle="运营侧查看家庭试点上线条件、阻塞项和下一步。"
      householdId={householdId}
    />
  );
}
