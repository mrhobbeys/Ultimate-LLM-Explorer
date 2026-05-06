import { NavLink, Route, Routes } from "react-router-dom";
import Ingest from "./pages/Ingest";
import Timeline from "./pages/Timeline";
import ConversationPage from "./pages/Conversation";
import Topics from "./pages/Topics";
import TopicDetail from "./pages/TopicDetail";
import Search from "./pages/Search";
import Stats from "./pages/Stats";
import Progression from "./pages/Progression";
import Conversations from "./pages/Conversations";

const tabs: { to: string; label: string }[] = [
  { to: "/", label: "Timeline" },
  { to: "/conversations", label: "Conversations" },
  { to: "/search", label: "Search" },
  { to: "/topics", label: "Topics" },
  { to: "/progression", label: "Progression" },
  { to: "/stats", label: "Stats" },
  { to: "/ingest", label: "Ingest" },
];

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-6">
          <div className="font-semibold tracking-tight">
            <span className="text-indigo-400">ULLE</span> · Ultimate LLM Explorer
          </div>
          <nav className="flex gap-1 text-sm">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.to === "/"}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-md ${
                    isActive
                      ? "bg-indigo-500/20 text-indigo-200"
                      : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
                  }`
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<Timeline />} />
          <Route path="/conversations" element={<Conversations />} />
          <Route path="/conversations/:id" element={<ConversationPage />} />
          <Route path="/topics" element={<Topics />} />
          <Route path="/topics/:id" element={<TopicDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/stats" element={<Stats />} />
          <Route path="/progression" element={<Progression />} />
          <Route path="/ingest" element={<Ingest />} />
        </Routes>
      </main>
    </div>
  );
}
