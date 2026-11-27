"use client";

import { LockedProduct } from "@/components/Shell";
import Workspace from "@/components/assistant/Workspace";
import { PageHeader } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function PersonalMode() {
  const { hasCap, capsLoaded } = useAuth();
  if (capsLoaded && !hasCap("assistant.personal")) return <LockedProduct productKey="product.business_assistant" />;
  return (
    <div>
      <PageHeader title="Personal Assistant" subtitle="Your private assistant: conversations, memory and reminders are visible only to you." />
      <Workspace mode="personal" />
    </div>
  );
}
