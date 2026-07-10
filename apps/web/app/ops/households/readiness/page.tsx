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
      title="家庭就绪工作台"
      subtitle="运营侧按阻塞项、责任归属和下一步扫描家庭试点上线条件。"
      householdId={householdId}
    />
  );
}
