"use client";
import { useRouter } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

export function RefreshButton() {
  const router = useRouter();
  const [spinning, setSpinning] = useState(false);

  const handleRefresh = () => {
    setSpinning(true);
    router.refresh();
    setTimeout(() => setSpinning(false), 1000);
  };

  return (
    <button
      onClick={handleRefresh}
      className="flex items-center gap-2 px-4 py-2 text-[12px] text-muted hover:text-text border border-border hover:border-subtle transition-colors"
    >
      <RefreshCw size={11} className={spinning ? "animate-spin" : ""} />
      Refresh
    </button>
  );
}
