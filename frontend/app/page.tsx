"use client";

import { useState } from "react";
import Sidebar, { Tab } from "@/components/Sidebar";
import TopBar from "@/components/TopBar";
import ChatPanel from "@/components/ChatPanel";
import AgentStatus from "@/components/AgentStatus";
import MemoryViewer from "@/components/MemoryViewer";
import TaskHistory from "@/components/TaskHistory";
import ToolActivity from "@/components/ToolActivity";

export default function Page() {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div className="flex h-screen overflow-hidden text-body">
      <Sidebar active={tab} onSelect={setTab} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 p-5">
          {tab === "chat" && <ChatPanel />}
          {tab === "agents" && <AgentStatus />}
          {tab === "memory" && <MemoryViewer />}
          {tab === "tasks" && <TaskHistory />}
          {tab === "activity" && <ToolActivity />}
        </main>
      </div>
    </div>
  );
}
