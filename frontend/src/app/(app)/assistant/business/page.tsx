"use client";

import Workspace from "@/components/assistant/Workspace";
import { PageHeader } from "@/components/ui";

export default function BusinessMode() {
  return (
    <div>
      <PageHeader title="Business Assistant" subtitle="Ask about sales, stock, receivables, calls and appointments using voice or text." />
      <Workspace mode="business" />
    </div>
  );
}
