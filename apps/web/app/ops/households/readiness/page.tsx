import HouseholdReadinessView from "@/components/HouseholdReadinessView";

export default async function OpsHouseholdReadinessPage({
  searchParams,
}: {
  searchParams: Promise<{ household_id?: string }>;
}) {
  const { household_id: householdId } = await searchParams;
  return (
    <HouseholdReadinessView
      role="operator"
      title="家庭就绪工作台"
      subtitle="运营侧按阻塞项、责任归属和下一步扫描家庭试点上线条件。"
      householdId={householdId}
    />
  );
}
